-- Ventas de tiendas AGREGADAS POR MES, directo de Siesa. Se ejecuta una vez por empresa (cada BD de Siesa).
-- Parametros: :cia (SIESA_CIA), :desde (primer dia del primer mes de la ventana), :bodegas (bodegas de la empresa).
-- Devuelve: mes (YYYYMM), bodega, referencia, cantidad (neta: las devoluciones restan) y valor (venta neta SIN IVA = bruto - descuento de linea - descuento global,
--   con el mismo signo que la cantidad; en Siesa vlr_neto incluye el impuesto, por eso no se usa). Sirve para la clasificacion ABC por margen.
--
-- Tablas sin prefijo de BD: se consulta la BD de la conexion (SIESA_DB para la 05, SIESA_DB_S para la 21).
-- Origen: misma logica del procedimiento Abastecimiento_Consulta_Ventas (el que alimentaba FUNATLAB), con estos cambios:
--   * agrega por mes en vez de traer lineas; filtra por la fecha del documento >= :desde
--   * solo bodegas de la empresa (:bodegas) y compania (:cia)
--   * NO exige criterios de laboratorio/categoria (un item vendido sin criterio tambien es demanda)
--   * solo extensiones ACTIVAS de Siesa (t121.f121_ind_estado) y los REC, que se suman a su original: el ETL reemplaza cada marcador ACTIVO por la condicion
--     de estado, o por nada si la regla solo_items_activos esta en No o la columna de estado no existe
--   * incluye el tipo NCP (nota credito) en los POS archivados; el original solo lo tenia en los POS vigentes
-- Tres ramas, sin traslape: POS vigente (t9820/t9830), POS archivado (t9920/t9930) y facturas de las bodegas que no pasan
-- por POS (t350/t470).
SELECT mes, bodega, referencia, CONVERT(float, SUM(cantidad)) AS cantidad, CONVERT(float, SUM(valor)) AS valor
FROM (
  SELECT CONVERT(char(6), F1.f9820_id_fecha_docto, 112) AS mes, RTRIM(B.f150_id) AS bodega, RTRIM(i.f120_referencia) AS referencia,
         CASE WHEN F2.f9830_ind_naturaleza = 1 THEN -F2.f9830_cant_1 ELSE F2.f9830_cant_1 END AS cantidad,
         CASE WHEN F2.f9830_ind_naturaleza = 1 THEN -1 ELSE 1 END * (F2.f9830_vlr_bruto - F2.f9830_vlr_dscto_linea - F2.f9830_vlr_dscto_global) AS valor
  FROM dbo.t9820_pdv_d_doctos F1
  JOIN dbo.t9830_pdv_d_movto_venta F2 ON F1.f9820_guid = F2.f9830_guid_docto
  JOIN dbo.t121_mc_items_extensiones ext ON ext.f121_rowid = F2.f9830_rowid_item_ext
  JOIN dbo.t120_mc_items i ON i.f120_rowid = ext.f121_rowid_item
  JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9830_rowid_bodega
  WHERE F1.f9820_id_tipo_docto IN ('PFA', 'PFM', 'PNA', 'FEP', 'NCP', 'FMC', 'PFE', 'EFB', 'NC2', 'FM2')
    AND F1.f9820_ind_estado = 1 AND F1.f9820_id_fecha_docto >= :desde
    AND i.f120_id_cia = :cia AND B.f150_id IN :bodegas /*ACTIVO:ext,i*/
  UNION ALL
  SELECT CONVERT(char(6), F1.f9920_id_fecha_docto, 112), RTRIM(B.f150_id), RTRIM(i.f120_referencia),
         CASE WHEN F2.f9930_ind_naturaleza = 1 THEN -F2.f9930_cant_1 ELSE F2.f9930_cant_1 END,
         CASE WHEN F2.f9930_ind_naturaleza = 1 THEN -1 ELSE 1 END * (F2.f9930_vlr_bruto - F2.f9930_vlr_dscto_linea - F2.f9930_vlr_dscto_global)
  FROM dbo.t9920_pdv_a_doctos F1
  JOIN dbo.t9930_pdv_a_movto_venta F2 ON F1.f9920_guid = F2.f9930_guid_docto
  JOIN dbo.t121_mc_items_extensiones ext ON ext.f121_rowid = F2.f9930_rowid_item_ext
  JOIN dbo.t120_mc_items i ON i.f120_rowid = ext.f121_rowid_item
  JOIN dbo.t150_mc_bodegas B ON B.f150_rowid = F2.f9930_rowid_bodega
  WHERE F1.f9920_id_tipo_docto IN ('PFA', 'PFM', 'PNA', 'FEP', 'NCP', 'FMC', 'PFE', 'EFB', 'NC2', 'FM2')
    AND F1.f9920_ind_estado = 1 AND F1.f9920_id_fecha_docto >= :desde
    AND i.f120_id_cia = :cia AND B.f150_id IN :bodegas /*ACTIVO:ext,i*/
  UNION ALL
  SELECT CONVERT(char(6), enc.f350_fecha, 112), RTRIM(bod.f150_id), RTRIM(ite.f120_referencia),
         CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END,
         CASE WHEN det.f470_ind_naturaleza = 1 THEN -1 ELSE 1 END * (det.f470_vlr_bruto - det.f470_vlr_dscto_linea - det.f470_vlr_dscto_global)
  FROM dbo.t350_co_docto_contable enc
  JOIN dbo.t470_cm_movto_invent det ON enc.f350_rowid = det.f470_rowid_docto_fact
  JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
  JOIN dbo.t121_mc_items_extensiones ext ON ext.f121_rowid = det.f470_rowid_item_ext
  JOIN dbo.t120_mc_items ite ON ite.f120_rowid = ext.f121_rowid_item
  WHERE enc.f350_id_tipo_docto IN ('CFV', 'FED', 'FEM', 'NED')
    AND bod.f150_id IN ('DM039', 'DM040', 'DM140', 'DM240', 'DM340', 'TC001')
    AND bod.f150_id IN :bodegas AND ite.f120_id_cia = :cia AND enc.f350_fecha >= :desde /*ACTIVO:ext,ite*/
) v
GROUP BY mes, bodega, referencia
