from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..orchestrator import pipeline_nocturno, ejecutar_motor
from ..etl.replicacion import correr_etl, sincronizar_bodegas_ahora, sincronizar_items_ahora
from ..security import usuario_actual, asignaciones

router = APIRouter(prefix="/admin", tags=["admin"])


def _solo_admin(user):
    if not any(a["es_admin"] for a in asignaciones(user["id"])):
        raise HTTPException(403, "Solo administradores")


@router.post("/correr-pipeline")
def pipeline(bg: BackgroundTasks, user=Depends(usuario_actual)):
    """ETL + motor completo, en segundo plano."""
    _solo_admin(user); bg.add_task(pipeline_nocturno); return {"estado": "lanzado"}


@router.post("/correr-etl")
def etl(user=Depends(usuario_actual)):
    _solo_admin(user); return correr_etl()


@router.post("/correr-motor")
def motor(user=Depends(usuario_actual)):
    _solo_admin(user); return ejecutar_motor()


@router.post("/sincronizar-bodegas")
def bodegas(user=Depends(usuario_actual)):
    """Trae las tiendas (codigo y nombre) de Siesa: sirve para que los Excel se llenen por codigo o por nombre."""
    _solo_admin(user); return {"tiendas": sincronizar_bodegas_ahora()}


@router.post("/sincronizar-items")
def items(user=Depends(usuario_actual)):
    """Trae de Siesa la descripcion, el laboratorio y todos los criterios de items (con sus nombres), para filtrar en las vistas."""
    _solo_admin(user)
    try:
        return sincronizar_items_ahora()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
