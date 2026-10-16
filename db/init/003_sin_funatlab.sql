-- 003: FUNATLAB deja de usarse. Las tablas de abastecimiento las alimenta la propia app (Excel / pantalla)
-- y las ventas se traen agregadas por mes. Idempotente: sirve para bases nuevas y ya creadas.
SET search_path = ddmrp, public;

-- Ventas ya agregadas: (mes, bodega, producto). Reemplaza a abast_ventas (lineas, 585k+ filas).
CREATE TABLE IF NOT EXISTS ventas_mensual (
  mes         CHAR(6)       NOT NULL,          -- YYYYMM
  bodega_id   TEXT          NOT NULL,
  producto_id TEXT          NOT NULL,
  cantidad    NUMERIC(14,0) NOT NULL DEFAULT 0,
  PRIMARY KEY (mes, bodega_id, producto_id)
);
CREATE INDEX IF NOT EXISTS idx_vm_pb ON ventas_mensual (producto_id, bodega_id);
DROP TABLE IF EXISTS abast_ventas;

-- DIA de abastecimiento por tienda (una tienda puede estar en varios dias)
CREATE TABLE IF NOT EXISTS bodega_dia (
  bodega_id TEXT     NOT NULL,
  dia       SMALLINT NOT NULL CHECK (dia > 0),
  PRIMARY KEY (bodega_id, dia)
);

-- Reglas de pedido (se leen en el motor; editables en la pantalla "Reglas")
INSERT INTO parametro (clave, valor, detalle) VALUES
  ('regla_disparo',       1, 'Cuando pedir: 1 = flujo neto <= TOY ajustado, 2 = flujo neto <= TOR (zona roja), 3 = flujo neto < TOG ajustado'),
  ('regla_objetivo',      1, 'Hasta donde reponer: 1 = TOG ajustado, 2 = TOY ajustado'),
  ('regla_redondeo',      1, 'Redondeo al multiplo de la unidad de despacho: 1 = hacia arriba, 2 = al mas cercano, 3 = hacia abajo'),
  ('sumar_vectorizacion', 1, 'Sumar la vectorizacion (derrame) a la cantidad sugerida: 1 = si, 0 = no'),
  ('incluir_transito',    1, 'Contar los traslados abiertos en el flujo neto: 1 = si, 0 = no'),
  ('restar_demanda_calificada', 1, 'Restar la demanda calificada del flujo neto: 1 = si, 0 = no'),
  ('cantidad_minima',     0, 'No sugerir cantidades menores a esta (0 = sin minimo)')
ON CONFLICT (clave) DO NOTHING;
