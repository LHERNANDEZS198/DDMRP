"""Clasificacion de items ABC x XYZ sobre la venta de una ventana de meses. Funciones puras (sin base de datos) para poder probarlas.

ABC: ordena por el criterio elegido (margen bruto $ por defecto) y acumula su porcentaje: A = lo que junta hasta el corte A (80 %),
     B = hasta el corte B (95 %), C = el resto. El item que cruza el corte se queda en la clase mejor. Lo que no suma (margen <= 0) es C.
Apartes (no entran al ranking, para no ensuciarlo): D = sin venta en las tiendas en la ventana (la venta del CEDI a wholesale/digital no cuenta), N = primera venta en los ultimos meses (producto nuevo, aun sin historia),
     S = sin costo conocido (solo si el criterio usa el costo).
XYZ: por el indice de variabilidad (IV) que ya calcula el motor: X = baja, Y = media, Z = alta (cortes de la tabla de factores VAR: 0.5 y 0.8).
     A nivel item el IV es el de sus tiendas ponderado por la venta diaria (ADU).
Margen = venta neta sin IVA - unidades x costo promedio actual (Siesa, por instalacion). GMROI = margen anualizado / inventario PROMEDIO a costo (promedio de los dias de la ventana que guarda inventario_mes; sin historia, el inventario de hoy)."""
from datetime import date

CRITERIOS = {"margen": "Margen bruto $", "venta": "Venta neta $ (sin IVA)", "costo": "Consumo a costo $"}
NIVELES = {"item": "Item (suma de las tiendas filtradas)", "tienda_item": "Tienda × item"}
APARTE = ("D", "N", "S")
ORDEN_ABC = ("I", "A", "B", "C", "N", "D", "S")   # I = Infaltables (solo con el metodo por percentil)
ORDEN_XYZ = ("X", "Y", "Z", "-")


def _f(v) -> float:
    return float(v) if v is not None else 0.0


def agregar(filas: list[dict], nivel: str) -> list[dict]:
    """filas = una por tienda x item (cant, valor, primer_mes, inventario, adu, iv, costo ...). Nivel item: suma las tiendas."""
    if nivel not in NIVELES:
        raise ValueError(f"nivel debe ser uno de {list(NIVELES)}")
    grupos: dict[tuple, dict] = {}
    for r in filas:
        k = (r.get("empresa"), r["bodega_id"], r["producto_id"]) if nivel == "tienda_item" else (r["producto_id"],)
        g = grupos.get(k)
        if g is None:
            g = grupos[k] = {"producto_id": r["producto_id"], "empresa": r.get("empresa") if nivel == "tienda_item" else None, "bodega_id": r["bodega_id"] if nivel == "tienda_item" else None,
                             "bodega_nombre": r.get("bodega_nombre") if nivel == "tienda_item" else None,
                             "descripcion": r.get("descripcion"), "laboratorio": r.get("laboratorio"), "costo": r.get("costo"),
                             "cant": 0.0, "valor": 0.0, "inventario": 0.0, "inv_prom": 0.0, "dias_hist": 0, "_dias_tot": 0, "_dias_cero": 0, "adu": 0.0, "primer_mes": None, "tiendas": 0,
                             "_iv_pond": 0.0, "_iv_sum": 0.0, "_iv_n": 0}
            if nivel == "tienda_item":      # estado del buffer: solo tiene sentido por tienda
                for c in ("zona", "pct_buffer", "flujo_neto", "sugerido"):
                    g[c] = r.get(c)
        g["cant"] += _f(r.get("cant")); g["valor"] += _f(r.get("valor")); g["inventario"] += max(_f(r.get("inventario")), 0.0)
        dh = int(r.get("dias_hist") or 0)       # inventario promedio de la ventana (suma de las tiendas); sin historia de esa tienda, su inventario de hoy
        g["inv_prom"] += (_f(r.get("inv_suma")) / dh) if dh > 0 else max(_f(r.get("inventario")), 0.0)
        g["dias_hist"] = max(g["dias_hist"], dh); g["_dias_tot"] += dh; g["_dias_cero"] += int(r.get("dias_cero") or 0)
        g["adu"] += _f(r.get("adu")); g["tiendas"] += 1
        pm = r.get("primer_mes")
        if pm and (g["primer_mes"] is None or pm < g["primer_mes"]):
            g["primer_mes"] = pm
        if r.get("iv") is not None:
            g["_iv_pond"] += _f(r["iv"]) * _f(r.get("adu")); g["_iv_sum"] += _f(r["iv"]); g["_iv_n"] += 1
        if g["costo"] is None and r.get("costo") is not None:
            g["costo"] = r["costo"]
    out = []
    for g in grupos.values():
        n = g.pop("_iv_n"); pond = g.pop("_iv_pond"); suma = g.pop("_iv_sum")
        dt = g.pop("_dias_tot"); dc = g.pop("_dias_cero")
        g["pct_sin_stock"] = None if dt == 0 else 100.0 * dc / dt     # % de los dias-tienda de la ventana con inventario 0 (solo donde hay historia)
        g["iv"] = None if n == 0 else (pond / g["adu"] if g["adu"] > 0 else suma / n)
        out.append(g)
    return out


def calcular(items: list[dict], dias: int) -> None:
    """Agrega a cada item: costo_venta, margen, margen_pct, inv_costo (hoy), inv_prom_costo (promedio de la ventana), gmroi, rotacion, dias_inv y
    cob_x_margen. `dias` = largo de la ventana (anualiza). GMROI = margen anual / inventario promedio a costo; rotacion = unidades vendidas por mes (promedio de la ventana; es la que usa cob_x_margen); costo de venta anual /
    inventario promedio a costo (veces al año). Sin historia de inventario el promedio es el inventario de hoy (dias_hist = 0)."""
    factor = 365.0 / max(dias, 1)
    for it in items:
        c = it.get("costo")
        c = None if c is None else float(c)
        it["costo"] = c
        it["costo_venta"] = None if c is None else it["cant"] * c
        it["margen"] = None if c is None else it["valor"] - it["costo_venta"]
        it["margen_pct"] = None if it["margen"] is None or it["valor"] <= 0 else 100.0 * it["margen"] / it["valor"]
        it["inv_costo"] = None if c is None else it["inventario"] * c
        ip = it.get("inv_prom", it["inventario"])
        it["inv_prom"] = ip
        it["inv_prom_costo"] = None if c is None else ip * c
        it["margen_anual"] = None if it["margen"] is None else it["margen"] * factor
        it["costo_venta_anual"] = None if it["costo_venta"] is None else it["costo_venta"] * factor
        it["gmroi"] = None if it["margen_anual"] is None or not it["inv_prom_costo"] else it["margen_anual"] / it["inv_prom_costo"]
        diario = it["cant"] / max(dias, 1)
        it["rotacion"] = diario * 30.4375            # unidades vendidas por mes (promedio de la ventana)
        it["dias_inv"] = None if diario <= 0 else ip / diario
        # indicador anterior (lo que se calculaba a mano): meses de cobertura (inv. promedio en uds / venta mensual en uds) x margen %. No es un retorno: no comparar con el GMROI
        it["cob_x_margen"] = None if diario <= 0 or it["margen_pct"] is None else (ip / it["rotacion"]) * it["margen_pct"]


DIAGNOSTICOS = {   # clave: (etiqueta, color, que hacer)
    "prioridad": ("Importante en rojo", "#c62828", "Item A o B con el buffer en rojo: reponer primero"),
    "reponer": ("En rojo", "#ef6c00", "Buffer en rojo en un item de menor peso: reponer"),
    "vigilar": ("A en amarillo", "#f9a825", "Item A en amarillo: vigilar antes de que caiga a rojo"),
    "exceso_clave": ("Exceso en importante", "#1565c0", "Item A o B por encima del buffer: revisar si el tope es el correcto"),
    "exceso": ("Exceso en baja rotación", "#6a1b9a", "Exceso en un item C: capital inmovilizado, frenar reposición"),
    "dormido": ("Sin venta con inventario", "#6d4c41", "No vendió en la ventana y tiene inventario: capital dormido"),
    "ok": ("Sano", "#2e7d32", "Sin alerta"),
}



def diagnostico(it: dict) -> str:
    """Cruza la zona del buffer de hoy con la clase ABC: que atender primero. Funciona con lo que ya trae el item (zona, abc, inventario)."""
    z, a = it.get("zona"), it.get("abc")
    if z == "ROJA":
        return "prioridad" if a in ("I", "A", "B") else ("reponer" if a in ("C", "N") else "ok")
    if a == "D" and it.get("inventario", 0) > 0:
        return "dormido"
    if z == "EXCESO":
        return "exceso_clave" if a in ("I", "A", "B") else ("exceso" if a in ("C",) else "ok")
    if z == "AMARILLA" and a in ("I", "A"):
        return "vigilar"
    return "ok"


def clase_xyz(iv, c1: float = 0.5, c2: float = 0.8) -> str:
    if iv is None:
        return "-"
    return "X" if iv < c1 else ("Y" if iv <= c2 else "Z")


def clasificar(items: list[dict], criterio: str = "margen", corte_a: float = 80.0, corte_b: float = 95.0,
               mes_nuevo: str | None = None, cortes_iv: tuple[float, float] = (0.5, 0.8), metodo: str = "pareto", corte_i: float = 93.0) -> None:
    """Pone en cada item: abc, xyz, clase (ABC+XYZ), pct_acum y puesto. `mes_nuevo` = 'YYYYMM': si la primera venta es de ese mes o posterior es N.
    metodo 'pareto': A hasta el corte_a % acumulado del criterio, B hasta el corte_b %, C el resto (I no existe).
    metodo 'percentil': por la posicion del item entre los clasificables (como PERCENTRANK.INC de Excel: 1 = el mejor, 0 = el peor):
    I (infaltable) si el percentil >= corte_i %, A si >= corte_a %, B si >= corte_b %, C el resto (aqui corte_a y corte_b son LIMITES INFERIORES)."""
    if criterio not in CRITERIOS:
        raise ValueError(f"criterio debe ser uno de {list(CRITERIOS)}")
    if metodo not in ("pareto", "percentil"):
        raise ValueError("metodo debe ser pareto o percentil")
    if metodo == "pareto" and not (0 < corte_a < corte_b <= 100):
        raise ValueError("los cortes deben cumplir 0 < A < B <= 100")
    if metodo == "percentil" and not (0 < corte_b < corte_a < corte_i < 100):
        raise ValueError("los cortes por percentil deben cumplir 0 < B < A < Infaltable < 100")
    llave = {"margen": "margen", "venta": "valor", "costo": "costo_venta"}[criterio]
    ranking = []
    for it in items:
        it["xyz"] = clase_xyz(it.get("iv"), *cortes_iv)
        it["pct_acum"] = None; it["puesto"] = None
        sin_venta = it["cant"] <= 0 and it["valor"] <= 0
        if sin_venta:
            it["abc"] = "D"
        elif mes_nuevo and it.get("primer_mes") and it["primer_mes"] >= mes_nuevo:
            it["abc"] = "N"
        elif criterio != "venta" and it.get("costo") is None:
            it["abc"] = "S"
        else:
            it["abc"] = None
            ranking.append(it)
    ranking.sort(key=lambda x: (-(x[llave] or 0.0), x["producto_id"], x.get("bodega_id") or ""))
    total = sum(max(x[llave] or 0.0, 0.0) for x in ranking)
    acum = 0.0
    n = len(ranking)
    for i, it in enumerate(ranking, 1):
        v = it[llave] or 0.0
        it["puesto"] = i
        if v <= 0 or total <= 0:
            it["abc"] = "C"; it["pct_acum"] = 100.0
        else:
            antes = 100.0 * acum / total
            if metodo == "percentil":
                pr = 100.0 * (n - i) / (n - 1) if n > 1 else 100.0
                it["abc"] = "I" if pr >= corte_i else ("A" if pr >= corte_a else ("B" if pr >= corte_b else "C"))
            else:
                it["abc"] = "A" if antes < corte_a else ("B" if antes < corte_b else "C")
            acum += v
            it["pct_acum"] = 100.0 * acum / total
    for it in items:
        it["clase"] = it["abc"] + (it["xyz"] if it["abc"] in ("I", "A", "B", "C") and it["xyz"] != "-" else "")


def retornos(x: dict) -> None:
    """GMROI y meses de inventario de un agregado (celda, grupo, total): se calculan sobre las sumas en pesos, no promediando los de cada item."""
    ip = x.get("inv_prom_costo") or 0.0
    x["gmroi"] = x["margen_anual"] / ip if ip > 0 else None
    cv = x["costo_venta_anual"] / 12.0
    x["meses_inv"] = ip / cv if cv > 0 else None       # meses que dura el inventario promedio al ritmo de venta (a costo)


def matriz(items: list[dict]) -> dict:
    """Resumen por clase ABC x XYZ: items, venta, margen e inventario a costo; mas los totales por ABC."""
    celdas: dict[tuple, dict] = {}
    def acc(k, it):
        c = celdas.setdefault(k, {"abc": k[0], "xyz": k[1], "n": 0, "venta": 0.0, "margen": 0.0, "costo_venta": 0.0, "inv_costo": 0.0, "inventario": 0.0, "inv_prom_costo": 0.0, "margen_anual": 0.0, "costo_venta_anual": 0.0})
        c["n"] += 1; c["venta"] += it["valor"]; c["margen"] += it["margen"] or 0.0
        c["costo_venta"] += it["costo_venta"] or 0.0; c["inv_costo"] += it["inv_costo"] or 0.0; c["inventario"] += it["inventario"]
        c["inv_prom_costo"] += it["inv_prom_costo"] or 0.0; c["margen_anual"] += it["margen_anual"] or 0.0; c["costo_venta_anual"] += it["costo_venta_anual"] or 0.0
    for it in items:
        acc((it["abc"], it["xyz"] if it["abc"] in ("I", "A", "B", "C") else "-"), it)
    tot = {"n": len(items), "venta": sum(i["valor"] for i in items), "margen": sum(i["margen"] or 0.0 for i in items),
           "inv_costo": sum(i["inv_costo"] or 0.0 for i in items), "inv_prom_costo": sum(i["inv_prom_costo"] or 0.0 for i in items),
           "margen_anual": sum(i["margen_anual"] or 0.0 for i in items), "costo_venta_anual": sum(i["costo_venta_anual"] or 0.0 for i in items)}
    por_abc = {}
    for (a, _), c in celdas.items():
        t = por_abc.setdefault(a, {"abc": a, "n": 0, "venta": 0.0, "margen": 0.0, "inv_costo": 0.0, "inv_prom_costo": 0.0, "margen_anual": 0.0, "costo_venta_anual": 0.0})
        for k in ("n", "venta", "margen", "inv_costo", "inv_prom_costo", "margen_anual", "costo_venta_anual"):
            t[k] += c[k]
    for x in [*celdas.values(), *por_abc.values(), tot]:
        retornos(x)
    return {"celdas": sorted(celdas.values(), key=lambda c: (ORDEN_ABC.index(c["abc"]), ORDEN_XYZ.index(c["xyz"]))),
            "por_abc": sorted(por_abc.values(), key=lambda c: ORDEN_ABC.index(c["abc"])), "total": tot}


def mes_nuevo(hoy: date, meses: int = 3) -> str:
    """Primer mes (YYYYMM) que cuenta como 'nuevo': los ultimos `meses` meses incluyendo el actual."""
    y, m = hoy.year, hoy.month - (meses - 1)
    while m <= 0:
        m += 12; y -= 1
    return f"{y:04d}{m:02d}"
