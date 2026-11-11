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

EMPRESAS = ("05", "21")   # Funat y Stores: cada una tiene su propia corrida del motor (ejecucion_motor.empresa) y su propia ultima corrida


def resumir_inventario_mensual(c, fecha):
    """Resume por mes (suma de inventario, dias y dias en cero de cada tienda x item) la foto diaria: es la base del inventario promedio del GMROI.
    Cada corrida rehace el mes de `fecha` (la historia diaria de un mes en curso siempre esta completa); la primera vez rehace todos los meses
    que aun tenga buffer_historia. Los meses anteriores no se tocan aunque la historia diaria ya se haya purgado. Se conservan 13 meses."""
    primera = not c.execute(text("SELECT EXISTS (SELECT 1 FROM ddmrp.inventario_mes)")).scalar()
    desde = c.execute(text("SELECT date_trunc('month', min(fecha))::date FROM ddmrp.buffer_historia")).scalar() if primera else None
    desde = desde or fecha.replace(day=1)
    c.execute(text("DELETE FROM ddmrp.inventario_mes WHERE mes >= to_char(CAST(:d AS date), 'YYYYMM')"), {"d": desde})
    c.execute(text("""INSERT INTO ddmrp.inventario_mes (mes, empresa, bodega_id, producto_id, inv_suma, dias, dias_cero, dias_z, dias_roja)
                      SELECT to_char(fecha, 'YYYYMM'), empresa, bodega_id, producto_id, SUM(GREATEST(inventario, 0)), COUNT(*),
                             COUNT(*) FILTER (WHERE COALESCE(inventario, 0) <= 0), COUNT(*) FILTER (WHERE zona IS NOT NULL), COUNT(*) FILTER (WHERE zona = 'ROJA')
                      FROM ddmrp.buffer_historia WHERE fecha >= :d GROUP BY 1, 2, 3, 4"""), {"d": desde})
    completar_dias_zona(c)
    c.execute(text("DELETE FROM ddmrp.inventario_mes WHERE mes < to_char(current_date - interval '13 months', 'YYYYMM')"))


def completar_dias_zona(c):
    """Meses resumidos antes de que existieran los dias en zona roja: se completan SOLO con lo que aun conserva la foto diaria (los meses ya purgados quedan sin dato).
    Tambien lo llama el calculo de Indicadores de compras, para no esperar a la proxima corrida del motor."""
    if c.execute(text("""SELECT EXISTS (SELECT 1 FROM ddmrp.inventario_mes WHERE dias_z IS NULL AND mes >= (SELECT to_char(min(fecha), 'YYYYMM') FROM ddmrp.buffer_historia))""")).scalar():
        c.execute(text("""UPDATE ddmrp.inventario_mes im SET dias_z = x.dz, dias_roja = x.dr
                          FROM (SELECT to_char(fecha, 'YYYYMM') AS mes, empresa, bodega_id, producto_id, COUNT(*) FILTER (WHERE zona IS NOT NULL) AS dz, COUNT(*) FILTER (WHERE zona = 'ROJA') AS dr
                                FROM ddmrp.buffer_historia GROUP BY 1, 2, 3, 4) x
                          WHERE im.dias_z IS NULL AND im.mes = x.mes AND im.empresa = x.empresa AND im.bodega_id = x.bodega_id AND im.producto_id = x.producto_id"""))


def guardar_historia(eid: int):
    """Foto diaria liviana de la corrida (reemplaza la del mismo dia) y limpieza: la historia dura `retener_dias`; el detalle
    completo de sugerencias (que es pesado) solo se conserva `DETALLE_DIAS` dias y una corrida por dia."""
    with pg.begin() as c:
        fecha, emp = c.execute(text("SELECT fecha_calculo, empresa FROM ddmrp.ejecucion_motor WHERE id = :e"), {"e": eid}).one()
        # la foto del dia se rehace SOLO de la empresa que corrio: la de la otra empresa no se toca
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha = :f AND empresa = :m"), {"f": fecha, "m": emp})
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
                                 WHERE estado = 'ok' AND empresa = :m ORDER BY fecha_calculo, id DESC) e
                           JOIN ddmrp.sugerencias_envio s ON s.ejecucion_id = e.id
                           WHERE e.fecha_calculo NOT IN (SELECT DISTINCT fecha FROM ddmrp.buffer_historia WHERE empresa = :m)
                           ON CONFLICT DO NOTHING"""), {"m": emp})
        # items fuera del maestro (no pasan el filtro de criterios, ej. materia prima) que quedaron en fotos de corridas anteriores
        for sql in purgas_fuera_del_maestro():
            c.execute(text(sql))
        resumir_inventario_mensual(c, fecha)
        dias = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'retener_dias'")).scalar()
        c.execute(text("DELETE FROM ddmrp.buffer_historia WHERE fecha < current_date - :d"), {"d": int(dias) if dias else 180})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_envio s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND e.id NOT IN (SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado = 'ok' GROUP BY empresa)
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (empresa, fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY empresa, fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})
        c.execute(text("""DELETE FROM ddmrp.sugerencias_cedi s USING ddmrp.ejecucion_motor e
                          WHERE s.ejecucion_id = e.id AND s.ejecucion_id <> :e
                            AND e.id NOT IN (SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado = 'ok' GROUP BY empresa)
                            AND (e.fecha_calculo < current_date - :d OR e.id NOT IN
                                 (SELECT DISTINCT ON (empresa, fecha_calculo) id FROM ddmrp.ejecucion_motor WHERE estado = 'ok'
                                  ORDER BY empresa, fecha_calculo, id DESC) AND e.fecha_calculo < current_date)"""), {"e": eid, "d": DETALLE_DIAS})

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


def ejecutar_motor(fecha: date | None = None, origen: str = "manual", usuario: str | None = None, empresa: str | None = None) -> dict:
    """Corre el motor de UNA empresa (05 Funat / 21 Stores): su corrida, su ultima corrida y su historia, sin tocar las de la otra.
    Sin `empresa` corre las dos, una tras otra (solo lo usa el nocturno); si una falla la otra se corre igual y el error queda en el resultado."""
    with progreso.tarea("Motor", "Motor listo"), bitacora.registrar("motor", origen, usuario) as r:
        if empresa:
            r.resumen = res = {**_ejecutar_motor(fecha, empresa), "empresa": empresa}
            return res
        res = {}
        for e in EMPRESAS:
            try:
                res[e] = _ejecutar_motor(fecha, e)
            except Exception as ex:
                log.exception("Motor de la empresa %s fallo", e)
                res[e] = {"error": str(ex)[-300:]}
        r.resumen = res
        if all("error" in v for v in res.values()):
            raise RuntimeError("El motor fallo en las dos empresas: " + "; ".join(f"{k}: {v['error']}" for k, v in res.items()))
        return res


def calcular_cedi(eid: int, fecha: date, empresa: str = "") -> dict:
    """Buffer del CEDI (PT001) con el mismo motor Rust en modo cedi: escribe en ddmrp.sugerencias_cedi, que despacho, reparto y planos no leen.
    Si falla NO tumba la corrida de las tiendas: se anota y los Informes en modo CEDI quedan sin la corrida de hoy."""
    try:
        out = subprocess.run(
            [settings.core_bin, "--ejecucion-id", str(eid), "--fecha", fecha.isoformat(), "--modo", "cedi", "--empresa", empresa or ""],
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


def _ejecutar_motor(fecha: date | None = None, empresa: str = "05") -> dict:
    fecha = fecha or date.today()
    progreso.avance(f"Leyendo el inventario fresco del CEDI ({empresa})…")
    cedi = refrescar_cedi(empresa)
    progreso.avance(f"Calculando buffers de la empresa {empresa} con el motor Rust (varios minutos con todas las tiendas)…")
    with pg.begin() as c:
        eid = c.execute(text("INSERT INTO ddmrp.ejecucion_motor (fecha_calculo, empresa) VALUES (:f, :m) RETURNING id"),
                        {"f": fecha, "m": empresa}).scalar_one()
    try:
        out = subprocess.run(
            [settings.core_bin, "--ejecucion-id", str(eid), "--fecha", fecha.isoformat(), "--empresa", empresa],
            env={**os.environ, "DATABASE_URL": settings.pg_dsn},
            capture_output=True, text=True, timeout=600, check=True)
        res = json.loads(out.stdout.strip().splitlines()[-1])
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.ejecucion_motor SET fin=now(), estado='ok', filas=:n WHERE id=:i"),
                      {"n": res["filas"], "i": eid})
        progreso.avance("Calculando el buffer del CEDI…")
        cedi_motor = calcular_cedi(eid, fecha, empresa)
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


def recalcular_compras(origen: str = "manual", usuario: str | None = None, empresa: str | None = None) -> dict:
    """Recalcula SOLO el buffer del CEDI (lo que usa Necesidades de compra) sin correr el motor completo: inventario fresco del CEDI y ordenes de compra abiertas de Siesa,
    y el motor Rust en modo CEDI sobre la ultima corrida. No toca las tiendas, el reparto ni la matriz de despacho. Las cantidades editadas por compras se conservan."""
    with progreso.tarea("Compras", "Necesidades de compra recalculadas"), bitacora.registrar("compras", origen, usuario) as r:
        if empresa:
            r.resumen = res = _recalcular_compras(empresa)
            return res
        res = {}
        for e in EMPRESAS:
            try:
                res[e] = _recalcular_compras(e)
            except Exception as ex:
                log.warning("Compras de la empresa %s no se recalcularon: %s", e, ex)
                res[e] = {"error": str(ex)[-300:]}
        r.resumen = res
        return res


def _recalcular_compras(empresa: str = "05") -> dict:
    from .etl.replicacion import refrescar_oc_cedi
    with pg.connect() as c:
        ej = c.execute(text("SELECT id FROM ddmrp.ejecucion_motor WHERE estado = 'ok' AND empresa = :m ORDER BY id DESC LIMIT 1"), {"m": empresa}).first()
    if not ej:
        raise RuntimeError(f"Aún no hay una corrida del motor de la empresa {empresa}: pídele a quien tenga el permiso que la corra una vez.")
    eid = ej[0]
    progreso.avance("Leyendo el inventario fresco del CEDI…")
    cedi = refrescar_cedi(empresa)
    progreso.avance("Leyendo las órdenes de compra abiertas de Siesa…")
    try:
        oc = refrescar_oc_cedi(empresa)
    except Exception as e:   # sin las OC el tránsito queda como estaba: se avisa pero se sigue
        log.exception("No se pudieron refrescar las OC abiertas")
        oc = {"error": str(e)[:200]}
    progreso.avance("Recalculando el buffer del CEDI…")
    tmp = -eid   # se calcula aparte (id negativo) y solo si sale bien se cambia por el anterior: un fallo del motor no deja a compras sin buffer
    with pg.begin() as c:
        c.execute(text("DELETE FROM ddmrp.sugerencias_cedi WHERE ejecucion_id = :t"), {"t": tmp})
    cm = calcular_cedi(tmp, date.today(), empresa)
    if not cm.get("ok", True) or "error" in cm:
        with pg.begin() as c:
            c.execute(text("DELETE FROM ddmrp.sugerencias_cedi WHERE ejecucion_id = :t"), {"t": tmp})
        raise RuntimeError("No se pudo recalcular el buffer del CEDI (queda el anterior): " + str(cm.get("error", ""))[:300])
    with pg.begin() as c:
        c.execute(text("DELETE FROM ddmrp.sugerencias_cedi WHERE ejecucion_id = :e"), {"e": eid})
        c.execute(text("UPDATE ddmrp.sugerencias_cedi SET ejecucion_id = :e WHERE ejecucion_id = :t"), {"e": eid, "t": tmp})
    return {"empresa": empresa, "ejecucion_id": eid, "cedi": cedi, "oc": oc, "cedi_motor": cm}


def revisar_pipeline():
    """Se llama cada minuto: corre el ETL + motor a la hora configurada en Reglas de pedido (pipeline_auto / pipeline_hora / pipeline_minuto / pipeline_cada_dias).
    Con pipeline_auto en 0 no corre nada solo. Tolera ~30 min de retraso (si el backend estaba reiniciando justo a esa hora); como maximo una vez por dia programado."""
    from datetime import datetime
    import pytz      # ya viene con APScheduler: no depende de que el sistema tenga la base de zonas horarias
    try:
        with pg.begin() as c:
            p = {k: float(v) for k, v in c.execute(text("SELECT clave, valor FROM ddmrp.parametro WHERE clave IN "
                 "('pipeline_auto', 'pipeline_hora', 'pipeline_minuto', 'pipeline_cada_dias', 'pipeline_ultima_auto')")).all()}
            if p.get("pipeline_auto", 1) < 1:
                return
            ahora = datetime.now(pytz.timezone("America/Bogota"))
            objetivo = int(p.get("pipeline_hora", settings.etl_cron_hour)) * 60 + int(p.get("pipeline_minuto", 0))
            minutos = ahora.hour * 60 + ahora.minute
            if not (objetivo <= minutos < objetivo + 30):
                return
            hoy = ahora.date()
            ult = int(p.get("pipeline_ultima_auto", 0))
            if ult:
                dif = (hoy - date(ult // 10000, ult // 100 % 100, ult % 100)).days
                if dif < max(int(p.get("pipeline_cada_dias", 1)), 1):
                    return
            c.execute(text("INSERT INTO ddmrp.parametro (clave, valor, detalle) VALUES ('pipeline_ultima_auto', :v, 'Ultimo dia (AAAAMMDD) en que corrio sola la corrida automatica') "
                           "ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"), {"v": hoy.year * 10000 + hoy.month * 100 + hoy.day})
    except Exception:
        log.exception("No se pudo revisar la corrida automatica")
        return
    pipeline_nocturno("auto")


def pipeline_nocturno(origen: str = "auto", usuario: str | None = None, empresa: str | None = None):
    """Programado (origen 'auto', las dos empresas) o lanzado a mano desde la pantalla (origen 'manual'; con `empresa` solo esa, sin ella las dos)."""
    try:
        with progreso.tarea("ETL + motor", "ETL y motor listos"), bitacora.registrar("pipeline", origen, usuario):
            log.info("Pipeline: ETL")
            etl = correr_etl(origen, usuario, empresa)
            log.info("ETL listo: %s. Pipeline: motor", etl)
            return {"etl": etl, "motor": ejecutar_motor(None, origen, usuario, empresa)}
    except progreso.Ocupado as e:   # otra corrida en curso: no se pisa, y queda anotado en el Log
        log.warning("Pipeline omitido: %s", e)
        bitacora.omitida("pipeline", origen, usuario, str(e))
