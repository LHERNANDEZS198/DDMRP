"""Reporte de lanzamientos: items que aparecen por primera vez con existencia en el CEDI y items que vuelven despues de un tiempo sin stock
(agotado, cartera, etc.). Los eventos los detecta el ETL (lanzamientos.registrar) comparando la existencia de cada corrida con la anterior;
no usa movimientos de Siesa. La historia empieza con la primera lectura del ETL (esa lectura es la base y no genera eventos)."""
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from .. import excel
from ..activos import solo_activos
from ..db import pg
from ..security import usuario_actual, requiere
from .control import _csv

router = APIRouter(prefix="/lanzamientos", tags=["lanzamientos"], dependencies=[Depends(requiere("ver_control"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"


def _sql(w: str) -> str:
    return f"""SELECT e.fecha, e.tipo, e.dias_sin_stock, e.empresa, e.producto_id, mi.descripcion,
                      COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, lb.nombre AS laboratorio_nombre,
                      e.existencia::float8 AS existencia,
                      (SELECT ci.costo::float8 FROM ddmrp.costo_item ci WHERE ci.producto_id = e.producto_id) AS costo,
                      st.tiendas, st.con_stock, st.en_rojo, st.sugerido
               FROM ddmrp.cedi_evento e
               LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = e.producto_id
               LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
               LEFT JOIN LATERAL (SELECT count(*) AS tiendas, count(*) FILTER (WHERE s.inventario > 0) AS con_stock,
                                         count(*) FILTER (WHERE s.zona = 'ROJA') AS en_rojo,
                                         COALESCE(sum(s.cantidad_sugerida), 0)::float8 AS sugerido
                                  FROM ddmrp.sugerencias_envio s
                                  WHERE s.ejecucion_id = {ULTIMA} AND s.producto_id = e.producto_id AND s.empresa = e.empresa) st ON TRUE
               WHERE {w} ORDER BY e.fecha DESC, e.empresa, e.producto_id"""


def _donde(desde, hasta, tipo, min_dias, empresa, labs, crit, q, e="e"):
    hasta = hasta or date.today()
    desde = desde or (hasta - timedelta(days=30))
    cond = ["e.fecha BETWEEN :d AND :h", solo_activos("e")]
    p: dict = {"d": desde, "h": hasta}
    if tipo:
        if tipo not in ("PRIMERA", "REINGRESO"):
            raise HTTPException(400, "tipo debe ser PRIMERA o REINGRESO")
        cond.append("e.tipo = :tipo"); p["tipo"] = tipo
    if min_dias and min_dias > 0:
        cond.append("(e.tipo = 'PRIMERA' OR e.dias_sin_stock >= :md)"); p["md"] = min_dias
    if _csv(empresa):
        cond.append("e.empresa = ANY(:emp)"); p["emp"] = _csv(empresa)
    if _csv(labs):
        cond.append("COALESCE(mi.categoria, '') = ANY(:labs)"); p["labs"] = [("" if x == "(sin laboratorio)" else x) for x in _csv(labs)]
    if q and q.strip():
        cond.append("(e.producto_id ILIKE :q OR mi.descripcion ILIKE :q)"); p["q"] = f"%{q.strip()}%"
    por_plan: dict[str, list[str]] = {}
    for x in _csv(crit):
        if ":" in x:
            pl, cr = x.split(":", 1); por_plan.setdefault(pl, []).append(cr)
    for i, (pl, crs) in enumerate(por_plan.items()):
        cond.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio ic{i} WHERE ic{i}.producto_id = e.producto_id AND ic{i}.plan_id = :cp{i} AND ic{i}.criterio_id = ANY(:cc{i}))")
        p[f"cp{i}"] = pl; p[f"cc{i}"] = crs
    return " AND ".join(cond), p, desde, hasta


@router.get("/filtros")
def filtros(user=Depends(usuario_actual)):
    with pg.connect() as c:
        labs = [dict(r) for r in c.execute(text(
            """SELECT DISTINCT COALESCE(mi.categoria, '') AS codigo, lb.nombre FROM ddmrp.cedi_evento e
               LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = e.producto_id LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria ORDER BY 1""")).mappings()]
        base = c.execute(text("SELECT empresa, fecha FROM ddmrp.cedi_base ORDER BY empresa")).all()
        crit_rows = c.execute(text("""SELECT ic.plan_id, COALESCE(p.nombre, ic.plan_id), ic.criterio_id, COALESCE(cr.nombre, ic.criterio_id)
                                      FROM (SELECT DISTINCT ic.plan_id, ic.criterio_id FROM ddmrp.item_criterio ic
                                            JOIN ddmrp.cedi_evento e ON e.producto_id = ic.producto_id) ic
                                      LEFT JOIN ddmrp.criterio_plan p ON p.plan_id = ic.plan_id
                                      LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id ORDER BY 1, 3""")).all()
    for l in labs:
        if not l["codigo"]:
            l["codigo"] = "(sin laboratorio)"
    crit: dict[str, dict] = {}
    for pid, pn, cid, cn in crit_rows:
        crit.setdefault(pid, {"plan_id": pid, "nombre": pn, "valores": []})["valores"].append({"id": cid, "nombre": cn})
    return {"laboratorios": labs, "criterios": list(crit.values()), "base": [{"empresa": e, "fecha": f} for e, f in base]}


@router.get("")
def listar(desde: date | None = None, hasta: date | None = None, tipo: str | None = None, min_dias: int = 0, empresa: str | None = None,
           labs: str | None = None, crit: str | None = None, q: str | None = None, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    w, p, d, h = _donde(desde, hasta, tipo, min_dias, empresa, labs, crit, q)
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(_sql(w) + " LIMIT :lim"), {**p, "lim": limit}).mappings()]
        n = c.execute(text(f"SELECT count(*) FROM ddmrp.cedi_evento e LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = e.producto_id WHERE {w}"), p).scalar()
        base = c.execute(text("SELECT min(fecha) FROM ddmrp.cedi_base")).scalar()
    return {"desde": d, "hasta": h, "filas": filas, "total": n, "truncado": n > len(filas), "historia_desde": base}


COLS = [{"t": "Fecha", "k": "fecha", "w": 12}, {"t": "Tipo", "k": "tipo", "w": 11}, {"t": "Dias sin stock", "k": "dias_sin_stock", "f": "int"},
        {"t": "Empresa", "k": "empresa", "w": 8}, {"t": "Item", "k": "producto_id", "w": 11}, {"t": "Descripcion", "k": "descripcion", "w": 44},
        {"t": "Laboratorio", "k": "laboratorio", "w": 14}, {"t": "Nombre laboratorio", "k": "laboratorio_nombre", "w": 24},
        {"t": "Existencia CEDI", "k": "existencia", "f": "int"}, {"t": "Costo", "k": "costo", "f": "cop"},
        {"t": "Tiendas", "k": "tiendas", "f": "int"}, {"t": "Tiendas con stock", "k": "con_stock", "f": "int"},
        {"t": "Tiendas en rojo", "k": "en_rojo", "f": "int"}, {"t": "Sugerido (un.)", "k": "sugerido", "f": "int"}]


@router.get("/excel")
def exportar(desde: date | None = None, hasta: date | None = None, tipo: str | None = None, min_dias: int = 0, empresa: str | None = None,
             labs: str | None = None, crit: str | None = None, q: str | None = None, user=Depends(usuario_actual)):
    w, p, d, h = _donde(desde, hasta, tipo, min_dias, empresa, labs, crit, q)
    wb = excel.libro()
    with pg.connect() as c:
        filas = c.execution_options(stream_results=True).execute(text(_sql(w)), p).mappings()
        excel.hoja(wb, "Lanzamientos", COLS, filas, fijar=6)
    excel.hoja_texto(wb, "Filtros", [("Reporte", "Lanzamientos y reingresos del CEDI"), ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")),
                                     ("Usuario", f"{user.get('nombre', '')} ({user.get('id', '')})"), ("Ventana", f"{d} a {h}"),
                                     ("Tipo", tipo or "todos"), ("Min. dias sin stock (reingresos)", min_dias or ""), ("Empresa", empresa or "todas"),
                                     ("Laboratorios", labs or ""), ("Criterios", crit or ""), ("Busqueda", q or ""),
                                     ("Nota", "PRIMERA = primera existencia vista por el ETL; REINGRESO = vuelve a tener stock tras dias sin stock. Solo items activos.")])
    return Response(excel.a_bytes(wb), media_type=excel.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="lanzamientos_{datetime.now():%Y%m%d_%H%M}.xlsx"'})
