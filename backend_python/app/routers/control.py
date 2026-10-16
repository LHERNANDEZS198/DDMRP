"""Vista de control DDMRP: indicadores por tienda / laboratorio / item con las zonas del buffer (rojo, amarillo, verde, exceso).
Siempre sobre la ultima ejecucion correcta del motor y limitado a lo que el usuario puede leer."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos

router = APIRouter(prefix="/control", tags=["control"])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
ZONAS = ("ROJA", "AMARILLA", "VERDE", "EXCESO")
FROM = """FROM ddmrp.sugerencias_envio s
          LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id
          LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = s.bodega_id
          LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria"""


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _donde(user, bodegas, labs, q, zonas, dia, empresa=None) -> tuple[str, dict]:
    w, p = filtro_sql_permisos(user)
    cond = [f"s.ejecucion_id = {ULTIMA}", w]
    if _csv(bodegas):
        cond.append("s.bodega_id = ANY(:f_bod)"); p["f_bod"] = _csv(bodegas)
    if _csv(labs):
        cond.append("COALESCE(mi.categoria, '') = ANY(:f_lab)"); p["f_lab"] = [("" if x == "(sin laboratorio)" else x) for x in _csv(labs)]
    if q and q.strip():
        cond.append("(s.producto_id ILIKE :f_q OR mi.descripcion ILIKE :f_q)"); p["f_q"] = f"%{q.strip()}%"
    z = [x for x in _csv(zonas) if x in ZONAS]
    if z:
        cond.append("s.zona::text = ANY(:f_z)"); p["f_z"] = z
    if _csv(empresa):
        cond.append("s.empresa = ANY(:f_emp)"); p["f_emp"] = _csv(empresa)
    if dia:
        cond.append("s.bodega_id IN (SELECT bodega_id FROM ddmrp.bodega_dia WHERE dia = :f_dia)"); p["f_dia"] = dia
    return " AND ".join(cond), p


@router.get("/filtros")
def filtros(user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user)
    base = f"{FROM} WHERE s.ejecucion_id = {ULTIMA} AND {w}"
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo, fin FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        tiendas = [dict(r) for r in c.execute(text(
            f"SELECT DISTINCT s.bodega_id, mb.descripcion AS nombre {base} ORDER BY 1"), p).mappings()]
        labs = [dict(r) for r in c.execute(text(
            f"SELECT DISTINCT COALESCE(mi.categoria, '') AS codigo, lb.nombre {base} ORDER BY 1"), p).mappings()]
        empresas = [r[0] for r in c.execute(text(f"SELECT DISTINCT s.empresa {base} ORDER BY 1"), p)]
        dias = [r[0] for r in c.execute(text("SELECT DISTINCT dia FROM ddmrp.bodega_dia ORDER BY 1"))]
    for l in labs:
        if not l["codigo"]:
            l["codigo"] = "(sin laboratorio)"
    return {"ejecucion": dict(ej) if ej else None, "tiendas": tiendas, "laboratorios": labs, "dias": dias, "empresas": empresas}


AGRUP = {
    "empresa": ("s.empresa", "CASE s.empresa WHEN '05' THEN 'Funat' WHEN '21' THEN 'Stores' ELSE s.empresa END"),
    "bodega": ("s.bodega_id", "mb.descripcion"),
    "laboratorio": ("COALESCE(mi.categoria, '(sin laboratorio)')", "lb.nombre"),
    "item": ("s.producto_id", "mi.descripcion"),
}


@router.get("/resumen")
def resumen(agrupar: str = "bodega", bodegas: str | None = None, labs: str | None = None, q: str | None = None,
            zonas: str | None = None, dia: int | None = None, empresa: str | None = None, limit: int = 1000, user=Depends(usuario_actual)):
    """Una fila por grupo con el numero de combinaciones en cada zona y el % de buffer promedio (cada % topado a 200)."""
    clave, nombre = AGRUP.get(agrupar, AGRUP["bodega"])
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa)
    sql = f"""SELECT {clave} AS clave, MAX({nombre}) AS nombre, count(*) AS n,
                     count(*) FILTER (WHERE s.zona = 'ROJA') AS roja, count(*) FILTER (WHERE s.zona = 'AMARILLA') AS amarilla,
                     count(*) FILTER (WHERE s.zona = 'VERDE') AS verde, count(*) FILTER (WHERE s.zona = 'EXCESO') AS exceso,
                     round(avg(LEAST(COALESCE(s.pct_buffer, 0), 200)), 1) AS pct_prom,
                     count(*) FILTER (WHERE s.cantidad_sugerida > 0) AS a_pedir,
                     COALESCE(sum(s.cantidad_sugerida), 0) AS unidades
              {FROM} WHERE {w} GROUP BY 1 ORDER BY (count(*) FILTER (WHERE s.zona = 'ROJA'))::float / count(*) DESC, 1 LIMIT :lim"""
    tot = f"""SELECT count(*) AS n, count(*) FILTER (WHERE s.zona = 'ROJA') AS roja, count(*) FILTER (WHERE s.zona = 'AMARILLA') AS amarilla,
                     count(*) FILTER (WHERE s.zona = 'VERDE') AS verde, count(*) FILTER (WHERE s.zona = 'EXCESO') AS exceso,
                     round(avg(LEAST(COALESCE(s.pct_buffer, 0), 200)), 1) AS pct_prom,
                     COALESCE(sum(s.cantidad_sugerida), 0) AS unidades {FROM} WHERE {w}"""
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
        total = dict(c.execute(text(tot), p).mappings().first())
    return {"grupos": filas, "total": total}


@router.get("/detalle")
def detalle(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None,
            dia: int | None = None, empresa: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    """Combinaciones tienda/item con los datos para dibujar la barra del buffer. Las mas criticas primero."""
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa)
    sql = f"""SELECT s.bodega_id, mb.descripcion AS bodega_nombre, s.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, s.zona::text AS zona, s.pct_buffer,
                     s.inventario, s.en_transito, s.flujo_neto, s.tor, s.toy_aj, s.tog_aj, s.adu, s.cantidad_sugerida
              {FROM} WHERE {w} ORDER BY s.pct_buffer NULLS FIRST, s.bodega_id, s.producto_id LIMIT :lim"""
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
        n = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
    return {"filas": filas, "total": n, "truncado": n > len(filas)}
