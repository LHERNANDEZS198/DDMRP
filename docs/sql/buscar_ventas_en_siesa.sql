-- Correr en la BD de Siesa (Funat, cia 1). Objetivo: encontrar de que documentos salen las filas de
-- Abastecimiento_Ventas_Tiendas_Funat. Fila de referencia del dump:
--   bodega TC001, referencia 800240, fecha 2026-03-27, cantidad 1, valorSubtotal 30504.00, "costo" 36300.00 (= precio con IVA 19%)
-- Compatible con SQL Server < 2017. Pasame el resultado de cada bloque.

-- 1) Columnas del movimiento de inventario y del documento
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('t470_cm_movto_invent', 't350_co_docto_contable', 't461_cm_docto_factura_venta')
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- 2) Movimientos de ese item en esa bodega y fecha (a ver que tipo de documento es)
SELECT TOP 20 m.*
FROM t470_cm_movto_invent m
JOIN t150_mc_bodegas b ON b.f150_rowid = m.f470_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f470_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE b.f150_id = 'TC001' AND i.f120_referencia LIKE '800240%' AND i.f120_id_cia = 1;

-- 3) Tipos de documento con movimiento en bodegas de tienda en los ultimos 60 dias (para elegir los de venta/devolucion)
SELECT m.f470_id_tipo_docto, COUNT(*) AS movs, SUM(m.f470_cant_base) AS unidades
FROM t470_cm_movto_invent m
JOIN t150_mc_bodegas b ON b.f150_rowid = m.f470_rowid_bodega
WHERE b.f150_id IN ('TC001', 'GN408') AND m.f470_id_cia = 1
GROUP BY m.f470_id_tipo_docto ORDER BY movs DESC;
