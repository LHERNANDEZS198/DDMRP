"""Orquesta: ETL -> motor Rust. El binario se invoca con lista de argumentos (sin shell)."""
import json, logging, subprocess, os
from datetime import date
from sqlalchemy import text
from .config import settings
from .db import pg
from .etl.replicacion import correr_etl, refrescar_cedi
from .reparto import aplicar_a_ejecucion
from .activos import purgas_fuera_del_maestro
from . import progreso, bitacora

log = logging.getLogger("orq")


def resumir_inventario_mensual(c, fecha):
    """Resume por mes (suma de inventario, dias y dias en cero de cada tienda x item) la foto diaria: es la base del inventario promedio del GMROI.
    Cada corrida rehace el mes de `fecha` (la historia diaria de un mes en curso siempre esta completa); la primera vez rehace todos los meses
    que aun tenga buffer_historia. Los meses anteriores no se tocan aunque la historia diaria ya se haya purgado. Se conservan 13 meses."""
    primera = not c.execute(text("SELECT EXISTS (SELECT 1 FROM ddmrp.inventario_mes)")).scalar()
    desde = c.execute(text("SELECT date_trunc('month', min(fecha))::date FROM ddmrp.buffer_historia")).scalar() if primera else None
    desde = desde or fecha.replace(day=1)
    c.execute(text("DELETE FROM ddmrp.inventario_mes WHERE mes >= to_char(CAST(:d AS date), 'YYYYMM')"), {"d": desde})
    c.execute(text("""INSERT INTO ddmrp.inventario_mes (mes, empresa, bodega_id, producto_id, inv_suma, dias, dias_cero)
                      SELECT to_char(fecha, 'YYYYMM'), empresa, bodega_id, producto_id, SUM(GREATEST(inventario, 0)), COUNT(*),
                             COUNT(*) FILTER (WHERE COALESCE(inventario, 0) <= 0)
                      FROM ddmrp.buffer_historia WHERE fecha >= :d GROUP BY 1, 2, 3, 4"""), {"d": desde})
    c.execute(text("DELETE FROM ddmrp.inventario_mes WHERE mes < to_char(current_date - interval '13 months', 'YYYYMM')"))


def guardar_historia(eid: int):
    """Foto diaria liviana de la corrida (reemplaza la del mismo dia) y limpieza: la historia dura `retener_dias`; el detalle
    completo de sugerencias (que es pesado) solo se conserva `DETALLE_DIAS` dias y una corrida por dia."""
    with pg.begin() as c:
        fecha = c.execute(text("SELECT fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = :e"), {"e": eid}).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha = :f"), {"f": fecha})
        cols = "empresa, bodega_id, producto_id, zona, tor, toy_aj, tog_aj, inventario, flujo_neto, pct_buffer"
        c.execute(text(f"INSERT INTO ddmrp.buffer_historia (fecha, {cols}) SELECT :f, {cols} FROM ddmrp.sugerencias_envio WHERE ejecucion_id = :e"),
                  {"f": fecha, "e": eid})
        # el CEDI tambien deja su foto diaria (tendencia / cambios / mapa en modo «Ver solo CEDI»); en los Informes se separa de las tiendas por el maestro de CEDIs
        c.execute(text(f"INSERT INTO ddmrp.buffer_historia (fecha, {cols}) SELECT :f, {cols} FROM ddmrp.sugerencias_cedi WHERE ejecucion_id = :e ON CONFLICT DO NOTHING"),
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
        for sql in purgas_fuera_del_maestro():
            c.execute(text(sql))
        resumir_inventario_mensual(c, fecha)
        dias = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'retener_dias'")).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha < current_date - :d"), {"d": int(dias) if dias else 180})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_envio s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_cedi s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})

    actualizar_estadisticas()


def actualizar_estadisticas():
    """ANALYZE de las tablas que el motor acaba de llenar. Sin el, Postgres no conoce la corrida nueva (ejecucion_id mayor que todo lo que vio) y elige
    planes que repiten agregaciones de cientos de miles de filas por cada fila (la matriz de despacho llego a tardar 20 minutos y dar 504)."""
    try:
        from .estadisticas import analizar_todo
        analizar_todo()
    except Exception:
        log.exception("No se pudo actualizar las estadisticas (ANALYZE)")


DETALLE_DIAS = 7


def heredar_enviadas(c, eid: int) -> int:
    """Corrida repetida el mismo dia: lo que ya se ENVIO (plano bajado y marcado como enviado) sigue ENVIADO en la corrida nueva, con la cantidad
    que se envio, para que nadie lo vuelva a despachar. Lo aprobado o editado a mano sin enviar si vuelve a PENDIENTE."""
    r = c.execute(text("""
        UPDATE ddmrp.sugerencias_envio n SET estado = 'ENVIADA'::ddmrp.estado_sugerencia, cantidad_aprobada = o.cant
        FROM (SELECT DISTINCT ON (s.empresa, s.bodega_id, s.producto_id) s.empresa, s.bodega_id, s.producto_id,
                     COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) AS cant
              FROM ddmrp.sugerencias_envio s JOIN ddmrp.ejecucion_motor e ON e.id = s.ejecucion_id
              WHERE s.estado = 'ENVIADA' AND s.ejecucion_id < :e AND e.estado = 'ok'
                AND e.fecha_calculo = (SELECT fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = :e)
              ORDER BY s.empresa, s.bodega_id, s.producto_id, s.ejecucion_id DESC) o
        WHERE n.ejecucion_id = :e AND n.empresa = o.empresa AND n.bodega_id = o.bodega_id AND n.producto_id = o.producto_id"""), {"e": eid})
    return r.rowcount or 0


def ejecutar_motor(fecha: date | None = None, origen: str = "manual", usuario: str | None = None) -> dict:
    with progreso.tarea("Motor", "Motor listo"), bitacora.registrar("motor", origen, usuario) as r:
        r.resumen = res = _ejecutar_motor(fecha)
        return res


def calcular_cedi(eid: int, fecha: date) -> dict:
    """Buffer del CEDI (PT001) con el mismo motor Rust en modo cedi: escribe en ddmrp.sugerencias_cedi, que despacho, reparto y planos no leen.
    Si falla NO tumba la corrida de las tiendas: se anota y los Informes en modo CEDI quedan sin la corrida de hoy."""
    try:
        out = subprocess.run(
            [settings.core_bin, "--ejecucion-id", str(eid), "--fecha", fecha.isoformat(), "--modo", "cedi"],
            env={**os.environ, "DATABASE_URL": settings.pg_dsn}, capture_output=True, text=True, timeout=300, check=True)
        res = json.loads(out.stdout.strip().splitlines()[-1])
        try:   # cuantas tiendas alimentan la demanda de cada CEDI: 0 seria un CEDI sin rotacion (y un buffer engañoso)
            with pg.connect() as c:
                res["tiendas_por_cedi"] = {f"{e}/{b}": n for e, b, n in c.execute(text(
                    "SELECT empresa, cedi, count(*) FILTER (WHERE origen <> cedi) FROM ddmrp.v_origen_cedi GROUP BY 1, 2")).all()}
        except Exception:
            log.exception("No se pudo contar las tiendas por CEDI")
        return res
    except Exception as e:
        log.exception("No se pudo calcular el buffer del CEDI")
        return {"ok": False, "error": ((getattr(e, "stderr", None) or str(e))[-300:])}


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
        progreso.avance("Calculando el buffer del CEDI…")
        cedi_motor = calcular_cedi(eid, fecha)
        progreso.avance("Repartiendo el inventario del CEDI entre las tiendas…")
        try:
            with pg.begin() as c:
                reparto = aplicar_a_ejecucion(c, eid)
        except Exception as e:
            log.exception("No se pudo repartir el inventario del CEDI")
            reparto = {"aplicado": False, "error": str(e)[:200]}
        try:
            with pg.begin() as c:
                reparto["enviadas_heredadas"] = heredar_enviadas(c, eid)
        except Exception:
            log.exception("No se pudieron heredar las filas ENVIADAS de la corrida anterior")
        progreso.avance("Guardando la foto diaria para las vistas de cambios y tendencia…")
        try:
            guardar_historia(eid)
        except Exception:
            log.exception("No se pudo guardar la historia del buffer")
        return {"ejecucion_id": eid, **res, "cedi": cedi, "cedi_motor": cedi_motor, "reparto": reparto}
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
