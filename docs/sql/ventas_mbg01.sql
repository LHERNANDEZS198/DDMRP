-- Correr en SSMS contra la base de Siesa de Funat (05). Busca de DONDE salen las ventas de MBG01 (Melonn) para que el ETL las traiga.
-- Contexto: etl/sql/ventas_siesa.sql lee (a) POS vigente, (b) POS archivado y (c) facturas t350/t470 SOLO de las bodegas DM039, DM040, DM140, DM240, DM340 y TC001.
-- Si las ventas de MBG01 son facturas (no POS), hoy no entran: en la app MBG01 queda con ventas 0, ADU 0 y casi sin necesidad.
-- Pasame el resultado de las 4 consultas (o solo la 2 y la 3).

DECLARE @desde date = '2026-05-01';

-- 1) ¿Entra algo por el POS vigente / archivado? (si esto trae filas, las ventas SI se leen y el problema es otro)
SELECT 'POS vigente' AS origen, CONVERT(char(6), F1.f9820_id_fecha_docto, 112) AS mes, F1.f9820_id_tipo_docto AS tipo, COUNT(*) AS lineas,
       SUM(CASE WHEN F2.f9830_ind_naturaleza = 1 THEN -F2.f9830_cant_1 ELSE F2.f9830_cant_1 END) AS unidades
FROM dbo.t9820_pdv_d_doctos F1 JOIN dbo.t9830_pdv_d_movto_venta F2 ON F1.f9820_guid = F2.f9830_guid_docto
JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9830_rowid_bodega
WHERE B.f150_id = 'MBG01' AND F1.f9820_id_fecha_docto >= @desde
GROUP BY CONVERT(char(6), F1.f9820_id_fecha_docto, 112), F1.f9820_id_tipo_docto
UNION ALL
SELECT 'POS archivado', CONVERT(char(6), F1.f9920_id_fecha_docto, 112), F1.f9920_id_tipo_docto, COUNT(*),
       SUM(CASE WHEN F2.f9930_ind_naturaleza = 1 THEN -F2.f9930_cant_1 ELSE F2.f9930_cant_1 END)
FROM dbo.t9920_pdv_a_doctos F1 JOIN dbo.t9930_pdv_a_movto_venta F2 ON F1.f9920_guid = F2.f9930_guid_docto
JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9930_rowid_bodega
WHERE B.f150_id = 'MBG01' AND F1.f9920_id_fecha_docto >= @desde
GROUP BY CONVERT(char(6), F1.f9920_id_fecha_docto, 112), F1.f9920_id_tipo_docto
ORDER BY 1, 2, 3;

-- 2) Facturas / documentos contables con movimiento de inventario en MBG01, por tipo de documento (aqui se ve cuales tipos son las ventas)
SELECT CONVERT(char(6), enc.f350_fecha, 112) AS mes, enc.f350_id_tipo_docto AS tipo, COUNT(*) AS lineas,
       SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END) AS unidades
FROM dbo.t350_co_docto_contable enc
JOIN dbo.t470_cm_movto_invent det ON enc.f350_rowid = det.f470_rowid_docto_fact
JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
WHERE bod.f150_id = 'MBG01' AND enc.f350_fecha >= @desde
GROUP BY CONVERT(char(6), enc.f350_fecha, 112), enc.f350_id_tipo_docto
ORDER BY 1, 2;

-- 3) El item del ejemplo (168169) en MBG01 por mes y tipo: en el modelo original vendio 0,2,1,1 en los meses de la ventana
SELECT CONVERT(char(6), enc.f350_fecha, 112) AS mes, enc.f350_id_tipo_docto AS tipo,
       SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END) AS unidades
FROM dbo.t350_co_docto_contable enc
JOIN dbo.t470_cm_movto_invent det ON enc.f350_rowid = det.f470_rowid_docto_fact
JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
JOIN dbo.t121_mc_items_extensiones ext ON ext.f121_rowid = det.f470_rowid_item_ext
JOIN dbo.t120_mc_items ite ON ite.f120_rowid = ext.f121_rowid_item
WHERE bod.f150_id = 'MBG01' AND RTRIM(ite.f120_referencia) = '168169' AND enc.f350_fecha >= @desde
GROUP BY CONVERT(char(6), enc.f350_fecha, 112), enc.f350_id_tipo_docto
ORDER BY 1, 2;

-- 4) Para comparar: lo que el ETL ya trae de las bodegas de facturas (deberia verse el mismo patron de tipos)
SELECT bod.f150_id AS bodega, enc.f350_id_tipo_docto AS tipo, COUNT(*) AS lineas
FROM dbo.t350_co_docto_contable enc
JOIN dbo.t470_cm_movto_invent det ON enc.f350_rowid = det.f470_rowid_docto_fact
JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
WHERE bod.f150_id IN ('DM039', 'DM040', 'DM140', 'DM240', 'DM340', 'TC001', 'MBG01') AND enc.f350_fecha >= @desde
GROUP BY bod.f150_id, enc.f350_id_tipo_docto
ORDER BY 1, 2;
