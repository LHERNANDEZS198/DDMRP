-- Verificacion en SSMS (base de Siesa, una por compania) del estado de los items y de los items REC.
-- El ETL filtra por t121_mc_items_extensiones.f121_ind_estado = 1 (activo). Confirma aqui los valores reales.

-- 1) Cuantas extensiones hay por estado (esperado: 1 activo, 0 inactivo, 2 bloqueado)
SELECT f121_ind_estado AS estado, COUNT(*) AS extensiones, COUNT(DISTINCT f121_rowid_item) AS items
FROM t121_mc_items_extensiones
WHERE f121_id_cia = 1
GROUP BY f121_ind_estado
ORDER BY 1;

-- 2) Items cuyo estado NO es 1 pero que tienen existencia en alguna bodega (stock "varado": dejara de verse en el modelo)
SELECT TOP 100 RTRIM(i.f120_referencia) AS referencia, i.f120_descripcion, x.f121_ind_estado AS estado, SUM(e.f400_cant_existencia_1) AS existencia
FROM t400_cm_existencia e
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = 1 AND x.f121_ind_estado <> 1
GROUP BY i.f120_referencia, i.f120_descripcion, x.f121_ind_estado
HAVING SUM(e.f400_cant_existencia_1) > 0
ORDER BY existencia DESC;

-- 3) Items REC y su original (SKU sin el primer digito)
SELECT r.f120_referencia AS rec, r.f120_descripcion, o.f120_referencia AS original, o.f120_descripcion AS desc_original
FROM t120_mc_items r
LEFT JOIN t120_mc_items o ON o.f120_id_cia = r.f120_id_cia AND o.f120_referencia = SUBSTRING(r.f120_referencia, 2, 50)
WHERE r.f120_id_cia = 1 AND (r.f120_descripcion LIKE 'REC %' OR r.f120_descripcion LIKE 'REC.%' OR r.f120_descripcion LIKE 'REC-%')
ORDER BY r.f120_referencia;
-- original NULL = el REC no tiene original en Siesa: queda como item normal (el ETL lo avisa).
