from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from ..orchestrator import pipeline_nocturno, ejecutar_motor
from ..security import usuario_actual, asignaciones

router = APIRouter(prefix="/admin", tags=["admin"])


def _solo_admin(user):
    if not any(a["es_admin"] for a in asignaciones(user["id"])):
        raise HTTPException(403, "Solo administradores")


@router.post("/correr-pipeline")
def pipeline(bg: BackgroundTasks, dias_ventas: int = 7, user=Depends(usuario_actual)):
    """Primera carga: dias_ventas=365 (o mas) para poblar el historico."""
    _solo_admin(user); bg.add_task(pipeline_nocturno, dias_ventas); return {"estado": "lanzado"}


@router.post("/correr-motor")
def motor(user=Depends(usuario_actual)):
    _solo_admin(user); return ejecutar_motor()
