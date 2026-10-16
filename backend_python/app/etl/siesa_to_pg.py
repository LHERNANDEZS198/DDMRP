"""ETL Siesa (MSSQL) -> PostgreSQL. Patron: leer en chunks, COPY a tabla staging, upsert/replace.
Una BD de Siesa por compania (ver SIESA_DB). Queries basadas en las de ChaTest."""
import logging
from datetime import date, timedelta
from sqlalchemy import text
from ..db import siesa_engine, pg
from ..config import settings

log = logging.getLogger("etl")
CHUNK = 100_000

# Tablas/columnas tomadas de ChaTest (logistica/views_inventario_api.py, pyLH/consultas.py).
SQL_ITEMS = """
SELECT RTRIM(i.f120_referencia), MAX(RTRIM(i.f120_descripcion)), CAST(NULL AS varchar(50)), CAST(NULL AS varchar(10))
FROM t120_mc_items i WHERE i.f120_id_cia = :cia GROUP BY i.f120_referencia"""   # TODO categoria (t125 criterios)

SQL_BODEGAS = """
SELECT RTRIM(f150_id), RTRIM(f150_descripcion) FROM t150_mc_bodegas WHERE f150_id_cia = :cia"""

SQL_INVENTARIO = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id), CAST(GETDATE() AS date),
       CONVERT(float, SUM(e.f400_cant_existencia_1 - e.f400_cant_comprometida_1))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia
GROUP BY i.f120_referencia, b.f150_id"""

SQL_VENTAS = """
SELECT CAST(d.f350_fecha AS date), RTRIM(i.f120_referencia), RTRIM(b.f150_id),
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_cant_base ELSE m.f470_cant_base END)),
       CONVERT(float, SUM(CASE WHEN m.f470_ind_naturaleza = 1 THEN -m.f470_vlr_bruto ELSE m.f470_vlr_bruto END))
FROM t350_co_docto_contable d
JOIN t470_cm_movto_invent m ON m.f470_rowid_docto_fact = d.f350_rowid AND m.f470_id_cia = :cia
JOIN t461_cm_docto_factura_venta f ON f.f461_rowid_docto = d.f350_rowid AND f.f461_id_cia = :cia
JOIN t150_mc_bodegas b ON b.f150_rowid = m.f470_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = m.f470_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE d.f350_fecha >= :desde AND d.f350_ind_estado = 1      -- VERIFICAR filtro de estado/tipos de docto
GROUP BY CAST(d.f350_fecha AS date), i.f120_referencia, b.f150_id"""

# TODO transitos: ordenes de compra/traslados abiertos (t420_cm_oc_docto / t421_cm_oc_movto) -> ddmrp.transitos

# (nombre, sql, destino, columnas) -> snapshots completos: TRUNCATE + COPY
JOBS = [
    ("items", SQL_ITEMS, "ddmrp.maestro_item", ["producto_id", "descripcion", "categoria", "unidad"]),
    ("bodegas", SQL_BODEGAS, "ddmrp.maestro_bodega", ["bodega_id", "nombre"]),
    ("inventario", SQL_INVENTARIO, "ddmrp.inventario_actual", ["producto_id", "bodega_id", "fecha_corte", "disponible"]),
]


def _copy_chunks(rows_iter, destino: str, cols: list[str], raw):
    with raw.cursor() as cur, cur.copy(f"COPY {destino} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in rows_iter:
            cp.write_row(r)


def _stream(sql: str, params=None):
    p = {"cia": settings.siesa_cia, **(params or {})}
    with siesa_engine().connect().execution_options(stream_results=True, yield_per=CHUNK) as c:
        for r in c.execute(text(sql), p):
            yield tuple(r)


def correr_etl(dias_ventas: int = 7):
    """Snapshots: TRUNCATE + COPY dentro de una transaccion. Ventas: borra ventana y recarga."""
    raw = pg.raw_connection()
    try:
        for nombre, sql, destino, cols in JOBS:
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
