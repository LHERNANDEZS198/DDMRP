"""Bitacora de operaciones: cada corrida del ETL, del motor, del pipeline nocturno, las sincronizaciones con Siesa,
las cargas de maestros y los planos descargados, con quien la lanzo (usuario o 'auto' = programada), cuando, cuanto
tardo y como termino. Registrar nunca debe tumbar la operacion: todo falla en silencio (queda en el log del servidor)."""
import contextvars, json, logging
from contextlib import contextmanager
from sqlalchemy import text
from .db import pg

log = logging.getLogger("bitacora")
_padre: contextvars.ContextVar[int | None] = contextvars.ContextVar("bitacora_padre", default=None)

TIPOS = {
    "pipeline": "Pipeline completo (ETL + motor)", "etl": "ETL de Siesa", "motor": "Motor DDMRP",
    "items": "Traer items de Siesa", "bodegas": "Traer tiendas de Siesa", "ventas": "Traer ventas por mes",
    "carga": "Carga de maestro", "plano": "Plano de despacho", "aprobacion": "Aprobación de despacho", "auditoria": "Excel de auditoría",
}


def _json(x):
    try:
        return json.dumps(x, default=str, ensure_ascii=False)[:8000]
    except Exception:
        return None


def usuario_de(user) -> str | None:
    return (user or {}).get("nombre") or (user or {}).get("id") if user else None


def _abrir(tipo, origen, usuario, mensaje=None):
    try:
        with pg.begin() as c:
            return c.execute(text("INSERT INTO ddmrp.bitacora (tipo, origen, usuario, mensaje, padre_id) "
                                  "VALUES (:t, :o, :u, :m, :p) RETURNING id"),
                             {"t": tipo, "o": origen, "u": usuario, "m": mensaje, "p": _padre.get()}).scalar_one()
    except Exception:
        log.exception("No se pudo abrir el registro de bitacora"); return None


def _cerrar(i, estado, resumen=None, mensaje=None):
    if i is None:
        return
    try:
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.bitacora SET fin = now(), estado = :e, resumen = CAST(:r AS jsonb), "
                           "mensaje = COALESCE(:m, mensaje) WHERE id = :i"),
                      {"e": estado, "r": _json(resumen) if resumen is not None else None, "m": mensaje, "i": i})
    except Exception:
        log.exception("No se pudo cerrar el registro de bitacora")


class _Reg:
    def __init__(self): self.resumen = None; self.mensaje = None


@contextmanager
def registrar(tipo: str, origen: str = "manual", usuario: str | None = None, mensaje: str | None = None):
    """with registrar('motor', 'manual', 'Lucas') as r: ... ; r.resumen = {...} (opcional). Si falla, deja el error."""
    i = _abrir(tipo, origen, usuario, mensaje)
    r = _Reg(); tok = _padre.set(i)
    try:
        yield r
    except BaseException as ex:
        _padre.reset(tok)
        _cerrar(i, "error", r.resumen, f"{type(ex).__name__}: {str(getattr(ex, 'detail', None) or getattr(ex, 'stderr', None) or ex)[-500:]}")
        raise
    else:
        _padre.reset(tok)
        _cerrar(i, "ok", r.resumen, r.mensaje)


def evento(tipo: str, usuario: str | None, mensaje: str, resumen=None, origen: str = "manual"):
    """Hecho instantaneo (una carga, un plano): una sola fila ya cerrada."""
    i = _abrir(tipo, origen, usuario, mensaje)
    _cerrar(i, "ok", resumen)


def cerrar_huerfanas():
    """Al arrancar: lo que quedo 'corriendo' murio con el reinicio del servidor."""
    try:
        with pg.begin() as c:
            n = c.execute(text("UPDATE ddmrp.bitacora SET fin = now(), estado = 'interrumpido', "
                               "mensaje = 'El servidor se reinicio mientras corria' WHERE estado = 'corriendo'")).rowcount
        if n:
            log.warning("Bitacora: %s operaciones quedaron interrumpidas por el reinicio", n)
    except Exception:
        log.exception("No se pudo limpiar la bitacora")
