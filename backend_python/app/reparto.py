"""Reparto del inventario finito del CEDI entre las tiendas que lo piden ("repartir la pobreza").
Es una funcion pura (repartir) mas el cargador de datos; se usa en la Matriz de despacho, entre las tiendas de la corrida."""
import math
from sqlalchemy import text

EPS = 1e-9
REGLAS = {0: "No limitar", 1: "Proporcional", 2: "Parejo", 3: "Prioridad al mas critico"}


def _bloques(x: float, u: float) -> float:
    """Mayor multiplo de u que cabe en x."""
    return math.floor(x / u + EPS) * u


def repartir(filas: list[tuple], disponible: float, regla: int) -> dict:
    """filas = [(clave, necesidad, unidad_despacho, prioridad)], prioridad menor = mas critico.
    Devuelve {clave: cantidad asignada}, siempre en multiplos de la unidad de despacho y sin pasarse de lo disponible ni de la necesidad."""
    total = sum(f[1] for f in filas)
    if regla == 0 or total <= disponible + EPS:
        return {f[0]: f[1] for f in filas}
    orden = sorted(filas, key=lambda f: (f[3], str(f[0])))
    u_de = {f[0]: (f[2] if f[2] and f[2] > 0 else 1.0) for f in filas}
    q = {f[0]: f[1] for f in filas}
    a = {f[0]: 0.0 for f in filas}
    resto = max(disponible, 0.0)

    def sobrantes():   # bloques sueltos: de a uno, siguiendo el orden de prioridad
        nonlocal resto
        cambio = True
        while cambio:
            cambio = False
            for k, *_ in orden:
                u = u_de[k]
                if resto + EPS >= u and a[k] + u <= q[k] + EPS:
                    a[k] += u; resto -= u; cambio = True

    if regla == 3:                                   # prioridad: el mas critico se cubre primero
        for k, *_ in orden:
            dar = min(q[k], _bloques(resto, u_de[k]))
            a[k] = dar; resto -= dar
    elif regla == 2:                                 # parejo: nivel comun, los que piden menos quedan cubiertos
        pend = [f[0] for f in orden]
        while pend and resto > EPS:
            nivel = resto / len(pend)
            cubiertos = [k for k in pend if q[k] - a[k] <= nivel + EPS]
            if cubiertos:
                for k in cubiertos:
                    dar = q[k] - a[k]; a[k] += dar; resto -= dar
                pend = [k for k in pend if k not in cubiertos]
                continue
            for k in pend:
                dar = _bloques(nivel, u_de[k]); a[k] += dar; resto -= dar
            break
        sobrantes()
    else:                                            # proporcional a lo que pide cada tienda
        crudo = {k: disponible * q[k] / total for k in q}
        for k in q:
            a[k] = min(q[k], _bloques(crudo[k], u_de[k])); resto -= a[k]
        orden = sorted(filas, key=lambda f: (-(crudo[f[0]] - a[f[0]]), f[3], str(f[0])))   # el que mas perdio por redondeo, primero
        sobrantes()
    return a


# ---- datos ----
def datos_cedi(c) -> dict:
    """{producto: (stock, reserva_fraccion)} y si hay datos del CEDI. Sin filas en inventario_cedi no se limita nada."""
    stock = {p: float(d) for p, d in c.execute(text("SELECT producto_id, disponible FROM ddmrp.inventario_cedi")).all()}
    res = {p: float(r) for p, r in c.execute(text("SELECT producto_id, porcentaje FROM ddmrp.reserva_cedi")).all()}
    return {"stock": stock, "reserva": res}


def regla_actual(c) -> int:
    v = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'cedi_regla_reparto'")).scalar()
    return int(v) if v is not None else 1


def aplicar(c, filas: list[dict], ejecucion_id: int) -> list[dict]:
    """Recibe las filas PENDIENTES de la matriz (con cantidad_sugerida = lo que pide el buffer) y devuelve las mismas
    con cantidad_necesaria (lo que pide), stock_cedi (lo disponible del item) y cantidad_sugerida (lo asignado)."""
    regla = regla_actual(c)
    d = datos_cedi(c)
    for f in filas:
        f["cantidad_necesaria"] = float(f["cantidad_sugerida"])
        f["stock_cedi"] = None
        f["limitado"] = False
    if regla == 0 or not d["stock"]:
        return filas
    gastado = {p: float(q) for p, q in c.execute(text(
        "SELECT producto_id, COALESCE(sum(cantidad_aprobada), 0) FROM ddmrp.sugerencias_envio "
        "WHERE ejecucion_id = :e AND estado IN ('APROBADA', 'ENVIADA') GROUP BY producto_id"), {"e": ejecucion_id}).all()}
    por_item: dict[str, list[dict]] = {}
    for f in filas:
        por_item.setdefault(f["producto_id"], []).append(f)
    for prod, grupo in por_item.items():
        bruto = d["stock"].get(prod, 0.0)
        util = max(0.0, math.floor(bruto * (1 - d["reserva"].get(prod, 0.0)) + EPS) - gastado.get(prod, 0.0))
        asign = repartir([((g["bodega_id"],), g["cantidad_necesaria"], float(g.get("unidad_despacho") or 0),
                           float(g["pct_buffer"]) if g.get("pct_buffer") is not None else 1e9) for g in grupo], util, regla)
        for g in grupo:
            g["stock_cedi"] = util
            g["cantidad_sugerida"] = asign[(g["bodega_id"],)]
            g["limitado"] = g["cantidad_sugerida"] + EPS < g["cantidad_necesaria"]
    return filas
