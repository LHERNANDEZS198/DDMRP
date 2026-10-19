"""Alertas: resumen por zona y lista de zona roja de la ultima corrida. Mismos filtros que Control DDMRP (empresa, tienda, laboratorio,
criterio de items, item), resueltos en el servidor y siempre limitados a lo que el usuario puede leer."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, requiere
from .control import _filtros

router = APIRouter(prefix="/alertas", tags=["alertas"], dependencies=[Depends(requiere("ver_alertas"))])

ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
BASE = "FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id"


def _donde(user, bodegas, labs, q, empresa, crit) -> tuple[str, dict]:
    cond, p = _filtros(user, bodegas, labs, q, None, None, empresa, crit=crit)   # permisos + solo items activos + filtros elegidos
    return " AND ".join([f"s.ejecucion_id = {ULTIMA}"] + cond), p


@router.get("/resumen")
def resumen(bodegas: str | None = None, labs: str | None = None, q: str | None = None, empresa: str | None = None, crit: str | None = None,
            user=Depends(usuario_actual)):
    w, p = _donde(user, bodegas, labs, q, empresa, crit)
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(f"SELECT s.zona::text AS zona, count(*) n {BASE} WHERE {w} GROUP BY 1"), p).mappings()]


@router.get("/zona-roja")
def zona_roja(bodegas: str | None = None, labs: str | None = None, q: str | None = None, empresa: str | None = None, crit: str | None = None,
              limit: int = Query(5000, ge=1, le=20000), user=Depends(usuario_actual)):
    """{total, filas}: total = cuantas hay con los filtros; filas = las primeras `limit` (las mas vacias primero)."""
    w, p = _donde(user, bodegas, labs, q, empresa, crit)
    w += " AND s.zona = 'ROJA' AND NOT s.condenado"
    with pg.connect() as c:
        total = c.execute(text(f"SELECT count(*) {BASE} WHERE {w}"), p).scalar()
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.producto_id, mi.descripcion, s.bodega_id, s.inventario, s.en_transito, s.flujo_neto, s.tor, s.tog_aj, s.pct_buffer, s.cantidad_sugerida
            {BASE} WHERE {w} ORDER BY s.pct_buffer LIMIT :lim"""), {**p, "lim": limit}).mappings()]
    return {"total": total, "filas": filas}
