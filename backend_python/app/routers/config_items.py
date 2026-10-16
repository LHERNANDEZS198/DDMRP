from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, exigir

router = APIRouter(prefix="/config", tags=["config"])
CAMPOS = {"lead_time_dias", "factor_lead_time", "factor_variabilidad", "factor_zona_roja",
          "factor_zona_amarilla", "factor_zona_verde", "ciclo_pedido_dias", "cantidad_minima",
          "multiplo_empaque", "clase_abc", "clase_xyz", "ventana_adu_dias", "activo"}


@router.get("/items")
def listar(bodega_id: str | None = None, limit: int = 20000, user=Depends(usuario_actual)):
    w, p = filtro_sql_permisos(user, "c.bodega_id", "mi.categoria")
    extra = " AND c.bodega_id = :b" if bodega_id else ""
    if bodega_id: p["b"] = bodega_id
    sql = f"""SELECT c.*, mi.descripcion, mi.categoria FROM ddmrp.maestro_item_bodega_config c
              LEFT JOIN ddmrp.maestro_item mi USING (producto_id) WHERE {w}{extra}
              ORDER BY c.bodega_id, c.producto_id LIMIT :lim"""
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]


class Cambio(BaseModel):
    producto_id: str
    bodega_id: str
    campo: str
    valor: str | float | int | bool | None


@router.patch("/items")
def editar(cambios: list[Cambio], user=Depends(usuario_actual)):
    with pg.begin() as c:
        for ch in cambios:
            if ch.campo not in CAMPOS:
                raise HTTPException(400, f"Campo no editable: {ch.campo}")
            cat = c.execute(text("SELECT categoria FROM ddmrp.maestro_item WHERE producto_id=:p"),
                            {"p": ch.producto_id}).scalar()
            exigir(user, ch.bodega_id, cat, "edicion")
            ant = c.execute(text(f"SELECT {ch.campo}::text FROM ddmrp.maestro_item_bodega_config "
                                 "WHERE producto_id=:p AND bodega_id=:b"),
                            {"p": ch.producto_id, "b": ch.bodega_id}).scalar()
            c.execute(text(f"UPDATE ddmrp.maestro_item_bodega_config SET {ch.campo}=:v, "
                           "actualizado_por=:u, actualizado=now() WHERE producto_id=:p AND bodega_id=:b"),
                      {"v": ch.valor, "u": user["nombre"], "p": ch.producto_id, "b": ch.bodega_id})
            c.execute(text("INSERT INTO ddmrp.config_audit (producto_id,bodega_id,campo,valor_anterior,valor_nuevo,usuario) "
                           "VALUES (:p,:b,:c,:a,:n,:u)"),
                      {"p": ch.producto_id, "b": ch.bodega_id, "c": ch.campo, "a": ant, "n": str(ch.valor), "u": user["nombre"]})
    return {"ok": True, "cambios": len(cambios)}
