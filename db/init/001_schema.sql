-- Esquema analitico DDMRP (PostgreSQL 16)
-- Las tablas abast_* replican dbGTIntegrationIntermediaReal.dbo.Abastecimiento_* (servidor FUNATLAB).
CREATE SCHEMA IF NOT EXISTS ddmrp;
SET search_path = ddmrp, public;

-- ===== Maestros derivados =====
CREATE TABLE maestro_item (
  producto_id   TEXT PRIMARY KEY,           -- referencia Siesa (sin espacios)
  descripcion   TEXT NOT NULL,
  categoria     TEXT,                       -- codigo de laboratorio (filtro de permisos)
  linea         TEXT,
  actualizado   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE maestro_bodega (
  bodega_id     TEXT PRIMARY KEY,
  empresa       TEXT NOT NULL               -- '05' Funat, '21' Store
);

-- Centro de operacion de cada bodega (f440_id_co del archivo plano de Siesa)
CREATE TABLE bodega_centro_operacion (
  bodega_id     TEXT PRIMARY KEY,
  id_co         TEXT NOT NULL
);

-- ===== Replica de tablas de abastecimiento (maestros editables) =====
CREATE TABLE abast_bitacora (               -- lead time y frecuencia por bodega
  empresa       TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  frecuencia    NUMERIC(12,2),              -- dias entre revisiones
  leadtime      NUMERIC(12,2),              -- dias
  PRIMARY KEY (empresa, bodega_id)
);
CREATE UNIQUE INDEX uq_bitacora_bodega ON abast_bitacora (bodega_id);

CREATE TABLE abast_control_referencias (    -- cotas max/min (porcentaje del TOG) por bodega/referencia
  empresa       TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  producto_id   TEXT NOT NULL,
  cota_maxima   NUMERIC(12,2),
  cota_minima   NUMERIC(12,2),
  PRIMARY KEY (empresa, bodega_id, producto_id)
);
CREATE INDEX idx_ctrl_pb ON abast_control_referencias (producto_id, bodega_id);

CREATE TABLE abast_unidad_despacho (        -- multiplo de despacho por referencia
  empresa         TEXT NOT NULL,
  producto_id     TEXT NOT NULL,
  unidad_despacho NUMERIC(12,2),
  PRIMARY KEY (empresa, producto_id)
);

CREATE TABLE abast_vectorizacion (          -- derrame (producto nuevo o campana): unidades a sumar
  empresa       TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  producto_id   TEXT NOT NULL,
  vectorizacion NUMERIC(12,2),
  PRIMARY KEY (empresa, bodega_id, producto_id)
);
CREATE INDEX idx_vect_pb ON abast_vectorizacion (producto_id, bodega_id);

CREATE TABLE abast_ventas (                 -- ventas de tiendas (lineas), tal cual el origen
  id            BIGINT PRIMARY KEY,
  bodega_id     TEXT NOT NULL,
  producto_id   TEXT NOT NULL,
  descripcion   TEXT,
  laboratorio   TEXT,
  linea         TEXT,
  cantidad      NUMERIC(12,0),
  valor_subtotal NUMERIC(12,2),
  valor_neto    NUMERIC(12,2),
  costo         NUMERIC(12,2),
  fecha         DATE,
  mes           CHAR(6)                     -- YYYYMM
);
CREATE INDEX idx_ventas_producto_bodega_mes ON abast_ventas (producto_id, bodega_id, mes);
CREATE INDEX idx_ventas_mes ON abast_ventas (mes);

-- ===== Entradas propias de la app (no existen en el origen) =====
CREATE TABLE pronostico (                   -- valor estatico que alimentan los analistas (unidades/mes)
  empresa       TEXT NOT NULL,
  bodega_id     TEXT NOT NULL,
  producto_id   TEXT NOT NULL,
  pronostico    NUMERIC(12,2) NOT NULL DEFAULT 0,
  PRIMARY KEY (empresa, bodega_id, producto_id)
);
CREATE INDEX idx_pron_pb ON pronostico (producto_id, bodega_id);

CREATE TABLE promocion (                    -- indicativo de promocion (0 no, 1 si, 2 variante GN); por definir
  empresa       TEXT NOT NULL,
  producto_id   TEXT NOT NULL,
  indicativo    SMALLINT NOT NULL DEFAULT 0,
  PRIMARY KEY (empresa, producto_id)
);

-- Factores del analista (hoja "Factores"): tramos (desde, hasta] ; el primer tramo incluye 'desde'
CREATE TABLE factor_tramo (
  tipo          TEXT NOT NULL CHECK (tipo IN ('LT','VAR')),
  descripcion   TEXT NOT NULL,
  factor        NUMERIC(6,3) NOT NULL,
  desde         NUMERIC(10,3) NOT NULL,
  hasta         NUMERIC(10,3),              -- NULL = sin tope
  PRIMARY KEY (tipo, descripcion)
);
INSERT INTO factor_tramo VALUES
  ('LT','Corto', 0.61, 0, 3),
  ('LT','Medio', 0.41, 3, 5),
  ('LT','Largo', 0.21, 5, 50),
  ('VAR','Baja',  0.21, 0,   0.5),
  ('VAR','Media', 0.41, 0.5, 0.8),
  ('VAR','Alta',  0.61, 0.8, NULL);

-- Parametros del modelo (hoja Modelo: AZ = cota x 1.2, BA = cota x 1.1)
CREATE TABLE parametro (
  clave   TEXT PRIMARY KEY,
  valor   NUMERIC NOT NULL,
  detalle TEXT
);
INSERT INTO parametro VALUES
  ('mult_cota_max_promo', 1.2, 'AZ: cota maxima x esto cuando hay promocion'),
  ('mult_cota_min_promo', 1.1, 'BA: cota minima x esto cuando hay promocion'),
  ('adu_bajo_min', 1, 'ADU entre min y max => ZRB = 0'),
  ('adu_bajo_max', 4, 'ADU entre min y max => ZRB = 0');

-- ===== Inventario y transitos (Siesa) =====
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

CREATE TABLE config_audit (
  id            BIGSERIAL PRIMARY KEY,
  tabla         TEXT NOT NULL,
  llave         TEXT NOT NULL,
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
  empresa        TEXT   NOT NULL,
  bodega_id      TEXT   NOT NULL,
  producto_id    TEXT   NOT NULL,
  -- demanda
  adu            NUMERIC(14,2) NOT NULL,   -- unidades/mes (columna W)
  iv             NUMERIC(10,4) NOT NULL,   -- indice de variabilidad (Y)
  forecast       NUMERIC(14,2) NOT NULL,   -- columna Q
  -- parametros
  lead_time      NUMERIC(8,2) NOT NULL,
  frecuencia     NUMERIC(8,2) NOT NULL,
  unidad_despacho NUMERIC(12,2) NOT NULL,
  -- zonas y topes
  zrb NUMERIC(14,2) NOT NULL, zrs NUMERIC(14,2) NOT NULL, za NUMERIC(14,2) NOT NULL, zv NUMERIC(14,2) NOT NULL,
  tor NUMERIC(14,2) NOT NULL, toy NUMERIC(14,2) NOT NULL, tog NUMERIC(14,2) NOT NULL,
  toy_aj NUMERIC(14,2) NOT NULL, tog_aj NUMERIC(14,2) NOT NULL,
  -- flujo neto
  inventario     NUMERIC(14,3) NOT NULL,
  en_transito    NUMERIC(14,3) NOT NULL,
  demanda_calificada NUMERIC(14,3) NOT NULL,
  flujo_neto     NUMERIC(14,3) NOT NULL,
  pct_buffer     NUMERIC(10,2),            -- flujo neto / TOG ajustado * 100
  zona           zona_buffer NOT NULL,
  vectorizacion  NUMERIC(14,2) NOT NULL DEFAULT 0,
  cantidad_sugerida NUMERIC(14,3) NOT NULL,
  cantidad_aprobada NUMERIC(14,3),
  estado         estado_sugerencia NOT NULL DEFAULT 'PENDIENTE',
  aprobado_por   TEXT,
  aprobado_en    TIMESTAMPTZ,
  PRIMARY KEY (ejecucion_id, bodega_id, producto_id)
);
CREATE INDEX idx_sug_fecha_zona ON sugerencias_envio (fecha_calculo, zona);
CREATE INDEX idx_sug_producto_bodega ON sugerencias_envio (producto_id, bodega_id);

-- ===== RBAC (autorizacion; la autenticacion es contra MySQL reloj) =====
CREATE TYPE nivel_permiso AS ENUM ('lectura','edicion','aprobacion');

CREATE TABLE rbac_asignacion (
  id           BIGSERIAL PRIMARY KEY,
  usuario_id   TEXT NOT NULL,              -- CODIGO del usuario en reloj
  bodega_id    TEXT NOT NULL DEFAULT '*',  -- '*' = todas
  categoria    TEXT NOT NULL DEFAULT '*',  -- laboratorio; '*' = todas
  nivel        nivel_permiso NOT NULL,
  es_admin     BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (usuario_id, bodega_id, categoria)
);
CREATE INDEX idx_rbac_usuario ON rbac_asignacion (usuario_id);
