-- Verificaciones para el conector de órdenes de compra (docs/OC_CONECTOR.md). Correr en SSMS, en la base de Siesa de cada compañía.

-- 1) Largo y tipo del campo donde se controla que no se repitan las OC (f420_num_docto_referencia): define el formato de la referencia que enviará DDMRP
SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, IS_NULLABLE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 't420_cm_oc_docto' AND COLUMN_NAME IN ('f420_num_docto_referencia', 'f420_id_cond_pago', 'f420_notas', 'f420_id_tercero_sol_comp', 'f420_id_tercero_solicit');

-- 2) Cómo se ven hoy esas referencias en las OCM recientes (¿solo números? ¿largo?)
SELECT TOP 30 d.f420_id_tipo_docto AS tipo, d.f420_consec_docto AS consecutivo, d.f420_fecha AS fecha, d.f420_num_docto_referencia AS referencia, LEN(d.f420_num_docto_referencia) AS largo,
       d.f420_id_co AS co, d.f420_ind_estado AS estado
FROM t420_cm_oc_docto d
WHERE d.f420_id_cia = 1 AND d.f420_id_tipo_docto = 'OCM'
ORDER BY d.f420_fecha DESC, d.f420_rowid DESC;

-- 3) Condiciones de pago usadas en las OC del último año: cuántas OC y cuántos proveedores usa cada una
SELECT RTRIM(d.f420_id_cond_pago) AS cond_pago, COUNT(*) AS ordenes, COUNT(DISTINCT d.f420_rowid_tercero_prov) AS proveedores
FROM t420_cm_oc_docto d
WHERE d.f420_id_cia = 1 AND d.f420_ind_estado <> 9 AND d.f420_fecha >= DATEADD(YEAR, -1, GETDATE())
GROUP BY d.f420_id_cond_pago
ORDER BY ordenes DESC;

-- 4) ¿La condición de pago de un proveedor cambia de una OC a otra? (proveedores con más de una condición en el último año)
SELECT TOP 50 RTRIM(t.f200_id) AS nit, RTRIM(t.f200_razon_social) AS proveedor, COUNT(DISTINCT d.f420_id_cond_pago) AS condiciones_distintas, COUNT(*) AS ordenes
FROM t420_cm_oc_docto d JOIN t200_mm_terceros t ON t.f200_rowid = d.f420_rowid_tercero_prov
WHERE d.f420_id_cia = 1 AND d.f420_ind_estado <> 9 AND d.f420_fecha >= DATEADD(YEAR, -1, GETDATE())
GROUP BY t.f200_id, t.f200_razon_social
HAVING COUNT(DISTINCT d.f420_id_cond_pago) > 1
ORDER BY condiciones_distintas DESC, ordenes DESC;

-- 5) Lo que usará el ETL como valor inicial: la condición de pago de la ÚLTIMA OC de cada proveedor (muestra de 30)
WITH u AS (
  SELECT d.f420_rowid_tercero_prov AS tercero, RTRIM(d.f420_id_cond_pago) AS cond, d.f420_fecha AS fecha,
         ROW_NUMBER() OVER (PARTITION BY d.f420_rowid_tercero_prov ORDER BY d.f420_fecha DESC, d.f420_rowid DESC) AS rn
  FROM t420_cm_oc_docto d
  WHERE d.f420_id_cia = 1 AND d.f420_ind_estado <> 9 AND d.f420_id_cond_pago IS NOT NULL AND RTRIM(d.f420_id_cond_pago) <> ''
)
SELECT TOP 30 RTRIM(t.f200_id) AS nit, RTRIM(t.f200_razon_social) AS proveedor, u.cond AS cond_pago, u.fecha AS ultima_oc
FROM u JOIN t200_mm_terceros t ON t.f200_rowid = u.tercero
WHERE u.rn = 1
ORDER BY u.fecha DESC;

-- 6) ¿El maestro de proveedores de Siesa guarda una condición de pago por defecto? (columnas con «cond» en proveedores y terceros)
SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME IN ('t202_mm_proveedores', 't200_mm_terceros') AND COLUMN_NAME LIKE '%cond%';

-- 7) Quién firma hoy las OCM como comprador (cédulas distintas de solicitante de compra): sirve para el mapa usuario → cédula
SELECT TOP 20 RTRIM(d.f420_id_tercero_sol_comp) AS cedula_comprador, COUNT(*) AS ordenes
FROM t420_cm_oc_docto d
WHERE d.f420_id_cia = 1 AND d.f420_id_tipo_docto = 'OCM' AND d.f420_fecha >= DATEADD(YEAR, -1, GETDATE())
GROUP BY d.f420_id_tercero_sol_comp
ORDER BY ordenes DESC;

-- 8) Tipos de documento y centro de operación que usan hoy las OC (confirma OCM / 000)
SELECT RTRIM(d.f420_id_tipo_docto) AS tipo, RTRIM(d.f420_id_co) AS co, COUNT(*) AS ordenes, MAX(d.f420_fecha) AS ultima
FROM t420_cm_oc_docto d
WHERE d.f420_id_cia = 1 AND d.f420_fecha >= DATEADD(YEAR, -1, GETDATE())
GROUP BY d.f420_id_tipo_docto, d.f420_id_co
ORDER BY ordenes DESC;

-- 9) (BASE INTERMEDIA DE GENERIC TRANSFER, la misma que consulta ChaTest; no es la base de Siesa) ¿Qué documento GT crea las OC?
--    a) El código de la función que arma los parámetros de la llamada: mira de qué tabla los lee y qué ids existen
EXEC sp_helptext 'FN_ParametrosConsumoSiesaWS';
--    b) Prueba con el id que usa hoy AuraPortal para la OC (o recórrelos): debe devolver NombreDocumento tipo OC / OCM, CompaniaGT, CompaniaSiesa, Path
--       (ChaTest usa 69 para los pedidos de Stores; cambia el número por el de la OC)
EXEC FN_ParametrosConsumoSiesaWS 69;
