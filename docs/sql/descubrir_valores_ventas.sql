-- Descubrimiento para la clasificacion ABC por margen (punto 2). Correr en SSMS en la BD de Siesa (05 y, si aplica, la 21)
-- y pasarme los resultados (o una captura). Solo lectura.

-- 1) Columnas con "val", "precio", "costo", "bruto", "neto", "dscto" en las tablas de venta que usa el ETL
SELECT t.name AS tabla, c.name AS columna, ty.name AS tipo
FROM sys.tables t
JOIN sys.columns c ON c.object_id = t.object_id
JOIN sys.types ty ON ty.user_type_id = c.user_type_id
WHERE t.name IN ('t9830_pdv_d_movto_venta', 't9930_pdv_a_movto_venta', 't470_cm_movto_invent')
  AND (c.name LIKE '%val%' OR c.name LIKE '%precio%' OR c.name LIKE '%costo%' OR c.name LIKE '%bruto%'
       OR c.name LIKE '%neto%' OR c.name LIKE '%dscto%' OR c.name LIKE '%desc%' OR c.name LIKE '%imp%')
ORDER BY t.name, c.column_id;

-- 2) Muestra de 20 lineas POS vigentes con todas sus columnas (para ver cual es el valor de la linea)
SELECT TOP 20 * FROM dbo.t9830_pdv_d_movto_venta ORDER BY f9830_rowid DESC;

-- 3) Muestra de 20 lineas de factura (rama sin POS)
SELECT TOP 20 * FROM dbo.t470_cm_movto_invent
WHERE f470_rowid_docto_fact IN (SELECT f350_rowid FROM dbo.t350_co_docto_contable WHERE f350_id_tipo_docto IN ('CFV','FED','FEM','NED'))
ORDER BY f470_rowid DESC;
