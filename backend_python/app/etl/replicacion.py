"""ETL: replica a Postgres lo que el motor necesita, para no consultar los servidores de origen en el calculo.

 - FUNATLAB (dbGTIntegrationIntermediaReal): tablas Abastecimiento_* -> ddmrp.abast_*
 - Siesa (una BD por compania): inventario disponible por bodega/referencia -> ddmrp.inventario_actual

Patron: leer el origen en chunks, COPY a una tabla temporal y volcar a destino en UNA transaccion
(si algo falla, Postgres queda como estaba). Los textos se recortan con RTRIM (el origen trae espacios).
"""
import logging
from sqlalchemy import bindparam, text
from ..config import settings
from ..db import lab_engine, pg, siesa_engine

log = logging.getLogger("etl")
CHUNK = 50_000

# (nombre, sql origen MSSQL, tabla destino, columnas destino)
MAESTROS = [
    ("bitacora",
     "SELECT RTRIM(codigoEmpresa), RTRIM(codigoBodega), frecuencia, leadtime FROM dbo.Abastecimiento_Bitacora",
     "ddmrp.abast_bitacora", ["empresa", "bodega_id", "frecuencia", "leadtime"]),
    ("control_referencias",
     "SELECT RTRIM(codigoEmpresa), RTRIM(codigoBodega), RTRIM(referencia), cotaMaxima, cotaMinima "
     "FROM dbo.Abastecimiento_Control_Referencias "
     "WHERE codigoEmpresa IS NOT NULL AND codigoBodega IS NOT NULL AND referencia IS NOT NULL",
     "ddmrp.abast_control_referencias", ["empresa", "bodega_id", "producto_id", "cota_maxima", "cota_minima"]),
    ("unidad_despacho",
     "SELECT RTRIM(empresa), RTRIM(referencia), unidadDespacho FROM dbo.Abastecimiento_Unidad_Despacho",
     "ddmrp.abast_unidad_despacho", ["empresa", "producto_id", "unidad_despacho"]),
    ("vectorizacion",
     "SELECT RTRIM(codigoEmpresa), RTRIM(codigoBodega), RTRIM(referencia), vectorizacion "
     "FROM dbo.Abastecimiento_Vectorizacion",
     "ddmrp.abast_vectorizacion", ["empresa", "bodega_id", "producto_id", "vectorizacion"]),
]

VENTAS = (
    "ventas",
    "SELECT id, RTRIM(CodigoBodega), RTRIM(referencia), RTRIM(descripcionProducto), RTRIM(codigoLaboratorio), "
    "RTRIM(codigoLinea), cantidad, valorSubtotal, valorNeto, costo, fecha, RTRIM(mes) "
    "FROM dbo.Abastecimiento_Ventas_Tiendas_Funat WHERE CodigoBodega IS NOT NULL AND referencia IS NOT NULL",
    "ddmrp.abast_ventas",
    ["id", "bodega_id", "producto_id", "descripcion", "laboratorio", "linea", "cantidad",
     "valor_subtotal", "valor_neto", "costo", "fecha", "mes"],
)

SQL_INVENTARIO = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id), CAST(GETDATE() AS date),
       CONVERT(float, SUM(e.f400_cant_existencia_1 - e.f400_cant_comprometida_1))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas
GROUP BY i.f120_referencia, b.f150_id"""

SQL_CO = "SELECT RTRIM(f150_id), RTRIM(f150_id_co) FROM t150_mc_bodegas WHERE f150_id_cia = :cia AND f150_id IN :bodegas"

# TODO transitos: ordenes de compra / traslados abiertos (t420_cm_oc_docto / t421_cm_oc_movto) -> ddmrp.transitos


def _stream(engine, sql, params=None, expanding=None):
    stmt = text(sql)
    if expanding:
        stmt = stmt.bindparams(bindparam(expanding, expanding=True))
    with engine.connect().execution_options(stream_results=True, yield_per=CHUNK) as c:
        for r in c.execute(stmt, params or {}):
            yield tuple(r)


def _volcar(cur, filas, destino: str, cols: list[str], reemplazar: bool = True) -> int:
    """COPY a tabla temporal y luego INSERT ... ON CONFLICT DO NOTHING (el origen puede traer duplicados)."""
    stg = "stg_" + destino.split(".")[-1]
    cur.execute(f"CREATE TEMP TABLE {stg} (LIKE {destino} INCLUDING DEFAULTS) ON COMMIT DROP")
    n = 0
    with cur.copy(f"COPY {stg} ({', '.join(cols)}) FROM STDIN") as cp:
        for r in filas:
            cp.write_row(r)
            n += 1
    if reemplazar:
        cur.execute(f"TRUNCATE {destino}")
    cur.execute(f"INSERT INTO {destino} ({', '.join(cols)}) SELECT {', '.join(cols)} FROM {stg} ON CONFLICT DO NOTHING")
    log.info("  %s: %s filas leidas", destino, n)
    return n


def correr_etl() -> dict:
    res: dict[str, int] = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            lab = lab_engine()
            if settings.sync_maestros:
                for nombre, sql, destino, cols in MAESTROS:
                    log.info("ETL %s", nombre)
                    res[nombre] = _volcar(cur, _stream(lab, sql), destino, cols)
            else:
                log.info("SYNC_MAESTROS=false: bitacora/cotas/unidad/vectorizacion NO se recargan (la app es el maestro)")

            nombre, sql, destino, cols = VENTAS
            log.info("ETL %s", nombre)
            res[nombre] = _volcar(cur, _stream(lab, sql), destino, cols)

            # Derivados en Postgres
            cur.execute("TRUNCATE ddmrp.maestro_item")
            cur.execute("""INSERT INTO ddmrp.maestro_item (producto_id, descripcion, categoria, linea)
                           SELECT DISTINCT ON (producto_id) producto_id, COALESCE(descripcion, producto_id), laboratorio, linea
                           FROM ddmrp.abast_ventas ORDER BY producto_id, fecha DESC NULLS LAST""")
            cur.execute("TRUNCATE ddmrp.maestro_bodega")
            cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa) SELECT bodega_id, empresa FROM ddmrp.abast_bitacora")
            cur.execute("SELECT bodega_id FROM ddmrp.abast_bitacora")
            bodegas = [r[0] for r in cur.fetchall()]

            # Inventario desde Siesa, una BD por empresa
            cur.execute("TRUNCATE ddmrp.inventario_actual")
            if settings.siesa_host and bodegas:
                for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                    if not db:
                        continue
                    log.info("ETL inventario empresa %s (%s)", empresa, db)
                    filas = _stream(siesa_engine(db), SQL_INVENTARIO,
                                    {"cia": settings.siesa_cia, "bodegas": bodegas}, expanding="bodegas")
                    res[f"inventario_{empresa}"] = _volcar(cur, filas, "ddmrp.inventario_actual",
                                                           ["producto_id", "bodega_id", "fecha_corte", "disponible"],
                                                           reemplazar=False)
                    try:  # centro de operacion de cada bodega (archivo plano); un fallo aqui no tumba el ETL
                        for b, co in _stream(siesa_engine(db), SQL_CO, {"cia": settings.siesa_cia, "bodegas": bodegas}, expanding="bodegas"):
                            cur.execute("INSERT INTO ddmrp.bodega_centro_operacion (bodega_id, id_co) VALUES (%s, %s) "
                                        "ON CONFLICT (bodega_id) DO UPDATE SET id_co = EXCLUDED.id_co", (b, co))
                    except Exception as e:
                        log.warning("No se pudo leer el centro de operacion de las bodegas (%s): %s", db, e)
            else:
                log.warning("Siesa no configurado: inventario_actual queda vacio")
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return res
