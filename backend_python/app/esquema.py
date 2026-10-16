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


# Tablas con empresa en la llave (y el resto de la llave): una carga vieja pudo guardar "Funat"/"Stores" en vez de 05/21
EMPRESA_EN_TABLAS = {
    "abast_bitacora": ["bodega_id"], "abast_control_referencias": ["bodega_id", "producto_id"],
    "abast_unidad_despacho": ["producto_id"], "abast_vectorizacion": ["bodega_id", "producto_id"],
    "pronostico": ["bodega_id", "producto_id"], "promocion": ["producto_id"], "maestro_bodega": [],
}
ALIAS = {"05": ("funat",), "21": ("stores", "store", "tiendas")}


def normalizar_empresas(c) -> int:
    """Convierte 'Funat'/'Stores' en 05/21. Si ya existe la fila con el codigo correcto, esa gana y la mala se borra."""
    n = 0
    for tabla, llave in EMPRESA_EN_TABLAS.items():
        for cod, nombres in ALIAS.items():
            mal = "lower(trim(t.empresa)) = ANY(:n)"
            dup = " AND ".join(f"x.{k} = t.{k}" for k in llave) if llave else "FALSE"
            if llave:
                c.execute(text(f"DELETE FROM ddmrp.{tabla} t WHERE {mal} AND EXISTS (SELECT 1 FROM ddmrp.{tabla} x WHERE x.empresa = :c AND {dup})"),
                          {"n": list(nombres), "c": cod})
            r = c.execute(text(f"UPDATE ddmrp.{tabla} t SET empresa = :c WHERE {mal}"), {"n": list(nombres), "c": cod})
            n += r.rowcount or 0
    return n


def asegurar_esquema():
    try:
        with pg.begin() as c:
            for s in SENTENCIAS:
                c.execute(text(s))
            n = normalizar_empresas(c)
            if n:
                log.warning("Empresas corregidas (Funat/Stores -> 05/21): %s fila(s)", n)
    except Exception:
        log.exception("No se pudo actualizar el esquema")
