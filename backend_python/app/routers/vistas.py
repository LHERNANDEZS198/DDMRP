"""Vistas guardadas: la configuracion de un informe (filtros, criterios, agrupacion...) con nombre, por usuario.
Cada quien ve las suyas y las que otros marcaron como compartidas; solo el dueno las cambia o borra.
No guardan datos: al abrir una vista se vuelve a calcular con lo que el usuario puede ver."""
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual

router = APIRouter(prefix="/vistas", tags=["vistas"])
INFORMES = {"clasificacion"}
MAX_POR_USUARIO = 100


def _informe(informe: str):
    if informe not in INFORMES:
        raise HTTPException(404, "Informe desconocido")


class VistaIn(BaseModel):
    config: dict
    compartida: bool = False


@router.get("/{informe}")
def listar(informe: str, user=Depends(usuario_actual)):
    _informe(informe)
    with pg.connect() as c:
        r = c.execute(text("SELECT v.nombre, v.config, v.compartida, v.actualizado, v.usuario_id = :u AS mia, "
                           "CASE WHEN v.usuario_id = :u THEN NULL ELSE COALESCE(u.nombre, v.usuario_id) END AS dueno "
                           "FROM ddmrp.vista_guardada v LEFT JOIN ddmrp.usuario u ON u.usuario_id = v.usuario_id "
                           "WHERE v.informe = :i AND (v.usuario_id = :u OR v.compartida) "
                           "ORDER BY (v.usuario_id = :u) DESC, lower(v.nombre)"), {"u": user["id"], "i": informe}).mappings().all()
    return [{**dict(x), "actualizado": x["actualizado"].isoformat()} for x in r]


@router.put("/{informe}")
def guardar(informe: str, nombre: str, b: VistaIn, user=Depends(usuario_actual)):
    _informe(informe)
    nombre = nombre.strip()
    if not nombre or len(nombre) > 60:
        raise HTTPException(400, "El nombre debe tener entre 1 y 60 caracteres")
    if len(str(b.config)) > 20000:
        raise HTTPException(400, "La configuracion es demasiado grande")
    with pg.begin() as c:
        existe = c.execute(text("SELECT 1 FROM ddmrp.vista_guardada WHERE usuario_id=:u AND informe=:i AND nombre=:n"),
                           {"u": user["id"], "i": informe, "n": nombre}).first()
        if not existe and c.execute(text("SELECT count(*) FROM ddmrp.vista_guardada WHERE usuario_id=:u"), {"u": user["id"]}).scalar() >= MAX_POR_USUARIO:
            raise HTTPException(400, f"Llegaste al maximo de {MAX_POR_USUARIO} vistas guardadas: borra alguna")
        c.execute(text("INSERT INTO ddmrp.vista_guardada (usuario_id, informe, nombre, config, compartida, actualizado) "
                       "VALUES (:u, :i, :n, CAST(:c AS jsonb), :s, now()) ON CONFLICT (usuario_id, informe, nombre) DO UPDATE "
                       "SET config = EXCLUDED.config, compartida = EXCLUDED.compartida, actualizado = now()"),
                  {"u": user["id"], "i": informe, "n": nombre, "c": json.dumps(b.config), "s": b.compartida})
    return {"ok": True, "nueva": not existe}


@router.delete("/{informe}")
def borrar(informe: str, nombre: str, user=Depends(usuario_actual)):
    _informe(informe)
    with pg.begin() as c:
        n = c.execute(text("DELETE FROM ddmrp.vista_guardada WHERE usuario_id=:u AND informe=:i AND nombre=:n"),
                      {"u": user["id"], "i": informe, "n": nombre}).rowcount
    return {"ok": True, "eliminada": bool(n)}
