# Contrato DDMRP ⇄ BPM para órdenes de compra

DDMRP arma el **plano de Siesa** (dueño del layout 0420/0421 v5 y de la referencia). El BPM lo revisa/aprueba, lo crea en Siesa (~30 s por OC) y avisa. Se activa con `OC_DESTINO=bpm` en DDMRP; con `directo` DDMRP crea en Siesa por su cuenta (prueba/contingencia).

Secreto compartido: `BPM_SECRET` (DDMRP) = `OC_API_SECRET` (BPM), cabecera `X-OC-Secret` en ambos sentidos. Si falta en cualquiera de los dos, todo se rechaza (401).

## 1. DDMRP → BPM: `POST {BPM_URL}/api/internal/oc`  → 202 `{ok, instance_id}`
Cuerpo: `id_externo` (id de `ddmrp.orden_compra`), `empresa` (05|21), `referencia` (`DDMRP00000123`), `plano` (texto completo), `proveedor_id`, `sucursal`, `proveedor_nombre`, `cond_pago`, `comprador`, `creado_por`, `valor`, `iva`, `total`, `items`, `requiere_revision` (bool; lo decide DDMRP con la «Configuración de compras»: umbral de total y desvíos por línea) y `motivo_revision` (texto), `lineas[]` (`producto_id`, `descripcion`, `cantidad`, `costo`, `fecha_entrega`).
Idempotente por `referencia`: reenviar no crea otra instancia. 4xx/5xx/timeout ⇒ DDMRP deja la OC en `error` (nada se creó en Siesa) y se puede reenviar.
`GET {BPM_URL}/api/internal/oc/{id_externo}` → estado en el BPM.

## 2. BPM → DDMRP: `POST {DDMRP_URL}/api/bpm/oc/{id}/estado`
`{estado, mensaje?, consecutivo?, grupo?, tomada_por?, instance_id?}` con `estado` ∈ `en_revision | aprobada | rechazada | creada | error | incierta`.
Una OC `creada` no retrocede. Si el callback falla, el BPM lo guarda (`app_oc.callback_pendiente`) y reintenta cada 5 min. `creada` suelta las cantidades editadas de esos ítems en DDMRP.

## 3. BPM → DDMRP: `POST {DDMRP_URL}/api/bpm/oc/{id}/plano` (para la edición en la revisión — v2)
`{lineas:[{producto_id, cantidad, costo}], nota}` → `{plano, valor, iva, total, items}`. Solo cambia cantidad/costo de líneas existentes o las quita (cantidad 0); nota obligatoria si cambia un costo. Guarda lo original (`cantidad_original`, `costo_original`). El BPM debe tomar el plano devuelto antes de crear (hoy `app_oc.plano`).

## Estados en DDMRP (`orden_compra.estado`)
`en_bpm` → `en_revision` → `aprobada` → `creada` | `rechazada` | `error` | `incierta`. (`incierta`: el web service no respondió; el BPM verifica por la referencia antes de reintentar. Nunca se reenvía a ciegas.)

## Lado BPM (flowable-node-BPM)
`node/ordenCompra.js` (router + callback), `node/siesaOc.js` (SOAP `ImportarXML`, duplicado en t420, cola), `processes/orden_compra_process.bpmn20.xml` (sin secretos: ver Seguridad), `node/scripts/orden_compra_forms.sql` (formularios `revisarOC` y `errorEnvioOC`), variables `OC_*` en `docker-compose.yml`/`.env.example`.

## Pendiente (v2)
Editar cantidades/costos en la revisión (hoy solo aprobar/rechazar), PDF y correo al proveedor, creador ≠ aprobador al tomar la tarea, recordatorio/escalada, Stores (21), grupo `compras_aprobadores` con miembros.

## Seguridad
- **DDMRP ⇄ BPM:** secreto compartido `OC_API_SECRET` / `BPM_SECRET`, solo en los `.env` (nunca en un BPMN ni en el repo).
- **BPMN → Node (`/api/internal/oc/tarea/*`):** sin secreto. El Node acepta la llamada solo si (1) llega por la red interna de Docker (sin `X-Forwarded-For`/`X-Real-IP`), (2) la instancia existe, está activa y es de `orden_compra_process`, y (3) está justo en el paso correspondiente. El nginx de la UI además devuelve 404 a `/api/internal/oc/tarea/`.
- Pendiente aparte: `solicitud_mantenimiento_process` sigue con el secreto embebido en su BPMN (patrón anterior).

## Plano vigente (fecha de hoy)
Siesa exige que la fecha del documento sea la del sistema. Una OC puede aprobarse días después de enviarse, así que justo antes de crearla el BPM llama
`POST /api/bpm/oc/{id}/plano/vigente` (mismo `X-OC-Secret`): DDMRP corre las fechas de entrega los mismos días que pasaron, arma el plano con la fecha de HOY (hora de Colombia, UTC-5) y lo devuelve.
Si DDMRP no responde, el BPM NO envía el plano viejo: el paso falla y se reintenta.
