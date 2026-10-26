-- Verificacion de la cotizacion y el IVA por item (correr en SSMS, base de Siesa de cada compania). El ETL usa SQL_COTIZACIONES y SQL_IVA_ITEM
-- (backend_python/app/etl/replicacion.py): misma logica de sp_cotizacion_consulta_compra, pero directo sobre las tablas y en UNA consulta.
-- Cambia @ref por referencias reales (ej. 17) y compara A (lo que calcula el ETL) con B (lo que muestra la consulta de Siesa).

DECLARE @ref varchar(50) = '391003';   -- ojo: la 17 es una materia prima sin cotizacion. Prueba con 391003, 391007, 391014 o 182033 (tienen cotizacion)

-- A) Cotizaciones vigentes de la referencia, con el costo bruto como lo calcula el ETL (precio - descuento del PRIMER rango de cantidad)
WITH vig AS (
  SELECT c.f212_rowid AS rowid, c.f212_rowid_tercero AS tercero, c.f212_id_sucursal AS sucursal, c.f212_rowid_item_ext AS item_ext, c.f212_id_moneda AS moneda,
         c.f212_precio AS precio, c.f212_fecha_activacion AS activacion,
         ROW_NUMBER() OVER (PARTITION BY c.f212_rowid_tercero, c.f212_id_sucursal, c.f212_rowid_item_ext, c.f212_id_moneda, c.f212_id_um,
                                         ISNULL(c.f212_id_co, ''), ISNULL(c.f212_id_instalacion, '')
                            ORDER BY c.f212_fecha_activacion DESC, c.f212_rowid DESC) AS rn
  FROM t212_mm_cotizaciones c
  WHERE c.f212_id_cia = 1 AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
)
SELECT RTRIM(i.f120_referencia) AS referencia, RTRIM(t.f200_id) AS nit, RTRIM(v.sucursal) AS sucursal, RTRIM(v.moneda) AS moneda, v.activacion,
       v.precio, ISNULL(d.f214_valor_dscto, 0) AS dscto_valor, ISNULL(d.f214_porcentaje_dscto, 0) AS dscto_pct,
       v.precio - CASE WHEN ISNULL(d.f214_valor_dscto, 0) <> 0 THEN d.f214_valor_dscto ELSE v.precio * ISNULL(d.f214_porcentaje_dscto, 0) / 100 END AS costo_bruto_etl
FROM vig v
JOIN t121_mc_items_extensiones x ON x.f121_rowid = v.item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
JOIN t200_mm_terceros t ON t.f200_rowid = v.tercero
OUTER APPLY (SELECT TOP 1 d2.f214_valor_dscto, d2.f214_porcentaje_dscto FROM t214_mm_cotizacion_dscto d2
             WHERE d2.f214_rowid_cotizacion = v.rowid ORDER BY d2.f214_cantidad_hasta ASC, d2.f214_orden ASC) d
WHERE v.rn = 1 AND i.f120_id_cia = 1 AND RTRIM(i.f120_referencia) = @ref;

-- B) Lo que muestra la consulta de Siesa para el mismo item (compara su columna de costo bruto con costo_bruto_etl de arriba)
DECLARE @rowid_item int = (SELECT TOP 1 f120_rowid FROM t120_mc_items WHERE f120_id_cia = 1 AND RTRIM(f120_referencia) = @ref);
EXEC sp_cotizacion_consulta_compra @p_cia = 1, @p_tipo_proveedor = NULL, @p_rowid_proveedor = NULL, @p_tipo_inv = NULL, @p_moneda = NULL,
     @p_fecha_activacion = NULL, @p_tiempo_entrega = NULL, @p_cons_tipo = 10047, @p_cons_nombre = N'Cotizaciones', @p_fecha_hasta = NULL,
     @p_ind_cotizaciones_vigentes = 1, @p_lista_precios = NULL, @p_id_clase_imp = 1, @p_rowid_usuario = 6, @p_rowid_item = @rowid_item;

-- C) Tarifa de IVA que usa el ETL para esa referencia (grupo impositivo del item -> llave de impuesto de la clase 1; solo calculo por tasa)
SELECT RTRIM(i.f120_referencia) AS referencia, i.f120_id_grupo_impositivo AS grupo, l.f037_tasa AS tasa, l.f037_ind_calculo AS ind_calculo
FROM t120_mc_items i
JOIN t114_mc_grupos_impo_impuestos g ON g.f114_grupo_impositivo = i.f120_id_grupo_impositivo AND g.f114_id_cia = i.f120_id_cia AND g.f114_id_clase_impuesto = 1
JOIN t037_mm_llaves_impuesto l ON l.f037_id = g.f114_id_llave_impuesto AND l.f037_id_cia = g.f114_id_cia
WHERE i.f120_id_cia = 1 AND RTRIM(i.f120_referencia) = @ref;

-- D) Cobertura: cotizaciones vigentes por moneda (el ETL solo toma la moneda de compra, SIESA_MONEDA_COMPRA = COP)
SELECT RTRIM(f212_id_moneda) AS moneda, COUNT(*) AS cotizaciones
FROM t212_mm_cotizaciones
WHERE f212_id_cia = 1 AND f212_fecha_activacion <= GETDATE() AND (f212_fecha_hasta IS NULL OR GETDATE() BETWEEN f212_fecha_activacion AND f212_fecha_hasta)
GROUP BY f212_id_moneda;

-- E) Items con VARIAS cotizaciones realmente vigentes de un mismo proveedor, o sea DESPUES de quedarse con la de mayor fecha de activacion por cada
--    proveedor-sucursal-item-moneda-UM-CO-instalacion (lo mismo que hace Siesa con «Solo vigentes» y el ETL). OJO: contar solo la ventana de fechas
--    da cifras infladas, porque las cotizaciones viejas que nunca se cerraron (fecha final vacia) siguen «dentro de fechas» aunque las reemplazo una mas nueva.
WITH vig AS (
  SELECT c.f212_rowid_tercero AS tercero, c.f212_rowid_item_ext AS item_ext,
         ROW_NUMBER() OVER (PARTITION BY c.f212_rowid_tercero, c.f212_id_sucursal, c.f212_rowid_item_ext, c.f212_id_moneda, c.f212_id_um,
                                         ISNULL(c.f212_id_co, ''), ISNULL(c.f212_id_instalacion, '')
                            ORDER BY c.f212_fecha_activacion DESC, c.f212_rowid DESC) AS rn
  FROM t212_mm_cotizaciones c
  WHERE c.f212_id_cia = 1 AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
)
SELECT TOP 30 RTRIM(i.f120_referencia) AS referencia, RTRIM(t.f200_id) AS nit, COUNT(*) AS vigentes
FROM vig v
JOIN t121_mc_items_extensiones x ON x.f121_rowid = v.item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
JOIN t200_mm_terceros t ON t.f200_rowid = v.tercero
WHERE v.rn = 1
GROUP BY i.f120_referencia, t.f200_id
HAVING COUNT(*) > 1
ORDER BY vigentes DESC;

-- F) Todas las cotizaciones de la referencia dentro de fechas, marcando cual es la VIGENTE de verdad (ultima = 1). Ej. 047114: Siesa muestra 1.
SELECT RTRIM(i.f120_referencia) AS referencia, RTRIM(t.f200_id) AS nit, RTRIM(c.f212_id_sucursal) AS sucursal, RTRIM(c.f212_id_moneda) AS moneda, RTRIM(c.f212_id_um) AS um,
       RTRIM(ISNULL(c.f212_id_co, '')) AS co, RTRIM(ISNULL(c.f212_id_instalacion, '')) AS instalacion, c.f212_fecha_activacion AS activacion, c.f212_fecha_hasta AS hasta,
       c.f212_precio AS precio,
       CASE WHEN ROW_NUMBER() OVER (PARTITION BY c.f212_rowid_tercero, c.f212_id_sucursal, c.f212_rowid_item_ext, c.f212_id_moneda, c.f212_id_um,
                                                 ISNULL(c.f212_id_co, ''), ISNULL(c.f212_id_instalacion, '')
                                    ORDER BY c.f212_fecha_activacion DESC, c.f212_rowid DESC) = 1 THEN 1 ELSE 0 END AS ultima
FROM t212_mm_cotizaciones c
JOIN t121_mc_items_extensiones x ON x.f121_rowid = c.f212_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
JOIN t200_mm_terceros t ON t.f200_rowid = c.f212_rowid_tercero
WHERE c.f212_id_cia = 1 AND RTRIM(i.f120_referencia) = '047114'
  AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
ORDER BY c.f212_fecha_activacion DESC;

-- G) Las 11 cotizaciones vigentes en USD: que items son (el ETL solo toma la moneda de compra, COP)
SELECT RTRIM(i.f120_referencia) AS referencia, RTRIM(i.f120_descripcion) AS item, RTRIM(t.f200_id) AS nit, c.f212_precio AS precio_usd
FROM t212_mm_cotizaciones c
JOIN t121_mc_items_extensiones x ON x.f121_rowid = c.f212_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
JOIN t200_mm_terceros t ON t.f200_rowid = c.f212_rowid_tercero
WHERE c.f212_id_cia = 1 AND RTRIM(c.f212_id_moneda) = 'USD'
  AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta);
