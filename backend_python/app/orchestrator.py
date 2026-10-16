"""Orquesta: ETL -> motor Rust. El binario se invoca con lista de argumentos (sin shell)."""
import json, logging, subprocess, os
from datetime import date
from sqlalchemy import text
from .config import settings
from .db import pg
from .etl.siesa_to_pg import correr_etl

log = logging.getLogger("orq")


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
        return {"ejecucion_id": eid, **res}
    except Exception as e:
        detalle = getattr(e, "stderr", None) or str(e)
        with pg.begin() as c:
            c.execute(text("UPDATE ddmrp.ejecucion_motor SET fin=now(), estado='error', detalle=:d WHERE id=:i"),
                      {"d": detalle[-2000:], "i": eid})
        raise


def pipeline_nocturno(dias_ventas: int = 7):
    log.info("Pipeline nocturno: ETL")
    correr_etl(dias_ventas)
    log.info("Pipeline nocturno: motor")
    return ejecutar_motor()
