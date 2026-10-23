"""Freno a la fuerza bruta del login: tras LOGIN_MAX_FALLOS claves malas de un mismo usuario dentro de LOGIN_VENTANA_MIN minutos, ese usuario queda
bloqueado LOGIN_BLOQUEO_MIN minutos (responde 429 con el tiempo que falta). Un acierto borra la cuenta. Vive en memoria de este proceso (un reinicio la borra).
Se cuenta por usuario escrito, existan o no, para no revelar cuales existen. El bloqueo de un usuario no impide que otros entren."""
import threading, time
from fastapi import HTTPException
from .config import settings

_lock = threading.Lock()
_fallos: dict[str, list[float]] = {}      # usuario -> momentos de los fallos recientes
_bloqueado: dict[str, float] = {}         # usuario -> hasta cuando (monotonic)
_MAX_USUARIOS = 5000                      # tope de memoria ante un ataque con usuarios inventados


def _clave(usuario: str) -> str:
    return (usuario or "").strip().lower()[:64]


def _espera(msg_seg: float) -> HTTPException:
    minutos = max(1, int(msg_seg // 60) + (1 if msg_seg % 60 else 0))
    return HTTPException(429, f"Demasiados intentos fallidos. Vuelve a intentar en {minutos} min.", headers={"Retry-After": str(int(msg_seg) + 1)})


def revisar(usuario: str) -> None:
    """Llamar ANTES de verificar la clave: si el usuario esta bloqueado, ni se consulta reloj."""
    k, ahora = _clave(usuario), time.monotonic()
    with _lock:
        hasta = _bloqueado.get(k)
        if hasta and hasta > ahora:
            raise _espera(hasta - ahora)
        if hasta:
            _bloqueado.pop(k, None)


def fallo(usuario: str) -> None:
    k, ahora = _clave(usuario), time.monotonic()
    ventana = settings.login_ventana_min * 60
    with _lock:
        if len(_fallos) >= _MAX_USUARIOS and k not in _fallos:      # limpieza de lo vencido; si sigue lleno, se descarta lo mas viejo
            for u in [u for u, v in _fallos.items() if not v or ahora - v[-1] > ventana]:
                _fallos.pop(u, None)
            if len(_fallos) >= _MAX_USUARIOS:
                _fallos.pop(next(iter(_fallos)), None)
        v = [t for t in _fallos.get(k, []) if ahora - t < ventana] + [ahora]
        _fallos[k] = v
        if len(v) >= settings.login_max_fallos:
            _bloqueado[k] = ahora + settings.login_bloqueo_min * 60
            _fallos.pop(k, None)


def acierto(usuario: str) -> None:
    k = _clave(usuario)
    with _lock:
        _fallos.pop(k, None); _bloqueado.pop(k, None)
