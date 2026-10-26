-- Ventas DIRECTAS del CEDI (PT001: mayorista / digital), agregadas por mes. Se ejecuta una vez por empresa, igual que ventas_siesa.sql.
-- Parametros: :cia, :desde (primer dia del primer mes de la ventana), :bodegas (los CEDI del maestro_cedi de esa empresa).
-- Devuelve lo mismo que ventas_siesa.sql: mes (YYYYMM), bodega, referencia, cantidad (neta: las devoluciones restan) y valor (venta neta SIN IVA).
--
-- Origen: la consulta de rotacion de PT001 que se uso como ejemplo (facturas t350/t470 con encabezado de venta t461), con estos cambios:
--   * fecha >= :desde sobre la fecha del documento (sargable) en vez de f350_id_periodo en el HAVING (que obligaba a leer todo)
--   * filtra en WHERE por bodega (IN :bodegas, la del maestro de CEDIs) y no por el grupo de bodegas 025 del HAVING
--   * cantidad en f470_cant_1, la MISMA unidad que ventas_siesa.sql para las tiendas (el original usaba f470_cant_base: si un item tiene
--     conversion de unidad de medida, las dos no coinciden y el ADU del CEDI mezclaria unidades). Verificar con docs/sql/comparar_cant_cedi.sql
--   * sin los joins de cliente / tipo de cliente / unidad de negocio / laboratorio (no se usan: el laboratorio y el criterio salen del maestro de items)
--   * sin AVG de precio/costo ni GROUP BY por f470_cant_2 (partia una misma referencia/mes en varias filas)
--   * solo items del maestro y extensiones activas (/*ACTIVO*/), igual que las tiendas
-- Los traslados NO entran: no son facturas de venta (ya van en la venta de las tiendas y en los transitos).
SELECT CONVERT(char(6), enc.f350_fecha, 112) AS mes, RTRIM(bod.f150_id) AS bodega, RTRIM(ite.f120_referencia) AS referencia,
       CONVERT(float, SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -det.f470_cant_1 ELSE det.f470_cant_1 END)) AS cantidad,
       CONVERT(float, SUM(CASE WHEN det.f470_ind_naturaleza = 1 THEN -1 ELSE 1 END * (det.f470_vlr_bruto - det.f470_vlr_dscto_linea - det.f470_vlr_dscto_global))) AS valor
FROM dbo.t350_co_docto_contable enc
JOIN dbo.t461_cm_docto_factura_venta fv ON fv.f461_rowid_docto = enc.f350_rowid AND fv.f461_id_cia = :cia
JOIN dbo.t470_cm_movto_invent det ON det.f470_rowid_docto_fact = enc.f350_rowid AND det.f470_id_cia = :cia
JOIN dbo.t150_mc_bodegas bod ON bod.f150_rowid = det.f470_rowid_bodega
JOIN dbo.t121_mc_items_extensiones ext ON ext.f121_rowid = det.f470_rowid_item_ext
JOIN dbo.t120_mc_items ite ON ite.f120_rowid = ext.f121_rowid_item
WHERE enc.f350_id_cia = :cia AND enc.f350_ind_estado = 1 AND enc.f350_fecha >= :desde
  AND bod.f150_id IN :bodegas AND ite.f120_id_cia = :cia /*ACTIVO:ext,ite*/
GROUP BY CONVERT(char(6), enc.f350_fecha, 112), RTRIM(bod.f150_id), RTRIM(ite.f120_referencia)
