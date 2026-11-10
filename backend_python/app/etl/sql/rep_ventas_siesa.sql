-- Reportes de compras: ventas FACTURADAS por mes, item, canal (tipo de cliente) y unidad de negocio. Misma logica de la consulta «Ventas» del Power BI de compras
-- (BI_Compras_2022.pbit), solo facturas de venta (t461) con su cliente; no trae las ventas POS de las tiendas (esas ya viven en ventas_mensual).
-- Parametros: :cia (SIESA_CIA: la compania 2 de Funat no se toca) y :periodo_desde (AAAAMM, texto como en el Power BI).
-- Devuelve: periodo (AAAAMM), referencia, canal, unidad_negocio, cantidad (neta: las devoluciones restan), valor_bruto, descuento (de linea) y costo.
--   venta neta = valor_bruto - descuento (como la medida «valor bruto menos valor del descuento»); % rent = (venta neta - costo) / venta neta.
-- Diferencia con el Power BI: el costo se suma linea a linea (cantidad x costo promedio unitario) en vez de AVG(costo) x SUM(cantidad) por grupo, que da lo mismo cuando
--   el costo no cambia dentro del grupo y es mas exacto cuando si cambia.
SELECT CONVERT(char(6), d.f350_id_periodo) AS periodo,
       RTRIM(i.f120_referencia) AS referencia,
       RTRIM(ISNULL(tc.f278_descripcion, '')) AS canal,
       RTRIM(ISNULL(un.f281_descripcion, '')) AS unidad_negocio,
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_cant_base ELSE m.f470_cant_base END)) AS cantidad,
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_vlr_bruto ELSE m.f470_vlr_bruto END)) AS valor_bruto,
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_vlr_dscto_linea ELSE m.f470_vlr_dscto_linea END)) AS descuento,
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_cant_base ELSE m.f470_cant_base END * m.f470_costo_prom_uni)) AS costo
FROM t350_co_docto_contable d
JOIN t470_cm_movto_invent m ON d.f350_rowid = m.f470_rowid_docto_fact AND m.f470_id_cia = :cia
JOIN t461_cm_docto_factura_venta fv ON fv.f461_rowid_docto = d.f350_rowid AND fv.f461_id_cia = :cia
JOIN t200_mm_terceros t ON d.f350_rowid_tercero = t.f200_rowid AND t.f200_id_cia = :cia
JOIN t201_mm_clientes c ON c.f201_id_sucursal = fv.f461_id_sucursal_fact AND c.f201_rowid_tercero = t.f200_rowid AND c.f201_id_cia = :cia
JOIN t278_co_tipo_cli tc ON c.f201_id_tipo_cli = tc.f278_id AND tc.f278_id_cia = :cia
JOIN t121_mc_items_extensiones x ON m.f470_rowid_item_ext = x.f121_rowid
JOIN t120_mc_items i ON x.f121_rowid_item = i.f120_rowid
LEFT JOIN t281_co_unidades_negocio un ON un.f281_id_cia = :cia AND m.f470_id_un_movto = un.f281_id
WHERE d.f350_id_cia = :cia AND d.f350_ind_estado = 1 AND i.f120_id_cia = :cia AND d.f350_id_periodo >= :periodo_desde
GROUP BY d.f350_id_periodo, i.f120_referencia, tc.f278_descripcion, un.f281_descripcion
