"""Lanzamientos: productos que ENTRAN al inventario del CEDI (PT001). Dos eventos, detectados en cada lectura del CEDI (ETL y motor)
comparando la existencia fisica contra la ultima que se guardo:
  PRIMERA   : primera existencia detectada (el item nunca habia tenido stock en el CEDI desde que el sistema lo vigila).
  REINGRESO : el item vuelve a tener stock tras haber estado en 0 al menos un dia (agotado, cartera, etc.).
La primera lectura de cada empresa es la LINEA BASE: lo que ya estaba en el CEDI ese dia no cuenta como lanzamiento.
Es historia propia del sistema: no usa los movimientos de Siesa."""
from datetime import date

# Si el CEDI tenia al menos esta cantidad de items con stock y de pronto ninguno, la lectura es sospechosa (Siesa devolvio vacio
# o la bodega cambio): no se registra nada para no inundar el reporte de falsos reingresos al dia siguiente.
MIN_PARA_SOSPECHA = 20


def detectar_eventos(prev: dict[str, tuple], ahora: dict[str, float], fecha: date, base: bool):
    """prev = {producto: (existencia, visto_desde, ultima_con_stock)} lo guardado; ahora = {producto: existencia} lo que dice Siesa hoy
    (los productos que ya no vienen cuentan como 0). Devuelve (estado_nuevo, eventos) con
    eventos = [(producto, tipo, dias_sin_stock | None, existencia)]. `base` = primera lectura de la empresa: sin eventos."""
    estado: dict[str, tuple] = {}
    eventos: list[tuple] = []
    for p in sorted(prev.keys() | ahora.keys()):
        e = max(float(ahora.get(p, 0.0) or 0.0), 0.0)        # existencia negativa no es stock
        if p in prev:
            e0, visto, ultima = prev[p]
            if e > 0:
                if e0 <= 0:
                    if ultima is None:
                        eventos.append((p, "PRIMERA", None, e))
                    elif (fecha - ultima).days >= 1:
                        eventos.append((p, "REINGRESO", (fecha - ultima).days, e))
                ultima = fecha
            estado[p] = (e, visto, ultima)
        elif e > 0:
            if not base:
                eventos.append((p, "PRIMERA", None, e))
            estado[p] = (e, fecha, fecha)
        else:
            estado[p] = (e, fecha, None)
    return estado, eventos


def registrar(cur, empresa: str, ahora: dict[str, float], fecha: date) -> dict:
    """Guarda el estado del CEDI de la empresa y los eventos del dia (cursor psycopg dentro de la transaccion del ETL)."""
    cur.execute("SELECT 1 FROM ddmrp.cedi_base WHERE empresa = %s", (empresa,))
    base = cur.fetchone() is None
    cur.execute("SELECT producto_id, existencia, visto_desde, ultima_con_stock FROM ddmrp.cedi_estado WHERE empresa = %s", (empresa,))
    prev = {p: (float(e), v, u) for p, e, v, u in cur.fetchall()}
    con_antes = sum(1 for v in prev.values() if v[0] > 0)
    con_hoy = sum(1 for v in ahora.values() if v and v > 0)
    if not base and con_antes >= MIN_PARA_SOSPECHA and con_hoy == 0:
        return {"omitido": f"lectura sospechosa: el CEDI tenia {con_antes} items con stock y hoy ninguno", "base": False}
    estado, eventos = detectar_eventos(prev, ahora, fecha, base)
    cambios = [(empresa, p, e, v, u) for p, (e, v, u) in estado.items() if prev.get(p) != (e, v, u)]
    if cambios:
        cur.executemany("INSERT INTO ddmrp.cedi_estado (empresa, producto_id, existencia, visto_desde, ultima_con_stock) VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT (empresa, producto_id) DO UPDATE SET existencia = EXCLUDED.existencia, "
                        "ultima_con_stock = EXCLUDED.ultima_con_stock", cambios)
    if eventos:
        cur.executemany("INSERT INTO ddmrp.cedi_evento (empresa, producto_id, fecha, tipo, dias_sin_stock, existencia) VALUES (%s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (empresa, producto_id, fecha) DO NOTHING", [(empresa, p, fecha, t, d, e) for p, t, d, e in eventos])
    if base:
        cur.execute("INSERT INTO ddmrp.cedi_base (empresa, fecha) VALUES (%s, %s) ON CONFLICT DO NOTHING", (empresa, fecha))
    return {"base": base, "items": len(estado), "con_stock": con_hoy,
            "primeras": sum(1 for e in eventos if e[1] == "PRIMERA"), "reingresos": sum(1 for e in eventos if e[1] == "REINGRESO")}
