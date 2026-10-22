"""Diagnostico (solo quien tenga la funcion ver_diagnostico, es decir administradores): que consultas se hicieron, con que filtros, cuanto tardaron
y como terminaron; consultas que estan corriendo ahora en Postgres (con opcion de cancelar) y el estado de la base (estadisticas, tamaños, meses de ventas)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from ..db import pg
from ..security import requiere

router = APIRouter(prefix="/diagnostico", tags=["diagnostico"], dependencies=[Depends(requiere("ver_diagnostico"))])


@router.get("/consultas")
def consultas(horas: int = Query(24, ge=1, le=720), ruta: str | None = None, usuario: str | None = None, estado: str | None = None,
              min_ms: int = Query(0, ge=0), q: str | None = None, limite: int = Query(300, ge=1, le=2000)):
    w, p = ["ts >= now() - make_interval(hours => :h)", "COALESCE(ms, 0) >= :m"], {"h": horas, "m": min_ms, "l": limite}
    if ruta: w.append("ruta = :ruta"); p["ruta"] = ruta
    if usuario: w.append("usuario = :usuario"); p["usuario"] = usuario
    if estado: w.append("estado = :estado"); p["estado"] = estado
    if q: w.append("(COALESCE(params::text, '') || ' ' || COALESCE(error, '') || ' ' || COALESCE(extra::text, '')) ILIKE :q"); p["q"] = f"%{q}%"
    with pg.connect() as c:
        filas = [dict(r._mapping) for r in c.execute(text(
            f"SELECT id, ts, usuario, metodo, ruta, params, http, estado, ms, ms_sql, ms_calc, filas, bytes, error, extra FROM ddmrp.consulta_log "
            f"WHERE {' AND '.join(w)} ORDER BY ts DESC, id DESC LIMIT :l"), p)]
        rutas = [r[0] for r in c.execute(text("SELECT DISTINCT ruta FROM ddmrp.consulta_log WHERE ts >= now() - interval '30 days' ORDER BY 1"))]
        usuarios = [r[0] for r in c.execute(text("SELECT DISTINCT usuario FROM ddmrp.consulta_log WHERE usuario IS NOT NULL AND ts >= now() - interval '30 days' ORDER BY 1"))]
    return {"filas": filas, "rutas": rutas, "usuarios": usuarios}


@router.get("/resumen")
def resumen(horas: int = Query(24, ge=1, le=720)):
    """Por ruta: cuantas veces, cuantas fallaron o se pasaron de tiempo, y la distribucion de tiempos (p50, p95, maximo)."""
    with pg.connect() as c:
        r = [dict(x._mapping) for x in c.execute(text("""
            SELECT ruta, count(*)::int AS n,
                   count(*) FILTER (WHERE estado = 'timeout')::int AS timeouts,
                   count(*) FILTER (WHERE estado IN ('error','rechazado'))::int AS fallas,
                   round(avg(ms))::int AS ms_prom,
                   round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ms))::int AS ms_p50,
                   round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms))::int AS ms_p95,
                   max(ms)::int AS ms_max,
                   round(avg(ms_sql))::int AS sql_prom, round(avg(ms_calc))::int AS calc_prom,
                   max(ts) AS ultima
            FROM ddmrp.consulta_log WHERE ts >= now() - make_interval(hours => :h) GROUP BY ruta ORDER BY sum(ms) DESC NULLS LAST"""), {"h": horas})]
    return {"rutas": r}


@router.get("/activas")
def activas():
    """Consultas que Postgres esta ejecutando ahora mismo (las mas largas primero)."""
    with pg.connect() as c:
        filas = [dict(x._mapping) for x in c.execute(text("""
            SELECT pid, usename AS usuario, state AS estado, wait_event_type || ':' || wait_event AS espera,
                   round(extract(epoch FROM now() - query_start))::int AS segundos, client_port AS puerto, left(query, 600) AS consulta
            FROM pg_stat_activity
            WHERE datname = current_database() AND pid <> pg_backend_pid() AND state <> 'idle' AND backend_type = 'client backend'
            ORDER BY query_start NULLS LAST"""))]
    return {"filas": filas}


@router.post("/cancelar/{pid}")
def cancelar(pid: int, user=Depends(requiere("ver_diagnostico"))):
    """Cancela la consulta (no la conexion) de un proceso de ESTA base. Solo procesos que aparecen en 'activas'."""
    with pg.connect() as c:
        ok = c.execute(text("SELECT 1 FROM pg_stat_activity WHERE pid = :p AND datname = current_database() AND pid <> pg_backend_pid() AND backend_type = 'client backend'"), {"p": pid}).scalar()
        if not ok:
            raise HTTPException(404, "Ese proceso ya no existe o no es una consulta de esta base")
        res = c.execute(text("SELECT pg_cancel_backend(:p)"), {"p": pid}).scalar()
    return {"cancelada": bool(res)}


@router.get("/base")
def base():
    """Salud de la base: ultima vez que se actualizaron las estadisticas por tabla, filas vivas/muertas, tamaño, y los meses de ventas cargados."""
    with pg.connect() as c:
        tablas = [dict(x._mapping) for x in c.execute(text("""
            SELECT relname AS tabla, n_live_tup::bigint AS filas, n_dead_tup::bigint AS muertas,
                   GREATEST(last_analyze, last_autoanalyze) AS analizada, GREATEST(last_vacuum, last_autovacuum) AS vaciada,
                   pg_total_relation_size(relid)::bigint AS bytes, n_mod_since_analyze::bigint AS cambios_desde_analyze
            FROM pg_stat_user_tables WHERE schemaname = 'ddmrp' ORDER BY pg_total_relation_size(relid) DESC LIMIT 25"""))]
        ventas = [dict(x._mapping) for x in c.execute(text("""
            SELECT mes, count(DISTINCT bodega_id)::int AS tiendas, count(DISTINCT producto_id)::int AS items, round(sum(valor) / 1e6)::bigint AS venta_millones
            FROM ddmrp.ventas_mensual GROUP BY mes ORDER BY mes DESC LIMIT 40"""))]
        conexiones = c.execute(text("SELECT count(*) FILTER (WHERE state <> 'idle'), count(*) FROM pg_stat_activity WHERE datname = current_database()")).one()
        timeout = c.execute(text("SHOW statement_timeout")).scalar()
        tam = c.execute(text("SELECT pg_database_size(current_database())")).scalar()
    return {"tablas": tablas, "ventas_por_mes": ventas, "conexiones_activas": conexiones[0], "conexiones": conexiones[1],
            "statement_timeout": timeout, "bytes_base": tam}
