"""Progreso de la tarea larga en curso (ETL, ventas, items, motor), para que la pantalla muestre que esta haciendo.
Es un solo estado en memoria y a la vez el CANDADO: solo puede haber una tarea larga corriendo; un segundo intento
(otro usuario, un refresco de pantalla, el cron de la noche) se rechaza con `Ocupado`. Las tareas anidadas (el motor
dentro del pipeline) corren en el mismo hilo y por eso no se bloquean entre si."""
import contextvars, threading, time
from contextlib import contextmanager

_l = threading.Lock()
_e: dict = {"tarea": None, "estado": "libre", "mensaje": "", "inicio": None, "fin": None}
_dentro: contextvars.ContextVar[bool] = contextvars.ContextVar("progreso_dentro", default=False)


class Ocupado(Exception):
    """Ya hay una tarea larga corriendo."""


def _msg_ocupado() -> str:
    hora = time.strftime("%H:%M", time.localtime(_e["inicio"])) if _e["inicio"] else ""
    return (f"Ya hay una corrida en curso ({_e['tarea']}{', desde las ' + hora if hora else ''}). Espera a que termine: "
            "puedes ver el avance en el aviso de arriba o en la pantalla Log.")


def exigir_libre():
    """Para rechazar antes de lanzar algo en segundo plano."""
    with _l:
        if _e["estado"] == "corriendo":
            raise Ocupado(_msg_ocupado())


def avance(mensaje: str):
    with _l:
        if _e["estado"] == "corriendo":
            _e["mensaje"] = mensaje


def estado() -> dict:
    with _l:
        return dict(_e, segundos=round((_e["fin"] or time.time()) - _e["inicio"]) if _e["inicio"] else 0)


@contextmanager
def tarea(nombre: str, final: str = "Listo"):
    """La tarea externa manda: si ya hay una corriendo en este mismo hilo (el motor dentro del pipeline) solo se suman mensajes;
    si la corre otro hilo, se rechaza con Ocupado."""
    with _l:
        corriendo = _e["estado"] == "corriendo"
        if corriendo and not _dentro.get():
            raise Ocupado(_msg_ocupado())
        propia = not corriendo
        if propia:
            _e.update(tarea=nombre, estado="corriendo", mensaje="Iniciando…", inicio=time.time(), fin=None)
    tok = _dentro.set(True)
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
    finally:
        _dentro.reset(tok)
