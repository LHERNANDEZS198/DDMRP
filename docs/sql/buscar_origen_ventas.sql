-- Correr en FUNATLAB (SSMS). Busca QUIEN llena dbo.Abastecimiento_Ventas_Tiendas_Funat para replicar esa logica
-- directo sobre Siesa. Compatible con SQL Server < 2017. Pasame el resultado de las consultas.

-- 1) Procedimientos / vistas / funciones / triggers que la mencionan (BD actual)
SELECT o.type_desc, SCHEMA_NAME(o.schema_id) AS esquema, o.name, m.definition
FROM sys.sql_modules m JOIN sys.objects o ON o.object_id = m.object_id
WHERE m.definition LIKE '%Abastecimiento_Ventas_Tiendas_Funat%';

-- 2) Pasos de jobs del Agente SQL que la mencionan
SELECT j.name AS job, s.step_id, s.step_name, s.subsystem, s.database_name, s.command
FROM msdb.dbo.sysjobsteps s JOIN msdb.dbo.sysjobs j ON j.job_id = s.job_id
WHERE s.command LIKE '%Abastecimiento_Ventas%';

-- 3) Patron de carga: ultimos registros y totales por mes
SELECT TOP 20 * FROM dbo.Abastecimiento_Ventas_Tiendas_Funat ORDER BY id DESC;
SELECT mes, COUNT(*) AS filas, SUM(cantidad) AS unidades, MIN(fecha) AS desde, MAX(fecha) AS hasta
FROM dbo.Abastecimiento_Ventas_Tiendas_Funat GROUP BY mes ORDER BY mes DESC;
