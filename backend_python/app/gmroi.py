"""Analisis de GMROI para compras (funciones puras, sin base de datos, para poder probarlas).
Parte de los items que ya calcula la Clasificacion (app/clasificacion.py: margen, margen anualizado, inventario promedio a costo, gmroi...) y agrega lo que compras
necesita para decidir: en que banda esta cada item (segun el minimo y la meta de Reglas de compras), cuanto capital hay en cada banda, cuanto inventario sobra para
llegar a la meta con el mismo margen y los agregados por grupo. Todo se calcula sobre sumas en pesos (nunca promediando GMROI de items).
  GMROI = margen anualizado / inventario promedio a costo  =  margen % x (venta anual / inventario promedio a costo)"""
from . import clasificacion as cl

ORDEN_BANDAS = ("bajo", "medio", "alto", "sin_venta", "sin_inv", "sin_costo")
ETIQUETAS = {"bajo": "GMROI bajo", "medio": "GMROI medio", "alto": "GMROI en meta o más", "sin_venta": "Sin venta con inventario",
             "sin_inv": "Vendió sin inventario promedio", "sin_costo": "Sin costo conocido"}


def banda(it: dict, minimo: float, meta: float) -> str:
    """bajo < minimo <= medio < meta <= alto; aparte: sin venta (capital dormido), sin inventario promedio y sin costo (no se puede medir)."""
    if it.get("costo") is None:
        return "sin_costo"
    if (it.get("cant") or 0) <= 0 and (it.get("valor") or 0) <= 0:
        return "sin_venta"
    if not (it.get("inv_prom_costo") or 0) > 0:
        return "sin_inv"
    g = it["gmroi"]
    return "bajo" if g < minimo else "medio" if g < meta else "alto"


def enriquecer(items: list[dict], dias: int, minimo: float, meta: float) -> None:
    """Agrega a cada item (ya pasado por clasificacion.calcular): banda, rot (venta anual / inventario promedio a costo), meses_inv y capital_exceso =
    inventario promedio a costo que sobra para llegar al GMROI meta con el mismo margen (todo si no hay margen). Es una referencia, no una orden de compra."""
    factor = 365.0 / max(dias, 1)
    meta = meta if meta > 0 else 1.0
    for it in items:
        ip = it.get("inv_prom_costo") or 0.0
        it["banda"] = banda(it, minimo, meta)
        it["rot"] = None if ip <= 0 else (it.get("valor") or 0.0) * factor / ip
        cv = it.get("costo_venta_anual")
        it["meses_inv"] = None if not cv or cv <= 0 else ip / (cv / 12.0)
        ma = it.get("margen_anual")
        it["capital_exceso"] = 0.0 if ma is None or ip <= 0 else max(0.0, ip - max(ma, 0.0) / meta)


def agregar(items: list[dict]) -> dict:
    """Totales de un conjunto de items con GMROI y meses de inventario recalculados sobre las sumas."""
    x = {"n": 0, "venta": 0.0, "margen": 0.0, "margen_anual": 0.0, "costo_venta_anual": 0.0, "inv_costo": 0.0, "inv_prom_costo": 0.0, "capital_exceso": 0.0, "n_bajo": 0, "n_sin_venta": 0}
    for it in items:
        x["n"] += 1
        x["venta"] += it.get("valor") or 0.0
        x["margen"] += it.get("margen") or 0.0
        x["margen_anual"] += it.get("margen_anual") or 0.0
        x["costo_venta_anual"] += it.get("costo_venta_anual") or 0.0
        x["inv_costo"] += it.get("inv_costo") or 0.0
        x["inv_prom_costo"] += it.get("inv_prom_costo") or 0.0
        x["capital_exceso"] += it.get("capital_exceso") or 0.0
        x["n_bajo"] += it.get("banda") == "bajo"
        x["n_sin_venta"] += it.get("banda") == "sin_venta"
    x["margen_pct"] = None if x["venta"] <= 0 else 100.0 * x["margen"] / x["venta"]
    cl.retornos(x)
    return x


def por_banda(items: list[dict]) -> list[dict]:
    total = sum(it.get("inv_prom_costo") or 0.0 for it in items)
    out = []
    for b in ORDEN_BANDAS:
        sub = [it for it in items if it.get("banda") == b]
        if not sub:
            continue
        a = agregar(sub)
        a.update(banda=b, etiqueta=ETIQUETAS[b], pct_capital=None if total <= 0 else 100.0 * a["inv_prom_costo"] / total)
        out.append(a)
    return out


def por_grupo(items: list[dict], clave, nombre) -> list[dict]:
    """Una fila por grupo (laboratorio, valor de un criterio...): `clave(item)` agrupa y `nombre(clave)` da la etiqueta. Orden: mas capital primero."""
    miembros: dict[str, list[dict]] = {}
    for it in items:
        miembros.setdefault(clave(it), []).append(it)
    total = sum(it.get("inv_prom_costo") or 0.0 for it in items)
    out = []
    for k, sub in miembros.items():
        a = agregar(sub)
        a.update(id=k, nombre=nombre(k), pct_capital=None if total <= 0 else 100.0 * a["inv_prom_costo"] / total)
        out.append(a)
    out.sort(key=lambda g: (-g["inv_prom_costo"], g["nombre"]))
    return out


def puntos(items: list[dict], tope: int = 800) -> list[dict]:
    """Los items que mas capital tienen y se pueden ubicar (margen % y rotacion): alimentan el grafico de dispersion."""
    cand = [it for it in items if it.get("gmroi") is not None and it.get("rot") is not None and it.get("margen_pct") is not None]
    cand.sort(key=lambda it: -(it.get("inv_prom_costo") or 0.0))
    return [{"id": it["producto_id"], "d": it.get("descripcion"), "x": it["rot"], "y": it["margen_pct"], "inv": it["inv_prom_costo"], "g": it["gmroi"], "b": it["banda"]} for it in cand[:tope]]


def unir_series(periodos: list[str], dias: dict[str, int], ventas: dict, inv: dict, otif: dict) -> list[dict]:
    """Una fila por mes con todos los indicadores. ventas[mes] = {venta, margen, costo_venta}; inv[mes] = {inv_costo, roja, ag, dz}; otif[mes] = {infull, ontime, otif, lineas} (otif = a tiempo Y completo en la misma linea).
    GMROI del mes = margen del mes anualizado (x 365 / dias del mes) / inventario promedio a costo del mes; abastecimiento = 1 - dias en roja / dias con zona
    (fuera de riesgo de agotarse); agot = dias agotados (con buffer e inventario 0) / dias con zona (la linea punteada del Control). Sin dato de un indicador en un mes queda None, nunca 0."""
    out = []
    for p in periodos:
        v, i, o = ventas.get(p) or {}, inv.get(p) or {}, otif.get(p) or {}
        f = 365.0 / max(dias.get(p, 30), 1)
        ic, mg, cv = i.get("inv_costo"), v.get("margen"), v.get("costo_venta")
        venta = v.get("venta")
        dz = i.get("dz") or 0
        out.append({"periodo": p, "venta": venta, "margen": mg, "margen_pct": None if not venta or mg is None else 100.0 * mg / venta,
                    "inv_costo": ic, "gmroi": None if not ic or ic <= 0 or mg is None else mg * f / ic,
                    "meses_inv": None if not ic or not cv or cv <= 0 else ic / (cv * f / 12.0),
                    "abast": None if dz <= 0 else 1.0 - float(i.get("roja") or 0) / dz,
                    "agot": None if dz <= 0 else float(i.get("ag") or 0) / dz,
                    "infull": o.get("infull"), "ontime": o.get("ontime"), "otif": o.get("otif"), "lineas_otif": o.get("lineas") or 0})
    return out
