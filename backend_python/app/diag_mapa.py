"""Diagnostico del mapa de calor: repite la ultima llamada LENTA del registro (ddmrp.consulta_log) y muestra el plan de sus dos consultas grandes (conteo y lista).
Uso (en el servidor):  docker compose exec -T backend python -m app.diag_mapa > docs/sql/plan_mapa2.txt
Solo lee; cada consulta se corta a los 90 s. No lo corras mientras el backend esta arrancando."""
import json, sys, time
from datetime import date
from sqlalchemy import text
from .db import pg
from . import modo
from .routers import control as ct_r


def main(minimo_ms: int = 5000) -> None:
    ct_r.filtro_sql_permisos = lambda user, *a, **k: ("TRUE", {})      # como administrador
    with pg.connect() as c:
        c.execute(text("SET LOCAL statement_timeout = 90000"))
        k = c.execute(text("""SELECT ts, params, ms FROM ddmrp.consulta_log WHERE ruta ~ '/control/mapa$' AND ms > :m ORDER BY ts DESC LIMIT 1"""), {"m": minimo_ms}).mappings().first()
        if not k:
            print("No hay llamadas lentas del mapa en el registro"); return
        pr = k["params"] or {}
        print(f"#### {k['ts']} total {k['ms']} ms  params: {json.dumps(pr, ensure_ascii=False)}")
        v = (pr.get("solo_cedi") or "false").lower()
        modo._MODO.set("cedi" if v in ("true", "1", "si", "cedi") else "todos" if v == "todos" else "tiendas")
        f = lambda x: date.fromisoformat(x) if x else None
        ct_r.EXPLAIN_MAPA["on"] = True
        t0 = time.perf_counter()
        try:
            ct_r._mapa_datos(c, {"id": "diag"}, pr.get("bodegas"), pr.get("labs"), pr.get("q"), pr.get("zonas"), int(pr["dia"]) if pr.get("dia") else None, pr.get("empresa"),
                             pr.get("crit"), f(pr.get("desde")), f(pr.get("hasta")), int(pr.get("paso") or 1), pr.get("metrica") or "inventario", pr.get("orden") or "critico",
                             int(pr.get("limit") or 2000), (pr.get("ignorar_vacios") or "true").lower() != "false")
        except Exception as e:     # noqa: BLE001
            print("-- FALLO:", str(e)[:300])
        print(f"\n-- total {time.perf_counter() - t0:.1f} s")


if __name__ == "__main__":
    main()