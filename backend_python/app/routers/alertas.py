"""Alertas: resumen por zona y lista de zona roja de la ultima corrida. Mismos filtros que Control DDMRP (empresa, tienda, laboratorio,
criterio de items, item), resueltos en el servidor y siempre limitados a lo que el usuario puede leer."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, requiere
from .control import _filtros

router = APIRouter(prefix="/alertas", tags=["alertas"], dependencies=[Depends(requiere("ver_alertas"))])

ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
BASE = "FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id"
BASE_C = BASE + " LEFT JOIN ddmrp.costo_item ci ON ci.producto_id = s.producto_id"
# unidades que sobran (sobre el tope verde ajustado, solo en sobrestock) o faltan (distancia al tope verde, en las demas zonas); x costo promedio = plata
SOBRAN = "CASE WHEN s.zona::text = 'EXCESO' THEN GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0) ELSE 0 END"
FALTAN = "CASE WHEN s.zona::text <> 'EXCESO' THEN GREATEST(s.tog_aj - s.flujo_neto, 0) ELSE 0 END"


def _donde(user, bodegas, labs, q, empresa, crit) -> tuple[str, dict]:
    cond, p = _filtros(user, bodegas, labs, q, None, None, empresa, crit=crit)   # permisos + solo items activos + filtros elegidos
    return " AND ".join([f"s.ejecucion_id = {ULTIMA}"] + cond), p


@router.get("/resumen")
def resumen(bodegas: str | None = None, labs: str | None = None, q: str | None = None, empresa: str | None = None, crit: str | None = None,
            user=Depends(usuario_actual)):
    w, p = _donde(user, bodegas, labs, q, empresa, crit)
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(f"""
            SELECT s.zona::text AS zona, count(*) n,
                   COALESCE(sum({SOBRAN}) FILTER (WHERE NOT s.condenado), 0)::float8 AS sobran,
                   COALESCE(sum({FALTAN}) FILTER (WHERE NOT s.condenado), 0)::float8 AS faltan,
                   COALESCE(sum({SOBRAN} * ci.costo) FILTER (WHERE NOT s.condenado), 0)::float8 AS sobran_costo,
                   COALESCE(sum({FALTAN} * ci.costo) FILTER (WHERE NOT s.condenado), 0)::float8 AS faltan_costo,
                   count(*) FILTER (WHERE NOT s.condenado AND ci.costo IS NULL AND ({SOBRAN} + {FALTAN}) > 0) AS sin_costo
            {BASE_C} WHERE {w} GROUP BY 1"""), p).mappings()]


ZONAS = ("ROJA", "AMARILLA", "VERDE", "EXCESO")


@router.get("/zona-roja")
def zona_roja(bodegas: str | None = None, labs: str | None = None, q: str | None = None, empresa: str | None = None, crit: str | None = None,
              zona: str = "ROJA", limit: int = Query(5000, ge=1, le=20000), user=Depends(usuario_actual)):
    """{total, filas}: lista de la zona elegida (por defecto la roja). total = cuantas hay con los filtros; filas = las primeras `limit`
    (las mas vacias primero), con el stock del CEDI antes y despues de repartir lo sugerido a todas las tiendas de la empresa."""
    zona = zona.upper()
    if zona not in ZONAS:
        raise HTTPException(400, f"zona debe ser una de {list(ZONAS)}")
    w, p = _donde(user, bodegas, labs, q, empresa, crit)
    w += " AND s.zona::text = :zona AND NOT s.condenado"; p["zona"] = zona
    with pg.connect() as c:
        total = c.execute(text(f"SELECT count(*) {BASE} WHERE {w}"), p).scalar()
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.producto_id, mi.descripcion, s.bodega_id, s.inventario, s.en_transito, s.flujo_neto, s.tor, s.tog_aj, s.pct_buffer, s.cantidad_sugerida,
                   s.stock_cedi::float8 AS stock_cedi, s.adu::float8 AS rotacion,
                   {SOBRAN}::float8 AS sobran, {FALTAN}::float8 AS faltan, ci.costo::float8 AS costo,
                   ({SOBRAN} * ci.costo)::float8 AS sobran_costo, ({FALTAN} * ci.costo)::float8 AS faltan_costo
            {BASE_C} WHERE {w} ORDER BY s.pct_buffer LIMIT :lim"""), {**p, "lim": limit}).mappings()]
        # totales de TODA la lista con estos filtros (no solo de las filas que se alcanzan a mostrar)
        totales = dict(c.execute(text(f"""
            SELECT COALESCE(sum(s.inventario), 0)::float8 AS inventario, COALESCE(sum(s.en_transito), 0)::float8 AS en_transito, COALESCE(sum(s.flujo_neto), 0)::float8 AS flujo_neto,
                   COALESCE(sum(s.cantidad_sugerida), 0)::float8 AS cantidad_sugerida, COALESCE(sum(s.adu), 0)::float8 AS rotacion,
                   COALESCE(sum({SOBRAN}), 0)::float8 AS sobran, COALESCE(sum({FALTAN}), 0)::float8 AS faltan,
                   COALESCE(sum({SOBRAN} * ci.costo), 0)::float8 AS sobran_costo, COALESCE(sum({FALTAN} * ci.costo), 0)::float8 AS faltan_costo,
                   count(*) FILTER (WHERE ci.costo IS NULL AND ({SOBRAN} + {FALTAN}) > 0) AS sin_costo
            {BASE_C} WHERE {w}"""), p).mappings().one())
        if filas:   # lo que se reparte de cada item entre TODAS las tiendas de la empresa (no solo las filtradas), calculado aparte
            tot = {(e, pr): v for e, pr, v in c.execute(text(
                f"SELECT empresa, producto_id, SUM(cantidad_sugerida)::float8 FROM ddmrp.sugerencias_envio WHERE ejecucion_id = {ULTIMA} AND NOT condenado "
                "AND producto_id = ANY(:ps) GROUP BY 1, 2"), {"ps": list({f['producto_id'] for f in filas})}).all()}
            for f in filas:
                f["cedi_despues"] = None if f["stock_cedi"] is None else f["stock_cedi"] - tot.get((f["empresa"], f["producto_id"]), 0.0)
    return {"total": total, "filas": filas, "zona": zona, "totales": totales}
