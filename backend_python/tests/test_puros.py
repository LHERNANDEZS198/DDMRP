"""Pruebas de las funciones puras (sin base de datos): REC, lanzamientos y mapa de calor. Correr: python -m pytest tests -q"""
import sys
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import apertura_calc, clase_tienda, lanzamientos, mapa_calor, rec, reparto  # noqa: E402


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
    assert abs(x["rotacion"] - 200 / 365 * 30.4375) < 1e-9               # unidades vendidas por mes
    assert abs(x["inv_prom"] / x["rotacion"] - 120 / (200 / 365 * 30.4375)) < 1e-9   # meses de cobertura
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
    assert agg["gmroi"] == 3.0 and agg["meses_inv"] == 2.0           # 100 de inventario con 50 de costo de venta al mes
    z = {"margen_anual": 1.0, "costo_venta_anual": 1.0, "inv_prom_costo": 0.0}; cl.retornos(z); assert z["gmroi"] is None and z["meses_inv"] == 0.0   # sin inventario promedio: GMROI indefinido, 0 meses de stock
    # sin historia en ninguna tienda: el promedio es el inventario de hoy
    s = cl.agregar([{"producto_id": "S", "bodega_id": "T", "cant": 10, "valor": 1000, "costo": 10, "inventario": 7, "iv": .3, "adu": 1}], "item"); cl.calcular(s, 365)
    assert s[0]["inv_prom"] == 7 and s[0]["dias_hist"] == 0 and s[0]["pct_sin_stock"] is None


def test_clasificar_por_percentil_con_infaltables():
    from app import clasificacion as cl
    items = [{"producto_id": f"P{i:02d}", "cant": 1, "valor": 100.0 - i, "margen": 100.0 - i, "costo": 1.0, "costo_venta": 1.0, "iv": 0.1, "primer_mes": "202001"} for i in range(21)]
    cl.clasificar(items, "margen", 75, 50, None, (0.5, 0.8), "percentil", 93)
    por = {}
    for it in sorted(items, key=lambda x: x["puesto"]):
        por.setdefault(it["abc"], []).append(it["puesto"])
    assert por["I"] == [1, 2]                 # percentil 100 y 95 (>= 93); el 3.o ya cae en 90 -> A
    assert set(por) == {"I", "A", "B", "C"}
    assert max(por["I"]) < min(por["A"]) < min(por["B"]) < min(por["C"])
    assert items[0]["clase"].startswith("I")


def test_apertura_meses():
    assert apertura_calc.sumar_meses("202611", 1) == "202612" and apertura_calc.sumar_meses("202601", -1) == "202512"
    assert apertura_calc.meses_entre("202610", "202610") == 1 and apertura_calc.meses_entre("202508", "202611") == 16
    assert apertura_calc.meses_entre("202611", "202610") == 0


def test_apertura_ventana_base():
    hoy = date(2026, 11, 3)
    # espejo con historia larga: los 6 meses cerrados anteriores al mes en curso
    assert apertura_calc.ventana_base("202401", hoy, 6) == ("202605", "202610", 6)
    # espejo que abrio hace 3 meses y medio: solo cuentan sus meses cerrados (sin los meses previos a su primera venta)
    assert apertura_calc.ventana_base("202608", hoy, 6) == ("202608", "202610", 3)
    # espejo que abrio este mes: ningun mes cerrado
    assert apertura_calc.ventana_base("202611", hoy, 6)[2] == 0
    assert apertura_calc.ventana_base(None, hoy, 3) == ("202608", "202610", 3)


def test_apertura_fin_y_restan():
    assert apertura_calc.fin_espejo("202611", 4) == "202702"      # primer mes de venta nov-26 + 4 meses con pronostico: ultimo mes feb-27
    assert apertura_calc.fin_espejo("202611", 1) == "202611"
    assert apertura_calc.fin_espejo(None, 4) is None
    assert apertura_calc.restan_espejo(0, 4) == 4                  # sin ventas aun: todos
    assert apertura_calc.restan_espejo(1, 4) == 4                  # el mes en curso cuenta
    assert apertura_calc.restan_espejo(4, 4) == 1
    assert apertura_calc.restan_espejo(5, 4) == 0


def test_apertura_pronostico_y_meses_con_venta():
    assert apertura_calc.pronostico_propuesto(10.2, 1.0) == 11.0 and apertura_calc.pronostico_propuesto(10.0, 0.8) == 8.0
    assert apertura_calc.pronostico_propuesto(0.2, 1.0) == 1.0           # minimo 1 si la espejo vende algo
    assert apertura_calc.pronostico_propuesto(0.0, 1.0) == 0.0 and apertura_calc.pronostico_propuesto(5, 0) == 0.0
    # como lo cuenta el motor: del mes de la primera venta al mes en curso, ambos incluidos
    assert apertura_calc.meses_con_venta("202611", date(2026, 11, 3)) == 1 and apertura_calc.meses_con_venta("202609", date(2026, 11, 3)) == 3
    assert apertura_calc.meses_con_venta(None, date(2026, 11, 3)) == 0


def test_clase_tienda_abc():
    r = clase_tienda.clasificar([("T1", 700), ("T2", 150), ("T3", 100), ("T4", 40), ("T5", 10), ("T6", 0)], 80, 95)
    assert [r[k][0] for k in ("T1", "T2", "T3", "T4", "T5", "T6")] == ["A", "A", "B", "C", "C", "C"]   # T2 empieza en 70 % (< 80): entra en A
    assert r["T6"][1] == 0 and abs(r["T5"][2] - 100.0) < 1e-6
    assert clase_tienda.clasificar([("X", 0), ("Y", 0)])["X"][0] == "C"                                  # sin ventas: todas C
    assert clase_tienda.clasificar([("B1", 5), ("A1", 5)], 50, 90)["A1"][0] == "A"                       # empate de venta: por codigo


def test_reparto_desempate_y_regla_clase():
    # dos tiendas con el mismo ADU y mismo % de buffer: 3 bloques de 1, alcanzan 3 de 4 pedidos
    filas = [("T_C", 2, 1, 50, 10, "C"), ("T_A", 2, 1, 50, 10, "A")]
    a = reparto.repartir(filas, 3, 1)
    assert a["T_A"] == 2 and a["T_C"] == 1                          # el sobrante va a la A, no a la de codigo menor
    a = reparto.repartir([("T1", 5, 1, 50, 10, "C"), ("T2", 5, 1, 50, 10, "A")], 5, 3)
    assert a["T2"] == 5 and a["T1"] == 0                            # regla 3, mismo % de buffer: gana la A
    # regla 5: toda la A antes que la B y la C; lo que sobra baja a la siguiente clase
    filas = [("A1", 6, 1, 90, 5, "A"), ("B1", 6, 1, 10, 50, "B"), ("C1", 6, 1, 0, 80, "C")]
    a = reparto.repartir(filas, 8, 5)
    assert a == {"A1": 6, "B1": 2, "C1": 0}
    a = reparto.repartir(filas, 20, 5)
    assert a == {"A1": 6, "B1": 6, "C1": 6} or sum(a.values()) == 18   # cabe todo: cada una lo que pide
    a = reparto.repartir([("A1", 4, 1, 1, 1, "A"), ("A2", 4, 1, 1, 3, "A")], 4, 5)
    assert a["A2"] == 3 and a["A1"] == 1                            # dentro de la clase: proporcional a la rotacion


# ---- reportes de compras ----
def test_otif_a_tiempo_y_completa():
    from app.etl.reportes_compras import calcular_otif
    f = lambda **k: ("OC-1", "A", "9", "P", k.get("oc", date(2026, 1, 1)), k.get("pact", date(2026, 1, 10)), k.get("ped", 100), k.get("ent", 100), k.get("ult", date(2026, 1, 10)))
    assert calcular_otif(f(), 0, .98, True) == ("202601", 1, 1)
    assert calcular_otif(f(ult=date(2026, 1, 12)), 0, .98, True)[1] == 0          # tarde
    assert calcular_otif(f(ult=date(2026, 1, 12)), 2, .98, True)[1] == 1          # con 2 dias de gracia
    assert calcular_otif(f(ent=97), 0, .98, True)[2] == 0 and calcular_otif(f(ent=98), 0, .98, True)[2] == 1
    assert calcular_otif(f(ult=None), 0, .98, True) is None                       # sin entrada no mide
    assert calcular_otif(f(oc=date(2026, 1, 10), ult=date(2026, 1, 10)), 0, .98, True) is None   # regularizacion
    assert calcular_otif(f(oc=date(2026, 1, 10), ult=date(2026, 1, 10)), 0, .98, False) is not None


def test_sql_reportes_y_parametros():
    import re
    from app.etl.reportes_compras import _sql
    for n in ("rep_ventas_siesa.sql", "rep_compras_siesa.sql", "rep_otif_siesa.sql"):
        q = _sql(n)
        assert q and not q.lstrip().startswith("--")
    c = _sql("rep_compras_siesa.sql")
    assert re.findall(r":(\w+)", c) == ["desde", "hasta", "desde", "hasta"]         # el orden de los ? depende de esto
    assert set(re.findall(r":(\w+)", _sql("rep_ventas_siesa.sql"))) == {"cia", "periodo_desde"}
    assert set(re.findall(r":(\w+)", _sql("rep_otif_siesa.sql"))) == {"cia", "desde"}


def test_filtros_reporte_sql():
    from app.routers import reportes_compras as r
    r.cfg_rep = lambda: {"rep_plan_categoria": 1, "rep_plan_accion": 3}
    r._labs_permitidos = lambda u: ["L1"]
    f = r.Filtros({"id": "x"}, "05", "202601", "202612", "A,B", "0002", None, "SUR", "ab", None)
    j, w, p = f.base("ddmrp.rep_venta_mes", con_un=True)
    assert p["plan_cat"] == "001" and p["plan_acc"] == "003" and p["labs"] == ["A", "B"] and p["cats"] == ["0002"] and p["un"] == ["SUR"] and p["perm"] == ["L1"]
    assert "x.periodo >= :desde" in w and "x.unidad_negocio = ANY(:un)" in w and "FROM ddmrp.rep_venta_mes x" in j
    _, w2, p2 = f.base("ddmrp.rep_compra_mes")
    assert "unidad_negocio" not in w2 and "un" not in p2
    try:
        r.Filtros({"id": "x"}, desde="2026")
        assert False
    except Exception as e:
        assert getattr(e, "status_code", 0) == 400


def test_filtros_reporte_criterios_de_items():
    from app.routers import reportes_compras as r
    r.cfg_rep = lambda: {"rep_plan_categoria": 1, "rep_plan_accion": 3}
    r._labs_permitidos = lambda u: None
    f = r.Filtros({"id": "x"}, crit="007:A,007:B,009:Z,sinplan")
    _, w, p = f.base("ddmrp.rep_venta_mes")
    assert f.crit == {"007": ["A", "B"], "009": ["Z"]}                       # mismo plan = O (lista), planes distintos = Y (un EXISTS por plan)
    assert w.count("EXISTS") == 2 and p["cp0"] == "007" and p["cc0"] == ["A", "B"] and p["cp1"] == "009" and p["cc1"] == ["Z"]
    assert "x.producto_id" in w and "perm" not in p


def _item_gmroi(pid, cant, valor, costo, inv_prom, lab="L1"):
    return {"producto_id": pid, "empresa": "05", "laboratorio": lab, "cant": cant, "valor": valor, "costo": costo, "inventario": inv_prom, "inv_prom": inv_prom}


def test_gmroi_bandas_y_capital():
    from app import clasificacion as cl, gmroi as gm
    items = [_item_gmroi("A", 100, 1000, 5, 50), _item_gmroi("B", 10, 60, 5, 20), _item_gmroi("C", 0, 0, 5, 10), _item_gmroi("D", 5, 50, None, 3),
             _item_gmroi("E", 10, 100, 4, 0), _item_gmroi("F", 100, 1000, 5, 10, "L2")]
    cl.calcular(items, 365)
    gm.enriquecer(items, 365, 1.0, 3.2)
    por = {i["producto_id"]: i for i in items}
    assert {k: v["banda"] for k, v in por.items()} == {"A": "medio", "B": "bajo", "C": "sin_venta", "D": "sin_costo", "E": "sin_inv", "F": "alto"}
    assert por["A"]["gmroi"] == 2.0 and por["A"]["rot"] == 4.0 and abs(por["A"]["meses_inv"] - 6.0) < 1e-9
    assert abs(por["A"]["capital_exceso"] - (250 - 500 / 3.2)) < 1e-9 and abs(por["C"]["capital_exceso"] - 50) < 1e-9 and por["D"]["capital_exceso"] == 0.0
    t = gm.agregar([por["A"], por["B"], por["C"], por["F"]])
    assert t["n"] == 4 and t["inv_prom_costo"] == 450 and abs(t["gmroi"] - 1010 / 450) < 1e-9 and t["n_bajo"] == 1 and t["n_sin_venta"] == 1      # GMROI sobre sumas, no promedio de items
    b = {x["banda"]: x for x in gm.por_banda(items)}
    assert list(b) == ["bajo", "medio", "alto", "sin_venta", "sin_inv", "sin_costo"] and abs(sum(x["pct_capital"] for x in b.values()) - 100) < 1e-9
    g = gm.por_grupo(items, lambda it: it["laboratorio"], lambda k: k.lower())
    assert [x["id"] for x in g] == ["L1", "L2"] and g[0]["nombre"] == "l1" and g[1]["gmroi"] == 10
    p = gm.puntos(items)
    assert {x["id"] for x in p} == {"A", "B", "F"} and p[0]["id"] == "A"       # solo los que se pueden ubicar, el de mas capital primero


def test_gmroi_serie_mensual():
    from app import gmroi as gm
    ps = ["202610", "202611", "202612"]
    ven = {"202610": {"venta": 1000.0, "margen": 400.0, "costo_venta": 600.0}, "202611": {"venta": 0.0, "margen": 0.0, "costo_venta": 0.0}}
    inv = {"202610": {"inv_costo": 1000.0, "roja": 30.0, "dz": 300.0}, "202611": {"inv_costo": 0.0, "roja": None, "dz": None}}
    ot = {"202610": {"infull": 0.9, "ontime": 0.5, "otif": 0.45, "lineas": 12}}
    s = {x["periodo"]: x for x in gm.unir_series(ps, {"202610": 31, "202611": 30, "202612": 31}, ven, inv, ot)}
    a = s["202610"]
    assert abs(a["gmroi"] - 400.0 * (365 / 31) / 1000.0) < 1e-9 and abs(a["abast"] - 0.9) < 1e-9 and a["margen_pct"] == 40.0 and a["infull"] == 0.9 and a["otif"] == 0.45 and a["lineas_otif"] == 12
    assert abs(a["meses_inv"] - 1000.0 / (600.0 * (365 / 31) / 12.0)) < 1e-9
    assert s["202611"]["gmroi"] is None and s["202611"]["abast"] is None and s["202611"]["margen_pct"] is None       # sin inventario o sin dato: vacio, no cero
    assert s["202612"]["gmroi"] is None and s["202612"]["infull"] is None and s["202612"]["lineas_otif"] == 0
