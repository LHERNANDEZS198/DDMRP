-- Proveedor del item en Siesa (pantalla Items > Generales: «Proveedor» + «Sucursal»). Correr en SSMS, en la base de Siesa de cada compania.
-- El ETL lee estas dos columnas de t120_mc_items (SIESA_ITEM_PROVEEDOR_COL y SIESA_ITEM_PROVEEDOR_SUC_COL en la configuracion). Los nombres por defecto
-- (f120_rowid_tercero_prov y f120_id_sucursal_prov) son los habituales pero NO estan confirmados: con esto se confirman o se corrigen.

-- 1) Columnas de t120_mc_items que hablan de proveedor / tercero / sucursal / cliente
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 't120_mc_items'
  AND (COLUMN_NAME LIKE '%prov%' OR COLUMN_NAME LIKE '%terc%' OR COLUMN_NAME LIKE '%sucur%' OR COLUMN_NAME LIKE '%cli%')
ORDER BY ORDINAL_POSITION;

-- 2) La fila del item de la captura (item 0017840, referencia 17, proveedor 8600..., sucursal 001): mira en que columnas aparecen esos valores
SELECT * FROM t120_mc_items WHERE f120_id_cia = 1 AND f120_referencia = '17';

-- 3) Con las columnas elegidas (ajusta los nombres si son otros): referencia, NIT, sucursal y razon social del proveedor
SELECT TOP 20 RTRIM(i.f120_referencia) AS referencia, RTRIM(t.f200_id) AS nit, RTRIM(CONVERT(varchar(10), i.f120_id_sucursal_prov)) AS sucursal,
       RTRIM(t.f200_razon_social) AS proveedor
FROM t120_mc_items i
JOIN t200_mm_terceros t ON t.f200_rowid = i.f120_rowid_tercero_prov
WHERE i.f120_id_cia = 1;

-- 4) Cobertura: items con y sin proveedor, por criterio de categoria (plan 001: 0001 productos Funat, 0002 de terceros)
SELECT cm.f125_id_criterio_mayor AS categoria,
       COUNT(*) AS items,
       SUM(CASE WHEN i.f120_rowid_tercero_prov IS NULL THEN 1 ELSE 0 END) AS sin_proveedor
FROM t120_mc_items i
JOIN t125_mc_items_criterios cm ON cm.f125_rowid_item = i.f120_rowid AND cm.f125_id_plan = '001'
WHERE i.f120_id_cia = 1
GROUP BY cm.f125_id_criterio_mayor
ORDER BY 1;

-- 5) Proveedores que no existen en terceros (rowid huerfano): deberia dar 0 filas
SELECT TOP 50 RTRIM(i.f120_referencia) AS referencia, i.f120_rowid_tercero_prov
FROM t120_mc_items i
LEFT JOIN t200_mm_terceros t ON t.f200_rowid = i.f120_rowid_tercero_prov
WHERE i.f120_id_cia = 1 AND i.f120_rowid_tercero_prov IS NOT NULL AND t.f200_rowid IS NULL;

-- 6) Los proveedores con mas items (sirve para ver que los NIT y nombres tengan sentido)
SELECT TOP 20 RTRIM(t.f200_id) AS nit, RTRIM(t.f200_razon_social) AS proveedor, COUNT(*) AS items
FROM t120_mc_items i JOIN t200_mm_terceros t ON t.f200_rowid = i.f120_rowid_tercero_prov
WHERE i.f120_id_cia = 1
GROUP BY t.f200_id, t.f200_razon_social
ORDER BY items DESC;
