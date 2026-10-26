# Módulo de compras en DDMRP: checklist

Estados: ✅ listo · 🟡 hecho, sin validar en producción · ⬜ pendiente · ⏸ espera datos o una decisión.
Última actualización: 26 oct 2026 (cotización e IVA).

## Base de datos y cálculo (fase 1: «solo lee y calcula»)
- 🟡 Rotación de PT001: ventas directas del CEDI (`ventas_cedi_05/21`) + ventas de las tiendas que abastece
- 🟡 Buffer del CEDI por empresa (motor Rust, `--modo cedi`, tabla `sugerencias_cedi`): ADU, zonas, flujo neto
- 🟡 Tránsito del CEDI = saldo de OC abiertas de Siesa (estado del ítem Aprobado o Parcial); tope de antigüedad `oc_dias_historia` (365)
- 🟡 Lead time del CEDI: ítem > proveedor del ítem > general (8 d) — maestro «Lead time del CEDI» y «Proveedores»
- 🟡 Informes en modo «Ver solo CEDI»: Control (foto/cambios/tendencia/mapa), Alertas, Salud y Clasificación
- ⬜ Retroprueba: validar la necesidad del CEDI contra lo que compras realmente pidió
- 🟡 Poca historia: alerta (no bloquea) con umbral configurable (3 meses con venta). ⬜ picos atípicos como demanda calificada o recortados; excluir días con quiebre en PT001
- 🟡 Se pide si flujo neto ≤ TOY hasta TOG (lo calcula el motor); la cantidad a pedir se lleva al múltiplo de la unidad de pedido del ítem con el redondeo del PROVEEDOR (arriba por defecto / cercano / abajo). No hay MOQ por ítem
- 🟡 Filtro de comprables = «Criterios comprables» (falta usarlo al calcular la necesidad)
- ✅ Lead time: manda el que se cargue en DDMRP (ítem > proveedor > general); NO se usa el tiempo de entrega de la cotización de Siesa (decidido)
- ✅ Descuentos por rango de cantidad: no se usan hoy en Siesa (no aplica; si algún día se usan, retomar)
- ✅ Varias cotizaciones vigentes del mismo proveedor: no hay (sección E vacía y 047114 da 1 fila, igual que Siesa); el ETL toma, como Siesa, la de mayor fecha de activación por combinación, solo UND y COP
- ✅ Cotización validada contra Siesa: 047114 → 365.546,22 igual en el ETL y en la consulta
- ✅ Cotizaciones en USD: se ignoran (decidido); el ETL solo toma COP
- ✅ Impuesto al consumo: queda FUERA del costo (decidido)
- ⬜ Ítems sin proveedor en Siesa (todos los estados, incluye inactivos): 737 de 7.587 de terceros (0002) y 1.501 de 4.271 de Productos Funat (0001); compras debe asignarlos en Siesa para que entren a la necesidad
- 🟡 Qué se compra: por CATEGORÍA (plan 001) y empresa, en el maestro «Criterios comprables»: Funat (05) compra Terceros (0002) y Maquila (0003), NO Productos Funat (0001); Stores (21) compra todo. (Se descartó la marca «propio» del proveedor: hay maquilas con Laboratorios Funat como proveedor en el ítem)
- ✅ Servidor: el `.env` de producción ya incluye `001:0003` en `SIESA_CRITERIOS_ITEMS` (la maquila entra al maestro y al ETL); el valor por defecto del código y `.env.example` quedaron igual
- 🟡 Proveedor vs cotización (medición previa, incluye inactivos): Terceros 0002 → 7.587 ítems: 737 sin proveedor, 4.998 cotizan con su proveedor, 144 solo con otro, 2.445 sin cotización · Maquila 0003 → 476: 90 sin proveedor, 4 con su proveedor, 65 solo con otro, 407 sin cotización
- ✅ Regla de proveedor (decidida con compras): lo que importa es la COTIZACIÓN. El proveedor de compra es el de la cotización vigente del ítem (varios proveedores → la de mayor fecha de activación); sin cotización se usa el que trae el ítem en Siesa. El maestro de ítems de compras muestra el origen y el proveedor del ítem
- 🟡 Validar el proveedor de cotización con el ETL: `proveedor_de_cotizacion`, `proveedor_del_item`, `proveedor_cotizacion_distinto_del_item`, `items_con_varios_proveedores_cotizando`, `items_sin_proveedor`
- ⬜ Opcional: secciones 4–6 de `docs/sql/proveedor_vs_cotizacion.sql` (cuántos ítems quedan sin cotización y cuántos tienen una OC previa); ya no hacen falta para decidir el proveedor
- 🟡 Costo cuando NO hay cotización: decidido = último costo de compra (precio de la última OC no anulada, línea aprobada/parcial/cumplida). Costo a usar = manual > cotización de Siesa > última compra; el maestro muestra «Origen del costo». Falta validar con el ETL (`items_con_ultimo_costo`, `aviso_ultimo_costo`)
- ⬜ Cotizaciones viejas: hay «vigentes» de 2020–2022 (sin fecha final); marcarlas como viejas pasado un umbral (ej. 12 meses) antes de usarlas en una OC
- ⬜ Zonas con factores parametrizables (prioridad ítem > proveedor > ABC > general)

- 🟡 Ítems sin cotización: se muestran con la marca «Sin cotización» y no suman a los totales (el costo de respaldo es la última compra)
- 🟡 Pedido mínimo del proveedor: config general en Maestros de compras → «Configuración de compras» (`pedido_minimo_bloquea`: 0 alerta / 1 bloquea y no muestra)

## DDMRP (pendientes de la lista original)
- ✅ 1. Menú de compras y permisos (`ver_compras`, `cargar_maestros_compras`, perfil Compras, «Maestros» con desplegable)
- 🟡 2. Maestros: **criterios comprables** · **proveedores** (NIT, sucursal, lead time, correos para/cc, activo, pedido mínimo, contacto, teléfono, notas) · **items de compras** (cotización, unidad de pedido y de empaque; sin crear ni borrar) · lead time del CEDI
- ⬜ 2b. Maestros que faltan: tiendas de compra directa, `item_compra_destino` (etapa 2), factores de zona
- 🟡 3. Proveedor por ítem desde Siesa: ✅ columnas confirmadas (`f120_rowid_tercero_prov`, `f120_id_sucursal_prov`), sin proveedores huérfanos; falta correr el ETL y ver `items_con_proveedor` · ✅ costo de la cotización validado · ✅ IVA por ítem validado
- 🟡 4. Informe «Necesidades de compra» (Informes > Compras): ítems comprables con necesidad, proveedor, cantidad, costo, valor e IVA estimado; Excel
  - 🟡 Navbar: «Necesidades de compra» es un botón propio (como la matriz de despacho); menú «Config» con Motor, Reglas de pedido, Usuarios, Log y Diagnóstico
  - 🟡 Pantalla: SKU y nombre fijos (se pueden fijar más arrastrando), clic en proveedor → sus ítems, clic en inventario/ADU → Control (ítem en todas las tiendas + CEDI), tooltips en todas las columnas/KPI/filtros, modal «¿Cómo funciona?»
  - 🟡 Excel: hoja «Cálculo CEDI» con todo el cálculo en fórmulas (ventas de los últimos meses → ADU → zonas → necesidad → a pedir → valor e IVA) + hoja «Parametros», como la Auditoría
  - 🟡 Cantidad a pedir editable (permiso `gestionar_compras`): se guarda aparte del cálculo (`compras_cantidad`) y SOBREVIVE a las corridas del motor hasta que se monte la OC; alertas si no es múltiplo o supera el doble del buffer
  - 🟡 Botón «Recalcular necesidades» (sin correr el motor completo ni dar acceso a él): inventario fresco del CEDI + OC abiertas + buffer del CEDI; las cantidades editadas se conservan
  - 🟡 Elegir las OC a montar: casilla por proveedor (NIT) y/o por ítem (SKU); «Revisar y enviar OC» muestra una orden por proveedor-empresa y la crea directo en Siesa (aprobada; ver conector de OC). La elección NO se guarda al recargar
  - 🟡 Lead time del proveedor en la vista por proveedor; NIT → maestro de proveedores; SKU → maestro de ítems de compras
  - 🟡 Frecuencia de compra por proveedor (defecto 15 d en «Configuración de compras») = tamaño de la zona verde del CEDI; lead time general 8 d; MOQ por ítem (defecto 1) que sube el pedido al mínimo; la vista de columnas (orden/ancho/fijas) se recuerda por navegador y hay «Restablecer columnas»
  - ⏸ Cotas máxima/mínima del CEDI: explicadas, sin implementar (decisión pendiente)
- 🟡 5. Vista con filtros multi-proveedor, resumen por proveedor, lista «Sin proveedor» y pedido mínimo (alerta o bloqueo, configurable). ⬜ Generación de borradores (BPM)
- ⬜ 6. Estado de OC (grupo asignado, días esperando) + conciliación con el BPM y Siesa
- 🟡 7. Excel por maestro: proveedores e items de compras ya suben y bajan por Excel; ⬜ resto de maestros nuevos

## BPM (nada empezado)
- ⬜ 1 credencial de servicio + endpoint 202 para recibir la OC y `GET /api/oc/{id_externo}`
- ⬜ 2 acción de sistema `crear_oc_siesa` · 3 BPMN `orden_compra_process` · 4 vistas humanas (revisar OC, error de envío, notificaciones)
- ⬜ 5 destinatarios por variable (para/cc) · 6 correo con adjunto · 7 generador de PDF con cola
- ⬜ 8 creador ≠ aprobador al tomar la tarea · 9 recordatorio y escalada · 10 callback de estado a DDMRP
- ⬜ 11 edición de cantidades/costos con revalidación y auditoría · 12 cola con límite de concurrencia · 13 tarea async con reintentos y reconsulta

- 🟡 Condición de pago (`f420_id_cond_pago`): columna en el maestro de proveedores, pre-llenada con la de la última OC del proveedor en Siesa (no pisa lo que escriba compras); sin ella no se creará la OC. ⏸ Decidir si es fija por proveedor o se negocia por OC (`docs/sql/oc_conector.sql`)

## Datos que faltan por pasar
- ✅ 1 ventas del CEDI (query de rotación PT001) · ✅ 3 OC abiertas
- ✅ 2 cotización / costo + tarifa de IVA por ítem (SP `sp_cotizacion_consulta_compra`; se replica su lógica sin llamarlo)
- ✅ 4 proveedor por ítem (columnas confirmadas con `proveedor_item.sql`)
- 🟡 5 Conector de OC: **directo al web service de Siesa** (WSUNOEE `ImportarXML`, plano de ancho fijo 0420 v5 / 0421 v5, como ChaTest con terceros), NO Generic Transfer. Construido: `siesa_oc.py` + `routers/oc.py` + botón en Necesidades (vista previa del plano, crear OC, historial). ⏸ Falta probar en Siesa real (sin ambiente de pruebas; las de prueba se anulan a mano) y llenar `.env` (`SIESA_WS_*`, Stores aparte). Pareja de versiones documento v5 / movimiento v5 por confirmar con el primer envío; si Siesa la rechaza, plan B = Generic Transfer (`docs/OC_CONECTOR.md`)
- ⏸ 6 plantilla del PDF · ⏸ 7 umbral de aprobación y grupos aprobadores

## Validaciones pendientes antes de confiar
1. ETL completo: `oc_abiertas_*`, `ventas_cedi_*`, `items_con_proveedor` / `items_sin_proveedor` / `proveedores_nuevos`, `items_con_cotizacion`, `items_con_iva`; no deben salir `aviso_proveedor`, `aviso_cotizacion`, `aviso_iva`
2. Motor: `cedi_motor` con filas y `tiendas_por_cedi` > 0 en las dos empresas
3. Cuadrar 5–10 ítems del CEDI con compras (rotación, stock, tránsito, zona, lead time)
4. `docs/sql/comparar_cant_cedi.sql`: diferencia 0
5. Cotización: comparar 5–10 ítems del maestro «Items de compras» contra la consulta de Siesa (`docs/sql/cotizacion_item.sql`, secciones A y B)
6. Nombres de los planes LINEA y EXHIBICIÓN en Siesa (la pantalla de ítems de compras los busca por nombre)

## Riesgos que seguimos vigilando
- Necesidad del CEDI mal calculada (aprobarían cantidades equivocadas con apariencia de rigor)
- Duplicados por timeout al crear la OC (probar en pruebas de Siesa, no en producción)
- LibreOffice saturando el Node del BPM
- El diseño sale de lo leído en ChaTest, no de una OC real: el XML de ejemplo puede cambiar el plan

## Envío de OC a Siesa (26-oct-2026)
- ✅ Decidido: referencia `DDMRP` + id con 8 dígitos (13 car.; el campo mide 15); entra aprobada (`f420_ind_estado=1`); comprador = id del usuario (el mismo del reloj); Siesa asigna el consecutivo; Siesa liquida el IVA; contacto del proveedor lo lee Siesa
- 🟡 Anti-duplicados: antes de enviar se consulta t420 por la referencia; un timeout deja la OC `incierta` (no se reenvía a ciegas; hay Reconsultar / Reenviar con espera de 3 min)
- ⬜ Llenar `.env` con `SIESA_WS_URL/USER/PASSWORD/CONEXION/CIA` (y `_S` para Stores) y reconstruir el backend; Stores sin `SIESA_WS_CONEXION_S` no envía
- ⬜ Primer envío de prueba con 1 proveedor y 1–2 ítems; revisar en Siesa (cond. pago, IVA, fecha de entrega, bodega PT001, un. negocio 12) y anular
- ⬜ Si una cotización trae decimales distintos de 2 en COP, ajustar `OC_DECIMALES_PRECIO`
- ⬜ Estado de la OC en Siesa (aprobada/anulada/cumplida) en el historial: hoy solo se lee el consecutivo al crear
- ⏸ BPM (aprobación, PDF, correo): ahora la OC entra aprobada directo; el flujo de aprobación queda para después
