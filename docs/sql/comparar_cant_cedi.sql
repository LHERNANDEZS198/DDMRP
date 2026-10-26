-- Verificacion previa a confiar en la rotacion de PT001: ¿f470_cant_1 y f470_cant_base difieren? (correr en la BD de Siesa de cada empresa)
-- Si "dif" sale 0 en todas las filas no hay problema de unidades; si sale distinto de 0, el ADU del CEDI y el de las tiendas no estan en la misma unidad.
SELECT CONVERT(char(6), enc.f350_fecha, 112) AS mes,
       SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END) AS cant_1,
       SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_base ELSE det.f470_cant_base END) AS cant_base,
       SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END)
     - SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_base ELSE det.f470_cant_base END) AS dif,
       COUNT(DISTINCT det.f470_rowid_item_ext) AS items
FROM dbo.t350_co_docto_contable enc
JOIN dbo.t461_cm_docto_factura_venta fv ON fv.f461_rowid_docto = enc.f350_rowid
JOIN dbo.t470_cm_movto_invent det ON det.f470_rowid_docto_fact = enc.f350_rowid
JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
WHERE enc.f350_ind_estado = 1 AND enc.f350_fecha >= '2026-04-01' AND bod.f150_id = 'PT001'
GROUP BY CONVERT(char(6), enc.f350_fecha, 112)
ORDER BY 1;
