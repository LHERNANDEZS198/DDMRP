# Módulo de compras en DDMRP: checklist

Estados: ✅ listo · 🟡 hecho, sin validar en producción · ⬜ pendiente · ⏸ espera datos o una decisión.
Última actualización: 26 oct 2026 (cotización e IVA).

## Base de datos y cálculo (fase 1: «solo lee y calcula»)
- 🟡 Rotación de PT001: ventas directas del CEDI (`ventas_cedi_05/21`) + ventas de las tiendas que abastece
- 🟡 Buffer del CEDI por empresa (motor Rust, `--modo cedi`, tabla `sugerencias_cedi`): ADU, zonas, flujo neto
- 🟡 Tránsito del CEDI = saldo de OC abiertas de Siesa (estado del ítem Aprobado o Parcial); tope de antigüedad `oc_dias_historia` (365)
- 🟡 Lead time del CEDI: ítem > proveedor del ítem > general (30 d) — maestro «Lead time del CEDI» y «Proveedores»
- 🟡 Informes en modo «Ver solo CEDI»: Control (foto/cambios/tendencia/mapa), Alertas, Salud y Clasificación
- ⬜ Retroprueba: validar la necesidad del CEDI contra lo que compras realmente pidió
- ⬜ Ítems con poca historia → revisión manual; picos atípicos como demanda calificada o recortados; excluir días con quiebre en PT001
- ⬜ Se pide si flujo neto ≤ TOY hasta TOG, redondeado a múltiplo de compra y respetando MOQ
- ⬜ Filtro de comprables (plan 001: 0002 Productos de terceros sí, 0001 Productos Funat no; maquila = compra) — editable
- ⬜ Lead time desde el tiempo de entrega de la cotización (f212_tiempo_entrega; en los ejemplos siempre 8): validar con compras que sea real antes de usarlo como capa del lead time
- ✅ Descuentos por rango de cantidad: no se usan hoy en Siesa (no aplica; si algún día se usan, retomar)
- ✅ Varias cotizaciones vigentes del mismo proveedor: no hay (sección E vacía y 047114 da 1 fila, igual que Siesa); el ETL toma, como Siesa, la de mayor fecha de activación por combinación, solo UND y COP
- ✅ Cotización validada contra Siesa: 047114 → 365.546,22 igual en el ETL y en la consulta
- ✅ Cotizaciones en USD: se ignoran (decidido); el ETL solo toma COP
- ⬜ Impuesto al consumo: queda FUERA del costo (decidido)
- ⬜ Ítems sin proveedor en Siesa (todos los estados, incluye inactivos): 737 de 7.587 de terceros (0002) y 1.501 de 4.271 de Productos Funat (0001); compras debe asignarlos en Siesa para que entren a la necesidad
- ⏸ Decidir: ítems cuyo proveedor es Laboratorios Funat (NIT 811000340, 3.295 ítems) = producción propia, no generan OC (maquila con otro proveedor sí se compra)
- ⬜ Zonas con factores parametrizables (prioridad ítem > proveedor > ABC > general)

## DDMRP (pendientes de la lista original)
- ✅ 1. Menú de compras y permisos (`ver_compras`, `cargar_maestros_compras`, perfil Compras, «Maestros» con desplegable)
- 🟡 2. Maestros: **proveedores** (NIT, sucursal, lead time, correos para/cc, activo, pedido mínimo, contacto, teléfono, notas) · **items de compras** (cotización, unidad de pedido y de empaque; sin crear ni borrar) · lead time del CEDI
- ⬜ 2b. Maestros que faltan: empaque/MOQ por proveedor-ítem si hace falta, criterios comprables, tiendas de compra directa, `item_compra_destino` (etapa 2), factores de zona
- 🟡 3. Proveedor por ítem desde Siesa: ✅ columnas confirmadas (`f120_rowid_tercero_prov`, `f120_id_sucursal_prov`), sin proveedores huérfanos; falta correr el ETL y ver `items_con_proveedor` · ✅ costo de la cotización validado · 🟡 IVA por ítem (falta validar la tarifa)
- ⬜ 4. Necesidad a nivel CEDI como informe de compras (lo calculado ya existe; falta la vista de «qué pedir»)
- ⬜ 5. Vista de necesidades con filtros multi-proveedor y generación de borradores
- ⬜ 6. Estado de OC (grupo asignado, días esperando) + conciliación con el BPM y Siesa
- 🟡 7. Excel por maestro: proveedores e items de compras ya suben y bajan por Excel; ⬜ resto de maestros nuevos

## BPM (nada empezado)
- ⬜ 1 credencial de servicio + endpoint 202 para recibir la OC y `GET /api/oc/{id_externo}`
- ⬜ 2 acción de sistema `crear_oc_siesa` · 3 BPMN `orden_compra_process` · 4 vistas humanas (revisar OC, error de envío, notificaciones)
- ⬜ 5 destinatarios por variable (para/cc) · 6 correo con adjunto · 7 generador de PDF con cola
- ⬜ 8 creador ≠ aprobador al tomar la tarea · 9 recordatorio y escalada · 10 callback de estado a DDMRP
- ⬜ 11 edición de cantidades/costos con revalidación y auditoría · 12 cola con límite de concurrencia · 13 tarea async con reintentos y reconsulta

## Datos que faltan por pasar
- ✅ 1 ventas del CEDI (query de rotación PT001) · ✅ 3 OC abiertas
- ✅ 2 cotización / costo + tarifa de IVA por ítem (SP `sp_cotizacion_consulta_compra`; se replica su lógica sin llamarlo)
- ✅ 4 proveedor por ítem (columnas confirmadas con `proveedor_item.sql`)
- ⏸ 5 XML/conector de OC de Siesa (campos, largo de la referencia, tipo de documento por empresa)
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
