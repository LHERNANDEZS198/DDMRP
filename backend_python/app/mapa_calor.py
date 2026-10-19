"""Mapa de calor item x tienda x fecha (como el Excel de control): cada celda lleva el color de la zona del buffer ese dia y un numero
(inventario, flujo neto o % de buffer). Funciones puras para poder probarlas sin base de datos."""
from datetime import date

METRICAS = {"inventario": "Inventario (unidades)", "flujo_neto": "Flujo neto (unidades)", "pct_buffer": "% de buffer"}
ZONA_LETRA = {"ROJA": "R", "AMARILLA": "A", "VERDE": "V", "EXCESO": "E"}
MAX_COLUMNAS = 120


def elegir_fechas(disponibles: list[date], paso: int = 1, maximo: int = MAX_COLUMNAS) -> list[date]:
    """De las fechas con foto guardada: la mas reciente y, hacia atras, una cada `paso` dias como minimo (paso 5 = el Excel de ejemplo).
    Devuelve a lo sumo `maximo` fechas, de la mas antigua a la mas reciente."""
    paso = max(int(paso), 1)
    elegidas: list[date] = []
    for d in sorted(set(disponibles), reverse=True):
        if not elegidas or (elegidas[-1] - d).days >= paso:
            elegidas.append(d)
        if len(elegidas) >= maximo:
            break
    return sorted(elegidas)


def pivotear(fechas: list[date], combos: list[tuple[str, str]], historia, metrica: str = "inventario") -> dict:
    """combos = [(bodega, producto)] en el orden de salida; historia = filas (bodega, producto, fecha, zona, inventario, flujo_neto, pct_buffer).
    Devuelve {(bodega, producto): (valores, zonas)}: valores = lista (None si ese dia no hubo foto), zonas = texto de una letra por fecha
    (R/A/V/E, espacio = sin foto)."""
    if metrica not in METRICAS:
        raise ValueError(f"metrica debe ser una de {list(METRICAS)}")
    col = {"inventario": 4, "flujo_neto": 5, "pct_buffer": 6}[metrica]
    idx = {f: i for i, f in enumerate(fechas)}
    n = len(fechas)
    vals = {c: [None] * n for c in combos}
    zon = {c: [" "] * n for c in combos}
    for r in historia:
        c = (r[0], r[1])
        i = idx.get(r[2])
        if i is None or c not in vals:
            continue
        v = r[col]
        vals[c][i] = None if v is None else float(v)
        zon[c][i] = ZONA_LETRA.get(str(r[3]), " ")
    return {c: (vals[c], "".join(zon[c])) for c in combos}


def redondear(v: float | None, metrica: str) -> int | float | None:
    """Numero que se muestra en la celda: enteros (las unidades de inventario casi siempre lo son)."""
    if v is None:
        return None
    return int(round(v))
