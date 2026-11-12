"""Diagnostico de lentitud de Salud / Clasificacion: repite las consultas mas lentas del registro (ddmrp.consulta_log) y muestra el plan de ejecucion real.
Uso (en el servidor o en local):  docker compose exec -T backend python -m app.diag_salud > plan_salud.txt
Solo lee; no cambia nada. Cada consulta puede tardar hasta 5 minutos (si no, se corta y lo dice)."""
import json, sys, time
from datetime import date
from sqlalchemy import text
from .db import pg
from .routers import clasificacion as cl_r, control as ct_r, alertas as al_r


def main(n: int = 3) -> None:
    cl_r.filtro_sql_permisos = lambda user, *a, **k: ("TRUE", {})      # como administrador: sin recorte por permisos
    ct_r.filtro_sql_permisos = cl_r.filtro_sql_permisos
    cl_r.EXPLAIN["on"] = True
    with pg.connect() as c:
        c.execute(text("SET LOCAL statement_timeout = 300000"))
        casos = c.execute(text("""SELECT ts, ruta, params, ms, ms_sql, filas, extra FROM ddmrp.consulta_log
                                  WHERE ruta ~ '/(salud|clasificacion)$' AND ts > now() - interval '30 days' AND ms_sql IS NOT NULL
                                  ORDER BY ms_sql DESC LIMIT :n"""), {"n": n}).mappings().all()
        print(f"== {len(casos)} consultas mas lentas del registro (de /salud y /clasificacion) ==")
        for k in casos:
            print(f"\n#### {k['ts']}  {k['ruta']}  total {k['ms']} ms, SQL {k['ms_sql']} ms, filas {k['filas']}, extra {json.dumps(k['extra'], default=str)}")
            print("params:", json.dumps(k["params"], ensure_ascii=False))
            pr = k["params"] or {}
            mes_desde, _, _ = cl_r._ventana(int(pr.get("meses") or 12))
            t0 = time.perf_counter()
            try:
                plan = cl_r._filas(c, {"id": "diag"}, mes_desde, True, pr.get("empresa"), pr.get("bodegas"), pr.get("labs"), pr.get("crit"), pr.get("q"))
                print(f"-- tiempo con filtros (incluye resolver los items del filtro): {time.perf_counter() - t0:.1f} s")
                print("\n".join(r["plan"] for r in plan))
            except Exception as e:     # noqa: BLE001
                print("-- FALLO:", str(e)[:300]); c.rollback(); c.execute(text("SET LOCAL statement_timeout = 300000"))
        casos = c.execute(text("""SELECT ts, params, ms FROM ddmrp.consulta_log WHERE ruta ~ '/alertas/resumen$' AND ts > now() - interval '30 days'
                                  ORDER BY ms DESC LIMIT 2""")).mappings().all()
        for k in casos:
            pr = k["params"] or {}
            print(f"\n#### {k['ts']}  /alertas/resumen  total {k['ms']} ms   params: {json.dumps(pr, ensure_ascii=False)}")
            try:
                w, p = al_r._donde({"id": "diag"}, pr.get("bodegas"), pr.get("labs"), pr.get("q"), pr.get("empresa"), pr.get("crit"))
                sql = f"""SELECT s.zona::text AS zona, count(*) n, COALESCE(sum({al_r.SOBRAN} * ci.costo) FILTER (WHERE NOT s.condenado), 0)::float8 AS sobran_costo,
                          COALESCE(sum({al_r.FALTAN} * ci.costo) FILTER (WHERE NOT s.condenado), 0)::float8 AS faltan_costo {al_r.BASE_C} WHERE {w} GROUP BY 1"""
                t0 = time.perf_counter()
                print("\n".join(r[0] for r in c.execute(text("EXPLAIN (ANALYZE, BUFFERS) " + sql), p)))
                print(f"-- tiempo: {time.perf_counter() - t0:.1f} s")
            except Exception as e:     # noqa: BLE001
                print("-- FALLO:", str(e)[:300]); c.rollback(); c.execute(text("SET LOCAL statement_timeout = 300000"))
        print("\n#### UNIVERSO (sin filtros: lo que calcula la 'clase global' cuando hay filtros y no esta en cache)")
        mes_desde, _, _ = cl_r._ventana(12)
        t0 = time.perf_counter()
        try:
            plan = cl_r._filas(c, {"id": "diag"}, mes_desde, False, hist=False)
            print(f"-- tiempo: {time.perf_counter() - t0:.1f} s")
            print("\n".join(r["plan"] for r in plan))
        except Exception as e:     # noqa: BLE001
            print("-- FALLO:", str(e)[:300])


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
