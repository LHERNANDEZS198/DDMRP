"""Cambios de esquema idempotentes que se aplican al arrancar el backend (la base puede ser anterior al cambio)."""
import logging
from sqlalchemy import text
from .db import pg

log = logging.getLogger("esquema")

SENTENCIAS = [
    """CREATE TABLE IF NOT EXISTS ddmrp.buffer_historia (   -- foto diaria liviana: sirve a "cambios en un periodo" y a la tendencia
         fecha DATE NOT NULL, empresa TEXT NOT NULL, bodega_id TEXT NOT NULL, producto_id TEXT NOT NULL,
         zona ddmrp.zona_buffer NOT NULL, tor REAL, toy_aj REAL, tog_aj REAL, inventario REAL, flujo_neto REAL, pct_buffer REAL,
         PRIMARY KEY (fecha, bodega_id, producto_id))""",
    "CREATE INDEX IF NOT EXISTS idx_bufhist_item ON ddmrp.buffer_historia (producto_id, bodega_id, fecha)",
    "INSERT INTO ddmrp.parametro VALUES ('retener_dias', 180, 'Dias de historia diaria del buffer que se conservan') ON CONFLICT DO NOTHING",
    "CREATE TABLE IF NOT EXISTS ddmrp.laboratorio (codigo TEXT PRIMARY KEY, nombre TEXT)",
    "ALTER TABLE ddmrp.maestro_bodega ADD COLUMN IF NOT EXISTS descripcion TEXT",
    # cotas como fraccion (0.125 = 12,5%): 4 decimales en vez de 2
    """DO $$ BEGIN
         IF (SELECT numeric_scale FROM information_schema.columns WHERE table_schema='ddmrp'
             AND table_name='abast_control_referencias' AND column_name='cota_maxima') = 2 THEN
           ALTER TABLE ddmrp.abast_control_referencias
             ALTER COLUMN cota_maxima TYPE NUMERIC(12,4), ALTER COLUMN cota_minima TYPE NUMERIC(12,4);
         END IF; END $$""",
]


def asegurar_esquema():
    try:
        with pg.begin() as c:
            for s in SENTENCIAS:
                c.execute(text(s))
    except Exception:
        log.exception("No se pudo actualizar el esquema")
