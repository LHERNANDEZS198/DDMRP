-- Correr en SSMS, una vez por base de Siesa (05 Funat y 21 Stores). Lista las bodegas que tienen VENTAS en los ultimos meses y por donde se registran,
-- para saber cuales deben estar en Maestros > «Bodegas que venden por factura» (las que venden por factura y no por POS).
-- Reglas: POS vigente/archivado ya se lee para cualquier bodega de la lista de tiendas; las facturas solo se leen de las bodegas del maestro.
-- PT001 (el CEDI) NO va en ese maestro: sus ventas directas se leen aparte (ventas_cedi_siesa.sql) por el maestro de CEDIs.
-- Pasame el resultado; las que salgan con «lineas_factura > 0» y «lineas_pos = 0» y no esten ya en el maestro son las que faltan.

DECLARE @desde date = DATEADD(month, -6, DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1));

WITH fact AS (
  SELECT RTRIM(bod.f150_id) AS bodega, enc.f350_id_tipo_docto AS tipo, COUNT(*) AS lineas,
         SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END) AS unidades
  FROM dbo.t350_co_docto_contable enc
  JOIN dbo.t461_cm_docto_factura_venta fv ON fv.f461_rowid_docto = enc.f350_rowid
  JOIN dbo.t470_cm_movto_invent det ON det.f470_rowid_docto_fact = enc.f350_rowid
  JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
  WHERE enc.f350_ind_estado = 1 AND enc.f350_fecha >= @desde
  GROUP BY RTRIM(bod.f150_id), enc.f350_id_tipo_docto
), pos AS (
  SELECT RTRIM(B.f150_id) AS bodega, COUNT(*) AS lineas
  FROM dbo.t9820_pdv_d_doctos F1 JOIN dbo.t9830_pdv_d_movto_venta F2 ON F1.f9820_guid = F2.f9830_guid_docto
  JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9830_rowid_bodega
  WHERE F1.f9820_ind_estado = 1 AND F1.f9820_id_fecha_docto >= @desde GROUP BY RTRIM(B.f150_id)
  UNION ALL
  SELECT RTRIM(B.f150_id), COUNT(*)
  FROM dbo.t9920_pdv_a_doctos F1 JOIN dbo.t9930_pdv_a_movto_venta F2 ON F1.f9920_guid = F2.f9930_guid_docto
  JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9930_rowid_bodega
  WHERE F1.f9920_ind_estado = 1 AND F1.f9920_id_fecha_docto >= @desde GROUP BY RTRIM(B.f150_id)
)
SELECT f.bodega, f.tipo, f.lineas AS lineas_factura, f.unidades, ISNULL(p.lineas, 0) AS lineas_pos,
       CASE WHEN f.bodega IN ('DM039', 'DM040', 'DM140', 'DM240', 'DM340', 'TC001', 'TC002', 'MBG01', 'MBQ01', 'MCA01', 'MMD01', 'SV036') THEN 'ya esta' ELSE 'REVISAR' END AS en_maestro_inicial,
       CASE WHEN f.tipo IN ('CFV', 'FED', 'FEM', 'NED', 'NCM', 'NCB', 'WEB', 'NYR', 'YR1', 'OVI', 'ARK', 'FML', 'ML', 'FAL') THEN 'lo lee el ETL (facturas)'
            WHEN f.tipo IN ('PFA', 'PFM', 'PNA', 'FEP', 'NCP', 'FMC', 'PFE', 'EFB', 'NC2', 'FM2') THEN 'POS: ya se lee, no agregar' ELSE 'TIPO NO LEIDO' END AS tipo_leido
FROM fact f LEFT JOIN (SELECT bodega, SUM(lineas) AS lineas FROM pos GROUP BY bodega) p ON p.bodega = f.bodega
ORDER BY f.bodega, f.tipo;
