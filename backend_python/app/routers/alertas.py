from fastapi import APIRouter, Depends
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, requiere
from ..activos import solo_activos

router = APIRouter(prefix="/alertas", tags=["alertas"], dependencies=[Depends(requiere("ver_alertas"))])

ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"


@router.get("/resumen")
def resumen(user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user)
    sql = f"""SELECT s.zona::text AS zona, count(*) n FROM ddmrp.sugerencias_envio s
              LEFT JOIN ddmrp.maestro_item mi USING (producto_id)
              WHERE s.ejecucion_id = {ULTIMA} AND {w} AND {solo_activos('s')} GROUP BY 1"""
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), p).mappings()]


@router.get("/zona-roja")
def zona_roja(limit: int = 5000, user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user)
    sql = f"""SELECT s.empresa, s.producto_id, mi.descripcion, s.bodega_id, s.inventario, s.en_transito,
                     s.flujo_neto, s.tor, s.tog_aj, s.pct_buffer, s.cantidad_sugerida
              FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi USING (producto_id)
              WHERE s.ejecucion_id = {ULTIMA} AND s.zona='ROJA' AND NOT s.condenado AND {w} AND {solo_activos('s')}
              ORDER BY s.pct_buffer LIMIT :lim"""
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
