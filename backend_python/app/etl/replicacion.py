"""ETL: trae a Postgres lo que el motor necesita, para no consultar los servidores de origen durante el calculo.

 SOLO Siesa (una BD por compania: '05' SIESA_DB, '21' SIESA_DB_S). FUNATLAB ya no se usa: los maestros de
 abastecimiento (bitacora, cotas, unidad de despacho, vectorizacion, pronostico, ...) los alimenta la propia app
 por pantalla o Excel, y no se tocan aqui.

   - inventario disponible por bodega/referencia          -> ddmrp.inventario_actual
   - traslados abiertos (t406, estado 0)                   -> ddmrp.transitos
   - descripcion de items (t120)                           -> ddmrp.maestro_item (no pisa categoria/linea)
   - centro de operacion de cada bodega                    -> ddmrp.bodega_centro_operacion (no fatal)
   - ventas por mes (consulta en etl/sql/ventas_siesa.sql) -> ddmrp.ventas_mensual (solo la ventana de meses)

Patron: leer el origen en chunks, COPY a tabla temporal y volcar a destino en UNA transaccion: si algo falla,
Postgres queda como estaba y el pipeline no corre el motor con datos viejos sin avisar.
"""
import logging
import psycopg
from datetime import date
from pathlib import Path
from sqlalchemy import bindparam, text
from ..config import settings
from ..db import pg, siesa_engine

log = logging.getLogger("etl")
CHUNK = 50_000
MESES_VENTANA = 7  # por defecto; se lee de ddmrp.parametro 'meses_historia' (2 a 12), editable en Reglas de pedido


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


SQL_CO = "SELECT RTRIM(f150_id), RTRIM(f150_id_co) FROM t150_mc_bodegas WHERE f150_id_cia = :cia AND f150_id IN :bodegas"

SQL_ITEMS = """SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)) FROM t120_mc_items
WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' GROUP BY RTRIM(f120_referencia)"""

# Laboratorio (categoria, base de los permisos) = criterio mayor del plan de items (mismo join que MercadoLibre_Items_Funat)
SQL_LAB = """SELECT RTRIM(i.f120_referencia), MAX(RTRIM(m.f106_id))
FROM t120_mc_items i
JOIN t125_mc_items_criterios c ON c.f125_rowid_item = i.f120_rowid AND c.f125_id_cia = i.f120_id_cia
JOIN t106_mc_criterios_item_mayores m ON m.f106_id_plan = c.f125_id_plan AND m.f106_id = c.f125_id_criterio_mayor
                                     AND m.f106_id_cia = c.f125_id_cia
WHERE c.f125_id_plan = :plan AND i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL
GROUP BY i.f120_referencia"""

# Traslados abiertos hacia las tiendas (f406_ind_estado = 0). Se agrupan por referencia/bodega destino/bodega origen.
SQL_TRANSITOS = """
SELECT RTRIM(i.f120_referencia), RTRIM(be.f150_id), 'TR-' + RTRIM(bs.f150_id),
       CONVERT(float, SUM(t.f406_cant_base_pendiente))
FROM t406_cm_movto_transito t
JOIN t150_mc_bodegas be ON be.f150_rowid = t.f406_rowid_bodega_ent
JOIN t150_mc_bodegas bs ON bs.f150_rowid = t.f406_rowid_bodega_sal
JOIN t121_mc_items_extensiones x ON x.f121_rowid = t.f406_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE t.f406_ind_estado = 0 AND t.f406_id_cia = :cia AND be.f150_id IN :bodegas
GROUP BY i.f120_referencia, be.f150_id, bs.f150_id
HAVING SUM(t.f406_cant_base_pendiente) > 0"""

VENTAS_SQL_FILE = Path(__file__).parent / "sql" / "ventas_siesa.sql"


def _ventas_sql() -> str | None:
    """Consulta de ventas por mes; None si el archivo solo tiene comentarios (aun no definida)."""
    if not VENTAS_SQL_FILE.exists():
        return None
    q = "\n".join(l for l in VENTAS_SQL_FILE.read_text(encoding="utf-8").splitlines() if not l.strip().startswith("--"))
    return q.strip() or None


def _primer_mes(hoy: date, meses: int = MESES_VENTANA) -> date:
    m = hoy.year * 12 + hoy.month - 1 - (meses - 1)
    return date(m // 12, m % 12 + 1, 1)


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
    cur.execute(f"DROP TABLE {stg}")
    log.info("  %s: %s filas leidas", destino, n)
    return n


def correr_etl() -> dict:
    res: dict = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT valor FROM ddmrp.parametro WHERE clave = 'meses_historia'")
            fila = cur.fetchone()
            desde = _primer_mes(date.today(), min(max(int(fila[0]), 2), 12) if fila else MESES_VENTANA)
            cur.execute("TRUNCATE ddmrp.maestro_bodega")
            cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa) SELECT bodega_id, empresa FROM ddmrp.abast_bitacora")
            cur.execute("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora")
            por_empresa: dict[str, list[str]] = {}
            for emp, b in cur.fetchall():
                por_empresa.setdefault(emp, []).append(b)
            if not por_empresa:
                log.warning("abast_bitacora vacia: cargala en Configuracion (Excel) antes de correr el ETL")
            if not settings.siesa_host:
                log.warning("Siesa no configurado: inventario, transitos y ventas quedan como estaban")
                raw.commit()
                return {"aviso": "Siesa no configurado"}

            cur.execute("TRUNCATE ddmrp.inventario_actual")
            cur.execute("TRUNCATE ddmrp.transitos")
            cur.execute("CREATE TEMP TABLE stg_vm (mes char(6), bodega_id text, producto_id text, cantidad numeric) ON COMMIT DROP")
            vsql = _ventas_sql()
            if not vsql:
                log.warning("etl/sql/ventas_siesa.sql sin consulta: las ventas NO se actualizan (cargalas por Excel)")
            ventas_ok: list[str] = []

            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                bodegas = por_empresa.get(empresa, [])
                if not db or not bodegas:
                    continue
                eng, prm = siesa_engine(db), {"cia": settings.siesa_cia, "bodegas": bodegas}
                log.info("ETL empresa %s (%s): %s bodegas", empresa, db, len(bodegas))
                res[f"inventario_{empresa}"] = _volcar(
                    cur, _stream(eng, SQL_INVENTARIO, prm, expanding="bodegas"), "ddmrp.inventario_actual",
                    ["producto_id", "bodega_id", "fecha_corte", "disponible"], reemplazar=False)
                res[f"transitos_{empresa}"] = _volcar(
                    cur, _stream(eng, SQL_TRANSITOS, prm, expanding="bodegas"), "ddmrp.transitos",
                    ["producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
                if vsql:
                    n = 0
                    with cur.copy("COPY stg_vm (mes, bodega_id, producto_id, cantidad) FROM STDIN") as cp:
                        for r in _stream(eng, vsql, {**prm, "desde": desde}, expanding="bodegas"):
                            cp.write_row(r); n += 1
                    res[f"ventas_{empresa}"] = n
                    ventas_ok += bodegas
                try:  # descripciones y centro de operacion: utiles pero no criticos
                    filas = list(_stream(eng, SQL_ITEMS, {"cia": settings.siesa_cia}))
                    cur.execute("CREATE TEMP TABLE stg_items (producto_id text, descripcion text) ON COMMIT DROP")
                    with cur.copy("COPY stg_items FROM STDIN") as cp:
                        for r in filas:
                            cp.write_row(r)
                    cur.execute("""INSERT INTO ddmrp.maestro_item (producto_id, descripcion)
                                   SELECT producto_id, COALESCE(descripcion, producto_id) FROM stg_items
                                   ON CONFLICT (producto_id) DO UPDATE SET descripcion = EXCLUDED.descripcion, actualizado = now()""")
                    cur.execute("DROP TABLE stg_items")
                    labs = list(_stream(eng, SQL_LAB, {"cia": settings.siesa_cia, "plan": settings.siesa_plan_laboratorio}))
                    cur.executemany("UPDATE ddmrp.maestro_item SET categoria = %s WHERE producto_id = %s", [(l, r) for r, l in labs])
                    for b, co in _stream(eng, SQL_CO, prm, expanding="bodegas"):
                        cur.execute("INSERT INTO ddmrp.bodega_centro_operacion (bodega_id, id_co) VALUES (%s, %s) "
                                    "ON CONFLICT (bodega_id) DO UPDATE SET id_co = EXCLUDED.id_co", (b, co))
                except Exception as e:  # solo fallos del origen; un error de Postgres si debe abortar
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("Items / centro de operacion de %s no se actualizaron: %s", db, e)

            if vsql and ventas_ok:
                # Se reemplaza solo la ventana de meses (el historico anterior no se toca) y solo las bodegas leidas.
                cur.execute("DELETE FROM ddmrp.ventas_mensual WHERE mes >= %s AND bodega_id = ANY(%s)",
                            (f"{desde:%Y%m}", ventas_ok))
                cur.execute("""INSERT INTO ddmrp.ventas_mensual (mes, bodega_id, producto_id, cantidad)
                               SELECT mes, bodega_id, producto_id, SUM(cantidad) FROM stg_vm
                               WHERE mes >= %s GROUP BY 1, 2, 3""", (f"{desde:%Y%m}",))
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    return res
