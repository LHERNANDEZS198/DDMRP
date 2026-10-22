"""ETL: trae a Postgres lo que el motor necesita, para no consultar los servidores de origen durante el calculo.

 SOLO Siesa (una BD por compania: '05' SIESA_DB, '21' SIESA_DB_S). FUNATLAB ya no se usa: los maestros de
 abastecimiento (bitacora, cotas, unidad de despacho, vectorizacion, pronostico, ...) los alimenta la propia app
 por pantalla o Excel, y no se tocan aqui.

   - inventario disponible por bodega/referencia          -> ddmrp.inventario_actual
   - traslados abiertos (t406, estado 0)                   -> ddmrp.transitos
   - descripcion de items (t120)                           -> ddmrp.maestro_item (no pisa categoria/linea)
   - centro de operacion de cada bodega                    -> columna id_co de ddmrp.abast_bitacora, solo donde falte (no fatal)
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
from .. import progreso, bitacora, lanzamientos
from ..db import pg, siesa_engine
from ..rec import detectar_rec
from ..activos import purgas_fuera_del_maestro

log = logging.getLogger("etl")
CHUNK = 50_000
MESES_VENTANA = 7  # por defecto; se lee de ddmrp.parametro 'meses_historia' (2 a 12), editable en Reglas de pedido


SQL_INVENTARIO = """
SELECT RTRIM(i.f120_referencia), RTRIM(b.f150_id), CAST(GETDATE() AS date),
       CONVERT(float, SUM(e.f400_cant_existencia_1 - :resta * e.f400_cant_comprometida_1
                       - :resta_sa * ISNULL(e.f400_cant_salida_sin_conf_1, 0)))
FROM t400_cm_existencia e
JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas /*ACTIVO:x,i*/
GROUP BY i.f120_referencia, b.f150_id"""

def _sql_costo() -> str:
    """Costo promedio unitario por referencia. Por defecto POR INSTALACION: tabla y columna configurables (SIESA_COSTO_TABLA /
    SIESA_COSTO_COLUMNA), unida por item y por la instalacion de la bodega (t400.f400_id_instalacion). Sin tabla, lee t400."""
    col = settings.siesa_costo_columna.strip().lower(); tabla = settings.siesa_costo_tabla.strip().lower()
    m = re.fullmatch(r"(f\d+)_[a-z0-9_]+", col)
    if not m or (tabla and not re.fullmatch(r"t\d+_[a-z0-9_]+", tabla)):
        raise ValueError(f"SIESA_COSTO_COLUMNA / SIESA_COSTO_TABLA invalida: {tabla!r} {col!r}")
    pref = m.group(1)
    union = (f"JOIN {tabla} c ON c.{pref}_id_cia = e.f400_id_cia AND c.{pref}_rowid_item_ext = e.f400_rowid_item_ext "
             f"AND c.{pref}_id_instalacion = e.f400_id_instalacion") if tabla else ""
    origen = "c" if tabla else "e"
    # Una referencia puede tener varias extensiones (unidad, caja...) con costos distintos: se toma el de la extension que tiene el
    # inventario en esas bodegas (la que se maneja como unidad), no el maximo de todas (la caja saldria 12 veces mas cara).
    return f"""
SELECT referencia, costo FROM (
  SELECT RTRIM(i.f120_referencia) AS referencia, CONVERT(float, MAX({origen}.{col})) AS costo,
         ROW_NUMBER() OVER (PARTITION BY RTRIM(i.f120_referencia)
                            ORDER BY SUM(e.f400_cant_existencia_1) DESC, MAX({origen}.{col})) AS rn
  FROM t400_cm_existencia e
  JOIN t150_mc_bodegas b ON b.f150_rowid = e.f400_rowid_bodega
  JOIN t121_mc_items_extensiones x ON x.f121_rowid = e.f400_rowid_item_ext
  JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item
  {union}
  WHERE i.f120_id_cia = :cia AND b.f150_id IN :bodegas AND {origen}.{col} > 0 /*ACTIVO:x,i*/
  GROUP BY RTRIM(i.f120_referencia), e.f400_rowid_item_ext) q
WHERE rn = 1"""


SQL_CO = "SELECT RTRIM(f150_id), RTRIM(f150_id_co) FROM t150_mc_bodegas WHERE f150_id_cia = :cia AND f150_id IN :bodegas"

def _sql_items(con_estado: bool) -> str:
    """Referencia, descripcion y, si la columna de estado existe, cuantas extensiones (t121) de esa referencia estan activas y cuantas
    bloqueadas (una referencia puede tener varias extensiones: es activa si alguna lo es)."""
    if not con_estado:
        return """SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)), CAST(NULL AS int), CAST(NULL AS int) FROM t120_mc_items
WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' GROUP BY RTRIM(f120_referencia)"""
    col = _col_estado()
    return f"""SELECT RTRIM(i.f120_referencia), MAX(RTRIM(i.f120_descripcion)),
       SUM(CASE WHEN x.{col} = {int(settings.siesa_item_estado_activo)} THEN 1 ELSE 0 END),
       SUM(CASE WHEN x.{col} = {int(settings.siesa_item_estado_bloqueado)} THEN 1 ELSE 0 END)
FROM t120_mc_items i LEFT JOIN t121_mc_items_extensiones x ON x.f121_rowid_item = i.f120_rowid
WHERE i.f120_id_cia = :cia AND i.f120_referencia IS NOT NULL AND RTRIM(i.f120_referencia) <> '' GROUP BY RTRIM(i.f120_referencia)"""

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
WHERE t.f406_ind_estado = 0 AND t.f406_id_cia = :cia AND be.f150_id IN :bodegas /*ACTIVO:x,i*/
GROUP BY i.f120_referencia, be.f150_id, bs.f150_id
HAVING SUM(t.f406_cant_base_pendiente) > 0"""

ACTIVO_RE = re.compile(r"/\*ACTIVO:(\w+),(\w+)\*/")


def _purgar_fuera_del_maestro(cur) -> int:
    """Quita de ventas, inventario, transitos, demanda y fotos lo que no esta en maestro_item (p.ej. materia prima MP...). Devuelve cuantas filas."""
    n = 0
    for sql in purgas_fuera_del_maestro():
        cur.execute(sql); n += max(cur.rowcount, 0)
    if n:
        log.info("Se sacaron %s filas de items que no estan en el maestro de items", n)
    return n


def _col_estado() -> str:
    col = settings.siesa_item_estado_col.strip().lower()
    if not re.fullmatch(r"f121_[a-z0-9_]+", col):
        raise ValueError(f"SIESA_ITEM_ESTADO_COL invalida: {col!r} (debe ser una columna de t121_mc_items_extensiones, p.ej. f121_ind_estado)")
    return col


def _cond_criterios(i: str) -> str:
    """Condicion de ITEM DEL MAESTRO sobre el alias `i` (t120): tiene alguno de los criterios de SIESA_CRITERIOS_ITEMS ("plan:criterio", los mismos
    con que se arma maestro_item) o es un REC (se suma a su original). Asi lo que no es del maestro (materia prima...) ni se trae de Siesa.
    Sin criterios configurados no filtra."""
    pares = [tuple(x.strip().split(":", 1)) for x in settings.siesa_criterios_items.split(",") if ":" in x]
    for plan, crit in pares:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", plan) or not re.fullmatch(r"[A-Za-z0-9_.-]+", crit):
            raise ValueError(f"SIESA_CRITERIOS_ITEMS invalido: {plan}:{crit}")
    if not pares:
        return ""
    por_plan: dict[str, list[str]] = {}
    for plan, crit in pares:
        por_plan.setdefault(plan, []).append(crit)
    alguno = " OR ".join(f"(cm.f125_id_plan = '{pl}' AND cm.f125_id_criterio_mayor IN ({', '.join(repr(c) for c in cs)}))" for pl, cs in por_plan.items())
    return (f"AND (EXISTS (SELECT 1 FROM t125_mc_items_criterios cm WHERE cm.f125_rowid_item = {i}.f120_rowid AND ({alguno})) "
            f"OR {i}.f120_descripcion LIKE 'REC[ .-]%')")


def _con_estado(sql: str, activo: bool) -> str:
    """Cada /*ACTIVO:ext,item*/ de la consulta se reemplaza por (1) la condicion de item del MAESTRO (criterios de SIESA_CRITERIOS_ITEMS; siempre) y
    (2) la de extension ACTIVA (alias de t121) o item REC (alias de t120: los REC se suman a su original y su estado no importa); (2) con
    activo=False por nada. Asi inventario, transitos, costos y ventas solo traen items del maestro y activos."""
    def cond(m):
        x, i = m.group(1), m.group(2)
        crit = _cond_criterios(i)
        if not activo:
            return crit
        return f"{crit} AND ({x}.{_col_estado()} = {int(settings.siesa_item_estado_activo)} OR {i}.f120_descripcion LIKE 'REC[ .-]%')"
    return ACTIVO_RE.sub(cond, sql)


def _probe_estado(eng) -> str | None:
    """None si la columna de estado se puede leer en t121; si no, el mensaje de error."""
    try:
        with eng.connect() as c:
            c.execute(text(f"SELECT TOP 1 {_col_estado()} FROM t121_mc_items_extensiones"))
        return None
    except Exception as e:   # solo fallos del origen (la columna no existe, permisos...)
        return str(e).splitlines()[0][:200]


def _solo_activos(cur) -> bool:
    """Regla 'solo_items_activos' (por defecto Si)."""
    v = _param(cur, "solo_items_activos")
    return True if v is None else v >= 1


def _filtrar_activos(solo: bool, eng) -> tuple[bool, str | None]:
    """(filtrar, aviso). Si la columna de estado no existe se sigue SIN filtrar (como antes) y se avisa en el resultado del ETL."""
    if not solo:
        return False, None
    err = _probe_estado(eng)
    if err:
        log.warning("Sin filtro de estado de items: no se pudo leer %s en t121 (%s). Revisa SIESA_ITEM_ESTADO_COL.", settings.siesa_item_estado_col, err)
        return False, f"No se filtro por estado: no se pudo leer {settings.siesa_item_estado_col} en t121 ({err}). Revisa SIESA_ITEM_ESTADO_COL."
    return True, None


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


def _costos(cur, eng, bodegas: list[str], pisar: bool, filtrar: bool = False) -> int | str:
    """Costo promedio por referencia de esas bodegas -> ddmrp.costo_item. `pisar`=True (CEDI) manda sobre lo que haya;
    False (tiendas) solo llena lo que falte. Un fallo del origen (p.ej. la columna no existe) no tumba el ETL: devuelve el aviso."""
    try:
        filas = list(_stream(eng, _con_estado(_sql_costo(), filtrar), {"cia": settings.siesa_cia, "bodegas": bodegas}, expanding="bodegas"))
    except Exception as e:
        if isinstance(e, psycopg.Error):
            raise
        log.warning("Costos no leidos (revisa SIESA_COSTO_TABLA/COLUMNA=%s.%s): %s", settings.siesa_costo_tabla, settings.siesa_costo_columna, e)
        return "no se pudo leer " + settings.siesa_costo_tabla + "." + settings.siesa_costo_columna + ": " + str(e)[:150]
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
                                              for r in c.execute(text("SELECT empresa, producto_id, bodega_id, fecha_corte, disponible FROM ddmrp.inventario_actual WHERE bodega_id = :b AND producto_id = :p"), {"b": bodega, "p": producto}).mappings()]
        out["local"]["costo"] = [float(r[0]) for r in c.execute(text("SELECT costo FROM ddmrp.costo_item WHERE producto_id = :p"), {"p": producto}).all()]
        out["local"]["resta_comprometido"] = bool((c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='inv_tiendas_resta_comprometido'")).scalar() or 0))
        out["local"]["resta_sin_acumular"] = bool((c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='inv_tiendas_resta_sin_acumular'")).scalar() or 0))
        out["local"]["en_maestro"] = c.execute(text("SELECT count(*) FROM ddmrp.maestro_item WHERE producto_id = :p"), {"p": producto}).scalar() > 0
        out["local"]["estado"] = [dict(r) for r in c.execute(text("SELECT empresa, estado FROM ddmrp.item_estado WHERE producto_id = :p"), {"p": producto}).mappings()]
        out["local"]["ultimo_etl_inventario"] = str(c.execute(text("SELECT max(fecha_corte) FROM ddmrp.inventario_actual WHERE bodega_id = :b"), {"b": bodega}).scalar())
        out["local"]["filas_bodega"] = c.execute(text("SELECT count(*) FROM ddmrp.inventario_actual WHERE bodega_id = :b"), {"b": bodega}).scalar()
        resta = int(out["local"]["resta_comprometido"]); resta_sa = int(out["local"]["resta_sin_acumular"])
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
        except Exception as e:
            out["siesa"].append({"empresa": empresa, "base": db, "error": str(e)[:300]})
    out["etl"] = _por_que_no_entra(out, bodega, producto, resta, resta_sa)
    return out


def _por_que_no_entra(out: dict, bodega: str, producto: str, resta: int, resta_sa: int) -> list[dict]:
    """Corre la consulta de inventario del ETL para esa tienda con tres niveles de filtro (ninguno, solo items del maestro, maestro + activos) y las
    extensiones del item con su estado, para decir en cual filtro se pierde la existencia que Siesa si tiene."""
    res = []
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db or not any(x["empresa"] == empresa and "columnas" in x for x in out["siesa"]):
            continue
        r: dict = {"empresa": empresa, "pasos": [], "extensiones": []}
        try:
            eng = siesa_engine(db)
            prm = {"cia": settings.siesa_cia, "bodegas": [bodega], "resta": resta, "resta_sa": resta_sa}
            def valor(sql: str):
                for ref, _b, _f, disp in _stream(eng, sql, prm, expanding="bodegas"):
                    if ref == producto:
                        return float(disp) if disp is not None else None
                return "sin fila"
            r["pasos"] = [
                {"filtro": "ninguno (toda la existencia de Siesa)", "valor": valor(ACTIVO_RE.sub("", SQL_INVENTARIO))},
                {"filtro": "solo items del maestro (criterios SIESA_CRITERIOS_ITEMS)", "valor": valor(_con_estado(SQL_INVENTARIO, False))},
                {"filtro": "maestro + solo extensiones activas (lo que hace el ETL)", "valor": valor(_con_estado(SQL_INVENTARIO, True))},
            ]
            col = _col_estado()
            for rowid, est in _stream(eng, f"SELECT x.f121_rowid, x.{col} FROM t121_mc_items_extensiones x "
                                                  f"JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item WHERE i.f120_id_cia = :cia AND RTRIM(i.f120_referencia) = :p",
                                              {"cia": settings.siesa_cia, "p": producto}):
                r["extensiones"].append({"rowid": rowid, "estado": est})
            r["extensiones_nota"] = f"estado en {col} (el ETL deja pasar solo {settings.siesa_item_estado_activo} = activo)"
            v = [p_["valor"] for p_ in r["pasos"]]
            num = lambda x: isinstance(x, (int, float))
            if num(v[0]) and not num(v[1]):
                r["causa"] = "El item NO pasa el filtro de criterios del maestro en esta empresa (SIESA_CRITERIOS_ITEMS): se descarta aunque tenga existencia."
            elif num(v[1]) and not num(v[2]):
                r["causa"] = "La extensión del item que tiene la existencia está inactiva o bloqueada en Siesa (aunque otra extensión del mismo item esté activa): el filtro de estado del ETL la descarta."
            elif num(v[2]):
                r["causa"] = "El ETL SI lo lee con sus filtros: si el sistema no lo tiene, el ETL no corrió desde que cambió la existencia, o fue purgado después (revisa Maestros → Items y la fecha del último ETL)."
            else:
                r["causa"] = "La consulta del ETL no devuelve fila para esa tienda y referencia (revisa la bodega y que la referencia sea la de t120)."
        except Exception as e:
            r["error"] = str(e).splitlines()[0][:300]
        res.append(r)
    return res


def diagnostico_estado_items() -> dict:
    """En vivo, por empresa: cuantas extensiones de item hay en cada valor de la columna de estado de t121 (para confirmar la columna y que 1 = activo,
    0 = inactivo, 2 = bloqueado antes de confiar en el filtro) y los items REC que se sumarian a su original. Solo lectura."""
    out: dict = {"columna": settings.siesa_item_estado_col, "valor_activo": settings.siesa_item_estado_activo,
                 "valor_bloqueado": settings.siesa_item_estado_bloqueado, "empresas": []}
    if not settings.siesa_host:
        out["aviso"] = "Siesa no esta configurado"; return out
    col = _col_estado()
    for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
        if not db:
            continue
        try:
            eng = siesa_engine(db)
            estados = [{"estado": r[0], "extensiones": r[1], "rec": r[2]} for r in _stream(
                eng, f"SELECT x.{col}, COUNT(*), SUM(CASE WHEN i.f120_descripcion LIKE 'REC[ .-]%' THEN 1 ELSE 0 END) "
                     f"FROM t121_mc_items_extensiones x JOIN t120_mc_items i ON i.f120_rowid = x.f121_rowid_item "
                     f"WHERE i.f120_id_cia = :cia GROUP BY x.{col} ORDER BY x.{col}", {"cia": settings.siesa_cia})]
            todos = [(r[0], r[1]) for r in _stream(eng, "SELECT RTRIM(f120_referencia), MAX(RTRIM(f120_descripcion)) FROM t120_mc_items "
                                                        "WHERE f120_id_cia = :cia AND f120_referencia IS NOT NULL AND RTRIM(f120_referencia) <> '' "
                                                        "GROUP BY RTRIM(f120_referencia)", {"cia": settings.siesa_cia})]
            pares, sin = detectar_rec(todos)
            out["empresas"].append({"empresa": empresa, "base": db, "estados": estados, "rec_con_original": len(pares), "rec_sin_original": sin[:20],
                                    "rec_ejemplos": [{"rec": r, "original": o, "descripcion": d} for r, o, d in pares[:15]]})
        except Exception as e:
            out["empresas"].append({"empresa": empresa, "base": db, "error": str(e).splitlines()[0][:300]})
    return out


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
                            "ON CONFLICT (empresa, bodega_id) DO UPDATE SET descripcion = EXCLUDED.descripcion",
                            (cod, empresa, nombre))
                n += 1
    cur.execute("INSERT INTO ddmrp.maestro_bodega (bodega_id, empresa) SELECT bodega_id, empresa FROM ddmrp.abast_bitacora "
                "ON CONFLICT (empresa, bodega_id) DO NOTHING")
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


def _items_de_siesa(cur, eng, primera: bool = True, empresa: str | None = None) -> dict:
    """Descripcion, laboratorio (plan 006) y TODOS los criterios de items de una base de Siesa.
    Primero se lee todo del origen y solo despues se escribe, para que un fallo de Siesa no deje la tabla a medias.
    Si hay dos bases (Funat y Stores), la primera manda y la segunda solo agrega lo que falte."""
    prm = {"cia": settings.siesa_cia}
    aviso_estado = _probe_estado(eng)     # None = la columna de estado existe
    items_all = list(_stream(eng, _sql_items(aviso_estado is None), prm))   # TODOS los t120: el estado y los REC se leen antes de filtrar por criterio
    items = [x[:2] for x in items_all]
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
    if empresa:   # a que empresa pertenece cada item (filtro por empresa de Maestros)
        cur.execute("DELETE FROM ddmrp.item_empresa WHERE empresa = %s", (empresa,))
        cur.execute("INSERT INTO ddmrp.item_empresa (empresa, producto_id) SELECT DISTINCT %s, producto_id FROM stg_items ON CONFLICT DO NOTHING", (empresa,))
    cur.execute("DROP TABLE stg_items")
    extra: dict = {}
    if empresa:
        if aviso_estado is None:   # estado de CADA item de Siesa (tambien los que quedan fuera de la seleccion por criterio)
            est = [(empresa, x[0], 1 if (x[2] or 0) > 0 else 2 if (x[3] or 0) > 0 else 0) for x in items_all]
            cur.execute("DELETE FROM ddmrp.item_estado WHERE empresa = %s", (empresa,))
            with cur.copy("COPY ddmrp.item_estado (empresa, producto_id, estado) FROM STDIN") as cp:
                for r in est:
                    cp.write_row(r)
            extra.update(activos=sum(1 for e in est if e[2] == 1), inactivos=sum(1 for e in est if e[2] == 0), bloqueados=sum(1 for e in est if e[2] == 2))
        else:
            extra["aviso_estado"] = f"No se filtra por estado: no se pudo leer {settings.siesa_item_estado_col} en t121 ({aviso_estado}). Revisa SIESA_ITEM_ESTADO_COL."
            log.warning(extra["aviso_estado"])
        pares, sin_original = detectar_rec(items_all)   # items REC -> su original (referencia sin el primer digito)
        cur.execute("DELETE FROM ddmrp.item_rec WHERE empresa = %s AND origen = 'auto'", (empresa,))
        cur.executemany("INSERT INTO ddmrp.item_rec (empresa, rec_id, original_id, descripcion, origen) VALUES (%s, %s, %s, %s, 'auto') "
                        "ON CONFLICT (empresa, rec_id) DO NOTHING", [(empresa, r, o, d) for r, o, d in pares])
        extra.update(rec=len(pares), rec_sin_original=len(sin_original))
        if sin_original:
            log.warning("Items REC sin original en Siesa (quedan como items normales): %s", ", ".join(sin_original[:10]))
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
    return {"items": len(items), "eliminados": borrados, "con_laboratorio": len(labs), "criterios": len(crit), "planes": len({c[1] for c in crit}), **extra}


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
                    out[empresa] = _items_de_siesa(cur, siesa_engine(db), primera=(empresa == "05"), empresa=empresa)
        raw.commit()
        return out
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()


def _cedi_de_siesa(cur) -> dict:
    """Inventario disponible del CEDI de cada empresa (05: SIESA_CEDI_BODEGA en la base Funat; 21: SIESA_CEDI_BODEGA_S en Stores).
    Se lee todo antes de escribir; si una empresa falla se conserva el ultimo corte de esa empresa y se avisa."""
    leidos: dict[str, tuple] = {}
    errores: dict[str, str] = {}
    avisos: dict[str, str] = {}
    solo = _solo_activos(cur)
    cur.execute("SELECT empresa, min(bodega_id) FROM ddmrp.maestro_cedi GROUP BY empresa")   # el CEDI de cada empresa sale del maestro de CEDIs
    cedis = dict(cur.fetchall())
    for emp, db, bod in (("05", settings.siesa_db, cedis.get("05") or settings.siesa_cedi_bodega), ("21", settings.siesa_db_s, cedis.get("21") or settings.siesa_cedi_bodega_s)):
        if not (db and bod):
            continue
        try:
            eng = siesa_engine(db)
            filtrar, aviso = _filtrar_activos(solo, eng)
            if aviso:
                avisos[emp] = aviso
            prm = {"cia": settings.siesa_cia, "bodegas": [bod], "resta": 1, "resta_sa": 0}
            filas = list(_stream(eng, _con_estado(SQL_INVENTARIO, filtrar), prm, expanding="bodegas"))   # el CEDI siempre descuenta lo comprometido; las ventas sin acumular no aplican
            try:   # existencia FISICA (sin descontar lo comprometido) de todos los items: base de los lanzamientos. Si falla, solo se omiten los lanzamientos
                fisica = list(_stream(eng, _con_estado(SQL_INVENTARIO, False), {**prm, "resta": 0}, expanding="bodegas"))
            except Exception as e:
                log.warning("Existencia fisica del CEDI %s no leida (lanzamientos omitidos): %s", emp, e); fisica = None
            leidos[emp] = (bod, eng, filas, fisica, filtrar)
        except Exception as e:
            if emp == "05":
                raise
            log.warning("Inventario del CEDI de la empresa %s no leido: %s", emp, e); errores[emp] = str(e)[:200]
    cur.execute("SELECT empresa, rec_id, original_id FROM ddmrp.v_item_rec")   # los REC suman al original
    rec: dict[str, dict[str, str]] = {}
    for e_, r_, o_ in cur.fetchall():
        rec.setdefault(e_, {})[r_] = o_
    out: dict = {}
    lanz: dict = {}
    for emp, (bod, eng, filas, fisica, filtrar) in leidos.items():
        costos = _costos(cur, eng, [bod], pisar=(emp == "05"), filtrar=filtrar)   # el costo del CEDI de Funat manda; el de Stores solo llena lo que falte
        cur.execute("DELETE FROM ddmrp.inventario_cedi WHERE empresa = %s", (emp,))
        mapa = rec.get(emp, {})
        datos: dict = {}
        for prod, _b, fecha, disp in filas:
            d = datos.setdefault(mapa.get(prod, prod), [fecha, 0.0])
            d[1] += float(disp or 0)
        for prod, (fecha, disp) in datos.items():
            cur.execute("INSERT INTO ddmrp.inventario_cedi (empresa, producto_id, disponible, fecha_corte) VALUES (%s, %s, %s, %s)", (emp, prod, max(disp, 0.0), fecha))
        out[emp] = {"bodega": bod, "productos": len(datos), "con_stock": sum(1 for d in datos.values() if d[1] > 0), "costos": costos, "rec_sumados": len(mapa)}
        if fisica is not None:
            exist: dict[str, float] = {}
            for prod, _b, fecha, disp in fisica:
                k = mapa.get(prod, prod)
                exist[k] = exist.get(k, 0.0) + float(disp or 0)
            hoy = (filas[0][2] if filas else fisica[0][2] if fisica else date.today())
            lanz[emp] = lanzamientos.registrar(cur, emp, exist, hoy)
    res = {**out["05"]} if "05" in out else {}
    res["por_empresa"] = out
    if lanz:
        res["lanzamientos"] = lanz
    if avisos:
        res["avisos_estado"] = avisos
    if errores:
        res["errores"] = errores
    return res


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
                solo = _solo_activos(cur)
                cur.execute("SELECT empresa, bodega_id FROM ddmrp.abast_bitacora")
                por_empresa: dict[str, list[str]] = {}
                for emp, b in cur.fetchall():
                    por_empresa.setdefault(emp, []).append(b)
                if not por_empresa:
                    raise RuntimeError("abast_bitacora esta vacia: cargala en Maestros antes de traer las ventas")
                cur.execute("CREATE TEMP TABLE stg_vm (empresa text, mes char(6), bodega_id text, producto_id text, cantidad numeric, valor numeric) ON COMMIT DROP")
                leidas: list[str] = []
                for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                    bodegas = por_empresa.get(empresa, [])
                    if not db or not bodegas:
                        continue
                    eng, n = siesa_engine(db), 0
                    filtrar, aviso = _filtrar_activos(solo, eng)
                    if aviso:
                        res[f"aviso_estado_{empresa}"] = aviso
                    progreso.avance(f"Leyendo ventas de {db} desde {desde:%Y-%m} ({len(bodegas)} bodegas)… puede tardar varios minutos")
                    with cur.copy("COPY stg_vm (empresa, mes, bodega_id, producto_id, cantidad, valor) FROM STDIN") as cp:
                        for r in _stream(eng, _con_estado(vsql, filtrar), {"cia": settings.siesa_cia, "bodegas": bodegas, "desde": desde}, expanding="bodegas"):
                            cp.write_row((empresa,) + tuple(r)); n += 1
                            if n % 50000 == 0:
                                progreso.avance(f"Leyendo ventas de {db}: {n:,} filas…")
                    res[f"ventas_{empresa}"] = n
                    leidas += [(empresa, b) for b in bodegas]
                if not leidas:
                    raise RuntimeError("No hay bodegas para leer (revisa SIESA_DB / SIESA_DB_S y la bitacora)")
                progreso.avance("Guardando las ventas en la base…")
                cur.execute("DELETE FROM ddmrp.ventas_mensual v WHERE v.mes >= %s AND (v.empresa || '|' || v.bodega_id) = ANY(%s)",
                            (f"{desde:%Y%m}", [f"{e}|{b}" for e, b in leidas]))
                cur.execute("""INSERT INTO ddmrp.ventas_mensual (empresa, mes, bodega_id, producto_id, cantidad, valor)
                               SELECT empresa, mes, bodega_id, producto_id, SUM(cantidad), COALESCE(SUM(valor), 0) FROM stg_vm
                               WHERE mes >= %s GROUP BY 1, 2, 3, 4""", (f"{desde:%Y%m}",))
                res["meses_desde"] = f"{desde:%Y%m}"
                ret = _param(cur, "meses_retencion_ventas")
                ret = int(min(max(ret if ret else 36, 13), 120))
                cur.execute("DELETE FROM ddmrp.ventas_mensual WHERE mes < to_char(current_date - make_interval(months => %s), 'YYYYMM')", (ret,))
                res["ventas_borradas_por_antiguas"] = cur.rowcount
                res["fuera_del_maestro"] = _purgar_fuera_del_maestro(cur)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()
    return res


def _analizar_tablas():
    """ANALYZE de lo que el ETL acaba de recargar: con estadisticas viejas Postgres elige planes pesimos en los informes (Clasificacion, Matriz)."""
    try:
        from ..estadisticas import analizar_todo
        analizar_todo()
    except Exception:
        log.exception("No se pudo actualizar las estadisticas tras el ETL (ANALYZE)")


def correr_etl(origen: str = "manual", usuario: str | None = None) -> dict:
    with progreso.tarea("ETL", "ETL listo"), bitacora.registrar("etl", origen, usuario) as r:
        r.resumen = res = _correr_etl(origen, usuario)
        _analizar_tablas()
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
            resta_sa = (_param(cur, "inv_tiendas_resta_sin_acumular") or 0) >= 1   # ventas del POS aun sin acumular (salida sin confirmar)
            solo = _solo_activos(cur)
            if not traer_ventas:
                log.info("ETL: las ventas por mes no se traen aqui (parametro etl_traer_ventas = 0); usa el boton 'Traer ventas'")
            for empresa, db in (("05", settings.siesa_db), ("21", settings.siesa_db_s)):
                bodegas = por_empresa.get(empresa, [])
                if not db or not bodegas:
                    continue
                eng, prm = siesa_engine(db), {"cia": settings.siesa_cia, "bodegas": bodegas}
                prm_inv = {**prm, "resta": 1 if resta_comp else 0, "resta_sa": 1 if resta_sa else 0}
                filtrar, aviso = _filtrar_activos(solo, eng)   # solo items activos de Siesa (y REC); sin la columna de estado no se filtra y se avisa
                if aviso:
                    res[f"aviso_estado_{empresa}"] = aviso
                log.info("ETL empresa %s (%s): %s bodegas", empresa, db, len(bodegas))
                progreso.avance(f"Leyendo inventario de Siesa ({db}, {len(bodegas)} bodegas)…")
                res[f"inventario_{empresa}"] = _volcar(
                    cur, ((empresa,) + r for r in _stream(eng, _con_estado(SQL_INVENTARIO, filtrar), prm_inv, expanding="bodegas")), "ddmrp.inventario_actual",
                    ["empresa", "producto_id", "bodega_id", "fecha_corte", "disponible"], reemplazar=False)
                progreso.avance(f"Leyendo costos promedio de Siesa ({db})…")
                res[f"costos_{empresa}"] = _costos(cur, eng, bodegas, pisar=False, filtrar=filtrar)   # respaldo: el costo del CEDI manda (se lee al final)
                progreso.avance(f"Leyendo traslados en tránsito de Siesa ({db})…")
                res[f"transitos_{empresa}"] = _volcar(
                    cur, ((empresa,) + r for r in _stream(eng, _con_estado(SQL_TRANSITOS, filtrar), prm, expanding="bodegas")), "ddmrp.transitos",
                    ["empresa", "producto_id", "bodega_id", "documento", "cantidad"], reemplazar=False)
                progreso.avance(f"Leyendo items, criterios y centros de operación ({db})…")
                try:  # descripciones, laboratorio, criterios y centro de operacion: utiles pero no criticos
                    res[f"items_{empresa}"] = _items_de_siesa(cur, eng, primera=(empresa == "05"), empresa=empresa)
                    for b, co in _stream(eng, SQL_CO, prm, expanding="bodegas"):
                        # solo completa el centro de operacion que falte en la bitacora (lo que el usuario escribio no se pisa; no crea tiendas)
                        cur.execute("UPDATE ddmrp.abast_bitacora SET id_co = %s WHERE empresa = %s AND bodega_id = %s AND (id_co IS NULL OR id_co = '')", (co, empresa, b))
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
            res["fuera_del_maestro"] = _purgar_fuera_del_maestro(cur)
        raw.commit()
    except Exception:
        raw.rollback()
        raise
    finally:
        raw.close()
    if traer_ventas:
        res.update(sincronizar_ventas(origen, usuario))
    return res
