-- Revision: ¿el proveedor del ITEM (pestaña Generales) es el mismo de su COTIZACION vigente? Sobre todo en maquila (001/0003), donde el item puede venir con
-- Laboratorios Funat como proveedor aunque la cotizacion sea del laboratorio que maquila. Correr en SSMS (base de Siesa de cada compania).
-- Misma logica que el ETL: cotizacion vigente = la de mayor fecha de activacion por proveedor-sucursal-item-moneda-UM-CO-instalacion, en COP y UND.

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
WHERE i.f120_id_cia = 1;

-- 1) Resumen por categoria (0002 terceros, 0003 maquila): cuantos items tienen cotizacion de SU proveedor, de OTRO proveedor o de ninguno
SELECT it.categoria,
       COUNT(*) AS items,
       SUM(CASE WHEN it.prov_item IS NULL THEN 1 ELSE 0 END) AS sin_proveedor,
       SUM(CASE WHEN EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item AND v.tercero = it.prov_item AND v.sucursal = it.suc_item) THEN 1 ELSE 0 END) AS cotiza_su_proveedor,
       SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item AND v.tercero = it.prov_item AND v.sucursal = it.suc_item)
                 AND EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item) THEN 1 ELSE 0 END) AS cotiza_solo_otro_proveedor,
       SUM(CASE WHEN NOT EXISTS (SELECT 1 FROM #vig v WHERE v.rowid_item = it.rowid_item) THEN 1 ELSE 0 END) AS sin_cotizacion
FROM #it it
GROUP BY it.categoria
ORDER BY it.categoria;

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

DROP TABLE #vig; DROP TABLE #it;
