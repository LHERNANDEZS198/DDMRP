-- Monedas y tasas que usan hoy las OC reales de Siesa (para llenar OC_MONEDA_CONV / OC_MONEDA_LOCAL / OC_IND_TASA / OC_TASA_* en el .env de DDMRP).
-- Correr en la base de Funat (y en la de Stores si se va a enviar alla). Pasame el resultado.
SELECT TOP 10 RTRIM(f420_id_moneda_docto) AS moneda_docto, RTRIM(f420_id_moneda_conv) AS moneda_conv, RTRIM(f420_id_moneda_local) AS moneda_local,
       f420_ind_tasa AS ind_tasa, f420_tasa_conv AS tasa_conv, f420_tasa_local AS tasa_local, COUNT(*) AS ocs
FROM t420_cm_oc_docto
WHERE f420_id_cia = 1 AND f420_fecha >= DATEADD(MONTH, -6, GETDATE())
GROUP BY RTRIM(f420_id_moneda_docto), RTRIM(f420_id_moneda_conv), RTRIM(f420_id_moneda_local), f420_ind_tasa, f420_tasa_conv, f420_tasa_local
ORDER BY COUNT(*) DESC;
