-- Revision: ¿el proveedor del ITEM (pestaña Generales) es el mismo de su COTIZACION vigente? Sobre todo en maquila (001/0003), donde el item puede venir con
-- Laboratorios Funat como proveedor aunque la cotizacion sea del laboratorio que maquila. Correr en SSMS (base de Siesa de cada compania).
-- Misma logica que el ETL: cotizacion vigente = la de mayor fecha de activacion por proveedor-sucursal-item-moneda-UM-CO-instalacion, en COP y UND.

-- @solo_activos = 1: solo items con alguna extension ACTIVA (los que ve compras en DDMRP); 0 = todos los items de Siesa (incluye inactivos y obsoletos)
DECLARE @solo_activos bit = 1;

IF OBJECT_ID('tempdb..#vig') IS NOT NULL DROP TABLE #vig;
IF OBJECT_ID('tempdb..#it') IS NOT NULL DROP TABLE #it;

SELECT x.f121_rowid_item AS rowid_item, v.f212_rowid_tercero AS tercero, v.f212_id_sucursal AS sucursal, v.f212_precio AS precio, v.f212_fecha_activacion AS activacion
INTO #vig
FROM (
  SELECT c.*, ROW_NUMBER() OVER (PARTITION BY c.f212_rowid_tercero, c.f212_id_sucursal, c.f212_rowid_item_ext, c.f212_id_moneda, c.f212_id_um,
                                              ISNULL(c.f212_id_co, ''), ISNULL(c.f212_id_instalacion, '')
                                 ORDER BY c.f212_fecha_activacion DESC, c.f212_rowid DESC) AS rn
  FROM t212_mm_cotizaciones c
  WHERE c.f212_id_cia = 1 AND RTRIM(c.f212_id_moneda) = 'COP' AND RTRIM(c.f212_id_um) = 'UND'
    AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
) v
JOIN t121_mc_items_extensiones x ON x.f121_rowid = v.f212_rowid_item_ext
WHERE v.rn = 1;

SELECT i.f120_rowid AS rowid_item, RTRIM(i.f120_referencia) AS referencia, RTRIM(i.f120_descripcion) AS item, RTRIM(cm.f125_id_criterio_mayor) AS categoria,
       i.f120_rowid_tercero_prov AS prov_item, i.f120_id_sucursal_prov AS suc_item
INTO #it
FROM t120_mc_items i
JOIN t125_mc_items_criterios cm ON cm.f125_rowid_item = i.f120_rowid AND cm.f125_id_plan = '001' AND RTRIM(cm.f125_id_criterio_mayor) IN ('0002', '0003')
WHERE i.f120_id_cia = 1
  AND (@solo_activos = 0 OR EXISTS (SELECT 1 FROM t121_mc_items_extensiones x WHERE x.f121_rowid_item = i.f120_rowid AND x.f121_ind_estado = 1));

-- 1) Resumen por categoria (0002 terceros, 0003 maquila): cuantos items tienen cotizacion de SU proveedor, de OTRO proveedor o de ninguno
--    (primero se marca cada item y despues se suma: SQL Server no admite una subconsulta dentro de un SUM)
SELECT x.categoria,
       COUNT(*) AS items,
       SUM(x.sin_prov) AS sin_proveedor,
       SUM(x.su_prov) AS cotiza_su_proveedor,
       SUM(CASE WHEN x.su_prov = 0 AND x.alguna = 1 THEN 1 ELSE 0 END) AS cotiza_solo_otro_proveedor,
       SUM(CASE WHEN x.alguna = 0 THEN 1 ELSE 0 END) AS sin_cotizacion
FROM (
  SELECT it.categoria,
         CASE WHEN it.prov_item IS NULL THEN 1 ELSE 0 END AS sin_prov,
         CASE WHEN EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item AND v.tercero = it.prov_item AND v.sucursal = it.suc_item) THEN 1 ELSE 0 END AS su_prov,
         CASE WHEN EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item) THEN 1 ELSE 0 END AS alguna
  FROM #it it
) x
GROUP BY x.categoria
ORDER BY x.categoria;

-- 2) Detalle de los que NO coinciden (el proveedor del item no tiene cotizacion vigente pero otro si): primero los de maquila
SELECT TOP 300 it.categoria, it.referencia, it.item,
       RTRIM(tp.f200_id) AS nit_item, RTRIM(tp.f200_razon_social) AS proveedor_item,
       RTRIM(tc.f200_id) AS nit_cotizacion, RTRIM(tc.f200_razon_social) AS proveedor_cotizacion, v.precio, v.activacion
FROM #it it
JOIN #vig v ON v.rowid_item = it.rowid_item
LEFT JOIN t200_mm_terceros tp ON tp.f200_rowid = it.prov_item
LEFT JOIN t200_mm_terceros tc ON tc.f200_rowid = v.tercero
WHERE NOT EXISTS (SELECT 1 FROM #vig v2 WHERE v2.rowid_item = it.rowid_item AND v2.tercero = it.prov_item AND v2.sucursal = it.suc_item)
ORDER BY it.categoria DESC, it.referencia;

-- 3) Cuantos items de maquila (0003) y de terceros (0002) trae cada proveedor del ITEM: Laboratorios Funat (811000340) en maquila seria la senal de que el item esta mal asignado
SELECT it.categoria, RTRIM(tp.f200_id) AS nit_item, RTRIM(tp.f200_razon_social) AS proveedor_item, COUNT(*) AS items
FROM #it it LEFT JOIN t200_mm_terceros tp ON tp.f200_rowid = it.prov_item
GROUP BY it.categoria, tp.f200_id, tp.f200_razon_social
ORDER BY it.categoria, items DESC;

-- 4) ¿Cuantos de los "no coinciden" son solo cuestion de SUCURSAL? (el mismo proveedor, pero el item tiene la sucursal 001 y la cotizacion otra). El ETL y esta consulta
--    comparan proveedor Y sucursal; si aqui sale un numero alto, el "desacuerdo" es mas aparente que real.
SELECT it.categoria, COUNT(DISTINCT it.rowid_item) AS items_mismo_proveedor_otra_sucursal
FROM #it it
JOIN #vig v ON v.rowid_item = it.rowid_item AND v.tercero = it.prov_item AND v.sucursal <> it.suc_item
WHERE NOT EXISTS (SELECT 1 FROM #vig v2 WHERE v2.rowid_item = it.rowid_item AND v2.tercero = it.prov_item AND v2.sucursal = it.suc_item)
GROUP BY it.categoria ORDER BY it.categoria;

-- 5) Items "sin cotizacion" que SI tienen una cotizacion vigente en OTRA moneda o unidad de medida (el ETL solo toma COP y UND): son falsos "sin cotizacion"
SELECT it.categoria, RTRIM(c.f212_id_moneda) AS moneda, RTRIM(c.f212_id_um) AS um, COUNT(DISTINCT it.rowid_item) AS items
FROM #it it
JOIN t121_mc_items_extensiones x ON x.f121_rowid_item = it.rowid_item
JOIN t212_mm_cotizaciones c ON c.f212_rowid_item_ext = x.f121_rowid AND c.f212_id_cia = 1
     AND c.f212_fecha_activacion <= GETDATE() AND (c.f212_fecha_hasta IS NULL OR GETDATE() BETWEEN c.f212_fecha_activacion AND c.f212_fecha_hasta)
WHERE NOT EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item)
GROUP BY it.categoria, c.f212_id_moneda, c.f212_id_um
ORDER BY it.categoria, items DESC;

-- 6) De los items SIN cotizacion (COP/UND), cuantos tienen una OC previa (no anulada, linea aprobada / parcial / cumplida): son los que tendran ULTIMO COSTO DE COMPRA
SELECT y.categoria, COUNT(*) AS items_sin_cotizacion, SUM(y.con_oc) AS con_ultimo_costo, COUNT(*) - SUM(y.con_oc) AS sin_ningun_costo
FROM (
  SELECT it.categoria,
         CASE WHEN EXISTS (SELECT 1 FROM t421_cm_oc_movto m
                           JOIN t420_cm_oc_docto d ON d.f420_rowid = m.f421_rowid_oc_docto
                           JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f421_rowid_item_ext
                           WHERE x.f121_rowid_item = it.rowid_item AND d.f420_ind_estado <> 9 AND m.f421_ind_estado IN (1, 2, 3) AND m.f421_precio_unitario > 0) THEN 1 ELSE 0 END AS con_oc
  FROM #it it
  WHERE NOT EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item)
) y
GROUP BY y.categoria ORDER BY y.categoria;

DROP TABLE #vig; DROP TABLE #it;
