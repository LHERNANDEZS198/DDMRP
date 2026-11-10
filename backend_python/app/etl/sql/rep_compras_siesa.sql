-- Reportes de compras: compras por mes, item y proveedor. Llama al MISMO procedimiento que el Power BI de compras (analisis de documentos de compras de Siesa,
-- «Compras-Completo»), asi las cifras cuadran con las que ya conoces; el ETL agrega por mes (fecha del documento), referencia y proveedor.
-- Parametros: :desde y :hasta, fechas en texto dd/mm/aaaa (rango de fechas de los documentos). Las demas fechas del llamado son filtros apagados (el 0 que las antecede).
-- SET DATEFORMAT dmy: el procedimiento recibe las fechas como texto dd/mm/aaaa igual que en el Power BI, sin depender del idioma del usuario de la conexion.
-- Columnas que usa el ETL del resultado: f_fecha, f_valor_bruto_local, f_cant_base, f_proveedor, f_proveedor_razon_soc, f_referencia.
-- {sp}: nombre del procedimiento de la empresa (Funat: sp_pv_cons_analisis_docto_com_FUNAT; Stores: sp_pv_cons_analisis_docto_com_stores, sin referencias a la base funat). Lo pone reportes_compras._sp_compras.
-- El primer parametro (1) es la compania de Siesa: no cambiarlo (la compania 2 de Funat no se toca).
SET NOCOUNT ON;
SET DATEFORMAT dmy;
EXEC {sp} 1, '   ', '   ', '          ', '   ', '   ', 0, 0, :desde, :hasta, 1, 20061, 'Compras-Completo-Google-NOTOCAR', '          ', 0, '   ', 1, 6, NULL, NULL, :desde, :hasta, 0, '01/01/2023', '01/01/2023', 0, '01/01/2023', '01/01/2023', 0, '01/01/2023', '01/01/2023', 0, '01/01/2023', '01/01/2023'
