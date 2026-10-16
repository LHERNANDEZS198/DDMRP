"""Vista de control DDMRP: indicadores por tienda / laboratorio / item con las zonas del buffer (rojo, amarillo, verde, exceso).
Siempre sobre la ultima ejecucion correcta del motor y limitado a lo que el usuario puede leer."""
from datetime import date, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, requiere

router = APIRouter(prefix="/control", tags=["control"], dependencies=[Depends(requiere("ver_control"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
ZONAS = ("ROJA", "AMARILLA", "VERDE", "EXCESO")
FROM = """FROM ddmrp.sugerencias_envio s
          LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id
          LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = s.bodega_id
          LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria"""


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="s", zona_expr="s.zona::text", crit=None) -> tuple[list[str], dict]:
    w, p = filtro_sql_permisos(user, f"{a}.bodega_id", "mi.categoria")
    cond = [w]
    if _csv(bodegas):
        cond.append(f"{a}.bodega_id = ANY(:f_bod)"); p["f_bod"] = _csv(bodegas)
    if _csv(labs):
        cond.append("COALESCE(mi.categoria, '') = ANY(:f_lab)"); p["f_lab"] = [("" if x == "(sin laboratorio)" else x) for x in _csv(labs)]
    if q and q.strip():
        cond.append(f"({a}.producto_id ILIKE :f_q OR mi.descripcion ILIKE :f_q)"); p["f_q"] = f"%{q.strip()}%"
    z = [x for x in _csv(zonas) if x in ZONAS]
    if z:
        cond.append(f"{zona_expr} = ANY(:f_z)"); p["f_z"] = z
    por_plan: dict[str, list[str]] = {}
    for x in _csv(crit):                       # plan:criterio  (varios criterios del mismo plan = o, planes distintos = y)
        if ":" in x:
            pl, cr = x.split(":", 1); por_plan.setdefault(pl, []).append(cr)
    for i, (pl, crs) in enumerate(por_plan.items()):
        cond.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio ic{i} WHERE ic{i}.producto_id = {a}.producto_id "
                    f"AND ic{i}.plan_id = :cp{i} AND ic{i}.criterio_id = ANY(:cc{i}))")
        p[f"cp{i}"] = pl; p[f"cc{i}"] = crs
    if _csv(empresa):
        cond.append(f"{a}.empresa = ANY(:f_emp)"); p["f_emp"] = _csv(empresa)
    if dia:
        cond.append(f"{a}.bodega_id IN (SELECT bodega_id FROM ddmrp.bodega_dia WHERE dia = :f_dia)"); p["f_dia"] = dia
    return cond, p


def _donde(user, bodegas, labs, q, zonas, dia, empresa=None, crit=None) -> tuple[str, dict]:
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, crit=crit)
    return " AND ".join([f"s.ejecucion_id = {ULTIMA}"] + cond), p


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
        crit_rows = c.execute(text("""SELECT ic.plan_id, COALESCE(p.nombre, ic.plan_id) AS plan_nombre, ic.criterio_id, COALESCE(cr.nombre, ic.criterio_id) AS nombre, count(*) AS n
                                      FROM ddmrp.item_criterio ic LEFT JOIN ddmrp.criterio_plan p ON p.plan_id = ic.plan_id
                                      LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id
                                      GROUP BY 1, 2, 3, 4 ORDER BY 1, 3""")).all()
    for l in labs:
        if not l["codigo"]:
            l["codigo"] = "(sin laboratorio)"
    criterios: dict[str, dict] = {}
    for pid, pnom, cid, cnom, n in crit_rows:
        criterios.setdefault(pid, {"plan_id": pid, "nombre": pnom, "valores": []})["valores"].append({"id": cid, "nombre": cnom, "items": n})
    return {"ejecucion": dict(ej) if ej else None, "tiendas": tiendas, "laboratorios": labs, "dias": dias, "empresas": empresas,
            "criterios": list(criterios.values())}


CRIT_JOIN = """ LEFT JOIN ddmrp.item_criterio ic ON ic.producto_id = {a}.producto_id AND ic.plan_id = :g_plan
          LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id"""
AGRUP = {
    "criterio": ("COALESCE(ic.criterio_id, '(sin criterio)')", "cr.nombre"),
    "empresa": ("s.empresa", "CASE s.empresa WHEN '05' THEN 'Funat' WHEN '21' THEN 'Stores' ELSE s.empresa END"),
    "bodega": ("s.bodega_id", "mb.descripcion"),
    "laboratorio": ("COALESCE(mi.categoria, '(sin laboratorio)')", "lb.nombre"),
    "item": ("s.producto_id", "mi.descripcion"),
}


@router.get("/resumen")
def resumen(agrupar: str = "bodega", bodegas: str | None = None, labs: str | None = None, q: str | None = None,
            zonas: str | None = None, dia: int | None = None, empresa: str | None = None, crit: str | None = None, plan: str | None = None,
            limit: int = 1000, user=Depends(usuario_actual)):
    """Una fila por grupo con el numero de combinaciones en cada zona y el % de buffer promedio (cada % topado a 200)."""
    clave, nombre = AGRUP.get(agrupar, AGRUP["bodega"])
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit)
    frm = FROM
    if agrupar == "criterio":
        frm = FROM + CRIT_JOIN.format(a="s"); p["g_plan"] = plan or ""
    sql = f"""SELECT {clave} AS clave, MAX({nombre}) AS nombre, count(*) AS n,
                     count(*) FILTER (WHERE s.zona = 'ROJA') AS roja, count(*) FILTER (WHERE s.zona = 'AMARILLA') AS amarilla,
                     count(*) FILTER (WHERE s.zona = 'VERDE') AS verde, count(*) FILTER (WHERE s.zona = 'EXCESO') AS exceso,
                     round(avg(LEAST(COALESCE(s.pct_buffer, 0), 200)), 1) AS pct_prom,
                     count(*) FILTER (WHERE s.cantidad_sugerida > 0) AS a_pedir,
                     COALESCE(sum(s.cantidad_sugerida), 0) AS unidades
              {frm} WHERE {w} GROUP BY 1 ORDER BY (count(*) FILTER (WHERE s.zona = 'ROJA'))::float / count(*) DESC, 1 LIMIT :lim"""
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
            dia: int | None = None, empresa: str | None = None, crit: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    """Combinaciones tienda/item con los datos para dibujar la barra del buffer. Las mas criticas primero."""
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit)
    sql = f"""SELECT s.bodega_id, mb.descripcion AS bodega_nombre, s.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, s.zona::text AS zona, s.pct_buffer,
                     s.inventario, s.en_transito, s.flujo_neto, s.tor, s.toy_aj, s.tog_aj, s.adu, s.cantidad_sugerida, s.condenado
              {FROM} WHERE {w} ORDER BY s.pct_buffer NULLS FIRST, s.bodega_id, s.producto_id LIMIT :lim"""
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
        n = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
    return {"filas": filas, "total": n, "truncado": n > len(filas)}


# ===================== Vista 2: cambios en un periodo =====================
RANGO = "(CASE {z} WHEN 'ROJA' THEN 0 WHEN 'AMARILLA' THEN 1 WHEN 'VERDE' THEN 2 WHEN 'EXCESO' THEN 2 END)"
MOV = {   # nombre -> condicion sobre x (zi/zf = zona inicial/final, ri/rf = rango de riesgo 0 rojo .. 2 verde/exceso)
    "entraron_rojo": "x.zf = 'ROJA' AND x.zi IS NOT NULL AND x.zi <> 'ROJA'",
    "salieron_rojo": "x.zi = 'ROJA' AND x.zf IS NOT NULL AND x.zf <> 'ROJA'",
    "entraron_exceso": "x.zf = 'EXCESO' AND x.zi IS NOT NULL AND x.zi <> 'EXCESO'",
    "salieron_exceso": "x.zi = 'EXCESO' AND x.zf IS NOT NULL AND x.zf <> 'EXCESO'",
    "empeoraron": "x.rf < x.ri",
    "mejoraron": "x.rf > x.ri",
    "cambiaron": "x.zi IS NOT NULL AND x.zf IS NOT NULL AND x.zi <> x.zf",
}


def _snapshot(c, dia: date) -> date:
    """Ultima foto guardada hasta ese dia; si el dia es anterior a la primera foto, la primera."""
    r = c.execute(text("SELECT max(fecha) FROM ddmrp.buffer_historia WHERE fecha <= :d"), {"d": dia}).scalar() \
        or c.execute(text("SELECT min(fecha) FROM ddmrp.buffer_historia")).scalar()
    if not r:
        raise HTTPException(404, "Aun no hay historia: corre el motor al menos una vez")
    return r


XCTE = f"""WITH x AS (
  SELECT COALESCE(b.bodega_id, a.bodega_id) AS bodega_id, COALESCE(b.producto_id, a.producto_id) AS producto_id,
         COALESCE(b.empresa, a.empresa) AS empresa, a.zona::text AS zi, b.zona::text AS zf,
         a.pct_buffer AS pi, b.pct_buffer AS pf,
         {RANGO.format(z="a.zona::text")} AS ri, {RANGO.format(z="b.zona::text")} AS rf
  FROM (SELECT * FROM ddmrp.buffer_historia WHERE fecha = :e_ini) a
  FULL JOIN (SELECT * FROM ddmrp.buffer_historia WHERE fecha = :e_fin) b
    ON a.bodega_id = b.bodega_id AND a.producto_id = b.producto_id)
"""
XFROM = """FROM x LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = x.producto_id
          LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = x.bodega_id
          LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria"""


@router.get("/fechas")
def fechas(user=Depends(usuario_actual)):
    """Dias con foto guardada, para escoger el periodo."""
    with pg.connect() as c:
        rows = c.execute(text("SELECT DISTINCT fecha FROM ddmrp.buffer_historia ORDER BY fecha DESC LIMIT 800")).all()
    return [{"fecha": r[0]} for r in rows]


def _periodo(c, desde: date | None, hasta: date | None):
    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=7))
    if desde > hasta:
        desde, hasta = hasta, desde
    f_fin = _snapshot(c, hasta); f_ini = _snapshot(c, desde)
    return {"e_ini": f_ini, "e_fin": f_fin}, {"desde": f_ini, "hasta": f_fin}


@router.get("/cambios")
def cambios(agrupar: str = "bodega", desde: date | None = None, hasta: date | None = None, bodegas: str | None = None,
            labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
            empresa: str | None = None, crit: str | None = None, plan: str | None = None, limit: int = 1000, user=Depends(usuario_actual)):
    """Compara dos fotos del motor (inicio y fin del periodo): zonas, % de buffer y movimientos entre zonas por grupo.
    `zonas` filtra por la zona al final del periodo."""
    clave, nombre = AGRUP.get(agrupar, AGRUP["bodega"])
    clave, nombre = clave.replace("s.", "x."), nombre.replace("s.empresa", "x.empresa")
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="x", zona_expr="x.zf", crit=crit)
    w = " AND ".join(cond)
    xfrom = XFROM
    if agrupar == "criterio":
        xfrom = XFROM + CRIT_JOIN.format(a="x"); p["g_plan"] = plan or ""
    cnt = lambda e: f"count(*) FILTER (WHERE {e})"
    sel = ", ".join([
        f"{cnt('x.zi IS NOT NULL')} AS n_ini", f"{cnt('x.zf IS NOT NULL')} AS n_fin",
        *[f"{cnt(f'x.zi = {chr(39)}{z}{chr(39)}')} AS {k}_ini, {cnt(f'x.zf = {chr(39)}{z}{chr(39)}')} AS {k}_fin"
          for z, k in (("ROJA", "roja"), ("AMARILLA", "amarilla"), ("VERDE", "verde"), ("EXCESO", "exceso"))],
        "round((avg(LEAST(COALESCE(x.pi, 0), 200)) FILTER (WHERE x.zi IS NOT NULL))::numeric, 1) AS pct_ini",
        "round((avg(LEAST(COALESCE(x.pf, 0), 200)) FILTER (WHERE x.zf IS NOT NULL))::numeric, 1) AS pct_fin",
        *[f"{cnt(MOV[m])} AS {m}" for m in ("entraron_rojo", "salieron_rojo", "entraron_exceso", "salieron_exceso", "empeoraron", "mejoraron")],
    ])
    with pg.connect() as c:
        ids, fechas_ = _periodo(c, desde, hasta)
        pr = {**p, **ids}
        grupos = [dict(r) for r in c.execute(text(
            f"{XCTE} SELECT {clave} AS clave, MAX({nombre}) AS nombre, {sel} {xfrom} WHERE {w} GROUP BY 1 "
            f"ORDER BY {cnt(MOV['entraron_rojo'])} DESC, 1 LIMIT :lim"), {**pr, "lim": limit}).mappings()]
        total = dict(c.execute(text(f"{XCTE} SELECT {sel} {xfrom} WHERE {w}"), pr).mappings().first())
        mat = [dict(r) for r in c.execute(text(
            f"{XCTE} SELECT x.zi AS de, x.zf AS a, count(*) AS n {xfrom} WHERE {w} AND x.zi IS NOT NULL AND x.zf IS NOT NULL GROUP BY 1, 2"), pr).mappings()]
    return {"periodo": fechas_, "grupos": grupos, "total": total, "matriz": mat}


@router.get("/cambios/detalle")
def cambios_detalle(desde: date | None = None, hasta: date | None = None, mov: str | None = None, bodegas: str | None = None,
                    labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
                    empresa: str | None = None, crit: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="x", zona_expr="x.zf", crit=crit)
    if mov:
        if mov not in MOV:
            raise HTTPException(400, f"mov debe ser uno de {list(MOV)}")
        cond.append(MOV[mov])
    else:
        cond.append("(x.zi IS DISTINCT FROM x.zf OR x.zi IS NULL)")
    w = " AND ".join(cond)
    sql = f"""{XCTE} SELECT x.bodega_id, mb.descripcion AS bodega_nombre, x.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, x.zi AS zona_ini, x.zf AS zona_fin,
                     x.pi AS pct_ini, x.pf AS pct_fin, (COALESCE(x.pf, 0) - COALESCE(x.pi, 0)) AS delta
              {XFROM} WHERE {w} ORDER BY (COALESCE(x.rf, -1) - COALESCE(x.ri, 3)), delta, x.bodega_id, x.producto_id LIMIT :lim"""
    with pg.connect() as c:
        ids, fechas_ = _periodo(c, desde, hasta)
        pr = {**p, **ids}
        filas = [dict(r) for r in c.execute(text(sql), {**pr, "lim": limit}).mappings()]
        n = c.execute(text(f"{XCTE} SELECT count(*) {XFROM} WHERE {w}"), pr).scalar()
    return {"periodo": fechas_, "filas": filas, "total": n, "truncado": n > len(filas)}


# ===================== Vista 3: tendencia en el tiempo =====================
@router.get("/tendencia")
def tendencia(desde: date | None = None, hasta: date | None = None, bodegas: str | None = None, labs: str | None = None,
              q: str | None = None, dia: int | None = None, empresa: str | None = None, crit: str | None = None, user=Depends(usuario_actual)):
    """Serie diaria del buffer para lo filtrado: TOR, TOY y TOG ajustados, inventario y flujo neto (sumados si son varios
    items/tiendas) y cuantas combinaciones hay en cada zona. Con tienda e item exactos es la curva de una sola combinacion."""
    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=90))
    cond, p = _filtros(user, bodegas, labs, q, None, dia, empresa, a="h", crit=crit)
    cond.append("h.fecha BETWEEN :d AND :h")
    sql = f"""SELECT h.fecha, count(*) AS n, sum(h.tor) AS tor, sum(h.toy_aj) AS toy_aj, sum(h.tog_aj) AS tog_aj,
                     sum(h.inventario) AS inventario, sum(h.flujo_neto) AS flujo_neto,
                     count(*) FILTER (WHERE h.zona = 'ROJA') AS roja, count(*) FILTER (WHERE h.zona = 'AMARILLA') AS amarilla,
                     count(*) FILTER (WHERE h.zona = 'VERDE') AS verde, count(*) FILTER (WHERE h.zona = 'EXCESO') AS exceso
              FROM ddmrp.buffer_historia h
              LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = h.producto_id
              WHERE {' AND '.join(cond)} GROUP BY h.fecha ORDER BY h.fecha"""
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "d": desde, "h": hasta}).mappings()]
    for f in filas:
        for k in ("tor", "toy_aj", "tog_aj", "inventario", "flujo_neto"):
            f[k] = round(float(f[k] or 0), 1)
    return {"desde": desde, "hasta": hasta, "serie": filas, "combinaciones": max((f["n"] for f in filas), default=0)}
