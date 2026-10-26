"""Modo «Ver solo CEDI» de los Informes (control, alertas, salud, clasificacion).

El CEDI (PT001) se calcula como una fila mas del buffer (empresa, bodega, item) en ddmrp.sugerencias_cedi, aparte de las tiendas para que la
matriz de despacho, el reparto y los planos de Siesa nunca lo vean. Los Informes leen la vista ddmrp.v_sugerencias_informe (tiendas + CEDI) y
este modulo decide cual de los dos mundos se muestra:
  - por defecto (solo_cedi = false): SOLO tiendas, exactamente como antes;
  - con ?solo_cedi=true: SOLO las bodegas del maestro de CEDIs;
  - con ?solo_cedi=todos: tiendas Y CEDI juntos (p.ej. el saldo y la rotacion de un item en todas las tiendas mas el CEDI).
La opcion viaja como parametro de la URL y se guarda en una variable de contexto de la peticion para no tener que pasarla por cada funcion.
Es una dependencia `async` a proposito: asi corre en la misma tarea que despues lanza el endpoint en el hilo, que hereda el contexto."""
from contextvars import ContextVar
from fastapi import Query

_MODO: ContextVar[str] = ContextVar("modo_cedi", default="tiendas")   # tiendas | cedi | todos


async def fijar_modo(solo_cedi: str = Query("false", description="true = solo el CEDI; todos = tiendas y CEDI; false = solo tiendas")) -> None:
    v = (solo_cedi or "").strip().lower()
    _MODO.set("cedi" if v in ("true", "1", "si", "sí", "cedi") else "todos" if v == "todos" else "tiendas")


def solo_cedi() -> bool:
    """True solo en el modo CEDI puro (en «todos» se comporta como tiendas para los calculos que no mezclan ambos mundos, p.ej. la clasificacion)."""
    return _MODO.get() == "cedi"


def cond_cedi(a: str = "s", solo: bool | None = None) -> str:
    """Fragmento WHERE: las filas de `a` (con empresa y bodega_id) son del CEDI (modo CEDI) o NO lo son (modo tiendas, el de siempre); en modo «todos», sin condicion."""
    if solo is None:
        m = _MODO.get()
        if m == "todos":
            return "TRUE"
        solo = m == "cedi"
    return f"(({a}.empresa, {a}.bodega_id) {'IN' if solo else 'NOT IN'} (SELECT mc_m.empresa, mc_m.bodega_id FROM ddmrp.maestro_cedi mc_m))"
