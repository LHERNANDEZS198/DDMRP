# Conector de órdenes de compra

> **Decisión (26-oct-2026): se envía DIRECTO al web service de Siesa (WSUNOEE `ImportarXML`, plano de ancho fijo), no por Generic Transfer.**
> Las secciones de abajo sobre «MyDataSet» quedan como **mapa de campos** (los nombres `f420_*` / `f421_*` son los mismos); lo que cambia es el formato y el envío.

## Ruta directa: lo que ya sabemos (de ChaTest `crear_tercero.py` + el conector de requisiciones)

**Envío** (idéntico al de terceros, se reutiliza tal cual):
- URL por empresa: `https://ws.funat.com.co:9160/WSUNOEE/WSUNOEE.asmx`; operación `ImportarXML`, SOAP 1.1, namespace `http://tempuri.org/`.
- Parámetros: `pvstrDatos` = `<Importar><NombreConexion/><IdCia/><Usuario/><Clave/><Datos><Linea>…</Linea>…</Datos></Importar>` (escapado) y `printTipoError=0`.
- `NombreConexion` decide la base: Funat(05) = `DB_name`, Stores(21) = `DB_name_S`. `IdCia` 1 en Funat (confirmar cía de Stores).
- Éxito = HTTP 200 + `printTipoError == 0`. Error = DataSet ADO.NET con `<Table>` por línea fallida (`f_nro_linea`, `f_tipo_reg`, `f_valor`, `f_detalle` con «Posición inicial: N»). Timeout = `SiesaNoDisponible` → **no se sabe si quedó**; nunca tratar como éxito ni reintentar a ciegas (primero reconsultar por referencia).
- Nunca registrar el sobre ni la respuesta cruda (llevan usuario y clave).

**Formato del plano** (confirmado con el ejemplo real de requisiciones, 1.888 líneas):
- Línea 1: control `0000` → `0000001` + `0000` + `00` + `01` + cía(3).
- Luego los registros, uno por línea, ancho fijo, `F_NUMERO_REG` consecutivo desde 2 (7 dígitos), `F_TIPO_REG` (4 dígitos), subtipo `00`, versión (2), cía (3).
- Última línea: `9999` con el número total de líneas.
- Requisiciones: tipo `0440` (encabezado, 375 car. en la versión usada) y `0441` (movimiento, 2.554 car.). Cantidades `000000000000001.0000`; fechas `AAAAMMDD`; alfanuméricos rellenos con espacios a la derecha; numéricos con ceros a la izquierda.
- `ChaTest.armar_plano`, `_render_registro`, `_control` ya hacen esto con una *spec* de campos (nombre, inicio, tamaño); para OC solo hace falta la spec nueva.
- **La OC irá como tipos `0420` (encabezado) y `0421` (movimiento)**, con la misma estructura. No inventamos posiciones: hay que usar el xls oficial.

**Control de duplicados:** el layout de requisiciones trae `f440_num_docto_referencia` (50 car., «Número de OC») y `f440_referencia` (20, «no se valida»). En OC es `f420_num_docto_referencia`; ahí va `DDMRP-{empresa}-{id_oc}`. Antes de crear: consulta a t420 por esa referencia (ruta directa a la BD, como hace `estado_tercero`); si existe → «ya existe», no se reenvía.

**Cosas que dice el ejemplo y que conviene aplicar:**
1. El consecutivo puede ser automático (`F_CONSEC_AUTO_REG=1`): Siesa asigna el número. En el ejemplo de requisiciones se mandó con número propio (`RIT` + 8 dígitos, uno por documento); para OC usaremos automático y leeremos el consecutivo por referencia.
2. Todo el archivo se importa de una vez (41 documentos y 1.845 movimientos en un solo envío). Para OC: **un envío por OC**, así un error no tumba las demás.
3. Orden de líneas: el movimiento lleva `consec_docto` + `nro_registro` (aquí sí consecutivo 1..n por documento; en el XML Generic Transfer todos iban en 1).

## Layout oficial de OC (xls «Solicitudes O.C. y contratos»): Documentos v5 · Movimientos v5 · Descuentos v2

**Registro 0420, versión 05 (761 car.)** — posiciones inicio/tamaño:
| Campo | Ini | Tam | Valor para DDMRP |
|---|---|---|---|
| F_NUMERO_REG | 1 | 7 | consecutivo del archivo |
| F_TIPO_REG / SUBTIPO / VERSION | 8/12/14 | 4/2/2 | `0420` / `00` / `05` |
| F_CIA | 16 | 3 | cía de la empresa |
| F_LIQUIDA_IMPUESTO | 19 | 1 | **1** (Siesa liquida el IVA; no mandamos registro 423) |
| F_CONSEC_AUTO_REG | 20 | 1 | **1** (Siesa asigna consecutivo) |
| f420_id_co | 21 | 3 | `000` |
| f420_id_tipo_docto | 24 | 3 | `OCM` |
| f420_consec_docto | 27 | 8 | 0 (automático) |
| f420_fecha | 35 | 8 | AAAAMMDD |
| f420_id_concepto | 43 | 3 | `401` fijo |
| f420_id_grupo_clase_docto | 46 | 3 | `402` (órdenes de compra) |
| f420_id_clase_docto | 49 | 3 | `404` (O.C.) |
| f420_ind_estado | 52 | 1 | 0 elaboración / 1 aprobado (por definir) |
| f420_ind_impresion | 53 | 1 | 0 |
| f420_id_tercero_sol_comp | 54 | 15 | cédula del comprador |
| f420_id_tercero_prov | 69 | 15 | NIT proveedor |
| f420_id_sucursal_prov | 84 | 3 | sucursal (ya la tenemos en `proveedor`) |
| f420_id_cond_pago | 87 | 3 | `proveedor.cond_pago` |
| f420_ind_tasa | 90 | 1 | 1 |
| f420_id_moneda_docto / conv / local | 91/94/110 | 3 | `COP` |
| f420_tasa_conv / tasa_local | 97/113 | 13 | 1 |
| descuentos globales 1 y 2 | 126/134 | 8 | vacío/0 |
| f420_notas | 142 | 255 | «Generado por DDMRP» |
| F_IND_CONTACTO | 397 | 1 | **1** (Siesa lee el contacto del proveedor) → se omiten los f419_* (398–715) |
| f420_num_docto_referencia | 716 | **15** | llave anti-duplicados |
| f420_id_mandato | 731 | 15 | vacío |
| f420_ind_consignacion | 746 | 1 | 0 |
| f420_id_tercero_solicit | 747 | 15 | cédula del comprador |

⚠️ **La referencia mide 15 caracteres, no 50.** `DDMRP-05-123456` ya llega a 15. Formato propuesto: `D05-` + id con ceros (`D05-00000123` = 12) o similar, determinista y que no pase de 15.

**Registro 0421, versión 05 (2.792 car.)** — campos que usamos: `id_co`(19,3) `000`, `id_tipo_docto`(22,3) `OCM`, `consec_docto`(25,8), `nro_registro`(33,10) **1..n por documento**, `id_bodega`(98,5) `PT001`, `id_concepto`(103,3) `401`, `id_motivo`(106,2) `01`, `ind_obsequio`(108,1) 0, `id_co_movto`(109,3) `000`, `id_unidad_medida`(144,4) `UND`, `cant_pedida_base`(148,20, `000000000000012.0000`), `fecha_entrega`(168,8) = fecha OC + lead time, `precio_unitario`(191,20, 15 enteros + punto + 4 decimales), `notas`(211,255), `referencia_item`(2517,50), `id_un_movto`(2627,20) `12`. El resto (campos vacíos, proyecto, ccosto, descripción, ext1/ext2, OP) va en blanco.

**Registro 0422 (descuentos v2):** no se usa (decisión: descuentos por rango fuera). **0423 (impuestos):** no se manda, `F_LIQUIDA_IMPUESTO=1`.

⚠️ **Ojo con las versiones:** el xls dice que «Movimientos V.5» es *solo para versión 3 de documento*, y que V.6 es para documento v4. Ninguna hoja de movimiento declara compatibilidad con documento v5. Probablemente se puede mezclar, pero hay que confirmarlo en ambiente de pruebas: si no calza, el WS devuelve «Posición inicial: N» y el error es claro. Alternativa más segura: documento v5 + el movimiento que pida Siesa (v.8 es para documento 7/8).

## Estado de la construcción (26-oct-2026)
Construido: `backend_python/app/siesa_oc.py` (plano 0420/0421 v5, SOAP, anti-duplicados), `routers/oc.py` (`POST /api/compras/oc/enviar`, `GET /api/compras/oc`, `/{id}/reconsultar`, `/{id}/reenviar`) y el diálogo de Necesidades. Decisiones del 26-oct: referencia `DDMRP00000123`; entra aprobada; comprador = id del usuario (reloj); sin ambiente de pruebas (se prueba en real y se anula). Variables de entorno `SIESA_WS_*` en `.env.example`.
Plan B si Siesa rechaza la pareja documento v5 / movimiento v5: el error trae el campo y la posición; probar movimiento V.6 u otra versión, y solo si no, Generic Transfer.

## Qué falta (histórico)
1. ~~xls de OC~~ **recibido** (ver layout arriba). Falta confirmar la pareja de versiones documento v5 / movimiento v5 en pruebas.
2. Credenciales/URL de Stores (21): `NombreConexion`, cía, usuario. ¿Mismo usuario del WS que ChaTest o uno de servicio para DDMRP/BPM?
3. Un ejemplo de respuesta **OK** de ImportarXML (en terceros ¿qué devuelve exactamente cuando acepta? ¿trae consecutivo?) y uno de error.
4. Si la OC puede entrar ya **aprobada** (`f420_ind_estado=1`) o hay que entrarla «en elaboración» (0) y aprobarla después. Importa por el flujo de aprobación del BPM.
5. Largo real de `f420_num_docto_referencia` (docs/sql/oc_conector.sql, secciones 1–2).
6. Cédula del comprador (`id_tercero_sol_comp` / `id_tercero_solicit`): ¿de dónde sale? (tabla usuarios→cédula) y en requisiciones el solicitante es de solo **5 caracteres**; en OC puede ser distinto: ver xls.
7. Para Stores: CO, tipo OCM, motivo 01, unidad de negocio 12.

**Cuidado con el txt de requisiciones:** vi que corresponde a *abastecimiento* (tipo 440/441, bodega PT001 → tiendas, concepto 605). Eso es el *otro* flujo (DDMRP ya sugiere traslados). Sirve de referencia de formato, no para OC.

---

## (Histórico) Mapa de campos — venía del XML de Generic Transfer

Ejemplo real del flujo actual (AuraPortal BPMS, formato **Generic Transfer**): `docs/conectores/oc_siesa_ejemplo.xml`. Tipo de documento: **OCM** (se sigue usando).
Los nombres de las etiquetas son los de las columnas de `t420_cm_oc_docto` (encabezado) y `t421_cm_oc_movto` (líneas).

## (Descartado) Cómo se enviaba: Generic Transfer
El XML de ejemplo **es el formato correcto**: Generic Transfer (GT) es la capa de integración por la que ya entran los pedidos de Shopify (`ChaTest/shopify_app/crearXML.py`). No se llama al servicio web nativo de Siesa: se llama al de GT.

- **Servicio:** `https://ws.funat.com.co:9160/GTIntegration<instancia>/ServiciosWeb/wsGenerarPlano.asmx`, operación SOAP `ImportarDatosXML` (espacio de nombres `http://generictransfer.com/`). Una instancia por empresa: `GTIntegrationfunatreal` (05) y `GTIntegrationStorereal` (21).
- **Parámetros de la llamada:** `idDocumento` (número del documento/conector en GT), `strNombreDocumento`, `idCompania` (compañía en GT), `strCompania` (compañía en Siesa), `strUsuario`, `strClave`, `Path` y `strFuenteDatos` = **el XML `MyDataSet`** (en CDATA).
- **De dónde salen los parámetros:** `EXEC FN_ParametrosConsumoSiesaWS <id>` en la base intermedia de GT (devuelve `NumeroDocumento`, `NombreDocumento`, `CompaniaGT`, `CompaniaSiesa`, `Usuario`, `Contrasena`, `Path`). Así los lee ChaTest; el BPM debe leerlos igual (una sola fuente, sin copiar credenciales).
- **Respuesta:** texto en `ImportarDatosXMLResult` (éxito o detalle del error). Hay que ver cómo responde GT al crear una OC bien y mal para interpretarlo; el consecutivo asignado se consulta después en Siesa por `f420_num_docto_referencia`.
- **Lo que falta:** el `id` del documento GT de la **OC** (el que usa hoy AuraPortal, o uno nuevo para DDMRP) en cada empresa. Se averigua con `docs/sql/oc_conector.sql` (sección 9).

## Encabezado (`Documentos`): una OC por proveedor y empresa
| Campo XML | Valor | De dónde sale en DDMRP / BPM |
|---|---|---|
| `F_CIA` | 1 | Compañía de la base de Siesa de la empresa (05 y 21 tienen su propia base) |
| `f420_id_co` | 000 | Centro de operación del documento (config por empresa) |
| `f420_id_tipo_docto` | **OCM** | Tipo de documento (config por empresa; confirmar que Stores también usa OCM) |
| `f420_consec_docto` | 0 | **0 = Siesa asigna el consecutivo** (lo controla Siesa) |
| `f420_fecha` | AAAAMMDD | Fecha de creación |
| `f420_ind_estado` | 1 | La OC se crea **aprobada** (la aprobación ya ocurrió en el BPM) |
| `f420_id_tercero_sol_comp` / `f420_id_tercero_solicit` | cédula | **Cédula del comprador** (las dos iguales). Falta de dónde sale: ver «Pendientes» |
| `f420_id_tercero_prov` | NIT | `proveedor.proveedor_id` (NIT del proveedor de la cotización). **No hay sucursal en el XML** |
| `f420_id_cond_pago` | C30 | **Condición de pago** (ver abajo) |
| `f420_ind_tasa`, `f420_tasa_conv`, `f420_tasa_local` | 1, 1, 1 | Constantes (COP) |
| `f420_id_moneda_docto` | COP | Constante (las cotizaciones en USD se ignoran) |
| `f420_notas` | texto | «Orden de Compra generada desde DDMRP» (+ la referencia) |
| `f420_num_docto_referencia` | 662743 | **Llave de idempotencia**: donde Siesa controla que no se repitan las OC. Antes de crear se consulta si ya existe; si Siesa rechaza por duplicada = «ya existe». Falta confirmar largo y tipo |

## Líneas (`Movimientos`): una por ítem
| Campo XML | Valor | De dónde sale |
|---|---|---|
| `f421_referencia_item` | SKU | `producto_id` |
| `f421_cant_pedida_base` | cantidad (10 decimales) | **A pedir** (la editable de Necesidades de compra) |
| `f421_precio_unitario` | costo unitario | **Costo a usar** (manual › cotización › última compra); Siesa respeta el costo que se envía |
| `f421_id_unidad_medida` | UND | Todo es UND |
| `f421_fecha_entrega` | AAAAMMDD | **Fecha de la OC + lead time** del ítem / proveedor (en el ejemplo: 8 días) |
| `f421_id_bodega` | PT001 | Bodega del CEDI de la empresa (en la etapa 2, la tienda con compra directa) |
| `f421_id_motivo` | 01 | Constante |
| `f421_id_un_movto` | 12 | Unidad de negocio del movimiento (config por empresa) |
| `f421_id_co_movt` | 000 | Centro de operación del movimiento |
| `f421_notas` | descripción | Nombre del ítem |
| `f421_nro_registro` | 1 | **En el ejemplo todas las líneas llevan 1** (no es consecutivo): confirmar si se debe replicar así o numerar 1..n |
| `f421_ind_obsequio`, `f421_cod_item_prov`, `f421_detalle`, `f421_id_ccosto_movto`, `f421_id_ext1/2_detalle` | 0 / vacíos | Constantes |

**No viaja en el XML:** el IVA (Siesa lo calcula al montar la OC, por eso en DDMRP es «estimado»), la sucursal del proveedor, el descuento.

## Condición de pago (`f420_id_cond_pago`)
- Define los plazos de pago: es plata. Una condición equivocada se paga mal o se causa mal.
- DDMRP la guarda en el **maestro de proveedores** (`cond_pago`, ej. `C30`). Al sincronizar ítems se **pre-llena** con la que se usó en la **última OC** de ese proveedor en Siesa, solo si está vacía; lo que escriba compras no se pisa.
- Regla propuesta: **no se crea la OC si el proveedor no tiene condición de pago**, y se muestra en la revisión de la OC y en la aprobación.
- Verificación en Siesa: `docs/sql/oc_conector.sql`.

## Pendientes antes de construir el envío
1. ¿La condición de pago es fija por proveedor o se negocia en cada OC? (si se negocia: editable en la revisión, con la del proveedor como valor inicial)
2. De dónde sale la **cédula del comprador** (¿el código de usuario de reloj es la cédula? si no, se guarda en Usuarios)
3. Largo máximo y tipo de `f420_num_docto_referencia` (consulta en `oc_conector.sql`) para definir el formato de la referencia
4. ¿OCM, centro de operación 000, motivo 01 y unidad de negocio 12 también en Stores (21)?
5. `f421_nro_registro`: ¿1 en todas las líneas a propósito?
6. Falta el conector XML de **abastecimiento** (solo llegó el de compras; seguramente es otro documento GT, el de los traslados que hoy salen por plano de Excel)
7. `id` del documento GT de la OC en 05 y en 21, y un ejemplo de la **respuesta** de GT (éxito y error)
