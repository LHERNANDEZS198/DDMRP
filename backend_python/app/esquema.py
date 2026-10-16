"""Cambios de esquema idempotentes que se aplican al arrancar el backend (la base puede ser anterior al cambio)."""
import logging
from sqlalchemy import text
from .db import pg

log = logging.getLogger("esquema")

SENTENCIAS = [
    "ALTER TABLE ddmrp.maestro_bodega ADD COLUMN IF NOT EXISTS descripcion TEXT",
]


def asegurar_esquema():
    try:
        with pg.begin() as c:
            for s in SENTENCIAS:
                c.execute(text(s))
    except Exception:
        log.exception("No se pudo actualizar el esquema")
