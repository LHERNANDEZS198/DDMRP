from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..orchestrator import pipeline_nocturno, ejecutar_motor
from ..etl.replicacion import correr_etl, sincronizar_bodegas_ahora, sincronizar_items_ahora
from ..security import requiere

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/correr-pipeline")
def pipeline(bg: BackgroundTasks, user=Depends(requiere("correr_motor"))):
    """ETL + motor completo, en segundo plano."""
    bg.add_task(pipeline_nocturno); return {"estado": "lanzado"}


@router.post("/correr-etl")
def etl(user=Depends(requiere("correr_motor"))):
    return correr_etl()


@router.post("/correr-motor")
def motor(user=Depends(requiere("correr_motor"))):
    return ejecutar_motor()


@router.post("/sincronizar-bodegas")
def bodegas(user=Depends(requiere("sincronizar_siesa"))):
    """Trae las tiendas (codigo y nombre) de Siesa: sirve para que los Excel se llenen por codigo o por nombre."""
    return {"tiendas": sincronizar_bodegas_ahora()}


@router.post("/sincronizar-items")
def items(user=Depends(requiere("sincronizar_siesa"))):
    """Trae de Siesa la descripcion, el laboratorio y todos los criterios de items (con sus nombres), para filtrar en las vistas."""
    try:
        return sincronizar_items_ahora()
    except RuntimeError as e:
        raise HTTPException(400, str(e))
