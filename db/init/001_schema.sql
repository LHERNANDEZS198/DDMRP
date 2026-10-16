-- Esquema analitico DDMRP (PostgreSQL 16)
CREATE SCHEMA IF NOT EXISTS ddmrp;
SET search_path = ddmrp, public;

-- ===== Maestros =====
CREATE TABLE maestro_item (
  producto_id   TEXT PRIMARY KEY,          -- codigo Siesa
  descripcion   TEXT NOT NULL,
  categoria     TEXT,
  unidad        TEXT,
  activo        BOOLEAN NOT NULL DEFAULT TRUE,
  actualizado   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE maestro_bodega (
  bodega_id     TEXT PRIMARY KEY,
  nombre        TEXT NOT NULL,
  tipo          TEXT,                       -- tienda, CEDI, etc.
  activo        BOOLEAN NOT NULL DEFAULT TRUE
);

-- ===== Historico de ventas (particionado mensual) =====
CREATE TABLE historico_ventas (
  fecha         DATE    NOT NULL,
  producto_id   TEXT    NOT NULL,
  bodega_id     TEXT    NOT NULL,
  cantidad      NUMERIC(14,3) NOT NULL,
  valor_neto    NUMERIC(16,2),
  PRIMARY KEY (fecha, producto_id, bodega_id)
) PARTITION BY RANGE (fecha);
CREATE TABLE historico_ventas_default PARTITION OF historico_ventas DEFAULT;
CREATE INDEX idx_hv_producto_bodega ON historico_ventas (producto_id, bodega_id, fecha);
-- (crear particiones mensuales con un job: ver backend_python/app/etl/partitions.py)

-- ===== Inventario y transitos (snapshot del dia) =====
CREATE TABLE inventario_actual (
  producto_id   TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  fecha_corte   DATE NOT NULL,
  disponible    NUMERIC(14,3) NOT NULL DEFAULT 0,
  PRIMARY KEY (producto_id, bodega_id)
);

CREATE TABLE transitos (
  producto_id   TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  documento     TEXT NOT NULL,
  cantidad      NUMERIC(14,3) NOT NULL,
  fecha_esperada DATE,
  PRIMARY KEY (producto_id, bodega_id, documento)
);
CREATE INDEX idx_transitos_pb ON transitos (producto_id, bodega_id);

CREATE TABLE demanda_calificada (          -- pedidos abiertos / picos (opcional)
  producto_id   TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  cantidad      NUMERIC(14,3) NOT NULL DEFAULT 0,
  PRIMARY KEY (producto_id, bodega_id)
);

-- ===== Configuracion DDMRP por item/bodega (editable desde la UI) =====
CREATE TABLE maestro_item_bodega_config (
  producto_id        TEXT NOT NULL,
  bodega_id          TEXT NOT NULL,
  -- Lead time
  lead_time_dias     NUMERIC(6,2) NOT NULL,
  factor_lead_time   NUMERIC(5,3) NOT NULL DEFAULT 0.5,   -- corto/medio/largo
  -- Variabilidad
  factor_variabilidad NUMERIC(5,3) NOT NULL DEFAULT 0.5,
  -- Factores de zona
  factor_zona_roja    NUMERIC(5,3) NOT NULL DEFAULT 1.0,
  factor_zona_amarilla NUMERIC(5,3) NOT NULL DEFAULT 1.0,
  factor_zona_verde   NUMERIC(5,3) NOT NULL DEFAULT 1.0,
  -- Reposicion
  ciclo_pedido_dias  NUMERIC(6,2) NOT NULL DEFAULT 1,
  cantidad_minima    NUMERIC(14,3) NOT NULL DEFAULT 0,    -- MOQ
  multiplo_empaque   NUMERIC(14,3) NOT NULL DEFAULT 1,
  -- Segmentacion
  clase_abc          CHAR(1) CHECK (clase_abc IN ('A','B','C')),
  clase_xyz          CHAR(1) CHECK (clase_xyz IN ('X','Y','Z')),
  -- ADU
  ventana_adu_dias   INT NOT NULL DEFAULT 90,
  activo             BOOLEAN NOT NULL DEFAULT TRUE,
  actualizado_por    TEXT,
  actualizado        TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (producto_id, bodega_id)
);
CREATE INDEX idx_cfg_bodega ON maestro_item_bodega_config (bodega_id);
CREATE INDEX idx_cfg_producto_bodega ON maestro_item_bodega_config (producto_id, bodega_id);

CREATE TABLE config_audit (
  id            BIGSERIAL PRIMARY KEY,
  producto_id   TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  campo         TEXT NOT NULL,
  valor_anterior TEXT,
  valor_nuevo   TEXT,
  usuario       TEXT NOT NULL,
  fecha         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ===== Ejecuciones y sugerencias =====
CREATE TABLE ejecucion_motor (
  id            BIGSERIAL PRIMARY KEY,
  fecha_calculo DATE NOT NULL,
  inicio        TIMESTAMPTZ NOT NULL DEFAULT now(),
  fin           TIMESTAMPTZ,
  estado        TEXT NOT NULL DEFAULT 'corriendo',  -- corriendo|ok|error
  filas         INT,
  detalle       TEXT
);

CREATE TYPE zona_buffer AS ENUM ('ROJA','AMARILLA','VERDE','EXCESO');
CREATE TYPE estado_sugerencia AS ENUM ('PENDIENTE','APROBADA','RECHAZADA','ENVIADA');

CREATE TABLE sugerencias_envio (
  ejecucion_id   BIGINT NOT NULL REFERENCES ejecucion_motor(id),
  fecha_calculo  DATE   NOT NULL,
  producto_id    TEXT   NOT NULL,
  bodega_id      TEXT   NOT NULL,
  adu            NUMERIC(14,4) NOT NULL,
  tor            NUMERIC(14,3) NOT NULL,   -- top of red
  toy            NUMERIC(14,3) NOT NULL,   -- top of yellow
  tog            NUMERIC(14,3) NOT NULL,   -- top of green
  inventario     NUMERIC(14,3) NOT NULL,
  en_transito    NUMERIC(14,3) NOT NULL,
  demanda_calificada NUMERIC(14,3) NOT NULL,
  flujo_neto     NUMERIC(14,3) NOT NULL,
  pct_buffer     NUMERIC(8,2),             -- flujo neto / TOG * 100
  zona           zona_buffer NOT NULL,
  cantidad_sugerida NUMERIC(14,3) NOT NULL,
  cantidad_aprobada NUMERIC(14,3),
  estado         estado_sugerencia NOT NULL DEFAULT 'PENDIENTE',
  aprobado_por   TEXT,
  aprobado_en    TIMESTAMPTZ,
  PRIMARY KEY (ejecucion_id, producto_id, bodega_id)
);
CREATE INDEX idx_sug_fecha_zona ON sugerencias_envio (fecha_calculo, zona);
CREATE INDEX idx_sug_producto_bodega ON sugerencias_envio (producto_id, bodega_id);

-- ===== RBAC (autorizacion; la autenticacion es contra MySQL reloj) =====
CREATE TYPE nivel_permiso AS ENUM ('lectura','edicion','aprobacion');

CREATE TABLE rbac_asignacion (
  id           BIGSERIAL PRIMARY KEY,
  usuario_id   TEXT NOT NULL,              -- id del usuario en MySQL reloj
  bodega_id    TEXT NOT NULL DEFAULT '*',  -- '*' = todas
  categoria    TEXT NOT NULL DEFAULT '*',  -- '*' = todas
  nivel        nivel_permiso NOT NULL,
  es_admin     BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (usuario_id, bodega_id, categoria)
);
CREATE INDEX idx_rbac_usuario ON rbac_asignacion (usuario_id);
