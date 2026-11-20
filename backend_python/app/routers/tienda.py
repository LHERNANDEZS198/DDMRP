"""Vista por tienda: ventas (unidades, pesos, margen), inventario, GMROI y rotacion mes a mes, zonas del buffer por dia, comparativo (mismo periodo del anio anterior y
promedio de las tiendas de su clase) y pareto de items y laboratorios. Las ventas estan por mes (ventas_mensual); el inventario y las zonas tienen historia diaria."""
import logging
import traceback
import re
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from ..activos import solo_activos
from ..db import pg
from ..security import filtro_sql_permisos, requiere, empresas_permitidas
from .control import FROM as CTRL_FROM, ULTIMA

log = logging.getLogger(__name__)
router = APIRouter(prefix="/tienda", tags=["tienda"])
_MES = re.compile(r"^\d{6}$")


def _meses(desde: str, hasta: str) -> list[str]:
    if not (_MES.match(desde) and _MES.match(hasta)) or desde > hasta:
        raise HTTPException(400, "Elige un rango de meses valido (desde <= hasta)")
    y, m = int(desde[:4]), int(desde[4:])
    out = []
    while f"{y:04d}{m:02d}" <= hasta:
        out.append(f"{y:04d}{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
        if len(out) > 36:
            raise HTTPException(400, "Maximo 36 meses")
    return out


def _ant(m: str) -> str:
    return f"{int(m[:4]) - 1:04d}{m[4:]}"


def _clase_abc(filas: list[dict], clave: str, a: float = 80.0, b: float = 95.0) -> None:
    """Clase ABC por el aporte acumulado de `clave` (los que no aportan quedan en C)."""
    tot = sum(max(f[clave] or 0.0, 0.0) for f in filas)
    acum = 0.0
    for f in sorted(filas, key=lambda x: -(x[clave] or 0.0)):
        v = max(f[clave] or 0.0, 0.0)
        acum += v
        pct = 100.0 * acum / tot if tot > 0 else 100.0
        f["pct_acum"] = round(pct, 1)
        f["clase"] = "A" if v > 0 and (pct - 100.0 * v / tot) < a else ("B" if v > 0 and (pct - 100.0 * v / tot) < b else "C")


@router.get("")
def vista(bodega: str, empresa: str, desde: str, hasta: str, labs: str | None = None, comparar: bool = True, user=Depends(requiere("ver_control"))):
    try:
        return _vista(bodega, empresa, desde, hasta, labs, comparar, user)
    except HTTPException:
        raise
    except Exception as e:      # que la pantalla muestre la causa en vez de un "Internal Server Error" mudo
        log.exception("tienda")
        fr = traceback.extract_tb(e.__traceback__)[-1]
        raise HTTPException(500, f"Vista por tienda: {type(e).__name__}: {str(e).strip()[:400]} (tienda.py linea {fr.lineno}: {(fr.line or '').strip()[:200]})")


def _vista(bodega, empresa, desde, hasta, labs, comparar, user):
    if empresa not in ("05", "21"):
        raise HTTPException(400, "Elige la empresa")
    perm = empresas_permitidas(user["id"])
    if perm and empresa not in perm:
        raise HTTPException(403, f"Tu usuario no tiene asignada la empresa {empresa}")
    meses = _meses(desde, hasta)
    ant = [_ant(m) for m in meses]
    lista_labs = [("" if x == "(sin laboratorio)" else x) for x in (labs or "").split(",") if x.strip()]
    wp, p = filtro_sql_permisos(user, "a.bodega_id", "mi.categoria")
    p.update(emp=empresa, bod=bodega, ms=meses, ma=meses + ant)
    cl = " AND COALESCE(mi.categoria, '') = ANY(:labs)" if lista_labs else ""
    if lista_labs:
        p["labs"] = lista_labs
    ventas_from = """FROM ddmrp.ventas_mensual a
        LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = a.empresa AND mi.producto_id = a.producto_id
        LEFT JOIN ddmrp.costo_item ci ON ci.empresa = a.empresa AND ci.producto_id = a.producto_id"""
    base = f"a.empresa = :emp AND a.bodega_id = :bod AND {wp}{cl}"
    f_ini, f_fin = date(int(desde[:4]), int(desde[4:]), 1), date(int(hasta[:4]) + (int(hasta[4:]) == 12), int(hasta[4:]) % 12 + 1, 1)
    with pg.connect() as c:
        info = c.execute(text("SELECT mb.descripcion AS nombre, tc.clase FROM ddmrp.maestro_bodega mb LEFT JOIN ddmrp.v_tienda_clase tc ON tc.empresa = mb.empresa AND tc.bodega_id = mb.bodega_id "
                              "WHERE mb.empresa = :emp AND mb.bodega_id = :bod LIMIT 1"), {"emp": empresa, "bod": bodega}).mappings().first()
        # --- ventas por mes (y las del mismo periodo del anio anterior)
        vm: dict[str, dict] = {}
        for mes, cant, val, vcc, cv in c.execute(text(f"""
            SELECT a.mes, sum(a.cantidad)::float8, sum(a.valor)::float8, sum(a.valor) FILTER (WHERE ci.costo IS NOT NULL)::float8,
                   sum(a.cantidad * ci.costo)::float8 {ventas_from} WHERE {base} AND a.mes = ANY(:ma) GROUP BY a.mes"""), p):
            vm[mes] = {"unidades": cant or 0.0, "venta": val or 0.0, "margen": (vcc or 0.0) - (cv or 0.0), "venta_con_costo": vcc or 0.0}
        # --- promedio de las tiendas de la misma clase (mismos meses y laboratorios)
        clase_prom: dict[str, dict] = {}
        if info and info["clase"]:
            pc = {"emp": empresa, "bod": bodega, "ms": meses, "clase": info["clase"]}
            clc = " AND COALESCE(mi.categoria, '') = ANY(:labs)" if lista_labs else ""
            if lista_labs:
                pc["labs"] = lista_labs
            for mes, nt, cant, val in c.execute(text(f"""
                SELECT a.mes, count(DISTINCT a.bodega_id), sum(a.cantidad)::float8, sum(a.valor)::float8
                FROM ddmrp.ventas_mensual a JOIN ddmrp.v_tienda_clase tc ON tc.empresa = a.empresa AND tc.bodega_id = a.bodega_id AND tc.clase = :clase
                LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = a.empresa AND mi.producto_id = a.producto_id
                WHERE a.empresa = :emp AND a.bodega_id <> :bod AND a.mes = ANY(:ms){clc} GROUP BY a.mes"""), pc):
                if nt:
                    clase_prom[mes] = {"unidades": (cant or 0.0) / nt, "venta": (val or 0.0) / nt, "tiendas": nt}
        # --- inventario promedio del mes (a costo y en unidades) y % de dias sin stock
        wi = wp.replace("a.bodega_id", "im.bodega_id")
        inv: dict[str, dict] = {}
        for mes, iu, ic, dz, dt in c.execute(text(f"""
            SELECT im.mes, sum(im.inv_suma / NULLIF(im.dias, 0))::float8, sum(im.inv_suma / NULLIF(im.dias, 0) * ci.costo)::float8, sum(im.dias_cero)::float8, sum(im.dias)::float8
            FROM ddmrp.inventario_mes im LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = im.empresa AND mi.producto_id = im.producto_id
            LEFT JOIN ddmrp.costo_item ci ON ci.empresa = im.empresa AND ci.producto_id = im.producto_id
            WHERE im.empresa = :emp AND im.bodega_id = :bod AND im.mes = ANY(:ms) AND {wi}{cl} GROUP BY im.mes"""), p):
            inv[mes] = {"inv_unidades": iu or 0.0, "inv_costo": ic or 0.0, "pct_sin_stock": 100.0 * (dz or 0.0) / dt if dt else None}
        # --- zonas del buffer por dia
        wh = wp.replace("a.bodega_id", "h.bodega_id")
        zonas = [{"fecha": str(f), "roja": r, "amarilla": am, "verde": v, "exceso": e, "no_aplica": n, "agotado": ag, "n": t} for f, r, am, v, e, n, ag, t in c.execute(text(f"""
            SELECT h.fecha, count(*) FILTER (WHERE h.zona::text = 'ROJA'), count(*) FILTER (WHERE h.zona::text = 'AMARILLA'), count(*) FILTER (WHERE h.zona::text = 'VERDE'),
                   count(*) FILTER (WHERE h.zona::text = 'EXCESO'), count(*) FILTER (WHERE h.zona::text = 'NO_APLICA'),
                   count(*) FILTER (WHERE h.zona::text <> 'NO_APLICA' AND COALESCE(h.inventario, 0) <= 0), count(*)
            FROM ddmrp.buffer_historia h LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = h.empresa AND mi.producto_id = h.producto_id
            WHERE h.empresa = :emp AND h.bodega_id = :bod AND h.fecha >= :fi AND h.fecha < :ff AND {wh}{cl} GROUP BY h.fecha ORDER BY h.fecha"""), {**p, "fi": f_ini, "ff": f_fin})]
        # --- pareto de items y de laboratorios en el periodo
        items = [dict(r) for r in c.execute(text(f"""
            SELECT a.producto_id, max(mi.descripcion) AS descripcion, max(COALESCE(mi.categoria, '')) AS laboratorio, sum(a.cantidad)::float8 AS unidades, sum(a.valor)::float8 AS venta,
                   (COALESCE(sum(a.valor) FILTER (WHERE ci.costo IS NOT NULL), 0) - COALESCE(sum(a.cantidad * ci.costo), 0))::float8 AS margen
            {ventas_from} WHERE {base} AND a.mes = ANY(:ms) GROUP BY a.producto_id HAVING sum(a.valor) <> 0 OR sum(a.cantidad) <> 0"""), p).mappings()]
        nombres = {k: v for k, v in c.execute(text("SELECT codigo, nombre FROM ddmrp.laboratorio"))}
        # --- hoy: inventario a costo y zonas (ultima corrida del motor)
        pw, pp = filtro_sql_permisos(user, "s.bodega_id", "mi.categoria")
        pp.update(emp=empresa, bod=bodega)
        cs = ""
        if lista_labs:
            cs = " AND COALESCE(mi.categoria, '') = ANY(:labs)"; pp["labs"] = lista_labs
        hoy = c.execute(text(f"""
            SELECT count(*) FILTER (WHERE s.zona::text = 'ROJA'), count(*) FILTER (WHERE s.zona::text = 'AMARILLA'), count(*) FILTER (WHERE s.zona::text = 'VERDE'),
                   count(*) FILTER (WHERE s.zona::text = 'EXCESO'), count(*) FILTER (WHERE s.zona::text = 'NO_APLICA'),
                   count(*) FILTER (WHERE s.zona::text <> 'NO_APLICA' AND COALESCE(s.inventario, 0) <= 0), COALESCE(sum(s.inventario), 0)::float8,
                   COALESCE(sum(s.inventario * cx.costo), 0)::float8, COALESCE(sum(s.cantidad_sugerida), 0)::float8,
                   COALESCE(sum(s.tor), 0)::float8, COALESCE(sum(s.toy_aj), 0)::float8, COALESCE(sum(s.tog_aj), 0)::float8,
                   COALESCE(sum(s.tor * cx.costo), 0)::float8, COALESCE(sum(s.toy_aj * cx.costo), 0)::float8, COALESCE(sum(s.tog_aj * cx.costo), 0)::float8,
                   COALESCE(sum(s.cantidad_sugerida * cx.costo), 0)::float8
            {CTRL_FROM} LEFT JOIN ddmrp.costo_item cx ON cx.empresa = s.empresa AND cx.producto_id = s.producto_id
            WHERE s.ejecucion_id = {ULTIMA} AND s.empresa = :emp AND s.bodega_id = :bod AND {pw} AND {solo_activos('s')}{cs}"""), pp).one()
    # --- armado
    serie = []
    for m in meses:
        v = vm.get(m, {"unidades": 0.0, "venta": 0.0, "margen": 0.0, "venta_con_costo": 0.0})
        i = inv.get(m, {})
        a_ = vm.get(_ant(m)) if comparar else None
        cp = clase_prom.get(m) if comparar else None
        gm = (v["margen"] * 12.0 / i["inv_costo"]) if i.get("inv_costo") else None
        rot = (v["unidades"] / i["inv_unidades"]) if i.get("inv_unidades") else None
        serie.append({"mes": m, **v, "margen_pct": (100.0 * v["margen"] / v["venta_con_costo"]) if v["venta_con_costo"] else None,
                      "inv_costo": i.get("inv_costo"), "inv_unidades": i.get("inv_unidades"), "pct_sin_stock": i.get("pct_sin_stock"), "gmroi": gm, "rotacion": rot,
                      "venta_ant": a_["venta"] if a_ else None, "unidades_ant": a_["unidades"] if a_ else None, "margen_ant": a_["margen"] if a_ else None,
                      "venta_clase": cp["venta"] if cp else None, "unidades_clase": cp["unidades"] if cp else None})
    tot_v = sum(s["venta"] for s in serie); tot_u = sum(s["unidades"] for s in serie); tot_m = sum(s["margen"] for s in serie); tot_vcc = sum(s["venta_con_costo"] for s in serie)
    ics = [s["inv_costo"] for s in serie if s["inv_costo"]]
    inv_prom = sum(ics) / len(ics) if ics else None
    ant_v = sum((s["venta_ant"] or 0.0) for s in serie) if comparar else None
    _clase_abc(items, "margen")
    por_margen = sorted(items, key=lambda x: -(x["margen"] or 0.0))
    labs_g: dict[str, dict] = {}
    for it in items:
        g = labs_g.setdefault(it["laboratorio"], {"laboratorio": it["laboratorio"] or "(sin laboratorio)", "nombre": nombres.get(it["laboratorio"]), "items": 0, "unidades": 0.0, "venta": 0.0, "margen": 0.0})
        g["items"] += 1; g["unidades"] += it["unidades"] or 0.0; g["venta"] += it["venta"] or 0.0; g["margen"] += it["margen"] or 0.0
    labs_l = list(labs_g.values()); _clase_abc(labs_l, "margen")
    for g in labs_l:
        g["margen_pct"] = 100.0 * g["margen"] / g["venta"] if g["venta"] else None
        g["rot_promedio"] = g["unidades"] / len(meses)
    for it in items:
        it["margen_pct"] = 100.0 * (it["margen"] or 0.0) / it["venta"] if it["venta"] else None
        it["rot_promedio"] = (it["unidades"] or 0.0) / len(meses)      # unidades por mes en promedio durante el periodo
    dias_periodo = max(1, (f_fin - f_ini).days)
    inv_hoy_u = hoy[6]
    return {
        "tienda": {"bodega_id": bodega, "nombre": info["nombre"] if info else bodega, "clase": info["clase"] if info else None, "empresa": empresa},
        "kpi": {"venta": tot_v, "unidades": tot_u, "margen": tot_m, "margen_pct": 100.0 * tot_m / tot_vcc if tot_vcc else None, "venta_ant": ant_v,
                "var_venta_pct": 100.0 * (tot_v - ant_v) / ant_v if ant_v else None, "inv_costo_hoy": hoy[7], "inv_unidades_hoy": inv_hoy_u, "inv_costo_prom": inv_prom,
                "gmroi": (tot_m * 365.0 / dias_periodo / inv_prom) if inv_prom else None, "rotacion_mes": (tot_u / (dias_periodo / 30.4375) / (sum(s["inv_unidades"] or 0.0 for s in serie) / max(1, len([s for s in serie if s["inv_unidades"]])))) if any(s["inv_unidades"] for s in serie) else None,
                "dias_inventario": (inv_hoy_u / (tot_u / dias_periodo)) if tot_u > 0 else None, "sugerido_hoy": hoy[8], "sugerido_costo_hoy": hoy[15], "rot_promedio": tot_u / len(meses),
                "buffer": {"tor": hoy[9], "toy": hoy[10], "tog": hoy[11], "tor_costo": hoy[12], "toy_costo": hoy[13], "tog_costo": hoy[14]},
                "hoy": {"roja": hoy[0], "amarilla": hoy[1], "verde": hoy[2], "exceso": hoy[3], "no_aplica": hoy[4], "agotado": hoy[5]}},
        "serie": serie, "zonas": zonas, "top_items": por_margen[:20], "peores_items": [x for x in reversed(por_margen[-10:]) if (x["margen"] or 0.0) <= 0][:10],
        "labs": sorted(labs_l, key=lambda x: -(x["margen"] or 0.0))[:25],
        "comparativo": {"clase": info["clase"] if info else None, "tiendas_clase": max((v["tiendas"] for v in clase_prom.values()), default=0)},
        "nota": "Margen = venta neta - unidades x costo promedio actual (Siesa). Las ventas son mensuales; inventario y zonas tienen historia diaria.",
    }
