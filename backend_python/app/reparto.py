"""Reparto del inventario finito del CEDI entre las tiendas que lo piden ("repartir la pobreza").
Es una funcion pura (repartir) mas el cargador de datos; se usa en la Matriz de despacho, entre las tiendas de la corrida."""
import math
from sqlalchemy import text
from .activos import solo_activos

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
    """{(empresa, producto): stock} y {producto: reserva_fraccion}. El inventario del CEDI es de cada empresa: solo se reparte
    entre las tiendas de esa empresa. Sin filas de una empresa en inventario_cedi no se limita nada de esa empresa."""
    stock = {(e, p): float(d) for e, p, d in c.execute(text("SELECT empresa, producto_id, disponible FROM ddmrp.inventario_cedi")).all()}
    res = {p: float(r) for p, r in c.execute(text("SELECT producto_id, porcentaje FROM ddmrp.reserva_cedi")).all()}
    return {"stock": stock, "reserva": res, "empresas": sorted({e for e, _ in stock})}


def regla_actual(c) -> int:
    v = c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'cedi_regla_reparto'")).scalar()
    return int(v) if v is not None else 1


def dias_alcance(c) -> list[int]:
    """DIAs de abastecimiento entre cuyas tiendas se reparte el CEDI. Vacio = todas las tiendas."""
    return [r[0] for r in c.execute(text("SELECT dia FROM ddmrp.reparto_dia ORDER BY dia")).all()]


def aplicar_a_ejecucion(c, eid: int) -> dict:
    """Reparte el inventario del CEDI de cada empresa entre las tiendas de ESA empresa, por referencia: todas las tiendas, o solo
    las de los DIAs elegidos (ddmrp.reparto_dia). Las tiendas fuera del alcance no compiten por el stock y quedan con lo que pide
    su buffer. Deja en sugerencias_envio: cantidad_necesaria (lo que pide el buffer), cantidad_sugerida (lo asignado) y stock_cedi
    (lo disponible de la referencia en el CEDI de su empresa: inventario menos la reserva; 0 si el CEDI no la tiene).
    Una empresa sin inventario del CEDI no se limita. Los laboratorios sin envio no compiten por el stock."""
    regla = regla_actual(c)
    c.execute(text("UPDATE ddmrp.sugerencias_envio SET cantidad_necesaria = cantidad_sugerida, stock_cedi = NULL WHERE ejecucion_id = :e"), {"e": eid})
    d = datos_cedi(c)
    if regla == 0 or not d["stock"]:
        return {"limitadas": 0, "regla": regla, "aplicado": False}
    dias = dias_alcance(c)
    filas = c.execute(text("SELECT s.empresa, s.producto_id, s.bodega_id, s.cantidad_sugerida::float8, s.unidad_despacho::float8, "
                           "COALESCE(s.pct_buffer::float8, 1e9), COALESCE(s.adu::float8, 0) FROM ddmrp.sugerencias_envio s "
                           "WHERE s.ejecucion_id = :e AND s.cantidad_sugerida > 0 AND NOT s.condenado AND s.empresa = ANY(CAST(:em AS text[])) "
                           "AND NOT EXISTS (SELECT 1 FROM ddmrp.maestro_item mi JOIN ddmrp.laboratorio_sin_envio ls ON ls.laboratorio = mi.categoria "
                           "                WHERE mi.producto_id = s.producto_id) "
                           f"AND {solo_activos('s')} "
                           "AND (cardinality(CAST(:d AS int[])) = 0 OR (s.empresa, s.bodega_id) IN (SELECT empresa, bodega_id FROM ddmrp.bodega_dia WHERE dia = ANY(CAST(:d AS int[]))))"),
                     {"e": eid, "d": dias, "em": d["empresas"]}).all()
    por_item: dict = {}
    for emp, prod, bod, q, ud, pct, adu in filas:
        por_item.setdefault((emp, prod), []).append((bod, q, ud, pct, adu))
    cambios = []
    for (emp, prod), grupo in por_item.items():
        util = float(max(0, math.floor(d["stock"].get((emp, prod), 0.0) * (1 - d["reserva"].get(prod, 0.0)) + EPS)))
        asign = repartir(grupo, util, regla)
        for bod, q, *_ in grupo:
            if asign[bod] + EPS < q:
                cambios.append((eid, emp, prod, bod, asign[bod]))
    # stock del CEDI de TODAS las filas de las empresas con inventario (tambien las de tiendas fuera del alcance o sin competir)
    c.execute(text("""UPDATE ddmrp.sugerencias_envio s
                      SET stock_cedi = GREATEST(0, FLOOR(COALESCE((SELECT ic.disponible FROM ddmrp.inventario_cedi ic
                                                                   WHERE ic.empresa = s.empresa AND ic.producto_id = s.producto_id), 0)
                                                         * (1 - COALESCE((SELECT r.porcentaje FROM ddmrp.reserva_cedi r WHERE r.producto_id = s.producto_id), 0)) + 1e-9))
                      WHERE s.ejecucion_id = :e AND s.empresa = ANY(CAST(:em AS text[]))"""), {"e": eid, "em": d["empresas"]})
    if cambios:
        c.execute(text("CREATE TEMP TABLE IF NOT EXISTS stg_asig (e bigint, em text, p text, b text, q numeric) ON COMMIT DROP"))
        c.execute(text("TRUNCATE stg_asig"))
        c.execute(text("INSERT INTO stg_asig VALUES (:e, :em, :p, :b, :q)"), [{"e": a, "em": em, "p": b, "b": x, "q": q} for a, em, b, x, q in cambios])
        c.execute(text("UPDATE ddmrp.sugerencias_envio s SET cantidad_sugerida = t.q FROM stg_asig t "
                       "WHERE s.ejecucion_id = t.e AND s.empresa = t.em AND s.producto_id = t.p AND s.bodega_id = t.b"))
    return {"limitadas": len(cambios), "items_sin_alcanzar": len({(x[1], x[2]) for x in cambios}), "regla": regla, "aplicado": True,
            "dias": dias, "tiendas_en_reparto": len({(f[0], f[2]) for f in filas}), "empresas": d["empresas"]}
