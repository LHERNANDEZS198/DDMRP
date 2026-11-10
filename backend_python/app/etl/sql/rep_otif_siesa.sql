-- Reportes de compras: cumplimiento del proveedor (OTIF) por linea de OC (OC x item). Misma base que Cumplimiento de proveedores (routers/cumplimiento.py): la entrada REAL de
-- cada OC es el documento de compras (t451, que apunta a la OC por f451_rowid_oc_docto) y su fecha (t350.f350_fecha); aqui se toma la ULTIMA entrada de la OC.
-- Parametros: :cia (SIESA_CIA) y :desde (fecha de la OC desde la que se mide).
-- Devuelve: oc, referencia, proveedor_id (NIT), proveedor_nombre, fecha_oc, fecha_pactada (la mas cercana de las lineas del item), cant_pedida, cant_entrada, fecha_entrada (ultima, NULL si no hay).
--   El ETL calcula a tiempo (ultima entrada <= fecha pactada + dias de gracia) y completa (recibido >= % de lo pedido); ambos umbrales se editan en Reglas de compras.
-- Lineas con estado de linea 1, 2 o 3 (aprobada, parcial, cumplida) y OC no anuladas (f420_ind_estado <> 9).
SELECT RTRIM(d.f420_id_tipo_docto) + '-' + RTRIM(CONVERT(varchar(12), d.f420_consec_docto)) AS oc,
       RTRIM(i.f120_referencia) AS referencia,
       RTRIM(t.f200_id) AS proveedor_id,
       RTRIM(t.f200_razon_social) AS proveedor_nombre,
       CONVERT(date, d.f420_fecha) AS fecha_oc,
       CONVERT(date, MIN(m.f421_fecha_entrega)) AS fecha_pactada,
       CONVERT(float, SUM(m.f421_cant_pedida_base)) AS cant_pedida,
       CONVERT(float, SUM(m.f421_cant_entrada)) AS cant_entrada,
       CONVERT(date, MAX(en.ultima)) AS fecha_entrada
FROM t420_cm_oc_docto d
JOIN t200_mm_terceros t ON t.f200_rowid = d.f420_rowid_tercero_prov
JOIN t421_cm_oc_movto m ON m.f421_rowid_oc_docto = d.f420_rowid
JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f421_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
LEFT JOIN (SELECT c.f451_rowid_oc_docto AS rowid_oc, MAX(e.f350_fecha) AS ultima
           FROM t451_cm_docto_compras c JOIN t350_co_docto_contable e ON e.f350_rowid = c.f451_rowid_docto
           WHERE c.f451_id_cia = :cia AND e.f350_ind_estado = 1 AND c.f451_rowid_oc_docto IS NOT NULL
           GROUP BY c.f451_rowid_oc_docto) en ON en.rowid_oc = d.f420_rowid
WHERE d.f420_id_cia = :cia AND i.f120_id_cia = :cia AND d.f420_ind_estado <> 9 AND m.f421_ind_estado IN (1, 2, 3) AND d.f420_fecha >= :desde
GROUP BY d.f420_id_tipo_docto, d.f420_consec_docto, i.f120_referencia, t.f200_id, t.f200_razon_social, d.f420_fecha
