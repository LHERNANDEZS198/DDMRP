"""Pruebas de las funciones puras (sin base de datos): REC, lanzamientos y mapa de calor. Correr: python -m pytest tests -q"""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import lanzamientos, mapa_calor, rec  # noqa: E402


def test_rec_pares_y_sin_original():
    items = [("190340", "CALENDULA SUSPENSION"), ("2190340", "REC CALENDULA SUSPENSION (ANTAX) X 360 m"),
             ("3555", "REC SIN ORIGINAL"), ("1500", "RECARGABLE PILA"), ("2100", "recubierto"), ("500", "REC. PUNTO")]
    pares, sin = rec.detectar_rec(items)
    assert pares == [("2190340", "190340", "REC CALENDULA SUSPENSION (ANTAX) X 360 m")] or ("2190340", "190340") in [(a, b) for a, b, _ in pares]
    assert "3555" in sin
    assert all(r != "1500" and r != "2100" for r, _, _ in pares)


def test_rec_cadena():
    pares, _ = rec.detectar_rec([("100", "X"), ("2100", "REC X"), ("32100", "REC REC X")])
    d = {a: b for a, b, _ in pares}
    assert d["2100"] == "100" and d["32100"] == "100"


def test_es_rec():
    assert rec.es_rec("REC ALGO") and rec.es_rec(" rec-algo") and not rec.es_rec("RECARGA") and not rec.es_rec(None)


def test_lanzamientos_base_primera_reingreso():
    d0 = date(2026, 10, 1)
    est, ev = lanzamientos.detectar_eventos({}, {"A": 10, "B": 0}, d0, base=True)
    assert ev == []                                           # la primera lectura es la base
    d1 = d0 + timedelta(days=1)
    est, ev = lanzamientos.detectar_eventos(est, {"A": 10, "B": 5, "C": 3}, d1, base=False)
    assert ("B", "PRIMERA", None, 5) in ev and ("C", "PRIMERA", None, 3) in ev and not any(e[0] == "A" for e in ev)
    d2 = d1 + timedelta(days=3)
    est, ev = lanzamientos.detectar_eventos(est, {"A": 0, "B": 5, "C": 3}, d2, base=False)   # A se agota
    assert ev == []
    d3 = d2 + timedelta(days=4)
    est, ev = lanzamientos.detectar_eventos(est, {"A": 7, "B": 5, "C": 3}, d3, base=False)   # A vuelve
    assert ev == [("A", "REINGRESO", 7, 7)]                   # ultima con stock fue d1, d3 = d1 + 7


def test_lanzamientos_negativo_es_cero():
    d0 = date(2026, 10, 1)
    est, _ = lanzamientos.detectar_eventos({}, {"A": -5}, d0, base=True)
    assert est["A"][0] == 0


def test_elegir_fechas():
    base = date(2026, 10, 1)
    disp = [base + timedelta(days=i) for i in range(30)]
    f = mapa_calor.elegir_fechas(disp, paso=5)
    assert f[-1] == disp[-1] and f == sorted(f) and all((b - a).days >= 5 for a, b in zip(f, f[1:]))
    assert len(mapa_calor.elegir_fechas(disp, paso=1, maximo=10)) == 10
    assert mapa_calor.elegir_fechas(disp, paso=1, maximo=10)[-1] == disp[-1]


def test_pivotear():
    f = [date(2026, 10, 1), date(2026, 10, 2)]
    h = [("05", "B1", "P1", f[0], "ROJA", 3, -1, 10), ("05", "B1", "P1", f[1], "VERDE", 9, 8, 120), ("21", "B1", "P1", f[1], "EXCESO", 50, 50, 300)]
    r = mapa_calor.pivotear(f, [("05", "B1", "P1"), ("21", "B1", "P1")], h, "inventario")   # misma tienda en las dos empresas: filas distintas
    assert r[("05", "B1", "P1")] == ([3.0, 9.0], "RV") and r[("21", "B1", "P1")] == ([None, 50.0], " E")
    assert mapa_calor.pivotear(f, [("05", "B1", "P1")], h, "pct_buffer")[("05", "B1", "P1")][0] == [10.0, 120.0]


def test_clasificacion_abc_xyz():
    from app import clasificacion as cl
    filas = []
    def fila(p, b, cant, valor, costo, inv=10, iv=0.3, adu=10, pm="202601"):
        filas.append({"producto_id": p, "bodega_id": b, "descripcion": p, "cant": cant, "valor": valor, "costo": costo, "inventario": inv, "iv": iv, "adu": adu, "primer_mes": pm})
    fila("P1", "T1", 100, 10000, 50)      # margen 5000
    fila("P1", "T2", 100, 10000, 50)      # P1 total 10000
    fila("P2", "T1", 50, 4000, 70)        # margen 500
    fila("P3", "T1", 10, 500, 80)         # margen -300 -> C
    fila("P4", "T1", 0, 0, 10)            # D
    fila("P5", "T1", 5, 300, 10, pm="202610")   # N
    fila("P6", "T1", 5, 300, None)        # S
    fila("P7", "T1", 40, 1000, 10, iv=0.9)  # margen 600 -> Z
    it = cl.agregar(filas, "item"); cl.calcular(it, 365); cl.clasificar(it, "margen", 80, 95, mes_nuevo="202608")
    d = {x["producto_id"]: x for x in it}
    assert d["P1"]["margen"] == 10000 and d["P1"]["abc"] == "A" and d["P1"]["puesto"] == 1
    assert d["P7"]["abc"] in ("B", "C") and d["P7"]["xyz"] == "Z" and d["P7"]["clase"] in ("BZ", "CZ")
    assert d["P3"]["abc"] == "C" and d["P4"]["abc"] == "D" and d["P5"]["abc"] == "N" and d["P6"]["abc"] == "S"
    assert d["P1"]["tiendas"] == 2 and d["P1"]["inventario"] == 20
    assert abs(d["P1"]["gmroi"] - 10000 / (20 * 50)) < 1e-9          # margen anual / inventario a costo
    m = cl.matriz(it); assert m["total"]["n"] == 7 and sum(c["n"] for c in m["celdas"]) == 7
    ti = cl.agregar(filas, "tienda_item"); cl.calcular(ti, 365); cl.clasificar(ti, "venta", 80, 95)
    assert len(ti) == 8 and next(x for x in ti if x["producto_id"] == "P6")["abc"] != "S"   # con criterio venta no hace falta el costo


def test_clasificacion_validaciones_y_cortes_iv():
    import pytest
    from app import clasificacion as cl
    assert cl.clase_xyz(0.49) == "X" and cl.clase_xyz(0.5) == "Y" and cl.clase_xyz(0.8) == "Y" and cl.clase_xyz(0.81) == "Z" and cl.clase_xyz(None) == "-"
    with pytest.raises(ValueError):
        cl.clasificar([], "margen", 95, 80)
    with pytest.raises(ValueError):
        cl.clasificar([], "otro")
    assert cl.mes_nuevo(date(2026, 10, 19), 3) == "202608" and cl.mes_nuevo(date(2026, 2, 1), 3) == "202512"


def test_diagnostico():
    from app import clasificacion as cl
    d = cl.diagnostico
    assert d({"zona": "ROJA", "abc": "A"}) == "prioridad" and d({"zona": "ROJA", "abc": "C"}) == "reponer" and d({"zona": "ROJA", "abc": "D"}) == "ok"
    assert d({"zona": "EXCESO", "abc": "A"}) == "exceso_clave" and d({"zona": "EXCESO", "abc": "C"}) == "exceso"
    assert d({"zona": "VERDE", "abc": "D", "inventario": 5}) == "dormido" and d({"zona": "VERDE", "abc": "D", "inventario": 0}) == "ok"
    assert d({"zona": "AMARILLA", "abc": "A"}) == "vigilar" and d({"zona": "VERDE", "abc": "A"}) == "ok"


def test_gmroi_con_inventario_promedio_y_retornos():
    from app import clasificacion as cl
    # P1: dos tiendas. T1 con historia (suma 3000 en 30 dias = promedio 100), T2 sin historia (cae al inventario de hoy = 20)
    filas = [
        {"producto_id": "P1", "bodega_id": "T1", "cant": 100, "valor": 10000, "costo": 50, "inventario": 5, "inv_suma": 3000, "dias_hist": 30, "dias_cero": 3, "iv": .3, "adu": 1},
        {"producto_id": "P1", "bodega_id": "T2", "cant": 100, "valor": 10000, "costo": 50, "inventario": 20, "iv": .3, "adu": 1},
    ]
    it = cl.agregar(filas, "item"); cl.calcular(it, 365); x = it[0]
    assert x["inv_prom"] == 120 and x["inventario"] == 25 and x["dias_hist"] == 30
    assert abs(x["pct_sin_stock"] - 10.0) < 1e-9                       # 3 de 30 dias-tienda con historia
    assert abs(x["gmroi"] - 10000 / (120 * 50)) < 1e-9                  # margen anual / inventario PROMEDIO a costo, no el de hoy
    assert abs(x["rotacion"] - (200 * 50) / (120 * 50)) < 1e-9
    assert abs(x["gmroi"] - x["rotacion"] * (x["margen"] / x["costo_venta"])) < 1e-9   # GMROI = rotacion x (margen/costo)
    # indicador anterior: meses de cobertura x margen %  -> 120 uds / (200 uds/12.0 meses...) 
    meses_cob = 120 / (200 / 365 * 30.4375)
    assert abs(x["cob_x_margen"] - meses_cob * 50.0) < 1e-6
    # el mismo GMROI con dos items de igual retorno pero distinta cobertura/margen: el indicador anterior los distingue, el GMROI no
    a = {"producto_id": "A", "bodega_id": "T", "cant": 120, "valor": 120 * 62.5, "costo": 50, "inventario": 10, "iv": .3, "adu": 1}      # cobertura 1 mes, margen 20 %
    b = {"producto_id": "B", "bodega_id": "T", "cant": 120, "valor": 120 * 200, "costo": 50, "inventario": 60, "iv": .3, "adu": 1}      # cobertura 6 meses, margen 75 %
    ai, bi = cl.agregar([a], "item")[0], cl.agregar([b], "item")[0]
    cl.calcular([ai, bi], 365 * 1)
    # agregados: se calculan sobre sumas en pesos
    agg = {"margen_anual": 300.0, "costo_venta_anual": 600.0, "inv_prom_costo": 100.0}; cl.retornos(agg)
    assert agg["gmroi"] == 3.0 and agg["rotacion"] == 6.0
    z = {"margen_anual": 1.0, "costo_venta_anual": 1.0, "inv_prom_costo": 0.0}; cl.retornos(z); assert z["gmroi"] is None
    # sin historia en ninguna tienda: el promedio es el inventario de hoy
    s = cl.agregar([{"producto_id": "S", "bodega_id": "T", "cant": 10, "valor": 1000, "costo": 10, "inventario": 7, "iv": .3, "adu": 1}], "item"); cl.calcular(s, 365)
    assert s[0]["inv_prom"] == 7 and s[0]["dias_hist"] == 0 and s[0]["pct_sin_stock"] is None
