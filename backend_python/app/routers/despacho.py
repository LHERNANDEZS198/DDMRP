from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, exigir

router = APIRouter(prefix="/despacho", tags=["despacho"])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"


@router.get("/matriz")
def matriz(bodega_id: str | None = None, solo_pendientes: bool = True, user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user)
    f = f"s.ejecucion_id = {ULTIMA} AND s.cantidad_sugerida > 0 AND {w}"
    if bodega_id: f += " AND s.bodega_id=:b"; p["b"] = bodega_id
    if solo_pendientes: f += " AND s.estado='PENDIENTE'"
    sql = f"""SELECT s.ejecucion_id, s.producto_id, mi.descripcion, mi.categoria, s.bodega_id, s.zona::text zona,
                     s.inventario, s.en_transito, s.flujo_neto, s.tog, s.cantidad_sugerida, s.cantidad_aprobada,
                     s.estado::text estado
              FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi USING (producto_id)
              WHERE {f} ORDER BY s.bodega_id, s.pct_buffer"""
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), p).mappings()]


class Aprobacion(BaseModel):
    ejecucion_id: int
    producto_id: str
    bodega_id: str
    cantidad_aprobada: float
    aprobar: bool = True


@router.post("/aprobar")
def aprobar(items: list[Aprobacion], user=Depends(usuario_actual)):
    with pg.begin() as c:
        for it in items:
            cat = c.execute(text("SELECT categoria FROM ddmrp.maestro_item WHERE producto_id=:p"),
                            {"p": it.producto_id}).scalar()
            exigir(user, it.bodega_id, cat, "aprobacion" if it.aprobar else "edicion")
            c.execute(text("""UPDATE ddmrp.sugerencias_envio SET cantidad_aprobada=:q,
                              estado = CASE WHEN :ap THEN 'APROBADA'::estado_sugerencia ELSE estado END,
                              aprobado_por=:u, aprobado_en=now()
                              WHERE ejecucion_id=:e AND producto_id=:p AND bodega_id=:b"""),
                      {"q": it.cantidad_aprobada, "ap": it.aprobar, "u": user["nombre"],
                       "e": it.ejecucion_id, "p": it.producto_id, "b": it.bodega_id})
    return {"ok": True, "n": len(items)}


@router.get("/exportar-plano")
def exportar_plano(user=Depends(usuario_actual)):
    """FASE 2: generar archivo plano para cargar a Siesa (formato por definir)."""
    raise HTTPException(501, "Pendiente: formato del archivo plano de Siesa")


@router.post("/enviar-siesa")
def enviar_siesa(user=Depends(usuario_actual)):
    """FASE 3: envio directo por web service de Siesa."""
    raise HTTPException(501, "Pendiente: integracion web service Siesa")
