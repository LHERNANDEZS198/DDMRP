"""Calculos puros de la apertura de tienda (meses, ventana de promedio, redondeo del pronostico). Sin base de datos: tienen prueba en tests/test_puros.py."""
import math
from datetime import date


def mes_de(d: date) -> str:
    return f"{d.year:04d}{d.month:02d}"


def sumar_meses(mes: str, n: int) -> str:
    """'202611' + n meses -> 'YYYYMM'."""
    t = int(mes[:4]) * 12 + (int(mes[4:6]) - 1) + n
    return f"{t // 12:04d}{t % 12 + 1:02d}"


def meses_entre(desde: str, hasta: str) -> int:
    """Meses calendario entre dos YYYYMM, ambos incluidos (0 si desde es posterior a hasta)."""
    d = (int(hasta[:4]) * 12 + int(hasta[4:6])) - (int(desde[:4]) * 12 + int(desde[4:6])) + 1
    return max(d, 0)


def ventana_base(inicio: str | None, hoy: date, base_meses: int) -> tuple[str, str, int]:
    """Meses CERRADOS sobre los que se promedia la venta de la espejo: los `base_meses` anteriores al mes en curso, sin contar los meses previos a su primera venta.
    Devuelve (desde, hasta, n); n = 0 si la espejo aun no tiene ningun mes cerrado con venta."""
    hasta = sumar_meses(mes_de(hoy), -1)
    desde = sumar_meses(hasta, -(max(base_meses, 1) - 1))
    if inicio and inicio > desde:
        desde = inicio
    return desde, hasta, meses_entre(desde, hasta)


def pronostico_propuesto(base: float, factor: float) -> float:
    """Base mensual x factor, redondeada hacia arriba a unidades enteras (minimo 1 si hay base)."""
    if base <= 0 or factor <= 0:
        return 0.0
    return float(max(1, math.ceil(round(base * factor, 6))))


def meses_con_venta(inicio: str | None, hoy: date) -> int:
    """Meses de venta de la tienda como los cuenta el motor: desde el mes de su primera venta hasta el mes en curso (el mes de apertura cuenta completo)."""
    return meses_entre(inicio, mes_de(hoy)) if inicio else 0
