"""Orquesta: ETL -> motor Rust. El binario se invoca con lista de argumentos (sin shell)."""
import json, logging, subprocess, os
from datetime import date
from sqlalchemy import text
from .config import settings
from .db import pg
from .etl.replicacion import correr_etl, refrescar_cedi
from .reparto import aplicar_a_ejecucion
from . import progreso, bitacora

log = logging.getLogger("orq")


def guardar_historia(eid: int):
    """Foto diaria liviana de la corrida (reemplaza la del mismo dia) y limpieza: la historia dura `retener_dias`; el detalle
    completo de sugerencias (que es pesado) solo se conserva `DETALLE_DIAS` dias y una corrida por dia."""
    with pg.begin() as c:
        fecha = c.execute(text("SELECT fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = :e"), {"e": eid}).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha = :f"), {"f": fecha})
        cols = "empresa, bodega_id, producto_id, zona, tor, toy_aj, tog_aj, inventario, flujo_neto, pct_buffer"
        c.execute(text(f"INSERT INTO ddmrp.buffer_historia (fecha, {cols}) SELECT :f, {cols} FROM ddmrp.sugerencias_envio WHERE ejecucion_id = :e"),
                  {"f": fecha, "e": eid})
        # dias anteriores que aun tengan detalle y no esten en la historia (primer despliegue)
        c.execute(text(f"""INSERT INTO ddmrp.buffer_historia (fecha, {cols})
                           SELECT e.fecha_calculo, {', '.join('s.' + x.strip() for x in cols.split(','))}
                           FROM (SELECT DISTINCT ON (fecha_calculo) id, fecha_calculo FROM ddmrp.ejecucion_motor
                                 WHERE estado = 'ok' ORDER BY fecha_calculo, id DESC) e
                           JOIN ddmrp.sugerencias_envio s ON s.ejecucion_id = e.id
                           WHERE e.fecha_calculo NOT IN (SELECT DISTINCT fecha FROM ddmrp.buffer_historia)
                           ON CONFLICT DO NOTHING"""))
        # items fuera del maestro (no pasan el filtro de criterios, ej. materia prima) que quedaron en fotos de corridas anteriores
        c.execute(text("DELETE FROM ddmrp.buffer_historia h WHERE EXISTS (SELECT 1 FROM ddmrp.maestro_item) "
                       "AND NOT EXISTS (SELECT 1 FROM ddmrp.maestro_item m WHERE m.producto_id = h.producto_id)"))
        dias = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'retener_dias'")).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha < current_date - :d"), {"d": int(dias) if dias else 180})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_envio s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})


DETALLE_DIAS = 7


def ejecutar_motor(fecha: date | None = None, origen: str = "manual", usuario: str | None = None) -> dict:
    with progreso.tarea("Motor", "Motor listo"), bitacora.registrar("motor", origen, usuario) as r:
        r.resumen = res = _ejecutar_motor(fecha)
        return res


def _ejecutar_motor(fecha: date | None = None) -> dict:
    fecha = fecha or date.today()
    progreso.avance("Leyendo el inventario fresco del CEDI…")
    cedi = refrescar_cedi()
    progreso.avance("Calculando buffers con el motor Rust (varios minutos con todas las tiendas)…")
    with pg.begin() as c:
        eid = c.execute(text("INSERT INTO ddmrp.ejecucion_motor (fecha_calculo) VALUES (:f) RETURNING id"),
                        {"f": fecha}).scalar_one()
    try:
        out = subprocess.run(
            [settings.core_bin, "--ejecucion-id", str(eid), "--fecha", fecha.isoformat()],
            env={**os.environ, "DATABASE_URL": settings.pg_dsn},
            capture_output=True, text=True, timeout=600, check=True)
        res = json.loads(out.stdout.strip().splitlines()[-1])
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.ejecucion_motor SET fin=now(), estado='ok', filas=:n WHERE id=:i"),
                      {"n": res["filas"], "i": eid})
        progreso.avance("Repartiendo el inventario del CEDI entre las tiendas…")
        try:
            with pg.begin() as c:
                reparto = aplicar_a_ejecucion(c, eid)
        except Exception as e:
            log.exception("No se pudo repartir el inventario del CEDI")
            reparto = {"aplicado": False, "error": str(e)[:200]}
        progreso.avance("Guardando la foto diaria para las vistas de cambios y tendencia…")
        try:
            guardar_historia(eid)
        except Exception:
            log.exception("No se pudo guardar la historia del buffer")
        return {"ejecucion_id": eid, **res, "cedi": cedi, "reparto": reparto}
    except Exception as e:
        detalle = getattr(e, "stderr", None) or str(e)
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.ejecucion_motor SET fin=now(), estado='error', detalle=:d WHERE id=:i"),
                      {"d": detalle[-2000:], "i": eid})
        raise


def pipeline_nocturno(origen: str = "auto", usuario: str | None = None):
    """Programado (origen 'auto') o lanzado a mano desde la pantalla (origen 'manual')."""
    try:
        with progreso.tarea("ETL + motor", "ETL y motor listos"), bitacora.registrar("pipeline", origen, usuario):
            log.info("Pipeline: ETL")
            etl = correr_etl(origen, usuario)
            log.info("ETL listo: %s. Pipeline: motor", etl)
            return {"etl": etl, **ejecutar_motor(None, origen, usuario)}
    except progreso.Ocupado as e:   # otra corrida en curso: no se pisa, y queda anotado en el Log
        log.warning("Pipeline omitido: %s", e)
        bitacora.omitida("pipeline", origen, usuario, str(e))
