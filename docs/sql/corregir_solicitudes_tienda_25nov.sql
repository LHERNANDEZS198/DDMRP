-- Corrige las solicitudes NxP «agregar» pendientes que se enviaron a nivel ITEM (todas las tiendas) pero la tienda quedo escrita en el motivo
-- ("16 en la 021", "35 items en la 411", "32enjardin", "Son 31 SKU en la tienda GN408"...). Las pasa a nivel tienda_item con su bodega.
-- Correr en DBeaver, EN ORDEN. El paso 1 no cambia nada; el paso 2 solo toca las que resolvieron a UNA sola tienda.

-- ===== PASO 1: vista previa (que tienda entiende de cada motivo) =====
CREATE TEMP TABLE sol_fix AS
WITH base AS (
  SELECT s.id, s.empresa, s.producto_id, s.motivo,
         COALESCE(upper((regexp_match(s.motivo, '(?i)\m((?:GN|SV|NS|MN|TC|DM)\d{3})\M'))[1]), NULL) AS cod_explicito,
         (regexp_match(s.motivo, '(?i)en la (?:tienda )?(\d{3})\M'))[1] AS num,
         CASE WHEN s.motivo ~* 'victoria' THEN 'victoria' WHEN s.motivo ~* 'jard[ií]n' THEN 'jard' WHEN s.motivo ~* 'castellana' THEN 'castellana' END AS nombre
  FROM ddmrp.solicitud_cambio s
  WHERE s.estado = 'pendiente' AND s.tipo = 'nxp' AND s.accion = 'agregar' AND s.nivel = 'item'),
cand AS (
  SELECT b.id, mb.bodega_id
  FROM base b JOIN ddmrp.maestro_bodega mb ON mb.empresa = b.empresa AND (
        (b.cod_explicito IS NOT NULL AND mb.bodega_id = b.cod_explicito)
     OR (b.cod_explicito IS NULL AND b.num IS NOT NULL AND right(mb.bodega_id, 3) = b.num AND (left(b.num, 1) <> '0' OR mb.bodega_id LIKE 'SV%'))
     OR (b.cod_explicito IS NULL AND b.num IS NULL AND b.nombre IS NOT NULL AND mb.descripcion ILIKE '%' || b.nombre || '%'))
  GROUP BY b.id, mb.bodega_id)
SELECT b.*, (SELECT count(*) FROM cand c WHERE c.id = b.id) AS n_cand, (SELECT min(c.bodega_id) FROM cand c WHERE c.id = b.id) AS bodega
FROM base b;

SELECT left(motivo, 45) AS motivo, bodega, n_cand AS candidatas, count(*) AS solicitudes
FROM sol_fix GROUP BY 1, 2, 3 ORDER BY 3 DESC, 1;
-- Revisa: «candidatas» debe ser 1 en todas (0 = no encontro la tienda, 2+ = ambigua; esas no se tocan).
-- Los conteos deben cuadrar con lo que dijo el usuario (16 en SV021, 22 en 413, ... 31 en GN408).

-- ===== PASO 2: aplicar (solo las de 1 candidata) =====
-- UPDATE ddmrp.solicitud_cambio s SET nivel = 'tienda_item', bodega_id = f.bodega
-- FROM sol_fix f WHERE f.id = s.id AND f.n_cand = 1
--   AND NOT EXISTS (SELECT 1 FROM ddmrp.solicitud_cambio x WHERE x.estado = 'pendiente' AND x.empresa = s.empresa AND x.tipo = 'nxp' AND x.accion = 'agregar'
--                   AND x.nivel = 'tienda_item' AND x.producto_id = s.producto_id AND x.bodega_id = f.bodega);
-- (quita los «--» de las 4 lineas anteriores para correrlo)
