-- Ejecutar en SSMS contra el servidor "50", base dbGTIntegrationIntermediaReal.
-- SOLO LECTURA. Pegarme los resultados de cada bloque (1 a 5).
USE dbGTIntegrationIntermediaReal;
GO

-- 1) Codigo completo del procedimiento base
--    (si se corta en la rejilla: Ctrl+T "Results to Text" y ejecutar EXEC sp_helptext 'dbo.Abastecimiento_Modelo_Consulta')
SELECT OBJECT_DEFINITION(OBJECT_ID('dbo.Abastecimiento_Modelo_Consulta')) AS definicion_sp;

-- 2) Objetos de los que depende el procedimiento (tablas, vistas, funciones, otras BDs)
SELECT d.referenced_server_name AS servidor, d.referenced_database_name AS bd, d.referenced_schema_name AS esquema,
       d.referenced_entity_name AS objeto, o.type_desc AS tipo
FROM sys.sql_expression_dependencies d
LEFT JOIN sys.objects o ON o.object_id = d.referenced_id
WHERE d.referencing_id = OBJECT_ID('dbo.Abastecimiento_Modelo_Consulta')
ORDER BY 1,2,3,4;

-- 3) Definicion de las vistas/funciones/procedimientos de ESTA base que usa el procedimiento
SELECT o.name AS objeto, o.type_desc AS tipo, OBJECT_DEFINITION(o.object_id) AS definicion
FROM sys.sql_expression_dependencies d
JOIN sys.objects o ON o.object_id = d.referenced_id
WHERE d.referencing_id = OBJECT_ID('dbo.Abastecimiento_Modelo_Consulta')
  AND o.type IN ('V','FN','IF','TF','P');

-- 4) Columnas, tipos, llaves e indices de las 5 tablas Abastecimiento_*
SELECT t.TABLE_NAME, c.ORDINAL_POSITION AS pos, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH AS largo,
       c.NUMERIC_PRECISION AS prec, c.NUMERIC_SCALE AS escala, c.IS_NULLABLE AS nulo
FROM INFORMATION_SCHEMA.TABLES t
JOIN INFORMATION_SCHEMA.COLUMNS c ON c.TABLE_NAME = t.TABLE_NAME AND c.TABLE_SCHEMA = t.TABLE_SCHEMA
WHERE t.TABLE_NAME LIKE 'Abastecimiento[_]%'
ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION;

SELECT OBJECT_NAME(i.object_id) AS tabla, i.name AS indice, i.is_primary_key AS pk, i.is_unique AS unico,
       STUFF((SELECT ', ' + c.name
              FROM sys.index_columns ic
              JOIN sys.columns c ON c.object_id = ic.object_id AND c.column_id = ic.column_id
              WHERE ic.object_id = i.object_id AND ic.index_id = i.index_id AND ic.is_included_column = 0
              ORDER BY ic.key_ordinal
              FOR XML PATH('')), 1, 2, '') AS columnas
FROM sys.indexes i
WHERE i.name IS NOT NULL AND OBJECT_NAME(i.object_id) LIKE 'Abastecimiento[_]%';

-- 5) Volumen: filas por tabla y 5 filas de muestra
SELECT t.name AS tabla, SUM(p.rows) AS filas
FROM sys.tables t JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0,1)
WHERE t.name LIKE 'Abastecimiento[_]%' GROUP BY t.name;

SELECT TOP 5 * FROM dbo.Abastecimiento_Bitacora;
SELECT TOP 5 * FROM dbo.Abastecimiento_Control_Referencias;
SELECT TOP 5 * FROM dbo.Abastecimiento_Unidad_Despacho;
SELECT TOP 5 * FROM dbo.Abastecimiento_Vectorizacion;
SELECT TOP 5 * FROM dbo.Abastecimiento_Ventas_Tiendas_Funat;
