"""Reparto del inventario finito del CEDI entre las tiendas que lo piden ("repartir la pobreza").
Es una funcion pura (repartir) mas el cargador de datos; se usa en la Matriz de despacho, entre las tiendas de la corrida."""
import math
from sqlalchemy import text

EPS = 1e-9
REGLAS = {0: "No limitar", 1: "Proporcional a la rotacion", 4: "Proporcional a la necesidad", 2: "Parejo", 3: "Prioridad al mas critico"}


def _bloques(x: float, u: float) -> float:
    """Mayor multiplo de u que cabe en x."""
    return math.floor(x / u + EPS) * u


def repartir(filas: list[tuple], disponible: float, regla: int) -> dict:
    """filas = [(clave, necesidad, unidad_despacho, prioridad, rotacion)]. prioridad menor = mas critico; rotacion = ADU.
    regla: 0 no limita | 1 proporcional a la rotacion | 4 proporcional a la necesidad | 2 parejo | 3 prioridad.
    Si la necesidad total cabe en lo disponible, cada tienda recibe lo que pide. Si no, se reparte segun la regla,
    siempre en multiplos de la unidad de despacho, sin pasar lo disponible ni la necesidad de cada tienda."""
    total = sum(f[1] for f in filas)
    if regla == 0 or total <= disponible + EPS:
        return {f[0]: f[1] for f in filas}
    orden = sorted(filas, key=lambda f: (f[3], str(f[0])))
    u_de = {f[0]: (f[2] if f[2] and f[2] > 0 else 1.0) for f in filas}
    q = {f[0]: f[1] for f in filas}
    a = {f[0]: 0.0 for f in filas}
    resto = max(disponible, 0.0)

    def sobrantes(orden_):   # bloques sueltos de la unidad de despacho: de a uno, siguiendo el orden dado
        nonlocal resto
        cambio = True
        while cambio:
            cambio = False
            for k in orden_:
                u = u_de[k]
                if resto + EPS >= u and a[k] + u <= q[k] + EPS:
                    a[k] += u; resto -= u; cambio = True

    if regla == 3:                                   # prioridad: el mas critico se cubre primero
        for f in orden:
            k = f[0]; dar = min(q[k], _bloques(resto, u_de[k]))
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
        sobrantes([f[0] for f in orden])
    else:                                            # proporcional: (peso de la tienda / peso total) x disponible
        peso = {f[0]: (f[4] if regla == 1 else f[1]) for f in filas}
        if sum(peso.values()) <= 0:
            peso = dict(q)                           # sin rotacion en ninguna: se usa la necesidad
        fijos: dict = {}
        pend = [f[0] for f in orden]
        libre = max(disponible, 0.0)
        while pend:                                  # la tienda a la que le toca mas de lo que pide queda cubierta; su sobrante se reparte
            sw = sum(peso[k] for k in pend)
            if sw <= 0:
                break
            llenas = [k for k in pend if libre * peso[k] / sw >= q[k] - EPS]
            if not llenas:
                break
            for k in llenas:
                fijos[k] = q[k]; libre -= q[k]
            pend = [k for k in pend if k not in llenas]
        sw = sum(peso[k] for k in pend)
        crudo = {k: (libre * peso[k] / sw if sw > 0 else 0.0) for k in pend}
        for k, v in fijos.items():
            a[k] = v
        for k in pend:
            a[k] = min(q[k], _bloques(crudo[k], u_de[k]))
        resto = max(disponible, 0.0) - sum(a.values())
        sobrantes(sorted(pend, key=lambda k: (-(crudo[k] - a[k]), next(f[3] for f in filas if f[0] == k), str(k))) + [k for k in fijos])
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


def aplicar_a_ejecucion(c, eid: int) -> dict:
    """Reparte el inventario del CEDI entre TODAS las tiendas de cada referencia de la ejecucion del motor.
    Deja en sugerencias_envio: cantidad_necesaria (lo que pide el buffer), cantidad_sugerida (lo asignado) y stock_cedi
    (lo disponible de la referencia: inventario del CEDI menos la reserva). Sin inventario del CEDI no se limita nada."""
    regla = regla_actual(c)
    c.execute(text("UPDATE ddmrp.sugerencias_envio SET cantidad_necesaria = cantidad_sugerida, stock_cedi = NULL WHERE ejecucion_id = :e"), {"e": eid})
    d = datos_cedi(c)
    if regla == 0 or not d["stock"]:
        return {"limitadas": 0, "regla": regla, "aplicado": False}
    filas = c.execute(text("SELECT producto_id, bodega_id, cantidad_sugerida::float8, unidad_despacho::float8, "
                           "COALESCE(pct_buffer::float8, 1e9), COALESCE(adu::float8, 0) FROM ddmrp.sugerencias_envio "
                           "WHERE ejecucion_id = :e AND cantidad_sugerida > 0 AND NOT condenado"), {"e": eid}).all()
    por_item: dict = {}
    for prod, bod, q, ud, pct, adu in filas:
        por_item.setdefault(prod, []).append((bod, q, ud, pct, adu))
    cambios, stocks = [], []
    for prod, grupo in por_item.items():
        util = float(max(0, math.floor(d["stock"].get(prod, 0.0) * (1 - d["reserva"].get(prod, 0.0)) + EPS)))
        asign = repartir(grupo, util, regla)
        stocks.append((eid, prod, util))
        for bod, q, *_ in grupo:
            if asign[bod] + EPS < q:
                cambios.append((eid, prod, bod, asign[bod]))
    if stocks:
        c.execute(text("CREATE TEMP TABLE IF NOT EXISTS stg_cedi (e bigint, p text, util numeric) ON COMMIT DROP"))
        c.execute(text("TRUNCATE stg_cedi"))
        c.execute(text("INSERT INTO stg_cedi VALUES (:e, :p, :u)"), [{"e": a, "p": b, "u": u} for a, b, u in stocks])
        c.execute(text("UPDATE ddmrp.sugerencias_envio s SET stock_cedi = t.util FROM stg_cedi t WHERE s.ejecucion_id = t.e AND s.producto_id = t.p"))
    if cambios:
        c.execute(text("CREATE TEMP TABLE IF NOT EXISTS stg_asig (e bigint, p text, b text, q numeric) ON COMMIT DROP"))
        c.execute(text("TRUNCATE stg_asig"))
        c.execute(text("INSERT INTO stg_asig VALUES (:e, :p, :b, :q)"), [{"e": a, "p": b, "b": x, "q": q} for a, b, x, q in cambios])
        c.execute(text("UPDATE ddmrp.sugerencias_envio s SET cantidad_sugerida = t.q FROM stg_asig t "
                       "WHERE s.ejecucion_id = t.e AND s.producto_id = t.p AND s.bodega_id = t.b"))
    return {"limitadas": len(cambios), "items_sin_alcanzar": len({x[1] for x in cambios}), "regla": regla, "aplicado": True}
