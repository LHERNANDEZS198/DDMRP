"""Progreso de la tarea larga en curso (ETL, ventas, items, motor), para que la pantalla muestre que esta haciendo.
Es un solo estado en memoria: estas tareas se lanzan a mano o de noche, una a la vez."""
import threading, time
from contextlib import contextmanager

_l = threading.Lock()
_e: dict = {"tarea": None, "estado": "libre", "mensaje": "", "inicio": None, "fin": None}


def avance(mensaje: str):
    with _l:
        if _e["estado"] == "corriendo":
            _e["mensaje"] = mensaje


def estado() -> dict:
    with _l:
        return dict(_e, segundos=round((_e["fin"] or time.time()) - _e["inicio"]) if _e["inicio"] else 0)


@contextmanager
def tarea(nombre: str, final: str = "Listo"):
    """La tarea externa manda: si ya hay una corriendo (p.ej. el motor dentro del pipeline) solo se suman mensajes."""
    with _l:
        propia = _e["estado"] != "corriendo"
        if propia:
            _e.update(tarea=nombre, estado="corriendo", mensaje="Iniciando…", inicio=time.time(), fin=None)
    try:
        yield
    except BaseException as ex:
        if propia:
            with _l:
                _e.update(estado="error", mensaje=f"Error: {str(ex)[:300]}", fin=time.time())
        raise
    else:
        if propia:
            with _l:
                _e.update(estado="ok", mensaje=final, fin=time.time())
