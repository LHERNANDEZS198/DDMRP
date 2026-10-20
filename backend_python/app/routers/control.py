"""Vista de control DDMRP: indicadores por tienda / laboratorio / item con las zonas del buffer (rojo, amarillo, verde, exceso).
Siempre sobre la ultima ejecucion correcta del motor y limitado a lo que el usuario puede leer."""
from datetime import date, timedelta
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from .. import excel, mapa_calor
from ..activos import solo_activos
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, requiere

router = APIRouter(prefix="/control", tags=["control"], dependencies=[Depends(requiere("ver_control"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
ZONAS = ("ROJA", "AMARILLA", "VERDE", "EXCESO")
FROM = """FROM ddmrp.sugerencias_envio s
          LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id
          LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = s.bodega_id AND mb.empresa = s.empresa
          LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria"""


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="s", zona_expr="s.zona::text", crit=None) -> tuple[list[str], dict]:
    w, p = filtro_sql_permisos(user, f"{a}.bodega_id", "mi.categoria")
    cond = [w, solo_activos(a)]   # solo items activos de Siesa (regla solo_items_activos), tambien en la historia
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
        cond.append(f"({a}.empresa, {a}.bodega_id) IN (SELECT empresa, bodega_id FROM ddmrp.bodega_dia WHERE dia = :f_dia)"); p["f_dia"] = dia
    return cond, p


def _donde(user, bodegas, labs, q, zonas, dia, empresa=None, crit=None) -> tuple[str, dict]:
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, crit=crit)
    return " AND ".join([f"s.ejecucion_id = {ULTIMA}"] + cond), p


@router.get("/filtros")
def filtros(user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user)
    base = f"{FROM} WHERE s.ejecucion_id = {ULTIMA} AND {w} AND {solo_activos('s')}"
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo, fin FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        tiendas = [dict(r) for r in c.execute(text(
            f"SELECT s.bodega_id, string_agg(DISTINCT mb.descripcion, ' / ') AS nombre {base} GROUP BY s.bodega_id ORDER BY 1"), p).mappings()]
        labs = [dict(r) for r in c.execute(text(
            f"SELECT DISTINCT COALESCE(mi.categoria, '') AS codigo, lb.nombre {base} ORDER BY 1"), p).mappings()]
        empresas = [r[0] for r in c.execute(text(f"SELECT DISTINCT s.empresa {base} ORDER BY 1"), p)]
        dias = [r[0] for r in c.execute(text("SELECT DISTINCT dia FROM ddmrp.bodega_dia ORDER BY 1"))]
        crit_rows = c.execute(text("""SELECT ic.plan_id, COALESCE(p.nombre, ic.plan_id) AS plan_nombre, ic.criterio_id, COALESCE(cr.nombre, ic.criterio_id) AS nombre, count(*) AS n
                                      FROM ddmrp.item_criterio ic LEFT JOIN ddmrp.criterio_plan p ON p.plan_id = ic.plan_id
                                      LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id
                                      WHERE COALESCE(p.en_filtros, 1) = 1
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
                     COALESCE(sum(s.cantidad_sugerida), 0) AS unidades,
                     COALESCE(sum(s.inventario), 0) AS inventario, COALESCE(sum(s.en_transito), 0) AS en_transito,
                     COALESCE(sum(s.flujo_neto), 0) AS flujo_neto, COALESCE(sum(s.tog_aj), 0) AS tog_aj
              {frm} WHERE {w} GROUP BY 1{", s.empresa" if agrupar == "bodega" else ""} ORDER BY (count(*) FILTER (WHERE s.zona = 'ROJA'))::float / count(*) DESC, 1 LIMIT :lim"""
    tot = f"""SELECT count(*) AS n, count(*) FILTER (WHERE s.zona = 'ROJA') AS roja, count(*) FILTER (WHERE s.zona = 'AMARILLA') AS amarilla,
                     count(*) FILTER (WHERE s.zona = 'VERDE') AS verde, count(*) FILTER (WHERE s.zona = 'EXCESO') AS exceso,
                     round(avg(LEAST(COALESCE(s.pct_buffer, 0), 200)), 1) AS pct_prom,
                     COALESCE(sum(s.cantidad_sugerida), 0) AS unidades,
                     COALESCE(sum(s.inventario), 0) AS inventario, COALESCE(sum(s.en_transito), 0) AS en_transito,
                     COALESCE(sum(s.tog_aj), 0) AS tog_aj {FROM} WHERE {w}"""
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
        total = dict(c.execute(text(tot), p).mappings().first())
    return {"grupos": filas, "total": total}


def _sql_detalle(w: str) -> str:
    return f"""SELECT s.bodega_id, mb.descripcion AS bodega_nombre, s.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, s.zona::text AS zona, s.pct_buffer,
                     s.inventario, s.en_transito, s.flujo_neto, s.tor, s.toy_aj, s.tog_aj, s.adu, s.cantidad_sugerida, s.condenado,
                     (SELECT ci.costo::float8 FROM ddmrp.costo_item ci WHERE ci.producto_id = s.producto_id) AS costo
              {FROM} WHERE {w} ORDER BY s.pct_buffer NULLS FIRST, s.bodega_id, s.producto_id"""


@router.get("/detalle")
def detalle(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None,
            dia: int | None = None, empresa: str | None = None, crit: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    """Combinaciones tienda/item con los datos para dibujar la barra del buffer. Las mas criticas primero."""
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit)
    sql = _sql_detalle(w) + " LIMIT :lim"
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
    ON a.empresa = b.empresa AND a.bodega_id = b.bodega_id AND a.producto_id = b.producto_id)
"""
XFROM = """FROM x LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = x.producto_id
          LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = x.bodega_id AND mb.empresa = x.empresa
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
            f"{XCTE} SELECT {clave} AS clave, MAX({nombre}) AS nombre, {sel} {xfrom} WHERE {w} GROUP BY 1{", x.empresa" if agrupar == "bodega" else ""} "
            f"ORDER BY {cnt(MOV['entraron_rojo'])} DESC, 1 LIMIT :lim"), {**pr, "lim": limit}).mappings()]
        total = dict(c.execute(text(f"{XCTE} SELECT {sel} {xfrom} WHERE {w}"), pr).mappings().first())
        mat = [dict(r) for r in c.execute(text(
            f"{XCTE} SELECT x.zi AS de, x.zf AS a, count(*) AS n {xfrom} WHERE {w} AND x.zi IS NOT NULL AND x.zf IS NOT NULL GROUP BY 1, 2"), pr).mappings()]
    return {"periodo": fechas_, "grupos": grupos, "total": total, "matriz": mat}


def _cond_cambios_detalle(user, mov, bodegas, labs, q, zonas, dia, empresa, crit) -> tuple[str, dict]:
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="x", zona_expr="x.zf", crit=crit)
    if mov:
        if mov not in MOV:
            raise HTTPException(400, f"mov debe ser uno de {list(MOV)}")
        cond.append(MOV[mov])
    else:
        cond.append("(x.zi IS DISTINCT FROM x.zf OR x.zi IS NULL)")
    return " AND ".join(cond), p


def _sql_cambios_detalle(w: str) -> str:
    return f"""{XCTE} SELECT x.bodega_id, mb.descripcion AS bodega_nombre, x.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, x.zi AS zona_ini, x.zf AS zona_fin,
                     x.pi AS pct_ini, x.pf AS pct_fin, (COALESCE(x.pf, 0) - COALESCE(x.pi, 0)) AS delta
              {XFROM} WHERE {w} ORDER BY (COALESCE(x.rf, -1) - COALESCE(x.ri, 3)), delta, x.bodega_id, x.producto_id"""


@router.get("/cambios/detalle")
def cambios_detalle(desde: date | None = None, hasta: date | None = None, mov: str | None = None, bodegas: str | None = None,
                    labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
                    empresa: str | None = None, crit: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    w, p = _cond_cambios_detalle(user, mov, bodegas, labs, q, zonas, dia, empresa, crit)
    sql = _sql_cambios_detalle(w) + " LIMIT :lim"
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
                     count(*) FILTER (WHERE h.inventario > 0) AS con_stock,
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


# ===================== Vista 4: mapa de calor item x tienda x fecha =====================
def _mapa_datos(c, user, bodegas, labs, q, zonas, dia, empresa, crit, desde, hasta, paso, metrica, orden, limit):
    """Una fila por tienda/item (las combinaciones que existen en la ultima foto del periodo) y una columna por fecha con foto.
    `zonas` filtra por la zona de la ultima foto. Devuelve (fechas, filas, total, periodo)."""
    if metrica not in mapa_calor.METRICAS:
        raise HTTPException(400, f"metrica debe ser una de {list(mapa_calor.METRICAS)}")
    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=30))
    if desde > hasta:
        desde, hasta = hasta, desde
    f_fin = _snapshot(c, hasta)
    disp = [r[0] for r in c.execute(text("SELECT DISTINCT fecha FROM ddmrp.buffer_historia WHERE fecha BETWEEN :d AND :h"), {"d": desde, "h": f_fin})]
    fechas_ = mapa_calor.elegir_fechas(disp or [f_fin], paso)
    f_fin = fechas_[-1]
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, a="h", zona_expr="h.zona::text", crit=crit)
    cond.append("h.fecha = :f_fin"); p["f_fin"] = f_fin
    w = " AND ".join(cond)
    base = """FROM ddmrp.buffer_historia h
              LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = h.producto_id
              LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = h.bodega_id AND mb.empresa = h.empresa
              LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria"""
    ORDEN = {"critico": "h.pct_buffer NULLS FIRST, h.bodega_id, h.producto_id",
             "item": "h.producto_id, h.bodega_id", "tienda": "h.bodega_id, h.producto_id"}
    if orden not in ORDEN:
        raise HTTPException(400, f"orden debe ser uno de {list(ORDEN)}")
    total = c.execute(text(f"SELECT count(*) {base} WHERE {w}"), p).scalar()
    sql = f"""SELECT h.empresa, h.bodega_id, mb.descripcion AS bodega_nombre, h.producto_id, mi.descripcion,
                     COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, h.zona::text AS zona, h.pct_buffer,
                     (SELECT s.adu::float8 FROM ddmrp.sugerencias_envio s WHERE s.ejecucion_id = {ULTIMA}
                        AND s.empresa = h.empresa AND s.bodega_id = h.bodega_id AND s.producto_id = h.producto_id) AS adu,
                     (SELECT ci.costo::float8 FROM ddmrp.costo_item ci WHERE ci.producto_id = h.producto_id) AS costo
              {base} WHERE {w} ORDER BY {ORDEN[orden]} LIMIT :lim"""
    combos = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
    llaves = [(r["empresa"], r["bodega_id"], r["producto_id"]) for r in combos]
    hist = []
    if llaves:
        hist = c.execute(text("""SELECT h.empresa, h.bodega_id, h.producto_id, h.fecha, h.zona::text, h.inventario, h.flujo_neto, h.pct_buffer
                                 FROM ddmrp.buffer_historia h
                                 JOIN unnest(CAST(:ke AS text[]), CAST(:kb AS text[]), CAST(:kp AS text[])) AS k(e, b, pr) ON k.e = h.empresa AND k.b = h.bodega_id AND k.pr = h.producto_id
                                 WHERE h.fecha = ANY(:fechas)"""),
                         {"ke": [k[0] for k in llaves], "kb": [k[1] for k in llaves], "kp": [k[2] for k in llaves], "fechas": fechas_}).all()
    piv = mapa_calor.pivotear(fechas_, llaves, hist, metrica)
    from .clasificacion import datos_clase      # import tardio: clasificacion importa de este modulo
    try:
        cls = datos_clase(user, empresa, bodegas, labs, crit, q) if llaves else {}
    except Exception:                            # la clasificacion es un extra: el mapa no debe caerse por ella
        cls = {}
    filas = []
    for r, k in zip(combos, llaves):
        v, z = piv[k]
        c = cls.get(k, {})
        filas.append({**r, "v": [mapa_calor.redondear(x, metrica) for x in v], "z": z, "clase": c.get("clase"), "ranking": c.get("ranking"),
                      "prom_venta": c.get("prom_venta"), "prom_unid": c.get("prom_unid")})
    return fechas_, filas, total, {"desde": fechas_[0], "hasta": fechas_[-1]}


@router.get("/mapa")
def mapa(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None,
         dia: int | None = None, empresa: str | None = None, crit: str | None = None, desde: date | None = None,
         hasta: date | None = None, paso: int = Query(1, ge=1, le=60), metrica: str = "inventario", orden: str = "critico",
         limit: int = Query(2000, le=20000), user=Depends(usuario_actual)):
    with pg.connect() as c:
        fechas_, filas, total, per = _mapa_datos(c, user, bodegas, labs, q, zonas, dia, empresa, crit, desde, hasta, paso, metrica, orden, limit)
    return {"periodo": per, "fechas": fechas_, "filas": filas, "total": total, "truncado": total > len(filas),
            "metrica": metrica, "metricas": mapa_calor.METRICAS}


# ===================== Excel (respeta todos los filtros activos) =====================
def _hoja_filtros(wb, user, titulo, pares):
    excel.hoja_texto(wb, "Filtros", [
        ("Reporte", titulo), ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")), ("Usuario", f"{user.get('nombre', '')} ({user.get('id', '')})"),
        *[(k, v) for k, v in pares if v not in (None, "")]])


def _dic_filtros(bodegas, labs, q, zonas, dia, empresa, crit):
    return [("Empresa", empresa), ("Tiendas", bodegas), ("Laboratorios", labs), ("Criterios", crit), ("Busqueda", q),
            ("Zonas", zonas), ("Dia de despacho", dia), ("Solo items activos", "Si (segun la regla solo_items_activos)")]


COLS_GRUPO = [{"t": "Clave", "k": "clave", "w": 16}, {"t": "Nombre", "k": "nombre", "w": 32}, {"t": "Combinaciones", "k": "n", "f": "int"},
              {"t": "Rojo", "k": "roja", "f": "int"}, {"t": "Amarillo", "k": "amarilla", "f": "int"}, {"t": "Verde", "k": "verde", "f": "int"},
              {"t": "Exceso", "k": "exceso", "f": "int"}, {"t": "% buffer prom", "k": "pct_prom", "f": "dec1"},
              {"t": "A pedir", "k": "a_pedir", "f": "int"}, {"t": "Unidades sugeridas", "k": "unidades", "f": "int"},
              {"t": "Inventario", "k": "inventario", "f": "int"}, {"t": "En transito", "k": "en_transito", "f": "int"},
              {"t": "Flujo neto", "k": "flujo_neto", "f": "int"}, {"t": "TOG ajustado", "k": "tog_aj", "f": "int"}]
COLS_DETALLE = [{"t": "Tienda", "k": "bodega_id", "w": 10}, {"t": "Nombre tienda", "k": "bodega_nombre", "w": 26},
                {"t": "Item", "k": "producto_id", "w": 12}, {"t": "Descripcion", "k": "descripcion", "w": 44},
                {"t": "Laboratorio", "k": "laboratorio", "w": 16}, {"t": "Zona", "k": "zona", "w": 11, "zona": True},
                {"t": "% buffer", "k": "pct_buffer", "f": "dec1"}, {"t": "Inventario", "k": "inventario", "f": "int"},
                {"t": "En transito", "k": "en_transito", "f": "int"}, {"t": "Flujo neto", "k": "flujo_neto", "f": "int"},
                {"t": "TOR", "k": "tor", "f": "dec1"}, {"t": "TOY ajustado", "k": "toy_aj", "f": "dec1"}, {"t": "TOG ajustado", "k": "tog_aj", "f": "dec1"},
                {"t": "ADU", "k": "adu", "f": "dec2"}, {"t": "Sugerido", "k": "cantidad_sugerida", "f": "int"},
                {"t": "Condenado", "k": "condenado", "w": 10}, {"t": "Costo", "k": "costo", "f": "cop"}]
COLS_CAMBIOS_G = [{"t": "Clave", "k": "clave", "w": 16}, {"t": "Nombre", "k": "nombre", "w": 32},
                  {"t": "Combin. inicio", "k": "n_ini", "f": "int"}, {"t": "Combin. fin", "k": "n_fin", "f": "int"},
                  *[{"t": f"{t} {s}", "k": f"{k}_{s2}", "f": "int"} for k, t in (("roja", "Rojo"), ("amarilla", "Amarillo"), ("verde", "Verde"), ("exceso", "Exceso"))
                    for s, s2 in (("inicio", "ini"), ("fin", "fin"))],
                  {"t": "% buffer inicio", "k": "pct_ini", "f": "dec1"}, {"t": "% buffer fin", "k": "pct_fin", "f": "dec1"},
                  {"t": "Entraron a rojo", "k": "entraron_rojo", "f": "int"}, {"t": "Salieron de rojo", "k": "salieron_rojo", "f": "int"},
                  {"t": "Entraron a exceso", "k": "entraron_exceso", "f": "int"}, {"t": "Salieron de exceso", "k": "salieron_exceso", "f": "int"},
                  {"t": "Empeoraron", "k": "empeoraron", "f": "int"}, {"t": "Mejoraron", "k": "mejoraron", "f": "int"}]
COLS_CAMBIOS_D = [{"t": "Tienda", "k": "bodega_id", "w": 10}, {"t": "Nombre tienda", "k": "bodega_nombre", "w": 26},
                  {"t": "Item", "k": "producto_id", "w": 12}, {"t": "Descripcion", "k": "descripcion", "w": 44},
                  {"t": "Laboratorio", "k": "laboratorio", "w": 16}, {"t": "Zona inicio", "k": "zona_ini", "w": 11, "zona": True},
                  {"t": "Zona fin", "k": "zona_fin", "w": 11, "zona": True}, {"t": "% buffer inicio", "k": "pct_ini", "f": "dec1"},
                  {"t": "% buffer fin", "k": "pct_fin", "f": "dec1"}, {"t": "Delta", "k": "delta", "f": "dec1"}]
COLS_TEND = [{"t": "Fecha", "k": "fecha", "w": 12}, {"t": "Combinaciones", "k": "n", "f": "int"}, {"t": "TOR", "k": "tor", "f": "int"},
             {"t": "TOY ajustado", "k": "toy_aj", "f": "int"}, {"t": "TOG ajustado", "k": "tog_aj", "f": "int"},
             {"t": "Inventario", "k": "inventario", "f": "int"}, {"t": "Flujo neto", "k": "flujo_neto", "f": "int"},
             {"t": "Con stock", "k": "con_stock", "f": "int"}, {"t": "Rojo", "k": "roja", "f": "int"}, {"t": "Amarillo", "k": "amarilla", "f": "int"},
             {"t": "Verde", "k": "verde", "f": "int"}, {"t": "Exceso", "k": "exceso", "f": "int"}]


def _stream(c, sql, params):
    return c.execution_options(stream_results=True).execute(text(sql), params).mappings()


def _respuesta(wb, nombre):
    return Response(excel.a_bytes(wb), media_type=excel.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}_{datetime.now():%Y%m%d_%H%M}.xlsx"'})


@router.get("/excel")
def exportar(vista: str = "foto", agrupar: str = "bodega", desde: date | None = None, hasta: date | None = None, mov: str | None = None,
             bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None,
             dia: int | None = None, empresa: str | None = None, crit: str | None = None, plan: str | None = None,
             user=Depends(usuario_actual)):
    """Excel de lo que se ve en pantalla, con los mismos filtros: resumen por `agrupar` + detalle tienda/item completo (sin el tope de la pantalla)."""
    if vista not in ("foto", "cambios", "tendencia"):
        raise HTTPException(400, "vista debe ser foto, cambios o tendencia")
    f = _dic_filtros(bodegas, labs, q, zonas, dia, empresa, crit)
    wb = excel.libro()
    if vista == "foto":
        r = resumen(agrupar, bodegas, labs, q, zonas, dia, empresa, crit, plan, 100000, user)
        excel.hoja(wb, "Resumen", COLS_GRUPO, r["grupos"] + [{"clave": "TOTAL", "nombre": "", **r["total"]}], fijar=2)
        w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit)
        with pg.connect() as c:
            ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).first()
            excel.hoja(wb, "Detalle", COLS_DETALLE, _stream(c, _sql_detalle(w), p), fijar=4)
        _hoja_filtros(wb, user, "Control DDMRP - foto actual", [("Agrupado por", agrupar), ("Corte del motor", f"{ej[1]} (ejecucion {ej[0]})" if ej else ""), *f])
    elif vista == "cambios":
        r = cambios(agrupar, desde, hasta, bodegas, labs, q, zonas, dia, empresa, crit, plan, 100000, user)
        excel.hoja(wb, "Resumen", COLS_CAMBIOS_G, r["grupos"] + [{"clave": "TOTAL", "nombre": "", **r["total"]}], fijar=2)
        w, p = _cond_cambios_detalle(user, mov, bodegas, labs, q, zonas, dia, empresa, crit)
        with pg.connect() as c:
            ids, per = _periodo(c, desde, hasta)
            excel.hoja(wb, "Detalle", COLS_CAMBIOS_D, _stream(c, _sql_cambios_detalle(w), {**p, **ids}), fijar=4)
        _hoja_filtros(wb, user, "Control DDMRP - cambios en un periodo",
                      [("Agrupado por", agrupar), ("Periodo (fotos)", f"{per['desde']} a {per['hasta']}"), ("Movimiento", mov), *f])
    else:
        r = tendencia(desde, hasta, bodegas, labs, q, dia, empresa, crit, user)
        excel.hoja(wb, "Tendencia", COLS_TEND, r["serie"], fijar=1)
        _hoja_filtros(wb, user, "Control DDMRP - tendencia diaria", [("Periodo", f"{r['desde']} a {r['hasta']}"), *[x for x in f if x[0] != "Zonas"]])
    return _respuesta(wb, f"control_{vista}")


@router.get("/mapa/excel")
def mapa_excel(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None,
               dia: int | None = None, empresa: str | None = None, crit: str | None = None, desde: date | None = None,
               hasta: date | None = None, paso: int = Query(1, ge=1, le=60), metrica: str = "inventario", orden: str = "critico",
               user=Depends(usuario_actual)):
    """Mapa de calor en Excel: numero + color de la zona por celda (rojo, amarillo, verde, exceso), igual al Excel de control."""
    with pg.connect() as c:
        n_fechas = len(mapa_calor.elegir_fechas([r[0] for r in c.execute(text(
            "SELECT DISTINCT fecha FROM ddmrp.buffer_historia WHERE fecha BETWEEN :d AND :h"),
            {"d": desde or ((hasta or date.today()) - timedelta(days=30)), "h": hasta or date.today()})] or [date.today()], paso)) or 1
        tope = max(1, 2_000_000 // (n_fechas + 8))          # filas x columnas <= ~2M celdas: Excel y la memoria lo aguantan
        fechas_, filas, total, per = _mapa_datos(c, user, bodegas, labs, q, zonas, dia, empresa, crit, desde, hasta, paso, metrica, orden, min(tope, 200000))
    cols = [{"t": "Tienda", "k": "bodega_id", "w": 9}, {"t": "Nombre tienda", "k": "bodega_nombre", "w": 24}, {"t": "Item", "k": "producto_id", "w": 11},
            {"t": "Descripcion", "k": "descripcion", "w": 40}, {"t": "Laboratorio", "k": "laboratorio", "w": 14},
            {"t": "ADU", "k": "adu", "f": "dec2", "w": 8}, {"t": "Costo", "k": "costo", "f": "cop", "w": 10},
            {"t": "Clase", "k": "clase", "w": 8}, {"t": "Ranking", "k": "ranking", "f": "int", "w": 9},
            {"t": "Prom. mes venta $", "k": "prom_venta", "f": "cop", "w": 14}, {"t": "Prom. mes unidades", "k": "prom_unid", "f": "int", "w": 12}]
    wb = excel.libro()
    excel.hoja_mapa(wb, "Mapa", cols, fechas_, filas)
    excel.hoja_texto(wb, "Leyenda", [("Numero de la celda", mapa_calor.METRICAS[metrica]), *[(n.title(), f"zona {n}") for _, n in excel.leyenda_zonas()],
                                     ("Celda vacia", "ese dia no hay foto del motor para la combinacion"),
                                     ("Clase / Ranking", "ABC x XYZ por margen de los ultimos 12 meses (o consumo a costo si las ventas aun no traen valor), recalculado con los filtros del mapa; ranking = puesto dentro de ese filtro"),
                                     ("Prom. mes venta / unidades", "venta neta sin IVA y unidades vendidas por mes en la ventana de 12 meses")])
    _hoja_filtros(wb, user, "Control DDMRP - mapa de calor", [("Periodo", f"{per['desde']} a {per['hasta']}"), ("Paso (dias)", paso), ("Orden", orden),
                  ("Filas", f"{len(filas)} de {total}" + (" (recortado: filtra mas)" if total > len(filas) else "")), *_dic_filtros(bodegas, labs, q, zonas, dia, empresa, crit)])
    return _respuesta(wb, "mapa_calor")
