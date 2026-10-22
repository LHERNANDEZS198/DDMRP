"""Registro de consultas a la API (ddmrp.consulta_log): quien llamo que, con que filtros, cuanto tardo y como termino.
Sirve para diagnosticar lentitud y fallas desde la pestaña Diagnostico. El registro nunca debe romper ni frenar una peticion:
se escribe en un hilo aparte y cualquier falla se ignora."""
import json, logging, queue, threading
from contextvars import ContextVar
from urllib.parse import parse_qsl
from sqlalchemy import text
from .db import pg

log = logging.getLogger("ddmrp.consultas")
RETENCION_DIAS = 30
OMITIR = ("/api/health", "/api/auth", "/api/diagnostico", "/api/admin/salud", "/api/admin/progreso")     # sondeos automaticos de la interfaz (cada pocos segundos) y la propia pantalla de diagnostico
_actual: ContextVar[dict | None] = ContextVar("consulta_actual", default=None)
_cola: "queue.Queue[dict]" = queue.Queue(maxsize=5000)
_n = 0


def iniciar() -> dict:
    d: dict = {}
    _actual.set(d)
    return d


def anotar(**kw) -> None:
    """Un endpoint agrega detalle a SU consulta en curso: ms_sql, ms_calc, filas, estado, error, o cualquier dato en `extra`."""
    d = _actual.get()
    if d is None:
        return
    for k, v in kw.items():
        if k in ("ms_sql", "ms_calc", "filas", "estado", "error"):
            d[k] = v
        else:
            d.setdefault("extra", {})[k] = v


def encolar(reg: dict) -> None:
    try:
        _cola.put_nowait(reg)
    except queue.Full:
        pass


def _escribir(reg: dict) -> None:
    global _n
    with pg.begin() as c:
        c.execute(text("""INSERT INTO ddmrp.consulta_log (usuario, metodo, ruta, params, http, estado, ms, ms_sql, ms_calc, filas, bytes, error, extra)
                          VALUES (:usuario, :metodo, :ruta, CAST(:params AS jsonb), :http, :estado, :ms, :ms_sql, :ms_calc, :filas, :bytes, :error, CAST(:extra AS jsonb))"""),
                  {**{k: reg.get(k) for k in ("usuario", "metodo", "ruta", "http", "estado", "ms", "ms_sql", "ms_calc", "filas", "bytes", "error")},
                   "params": json.dumps(reg.get("params") or {}), "extra": json.dumps(reg.get("extra") or {}, default=str)})
        _n += 1
        if _n % 300 == 0:
            c.execute(text("DELETE FROM ddmrp.consulta_log WHERE ts < now() - make_interval(days => :d)"), {"d": RETENCION_DIAS})


def _trabajador() -> None:
    while True:
        reg = _cola.get()
        try:
            _escribir(reg)
        except Exception as e:      # noqa: BLE001  - el registro jamas debe afectar a la aplicacion
            log.warning("no se pudo registrar la consulta: %s", e)


_hilo = None


def arrancar() -> None:
    global _hilo
    if _hilo is None:
        _hilo = threading.Thread(target=_trabajador, name="consulta-log", daemon=True)
        _hilo.start()


def parametros(query: str) -> dict:
    """Querystring -> dict (valores largos se recortan; los repetidos se unen con coma)."""
    out: dict = {}
    for k, v in parse_qsl(query, keep_blank_values=False):
        v = v if len(v) <= 300 else v[:300] + "…"
        out[k] = f"{out[k]},{v}" if k in out else v
    return out
