"""Orquesta: ETL -> motor Rust. El binario se invoca con lista de argumentos (sin shell)."""
import json, logging, subprocess, os
from datetime import date
from sqlalchemy import text
from .config import settings
from .db import pg
from .etl.replicacion import correr_etl

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
        dias = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'retener_dias'")).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha < current_date - :d"), {"d": int(dias) if dias else 180})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_envio s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})


DETALLE_DIAS = 7


def ejecutar_motor(fecha: date | None = None) -> dict:
    fecha = fecha or date.today()
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
        try:
            guardar_historia(eid)
        except Exception:
            log.exception("No se pudo guardar la historia del buffer")
        return {"ejecucion_id": eid, **res}
    except Exception as e:
        detalle = getattr(e, "stderr", None) or str(e)
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.ejecucion_motor SET fin=now(), estado='error', detalle=:d WHERE id=:i"),
                      {"d": detalle[-2000:], "i": eid})
        raise


def pipeline_nocturno():
    log.info("Pipeline nocturno: ETL")
    etl = correr_etl()
    log.info("ETL listo: %s. Pipeline nocturno: motor", etl)
    return {"etl": etl, **ejecutar_motor()}
