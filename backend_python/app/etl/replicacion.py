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
import re
import psycopg
from datetime import date
from pathlib import Path
from sqlalchemy import bindparam, text
from ..config import settings
from .. import progreso, bitacora
from ..db import pg, siesa_engine

log = logging.getLogger("etl")
CHUNK = 50_000
MESES_VENTANA = 7  # por defecto; se lee de ddmrp.parametro 'meses_historia' (2 a 12), editable en Reglas de pedido


SQL_INVENTARIO = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id), CAST(GETDATE() AS date),
       CONVERT(float, SUM(e.f400_cant_existencia_1 - :resta * e.f400_cant_comprometida_1))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas
GROUP BY i.f120_referencia, b.f150_id"""

def _sql_costo() -> str:
    """Costo promedio unitario por referencia (la columna es configurable: SIESA_COSTO_COLUMNA)."""
    col = settings.siesa_costo_columna.strip().lower()
    if not re.fullmatch(r"f400_[a-z0-9_]+", col):
        raise ValueError(f"SIESA_COSTO_COLUMNA invalida: {col!r}")
    return f"""
SELECT RTRIM(i.f120_referencia), CONVERT(float, MAX(e.{col}))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas AND e.{col} > 0
GROUP BY i.f120_referencia"""


SQL_CO = "SELECT RTRIM(f150_id), RTRIM(f150_id_co) FROM t150_mc_bodegas WHERE f150_id_cia = :cia AND f150_id IN :bodegas"

SQL_ITEMS = """SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)) FROM t120_mc_items
WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' GROUP BY RTRIM(f120_referencia)"""

# Tiendas: bodegas del grupo de bodegas de tiendas (t152) con su nombre. Es la lista que ve el usuario en los Excel.
SQL_BODEGAS = """SELECT RTRIM(b.f150_id), RTRIM(b.f150_descripcion)
FROM t150_mc_bodegas b
JOIN t152_mc_bodega_grupo_bodega g ON g.f152_rowid_bodega = b.f150_rowid
WHERE b.f150_id_cia = :cia AND g.f152_id_grupo_bodega = :grupo"""

# Laboratorio (categoria, base de los permisos) = criterio mayor del plan de items (mismo join que MercadoLibre_Items_Funat)
SQL_LAB = """SELECT RTRIM(i.f120_referencia), MAX(RTRIM(m.f106_id))
FROM t120_mc_items i
JOIN t125_mc_items_criterios c ON c.f125_rowid_item = i.f120_rowid
JOIN t106_mc_criterios_item_mayores m ON m.f106_id_plan = c.f125_id_plan AND m.f106_id = c.f125_id_criterio_mayor
                                     AND m.f106_id_cia = i.f120_id_cia
WHERE c.f125_id_plan = :plan AND i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL
GROUP BY i.f120_referencia"""

# Todos los criterios de items (cada plan de criterios tiene un criterio mayor por item): linea, marca, categoria, etc.
SQL_ITEM_CRITERIOS = """SELECT DISTINCT RTRIM(i.f120_referencia), RTRIM(c.f125_id_plan), RTRIM(c.f125_id_criterio_mayor)
FROM t120_mc_items i
JOIN t125_mc_items_criterios c ON c.f125_rowid_item = i.f120_rowid
WHERE i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> ''
  AND c.f125_id_criterio_mayor IS NOT NULL"""
SQL_PLANES_NOMBRES = "SELECT RTRIM(f105_id), RTRIM(f105_descripcion) FROM t105_mc_criterios_item_planes WHERE f105_id_cia = :cia"
SQL_CRITERIOS_NOMBRES = """SELECT RTRIM(f106_id_plan), RTRIM(f106_id), RTRIM(f106_descripcion) FROM t106_mc_criterios_item_mayores
WHERE f106_id_cia = :cia"""

# Nombre de cada laboratorio (criterio mayor del mismo plan)
SQL_LAB_NOMBRES = """SELECT RTRIM(f106_id), MAX(RTRIM(f106_descripcion)) FROM t106_mc_criterios_item_mayores
WHERE f106_id_plan = :plan AND f106_id_cia = :cia GROUP BY f106_id"""

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


def _costos(cur, eng, bodegas: list[str], pisar: bool) -> int | str:
    """Costo promedio por referencia de esas bodegas -> ddmrp.costo_item. `pisar`=True (CEDI) manda sobre lo que haya;
    False (tiendas) solo llena lo que falte. Un fallo del origen (p.ej. la columna no existe) no tumba el ETL: devuelve el aviso."""
    try:
        filas = list(_stream(eng, _sql_costo(), {"cia": settings.siesa_cia, "bodegas": bodegas}, expanding="bodegas"))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Costos no leidos (revisa SIESA_COSTO_COLUMNA=%s): %s", settings.siesa_costo_columna, e)
        return "no se pudo leer la columna " + settings.siesa_costo_columna + ": " + str(e)[:150]
    accion = "DO UPDATE SET costo = EXCLUDED.costo, fecha_corte = current_date" if pisar else "DO NOTHING"
    cur.executemany(f"INSERT INTO ddmrp.costo_item (producto_id, costo) VALUES (%s, %s) ON CONFLICT (producto_id) {accion}",
                    [(p, c) for p, c in filas if c and c > 0])
    return len(filas)


def diagnostico_inventario(bodega: str, producto: str) -> dict:
    """Para entender por que un inventario no cuadra: la fila de Siesa (t400, todas las columnas con dato) en vivo, y lo que
    tiene este sistema (bitacora, inventario del ETL, costo). Solo lectura."""
    out: dict = {"bodega": bodega, "producto": producto, "siesa": [], "local": {}}
    with pg.connect() as c:
        out["local"]["en_bitacora"] = [dict(r) for r in c.execute(text("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora WHERE bodega_id = :b"), {"b": bodega}).mappings()]
        out["local"]["inventario_actual"] = [{k: (float(v) if hasattr(v, "as_tuple") else str(v) if k == "fecha_corte" else v) for k, v in r.items()}
                                              for r in c.execute(text("SELECT producto_id, bodega_id, fecha_corte, disponible FROM ddmrp.inventario_actual WHERE bodega_id = :b AND producto_id = :p"), {"b": bodega, "p": producto}).mappings()]
        out["local"]["costo"] = [float(r[0]) for r in c.execute(text("SELECT costo FROM ddmrp.costo_item WHERE producto_id = :p"), {"p": producto}).all()]
        out["local"]["resta_comprometido"] = bool((c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='inv_tiendas_resta_comprometido'")).scalar() or 0))
    if not settings.siesa_host:
        out["aviso"] = "Siesa no esta configurado"; return out
    sql = ("SELECT RTRIM(b.f150_id) AS bodega, RTRIM(i.f120_referencia) AS referencia, e.* FROM t400_cm_existencia e "
           "JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega "
           "JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext "
           "JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item "
           "WHERE i.f120_id_cia = :cia AND RTRIM(b.f150_id) = :b AND RTRIM(i.f120_referencia) = :p")
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db:
            continue
        try:
            with siesa_engine(db).connect() as cn:
                for r in cn.execute(text(sql), {"cia": settings.siesa_cia, "b": bodega, "p": producto}).mappings():
                    out["siesa"].append({"empresa": empresa, "base": db, "columnas": {
                        k: (float(v) if hasattr(v, "as_tuple") else v if isinstance(v, (int, float, str)) else str(v))
                        for k, v in r.items() if v not in (None, "", 0, 0.0)}})
            _otras_tablas_costo(out["siesa"][-1] if out["siesa"] and out["siesa"][-1].get("empresa") == empresa else None, db, bodega, producto)
        except Exception as e:
            out["siesa"].append({"empresa": empresa, "base": db, "error": str(e)[:300]})
    return out


def _otras_tablas_costo(destino: dict | None, db: str, bodega: str, producto: str) -> None:
    """Busca en Siesa otras tablas (que se unan por item) con columnas de costo (p.ej. costo por instalacion) y trae, para ese item, las filas que
    tengan dato. Es para ubicar de donde sale un costo que no esta en t400. Un fallo aqui no tumba el diagnostico."""
    if destino is None:
        return
    try:
        with siesa_engine(db).connect() as cn:
            cols = cn.execute(text("SELECT TABLE_NAME, COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                                   "WHERE TABLE_NAME LIKE 't%' AND TABLE_NAME <> 't400_cm_existencia' AND COLUMN_NAME LIKE '%costo%' "
                                   "AND TABLE_NAME IN (SELECT TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME LIKE '%rowid_item_ext%')")).all()
            por: dict[str, list[str]] = {}
            for t, c in cols:
                if re.fullmatch(r"[A-Za-z0-9_]+", t) and re.fullmatch(r"[A-Za-z0-9_]+", c):
                    por.setdefault(t, []).append(c)
            rowid = cn.execute(text("SELECT TOP 1 x.f121_rowid FROM t121_mc_items_extensiones x JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item "
                                    "WHERE i.f120_id_cia = :cia AND RTRIM(i.f120_referencia) = :p"), {"cia": settings.siesa_cia, "p": producto}).scalar()
            hallado = []
            for t, cs in sorted(por.items())[:30]:
                clave = cn.execute(text("SELECT TOP 1 COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = :t AND COLUMN_NAME LIKE '%rowid_item_ext%'"), {"t": t}).scalar()
                if not clave or rowid is None:
                    hallado.append({"tabla": t, "columnas_costo": cs, "filas": []}); continue
                filas = []
                for r in cn.execute(text(f"SELECT TOP 5 * FROM {t} WHERE {clave} = :r"), {"r": rowid}).mappings():
                    filas.append({k: (float(v) if hasattr(v, "as_tuple") else v if isinstance(v, (int, float, str)) else str(v))
                                  for k, v in r.items() if v not in (None, "", 0, 0.0) and ("costo" in k or "instal" in k or "bodega" in k or "cia" in k)})
                hallado.append({"tabla": t, "columnas_costo": cs, "filas": filas})
            destino["otras_tablas_costo"] = hallado
    except Exception as e:
        destino["otras_tablas_costo"] = [{"tabla": "(error)", "columnas_costo": [str(e)[:200]], "filas": []}]


def sincronizar_bodegas(cur) -> int:
    """Trae de Siesa las tiendas (codigo + nombre) a ddmrp.maestro_bodega y suma las que ya esten en la bitacora.
    Un fallo del origen no tumba el ETL: se registra y se sigue con lo que haya."""
    n = 0
    if settings.siesa_host:
        for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
            if not db:
                continue
            try:
                filas = list(_stream(siesa_engine(db), SQL_BODEGAS,
                                     {"cia": settings.siesa_cia, "grupo": settings.siesa_grupo_bodegas_tienda}))
            except Exception as e:
                log.warning("No se pudieron leer las tiendas de %s: %s", db, e)
                continue
            for cod, nombre in filas:
                cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa, descripcion) VALUES (%s, %s, %s) "
                            "ON CONFLICT (bodega_id) DO UPDATE SET descripcion = EXCLUDED.descripcion, empresa = EXCLUDED.empresa",
                            (cod, empresa, nombre))
                n += 1
    cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa) SELECT bodega_id, empresa FROM ddmrp.abast_bitacora "
                "ON CONFLICT (bodega_id) DO NOTHING")
    return n


def sincronizar_bodegas_ahora(usuario: str | None = None) -> int:
    with bitacora.registrar("bodegas", "manual", usuario) as r:
        r.resumen = {"tiendas": (n := _sincronizar_bodegas_ahora())}
        return n


def _sincronizar_bodegas_ahora() -> int:
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            n = sincronizar_bodegas(cur)
        raw.commit()
        return n
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _items_de_siesa(cur, eng, primera: bool = True) -> dict:
    """Descripcion, laboratorio (plan 006) y TODOS los criterios de items de una base de Siesa.
    Primero se lee todo del origen y solo despues se escribe, para que un fallo de Siesa no deje la tabla a medias.
    Si hay dos bases (Funat y Stores), la primera manda y la segunda solo agrega lo que falte."""
    prm = {"cia": settings.siesa_cia}
    items = list(_stream(eng, SQL_ITEMS, prm))
    labs = list(_stream(eng, SQL_LAB, {**prm, "plan": settings.siesa_plan_laboratorio}))
    crit = list(_stream(eng, SQL_ITEM_CRITERIOS, prm))
    permitidos = {tuple(x.strip().split(":", 1)) for x in settings.siesa_criterios_items.split(",") if ":" in x}
    if permitidos:   # el filtro elige ITEMS (los que tienen alguno de esos criterios); de cada uno se traen todos sus criterios
        validos = {c[0] for c in crit if (c[1], c[2]) in permitidos}
        crit = [c for c in crit if c[0] in validos]
        items = [x for x in items if x[0] in validos]
        labs = [x for x in labs if x[0] in validos]
    nombres_lab, nombres_plan, nombres_crit = [], [], []
    for sql, destino, aviso in ((SQL_LAB_NOMBRES, nombres_lab, "laboratorios"), (SQL_PLANES_NOMBRES, nombres_plan, "planes"),
                                (SQL_CRITERIOS_NOMBRES, nombres_crit, "criterios")):
        try:   # los nombres son un adorno: si la consulta falla no se pierde lo demas
            destino.extend(_stream(eng, sql, {**prm, "plan": settings.siesa_plan_laboratorio}))
        except Exception as e:
            log.warning("Nombres de %s no leidos: %s", aviso, e)
    cur.execute("CREATE TEMP TABLE IF NOT EXISTS stg_items (producto_id text, descripcion text)")
    cur.execute("TRUNCATE stg_items")
    with cur.copy("COPY stg_items FROM STDIN") as cp:
        for x in items:
            cp.write_row(x)
    cur.execute("""INSERT INTO ddmrp.maestro_item (producto_id, descripcion)
                   SELECT producto_id, COALESCE(descripcion, producto_id) FROM stg_items
                   ON CONFLICT (producto_id) DO UPDATE SET descripcion = EXCLUDED.descripcion, actualizado = now()""")
    borrados = 0
    if primera and items:   # espejo de Siesa: se van los items viejos que ya no estan en la seleccion (los de Stores se agregan despues)
        cur.execute("DELETE FROM ddmrp.maestro_item m WHERE NOT EXISTS (SELECT 1 FROM stg_items s WHERE s.producto_id = m.producto_id)")
        borrados = cur.rowcount
    cur.execute("DROP TABLE stg_items")
    cur.executemany("UPDATE ddmrp.maestro_item SET categoria = %s WHERE producto_id = %s", [(l, p) for p, l in labs])
    for cod, nom in nombres_lab:
        cur.execute("INSERT INTO ddmrp.laboratorio (codigo, nombre) VALUES (%s, %s) "
                    "ON CONFLICT (codigo) DO UPDATE SET nombre = EXCLUDED.nombre", (cod, nom))
    if primera and crit:
        cur.execute("TRUNCATE ddmrp.item_criterio")
    resolver = "DO UPDATE SET criterio_id = EXCLUDED.criterio_id" if primera else "DO NOTHING"
    cur.executemany(f"INSERT INTO ddmrp.item_criterio (producto_id, plan_id, criterio_id) VALUES (%s, %s, %s) "
                    f"ON CONFLICT (producto_id, plan_id) {resolver}", crit)
    for pid, nom in nombres_plan:
        cur.execute("INSERT INTO ddmrp.criterio_plan (plan_id, nombre) VALUES (%s, %s) "
                    "ON CONFLICT (plan_id) DO UPDATE SET nombre = EXCLUDED.nombre", (pid, nom))
    for pid, cid, nom in nombres_crit:
        cur.execute("INSERT INTO ddmrp.criterio (plan_id, criterio_id, nombre) VALUES (%s, %s, %s) "
                    "ON CONFLICT (plan_id, criterio_id) DO UPDATE SET nombre = EXCLUDED.nombre", (pid, cid, nom))
    return {"items": len(items), "eliminados": borrados, "con_laboratorio": len(labs), "criterios": len(crit), "planes": len({c[1] for c in crit})}


def sincronizar_items_ahora(usuario: str | None = None) -> dict:
    with bitacora.registrar("items", "manual", usuario) as r:
        r.resumen = res = _sincronizar_items_ahora()
        return res


def _sincronizar_items_ahora() -> dict:
    """Boton "Traer items de Siesa": las dos bases (Funat y Stores) sin correr el ETL completo."""
    if not settings.siesa_host:
        raise RuntimeError("Siesa no esta configurado (SIESA_HOST)")
    out: dict = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                if db:
                    out[empresa] = _items_de_siesa(cur, siesa_engine(db), primera=(empresa == "05"))
        raw.commit()
        return out
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _cedi_de_siesa(cur) -> dict:
    """Inventario disponible del CEDI (bodega SIESA_CEDI_BODEGA, empresa 05). Se lee todo antes de escribir."""
    bod = settings.siesa_cedi_bodega
    eng = siesa_engine(settings.siesa_db)
    filas = list(_stream(eng, SQL_INVENTARIO, {"cia": settings.siesa_cia, "bodegas": [bod], "resta": 1}, expanding="bodegas"))   # el CEDI siempre descuenta lo comprometido
    costos = _costos(cur, eng, [bod], pisar=True)
    cur.execute("TRUNCATE ddmrp.inventario_cedi")
    datos = {}
    for prod, _b, fecha, disp in filas:
        d = datos.setdefault(prod, [fecha, 0.0])
        d[1] += float(disp or 0)
    for prod, (fecha, disp) in datos.items():
        cur.execute("INSERT INTO ddmrp.inventario_cedi (producto_id, disponible, fecha_corte) VALUES (%s, %s, %s)", (prod, max(disp, 0.0), fecha))
    return {"bodega": bod, "productos": len(datos), "con_stock": sum(1 for d in datos.values() if d[1] > 0), "costos": costos}


def refrescar_cedi() -> dict:
    """Lee de Siesa el inventario FRESCO del CEDI, para que el reparto del motor no dependa de cuando corrio el ETL.
    Si Siesa no responde se sigue con el ultimo corte y se avisa."""
    if not (settings.siesa_host and settings.siesa_db and settings.siesa_cedi_bodega):
        return {"fresco": False, "motivo": "Siesa no configurado"}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            r = _cedi_de_siesa(cur)
        raw.commit()
        return {"fresco": True, **r}
    except Exception as e:
        raw.rollback()
        log.warning("Inventario fresco del CEDI no leido, se usa el ultimo corte: %s", e)
        return {"fresco": False, "motivo": str(e)[:200]}
    finally:
        raw.close()


def _param(cur, clave: str):
    cur.execute("SELECT valor FROM ddmrp.parametro WHERE clave = %s", (clave,))
    f = cur.fetchone()
    return float(f[0]) if f else None


def sincronizar_ventas(origen: str = "manual", usuario: str | None = None) -> dict:
    with bitacora.registrar("ventas", origen, usuario) as r:
        r.resumen = res = _sincronizar_ventas()
        return res


def _sincronizar_ventas() -> dict:
    """Ventas por mes de Siesa -> ddmrp.ventas_mensual. Solo reemplaza la ventana de meses y las bodegas leidas
    (el historico anterior no se toca). Va aparte del ETL porque es la consulta pesada: se lanza a demanda o por parametro."""
    res: dict = {}
    with progreso.tarea("Ventas", "Ventas por mes traídas de Siesa"):
        vsql = _ventas_sql()
        if not vsql:
            raise RuntimeError("etl/sql/ventas_siesa.sql no tiene consulta: cargalas por Excel (maestro ventas por mes)")
        if not settings.siesa_host:
            raise RuntimeError("Siesa no esta configurado (SIESA_HOST)")
        raw = pg.raw_connection()
        try:
            with raw.cursor() as cur:
                meses = _param(cur, "meses_historia")
                desde = _primer_mes(date.today(), min(max(int(meses), 2), 12) if meses else MESES_VENTANA)
                cur.execute("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora")
                por_empresa: dict[str, list[str]] = {}
                for emp, b in cur.fetchall():
                    por_empresa.setdefault(emp, []).append(b)
                if not por_empresa:
                    raise RuntimeError("abast_bitacora esta vacia: cargala en Maestros antes de traer las ventas")
                cur.execute("CREATE TEMP TABLE stg_vm (mes char(6), bodega_id text, producto_id text, cantidad numeric) ON COMMIT DROP")
                leidas: list[str] = []
                for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                    bodegas = por_empresa.get(empresa, [])
                    if not db or not bodegas:
                        continue
                    eng, n = siesa_engine(db), 0
                    progreso.avance(f"Leyendo ventas de {db} desde {desde:%Y-%m} ({len(bodegas)} bodegas)… puede tardar varios minutos")
                    with cur.copy("COPY stg_vm (mes, bodega_id, producto_id, cantidad) FROM STDIN") as cp:
                        for r in _stream(eng, vsql, {"cia": settings.siesa_cia, "bodegas": bodegas, "desde": desde}, expanding="bodegas"):
                            cp.write_row(r); n += 1
                            if n % 50000 == 0:
                                progreso.avance(f"Leyendo ventas de {db}: {n:,} filas…")
                    res[f"ventas_{empresa}"] = n
                    leidas += bodegas
                if not leidas:
                    raise RuntimeError("No hay bodegas para leer (revisa SIESA_DB / SIESA_DB_S y la bitacora)")
                progreso.avance("Guardando las ventas en la base…")
                cur.execute("DELETE FROM ddmrp.ventas_mensual WHERE mes >= %s AND bodega_id = ANY(%s)", (f"{desde:%Y%m}", leidas))
                cur.execute("""INSERT INTO ddmrp.ventas_mensual (mes, bodega_id, producto_id, cantidad)
                               SELECT mes, bodega_id, producto_id, SUM(cantidad) FROM stg_vm
                               WHERE mes >= %s GROUP BY 1, 2, 3""", (f"{desde:%Y%m}",))
                res["meses_desde"] = f"{desde:%Y%m}"
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
    return res


def correr_etl(origen: str = "manual", usuario: str | None = None) -> dict:
    with progreso.tarea("ETL", "ETL listo"), bitacora.registrar("etl", origen, usuario) as r:
        r.resumen = res = _correr_etl(origen, usuario)
        return res


def _correr_etl(origen: str = "manual", usuario: str | None = None) -> dict:
    res: dict = {}
    raw = pg.raw_connection()
    try:
        with raw.cursor() as cur:
            cur.execute("SELECT valor FROM ddmrp.parametro WHERE clave = 'meses_historia'")
            fila = cur.fetchone()
            desde = _primer_mes(date.today(), min(max(int(fila[0]), 2), 12) if fila else MESES_VENTANA)
            res["tiendas"] = sincronizar_bodegas(cur)
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
            traer_ventas = (_param(cur, "etl_traer_ventas") or 0) >= 1
            resta_comp = (_param(cur, "inv_tiendas_resta_comprometido") or 0) >= 1
            if not traer_ventas:
                log.info("ETL: las ventas por mes no se traen aqui (parametro etl_traer_ventas = 0); usa el boton 'Traer ventas'")
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                bodegas = por_empresa.get(empresa, [])
                if not db or not bodegas:
                    continue
                eng, prm = siesa_engine(db), {"cia": settings.siesa_cia, "bodegas": bodegas}
                prm_inv = {**prm, "resta": 1 if resta_comp else 0}
                log.info("ETL empresa %s (%s): %s bodegas", empresa, db, len(bodegas))
                progreso.avance(f"Leyendo inventario de Siesa ({db}, {len(bodegas)} bodegas)…")
                res[f"inventario_{empresa}"] = _volcar(
                    cur, _stream(eng, SQL_INVENTARIO, prm_inv, expanding="bodegas"), "ddmrp.inventario_actual",
                    ["producto_id", "bodega_id", "fecha_corte", "disponible"], reemplazar=False)
                progreso.avance(f"Leyendo costos promedio de Siesa ({db})…")
                res[f"costos_{empresa}"] = _costos(cur, eng, bodegas, pisar=False)   # respaldo: el costo del CEDI manda (se lee al final)
                progreso.avance(f"Leyendo traslados en tránsito de Siesa ({db})…")
                res[f"transitos_{empresa}"] = _volcar(
                    cur, _stream(eng, SQL_TRANSITOS, prm, expanding="bodegas"), "ddmrp.transitos",
                    ["producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
                progreso.avance(f"Leyendo items, criterios y centros de operación ({db})…")
                try:  # descripciones, laboratorio, criterios y centro de operacion: utiles pero no criticos
                    res[f"items_{empresa}"] = _items_de_siesa(cur, eng, primera=(empresa == "05"))
                    for b, co in _stream(eng, SQL_CO, prm, expanding="bodegas"):
                        cur.execute("INSERT INTO ddmrp.bodega_centro_operacion (bodega_id, id_co) VALUES (%s, %s) "
                                    "ON CONFLICT (bodega_id) DO UPDATE SET id_co = EXCLUDED.id_co", (b, co))
                except Exception as e:  # solo fallos del origen; un error de Postgres si debe abortar
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("Items / centro de operacion de %s no se actualizaron: %s", db, e)

            if settings.siesa_db and settings.siesa_cedi_bodega:
                progreso.avance(f"Leyendo el inventario del CEDI ({settings.siesa_cedi_bodega})…")
                try:
                    res["cedi"] = _cedi_de_siesa(cur)
                except Exception as e:   # un fallo de Siesa no debe tumbar el ETL: el CEDI queda con el corte anterior
                    if isinstance(e, psycopg.Error):
                        raise
                    log.warning("Inventario del CEDI no leido: %s", e); res["cedi_error"] = str(e)[:200]
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    if traer_ventas:
        res.update(sincronizar_ventas(origen, usuario))
    return res
