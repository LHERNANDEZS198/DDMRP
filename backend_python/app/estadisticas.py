"""ANALYZE de las tablas que usan los informes (tras el ETL, tras el motor y a pedido desde el Log)."""
import time
from sqlalchemy import text
from .db import pg

TABLAS_ANALIZAR = ("sugerencias_envio", "buffer_historia", "inventario_mes", "ventas_mensual", "inventario_actual", "transitos", "item_criterio", "criterio",
                   "maestro_item", "costo_item", "item_estado", "inventario_cedi", "demanda_calificada")


def analizar_todo() -> dict:
    """ANALYZE a pedido (boton del Log) de todas las tablas que usan los informes. No toca datos: solo actualiza las estadisticas del planificador."""
    hechas, fallas = {}, {}
    with pg.connect() as c:
        for t in TABLAS_ANALIZAR:
            t0 = time.time()
            try:
                c.execute(text(f"ANALYZE ddmrp.{t}")); c.commit()
                hechas[t] = round(time.time() - t0, 1)
            except Exception as e:
                c.rollback(); fallas[t] = str(e).splitlines()[0][:120]
    return {"tablas": len(hechas), "segundos": round(sum(hechas.values()), 1), "detalle": hechas, **({"fallas": fallas} if fallas else {})}
