"""ETL Siesa (MSSQL) -> PostgreSQL. Patron: leer en chunks, COPY a tabla staging, upsert/replace.
Los SQL de origen son PLANTILLAS: se ajustan al esquema real de Siesa (tablas t120, t400, t350, etc.)."""
import logging
from datetime import date, timedelta
from sqlalchemy import text
from ..db import siesa_engine, pg
from ..config import settings

log = logging.getLogger("etl")
CHUNK = 100_000

# (nombre, sql_origen_mssql, tabla_destino, columnas_destino, modo)
# modo: 'replace' = snapshot completo | 'ventas' = incremental por fecha
JOBS = [
    ("items", "SELECT /*TODO*/ codigo, descripcion, categoria, unidad FROM items_placeholder",
     "ddmrp.maestro_item", ["producto_id", "descripcion", "categoria", "unidad"], "replace"),
    ("inventario", "SELECT /*TODO*/ producto, bodega, CAST(GETDATE() AS date), disponible FROM inv_placeholder",
     "ddmrp.inventario_actual", ["producto_id", "bodega_id", "fecha_corte", "disponible"], "replace"),
    ("transitos", "SELECT /*TODO*/ producto, bodega, documento, cantidad, fecha_esperada FROM transitos_placeholder",
     "ddmrp.transitos", ["producto_id", "bodega_id", "documento", "cantidad", "fecha_esperada"], "replace"),
]
SQL_VENTAS = ("SELECT /*TODO*/ fecha, producto, bodega, SUM(cantidad), SUM(valor) FROM ventas_placeholder "
              "WHERE fecha >= :desde GROUP BY fecha, producto, bodega")


def _copy_chunks(rows_iter, destino: str, cols: list[str], raw):
    with raw.cursor() as cur, cur.copy(f"COPY {destino} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows_iter:
            cp.write_row(r)


def _stream(sql: str, params=None):
    with siesa_engine().connect().execution_options(stream_results=True, yield_per=CHUNK) as c:
        for r in c.execute(text(sql), params or {}):
            yield tuple(r)


def correr_etl(dias_ventas: int = 7):
    """Snapshots: TRUNCATE + COPY dentro de una transaccion. Ventas: borra ventana y recarga."""
    raw = pg.raw_connection()
    try:
        for nombre, sql, destino, cols, _ in JOBS:
            log.info("ETL %s", nombre)
            with raw.cursor() as cur:
                cur.execute(f"TRUNCATE {destino}")
            _copy_chunks(_stream(sql), destino, cols, raw)
        log.info("ETL ventas (ultimos %s dias)", dias_ventas)
        with raw.cursor() as cur:
            cur.execute("DELETE FROM ddmrp.historico_ventas WHERE fecha >= CURRENT_DATE - %s", (dias_ventas,))
        _copy_chunks(_stream(SQL_VENTAS, {"desde": date.today() - timedelta(days=dias_ventas)}), "ddmrp.historico_ventas",
                     ["fecha", "producto_id", "bodega_id", "cantidad", "valor_neto"], raw)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
