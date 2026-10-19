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
    h = [("B1", "P1", f[0], "ROJA", 3, -1, 10), ("B1", "P1", f[1], "VERDE", 9, 8, 120), ("B2", "P1", f[1], "EXCESO", 50, 50, 300)]
    r = mapa_calor.pivotear(f, [("B1", "P1"), ("B2", "P1")], h, "inventario")
    assert r[("B1", "P1")] == ([3.0, 9.0], "RV") and r[("B2", "P1")] == ([None, 50.0], " E")
    assert mapa_calor.pivotear(f, [("B1", "P1")], h, "pct_buffer")[("B1", "P1")][0] == [10.0, 120.0]
