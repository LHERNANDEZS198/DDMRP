"""Modo «Ver solo CEDI» de los Informes (control, alertas, salud, clasificacion).

El CEDI (PT001) se calcula como una fila mas del buffer (empresa, bodega, item) en ddmrp.sugerencias_cedi, aparte de las tiendas para que la
matriz de despacho, el reparto y los planos de Siesa nunca lo vean. Los Informes leen la vista ddmrp.v_sugerencias_informe (tiendas + CEDI) y
este modulo decide cual de los dos mundos se muestra:
  - por defecto (solo_cedi = false): SOLO tiendas, exactamente como antes;
  - con ?solo_cedi=true: SOLO las bodegas del maestro de CEDIs.
La opcion viaja como parametro de la URL y se guarda en una variable de contexto de la peticion para no tener que pasarla por cada funcion.
Es una dependencia `async` a proposito: asi corre en la misma tarea que despues lanza el endpoint en el hilo, que hereda el contexto."""
from contextvars import ContextVar
from fastapi import Query

_SOLO_CEDI: ContextVar[bool] = ContextVar("solo_cedi", default=False)


async def fijar_modo(solo_cedi: bool = Query(False, description="true = ver solo el CEDI (necesidad, sobrestock, clasificacion); false = solo tiendas")) -> None:
    _SOLO_CEDI.set(bool(solo_cedi))


def solo_cedi() -> bool:
    return _SOLO_CEDI.get()


def cond_cedi(a: str = "s", solo: bool | None = None) -> str:
    """Fragmento WHERE: las filas de `a` (con empresa y bodega_id) son del CEDI (modo CEDI) o NO lo son (modo tiendas, el de siempre)."""
    solo = solo_cedi() if solo is None else solo
    return f"(({a}.empresa, {a}.bodega_id) {'IN' if solo else 'NOT IN'} (SELECT mc_m.empresa, mc_m.bodega_id FROM ddmrp.maestro_cedi mc_m))"
