from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..orchestrator import pipeline_nocturno, ejecutar_motor
from ..etl.replicacion import correr_etl
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
