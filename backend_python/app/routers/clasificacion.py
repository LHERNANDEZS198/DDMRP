"""Clasificacion ABC x XYZ de items sobre las ventas de la ultima ventana de meses, recalculada con los filtros que escoja el usuario
(tiendas, laboratorios, criterios, empresa) y descargable a Excel. Metodologia en app/clasificacion.py y en la hoja 'Metodologia' del Excel."""
import re
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from .. import clasificacion as cl, excel
from ..activos import solo_activos
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, requiere
from .control import _csv

router = APIRouter(prefix="/clasificacion", tags=["clasificacion"], dependencies=[Depends(requiere("ver_control"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"


def _ventana(meses: int) -> tuple[str, date, int]:
    """(primer mes YYYYMM, primer dia, dias) de la ventana: los ultimos `meses` meses incluyendo el actual (igual que el ETL de ventas)."""
    meses = min(max(int(meses), 1), 12)
    hoy = date.today()
    y, m = hoy.year, hoy.month - (meses - 1)
    while m <= 0:
        m += 12; y -= 1
    d0 = date(y, m, 1)
    return f"{y:04d}{m:02d}", d0, (hoy - d0).days + 1


def _cortes_iv(c) -> tuple[float, float]:
    r = {d: (lo, hi) for d, lo, hi in c.execute(text("SELECT descripcion, desde::float8, hasta::float8 FROM ddmrp.factor_tramo WHERE tipo = 'VAR'")).all()}
    try:
        return float(r["Media"][0]), float(r["Media"][1])
    except (KeyError, TypeError):
        return 0.5, 0.8


def _filas(c, user, mes_desde: str, filtrar: bool, empresa=None, bodegas=None, labs=None, crit=None, q=None, hist: bool = True, planes=None, solo_con: bool = False) -> list[dict]:
    """Una fila por tienda x item (REC ya sumado al original) con la venta de la ventana, el buffer de la ultima corrida y el costo."""
    w, p = filtro_sql_permisos(user, "k.bodega_id", "mi.categoria")
    cond = [w, solo_activos("k")]
    pre_h = pre_v = pre_s = ""     # empresa y tienda elegidas tambien dentro de cada CTE (si no, Postgres agrega TODA la historia y filtra al final)
    if filtrar:
        if _csv(empresa):
            cond.append("k.empresa = ANY(:f_emp)"); p["f_emp"] = _csv(empresa)
            pre_h += " AND empresa = ANY(:f_emp)"; pre_v += " AND a.empresa = ANY(:f_emp)"; pre_s += " AND empresa = ANY(:f_emp)"
        if _csv(bodegas):
            cond.append("k.bodega_id = ANY(:f_bod)"); p["f_bod"] = _csv(bodegas)
            pre_h += " AND bodega_id = ANY(:f_bod)"; pre_v += " AND a.bodega_id = ANY(:f_bod)"; pre_s += " AND bodega_id = ANY(:f_bod)"
        if _csv(labs):
            cond.append("COALESCE(mi.categoria, '') = ANY(:f_lab)"); p["f_lab"] = [("" if x == "(sin laboratorio)" else x) for x in _csv(labs)]
        if q and q.strip():
            cond.append("(k.producto_id ILIKE :f_q OR mi.descripcion ILIKE :f_q)"); p["f_q"] = f"%{q.strip()}%"
        por_plan: dict[str, list[str]] = {}
        for x in _csv(crit):
            if ":" in x:
                pl, cr = x.split(":", 1); por_plan.setdefault(pl, []).append(cr)
        for i, (pl, crs) in enumerate(por_plan.items()):
            cond.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio ic{i} WHERE ic{i}.producto_id = k.producto_id AND ic{i}.plan_id = :cp{i} AND ic{i}.criterio_id = ANY(:cc{i}))")
            p[f"cp{i}"] = pl; p[f"cc{i}"] = crs
        if solo_con:    # excluir los items que no tienen valor en los criterios elegidos (los del filtro ya lo exigen)
            for j, pl in enumerate(dict.fromkeys(_csv(planes))):
                cond.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio is{j} WHERE is{j}.producto_id = k.producto_id AND is{j}.plan_id = :sp{j})")
                p[f"sp{j}"] = pl
    if filtrar and (_csv(labs) or _csv(crit) or (q and q.strip()) or (solo_con and _csv(planes))):
        # los filtros de item se resuelven UNA vez a la lista de productos y se empujan a cada CTE: el planner ya no agrega toda la historia ni evalua EXISTS por fila
        wi = ["true"]; pi: dict = {}
        if _csv(labs):
            wi.append("COALESCE(mi2.categoria, '') = ANY(:i_lab)"); pi["i_lab"] = [("" if x == "(sin laboratorio)" else x) for x in _csv(labs)]
        if q and q.strip():
            wi.append("(mi2.producto_id ILIKE :i_q OR mi2.descripcion ILIKE :i_q)"); pi["i_q"] = f"%{q.strip()}%"
        for i, (pl, crs) in enumerate(por_plan.items()):
            wi.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio xc{i} WHERE xc{i}.producto_id = mi2.producto_id AND xc{i}.plan_id = :xp{i} AND xc{i}.criterio_id = ANY(:xc{i}))")
            pi[f"xp{i}"] = pl; pi[f"xc{i}"] = crs
        if solo_con:
            for j, pl in enumerate(dict.fromkeys(_csv(planes))):
                wi.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio xs{j} WHERE xs{j}.producto_id = mi2.producto_id AND xs{j}.plan_id = :xq{j})")
                pi[f"xq{j}"] = pl
        ids = [r[0] for r in c.execute(text("SELECT mi2.producto_id FROM ddmrp.maestro_item mi2 WHERE " + " AND ".join(wi)), pi)]
        p["f_ids"] = ids
        pre_h += " AND producto_id = ANY(:f_ids)"; pre_s += " AND producto_id = ANY(:f_ids)"; pre_v += " AND COALESCE(r.original_id, a.producto_id) = ANY(:f_ids)"
    p["mes_desde"] = mes_desde
    # inventario promedio de la ventana: lo resume el orquestador por mes (inventario_mes) para no recorrer la historia diaria completa; sin el (clase global) no se usa
    sql = f"""
    WITH h AS (
      SELECT empresa, bodega_id, producto_id, SUM(inv_suma)::float8 AS inv_suma, SUM(dias)::int AS dias_hist, SUM(dias_cero)::int AS dias_cero
      FROM ddmrp.inventario_mes WHERE mes >= :mes_desde AND {'true' if hist else 'false'}{pre_h} GROUP BY 1, 2, 3),
    v AS (
      SELECT a.empresa, a.bodega_id, COALESCE(r.original_id, a.producto_id) AS producto_id,
             SUM(a.cantidad)::float8 AS cant, SUM(a.valor)::float8 AS valor,
             MIN(a.mes) FILTER (WHERE a.cantidad > 0) AS primer_mes
      FROM ddmrp.ventas_mensual a
      LEFT JOIN ddmrp.v_item_rec r ON r.empresa = a.empresa AND r.rec_id = a.producto_id
      WHERE a.mes >= :mes_desde{pre_v}
      GROUP BY 1, 2, 3),
    s AS (
      SELECT empresa, bodega_id, producto_id, inventario::float8 AS inventario, iv::float8 AS iv, adu::float8 AS adu,
             zona::text AS zona, pct_buffer::float8 AS pct_buffer, flujo_neto::float8 AS flujo_neto, cantidad_sugerida::float8 AS sugerido
      FROM ddmrp.sugerencias_envio WHERE ejecucion_id = {ULTIMA}{pre_s}),
    k AS (
      SELECT COALESCE(v.empresa, s.empresa) AS empresa, COALESCE(v.bodega_id, s.bodega_id) AS bodega_id,
             COALESCE(v.producto_id, s.producto_id) AS producto_id,
             v.cant, v.valor, v.primer_mes, s.inventario, s.iv, s.adu, s.zona, s.pct_buffer, s.flujo_neto, s.sugerido,
             h.inv_suma, h.dias_hist, h.dias_cero
      FROM v FULL JOIN s ON s.empresa = v.empresa AND s.bodega_id = v.bodega_id AND s.producto_id = v.producto_id
      LEFT JOIN h ON h.empresa = COALESCE(v.empresa, s.empresa) AND h.bodega_id = COALESCE(v.bodega_id, s.bodega_id) AND h.producto_id = COALESCE(v.producto_id, s.producto_id))
    SELECT k.empresa, k.bodega_id, mb.descripcion AS bodega_nombre, k.producto_id, mi.descripcion, COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio,
           COALESCE(k.cant, 0) AS cant, COALESCE(k.valor, 0) AS valor, k.primer_mes, COALESCE(k.inventario, 0) AS inventario, k.iv, COALESCE(k.adu, 0) AS adu,
           k.zona, k.pct_buffer, k.flujo_neto, k.sugerido, k.inv_suma, k.dias_hist, k.dias_cero,
           (SELECT ci.costo::float8 FROM ddmrp.costo_item ci WHERE ci.producto_id = k.producto_id) AS costo
    FROM k LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = k.producto_id LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = k.bodega_id AND mb.empresa = k.empresa
    WHERE {' AND '.join(cond)}
      AND (COALESCE(k.cant, 0) > 0 OR COALESCE(k.valor, 0) > 0 OR COALESCE(k.inventario, 0) > 0)"""   # sin venta y sin inventario no es un D: no se lista
    return [dict(r) for r in c.execute(text(sql), p).mappings()]


_CACHE_GLOBAL: dict = {}      # clase de cada item contra TODO el universo visible: no depende de los filtros de pantalla, se reutiliza mientras no corra el motor
_CACHE_TTL = 600


def _clase_global(c, user, mes_desde, nivel, criterio, corte_a, corte_b, nuevo, cortes, dias, metodo="pareto", corte_i=93.0):
    """{clave: clase} del universo completo que el usuario puede ver. Es la consulta mas pesada (todo el universo) y no cambia al mover los filtros:
    se guarda 10 minutos por (corrida del motor, permisos del usuario, ventana, nivel, criterio y cortes)."""
    import time
    w, p = filtro_sql_permisos(user, "k.bodega_id", "mi.categoria")
    ej = c.execute(text(f"SELECT {ULTIMA}")).scalar()
    clave_c = (ej, w, tuple(sorted((k, str(v)) for k, v in p.items())), mes_desde, nivel, criterio, corte_a, corte_b, str(nuevo), tuple(cortes), metodo, corte_i)
    hit = _CACHE_GLOBAL.get(clave_c)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    filas_g = _filas(c, user, mes_desde, False, hist=False)
    glob = cl.agregar(filas_g, nivel); cl.calcular(glob, dias); cl.clasificar(glob, criterio, corte_a, corte_b, nuevo, cortes, metodo, corte_i)
    clave = (lambda x: (x["empresa"], x["bodega_id"], x["producto_id"])) if nivel == "tienda_item" else (lambda x: x["producto_id"])
    g = {clave(x): x["clase"] for x in glob}
    if len(_CACHE_GLOBAL) >= 8:
        _CACHE_GLOBAL.pop(next(iter(_CACHE_GLOBAL)))
    _CACHE_GLOBAL[clave_c] = (time.time(), g)
    return g


def _calcular(user, nivel, criterio, meses, corte_a, corte_b, empresa, bodegas, labs, crit, q, con_global=True, planes=None, solo_con=False, metodo="pareto", corte_i=93.0):
    if nivel not in cl.NIVELES:
        raise HTTPException(400, f"nivel debe ser uno de {list(cl.NIVELES)}")
    if criterio not in cl.CRITERIOS:
        raise HTTPException(400, f"criterio debe ser uno de {list(cl.CRITERIOS)}")
    if metodo not in ("pareto", "percentil"):
        raise HTTPException(400, "metodo debe ser pareto o percentil")
    if metodo == "pareto" and not (0 < corte_a < corte_b <= 100):
        raise HTTPException(400, "Los cortes deben cumplir 0 < A < B <= 100")
    if metodo == "percentil" and not (0 < corte_b < corte_a < corte_i < 100):
        raise HTTPException(400, "Los cortes por percentil deben cumplir 0 < B < A < Infaltable < 100")
    mes_desde, d0, dias = _ventana(meses)
    nuevo = cl.mes_nuevo(date.today(), 3) if meses >= 6 else None     # con ventanas cortas todo seria 'nuevo'
    with pg.connect() as c:
        cortes = _cortes_iv(c)
        c.execute(text("SET LOCAL statement_timeout = 50000"))     # menos que el timeout de nginx (60 s): falla con mensaje en vez de dejar consultas colgadas
        try:
            filas = _filas(c, user, mes_desde, True, empresa, bodegas, labs, crit, q, planes=planes, solo_con=solo_con)
            hay_filtro = bool(_csv(empresa) or _csv(bodegas) or _csv(labs) or _csv(crit) or (q and q.strip()) or (solo_con and _csv(planes)))
            g = _clase_global(c, user, mes_desde, nivel, criterio, corte_a, corte_b, nuevo, cortes, dias, metodo, corte_i) if (con_global and hay_filtro) else None
        except DBAPIError as e:
            if "statement timeout" in str(e):
                raise HTTPException(503, "El informe tardo demasiado. Acota con una tienda o un laboratorio, o avisa a sistemas (estadisticas de la base).")
            raise
    items = cl.agregar(filas, nivel); cl.calcular(items, dias); cl.clasificar(items, criterio, corte_a, corte_b, nuevo, cortes, metodo, corte_i)
    if g is not None:       # clase de cada item contra TODO el universo que el usuario puede ver (sin los filtros de pantalla)
        clave = (lambda x: (x["empresa"], x["bodega_id"], x["producto_id"])) if nivel == "tienda_item" else (lambda x: x["producto_id"])
        for it in items:
            it["clase_global"] = g.get(clave(it))
    else:
        for it in items:
            it["clase_global"] = it["clase"]
    meta = {"nivel": nivel, "criterio": criterio, "criterio_nombre": cl.CRITERIOS[criterio], "meses": min(max(meses, 1), 12), "desde": d0, "hasta": date.today(),
            "dias": dias, "corte_a": corte_a, "corte_b": corte_b, "corte_i": corte_i, "metodo": metodo, "cortes_iv": cortes, "nuevo_desde": nuevo,
            "sin_valor": not any(i["valor"] for i in items) and bool(items)}
    return items, meta


def _filtrar_salida(items, abc, xyz):
    a = [x for x in _csv(abc) if x in cl.ORDEN_ABC]; z = [x for x in _csv(xyz) if x in cl.ORDEN_XYZ]
    return [i for i in items if (not a or i["abc"] in a) and (not z or i["xyz"] in z)]


def _por_grupo(items: list[dict], plan: str | None, dentro: bool = False, criterio: str = "margen", corte_a: float = 80, corte_b: float = 95,
               nuevo: str | None = None, cortes_iv: tuple = (0.5, 0.8), metodo: str = "pareto", corte_i: float = 93.0) -> dict | None:
    """Vista por dentro de un criterio de items (CATEGORIA, LINEA...): una fila por valor del criterio con cuantos items hay de cada clase ABC
    y su venta, margen e inventario. Por defecto la clase de cada item es la de la lista; con `dentro` el ABC se recalcula DENTRO de cada grupo
    (cada item contra los de su mismo valor). Cada item tiene un solo valor por plan. Se combina con los filtros: el filtro de otro criterio
    (p.ej. CATEGORIA = TERCEROS) deja solo esos items y aqui se agrupan por LINEA."""
    if not plan or not items:
        return None
    with pg.connect() as c:
        pn = c.execute(text("SELECT nombre FROM ddmrp.criterio_plan WHERE plan_id = :p"), {"p": plan}).scalar()
        val = dict(c.execute(text("SELECT producto_id, criterio_id FROM ddmrp.item_criterio WHERE plan_id = :p"), {"p": plan}).all())
        nom = dict(c.execute(text("SELECT criterio_id, nombre FROM ddmrp.criterio WHERE plan_id = :p"), {"p": plan}).all())
    grupos: dict[str, dict] = {}
    miembros: dict[str, list[dict]] = {}
    for it in items:
        v = val.get(it["producto_id"]) or ""
        g = grupos.setdefault(v, {"id": v, "nombre": (nom.get(v) or v).strip() if v else "(sin valor)", "n": 0, "venta": 0.0, "margen": 0.0, "inv_costo": 0.0,
                                  "inv_prom_costo": 0.0, "margen_anual": 0.0, "costo_venta_anual": 0.0, **{a: 0 for a in cl.ORDEN_ABC}})
        miembros.setdefault(v, []).append(it)
        g["n"] += 1
        g["venta"] += it["valor"]; g["margen"] += it["margen"] or 0.0; g["inv_costo"] += it["inv_costo"] or 0.0
        g["inv_prom_costo"] += it["inv_prom_costo"] or 0.0; g["margen_anual"] += it["margen_anual"] or 0.0; g["costo_venta_anual"] += it["costo_venta_anual"] or 0.0
    for v, g in grupos.items():
        lista = [dict(i) for i in miembros[v]] if dentro else miembros[v]
        if dentro:
            cl.clasificar(lista, criterio, corte_a, corte_b, nuevo, cortes_iv, metodo, corte_i)
        for it in lista:
            g[it["abc"]] += 1
    out = sorted(grupos.values(), key=lambda g: (-g["margen"], g["nombre"]))
    for g in out:
        g["margen_pct"] = None if g["venta"] <= 0 else 100.0 * g["margen"] / g["venta"]
        cl.retornos(g)
    return {"plan_id": plan, "plan_nombre": (pn or plan).strip(), "grupos": out}


@router.get("")
def clasificar(nivel: str = "item", criterio: str = "margen", meses: int = 12, corte_a: float = 80, corte_b: float = 95,
               empresa: str | None = None, bodegas: str | None = None, labs: str | None = None, crit: str | None = None, q: str | None = None,
               abc: str | None = None, xyz: str | None = None, agrupar: str | None = None, dentro: bool = False, planes: str | None = None, solo_con: bool = False, metodo: str = "pareto", corte_i: float = 93, limit: int = Query(3000, le=20000), user=Depends(usuario_actual)):
    items, meta = _calcular(user, nivel, criterio, meses, corte_a, corte_b, empresa, bodegas, labs, crit, q, planes=planes, solo_con=solo_con, metodo=metodo, corte_i=corte_i)
    m = cl.matriz(items)                                                  # la matriz siempre es del filtro completo (no del filtro de clase)
    vis = _filtrar_salida(items, abc, xyz)
    vis.sort(key=lambda i: (cl.ORDEN_ABC.index(i["abc"]), i["puesto"] or 10**9, i["producto_id"]))
    return {"meta": meta, "matriz": m, "por_criterio": _por_grupo(items, agrupar, dentro, criterio, corte_a, corte_b, meta["nuevo_desde"], tuple(meta["cortes_iv"]), metodo, corte_i), "filas": vis[:limit], "total": len(vis), "truncado": len(vis) > limit}


COLS = [{"t": "Puesto", "k": "puesto", "f": "int", "w": 8}, {"t": "Clase", "k": "clase", "w": 8}, {"t": "ABC", "k": "abc", "w": 6}, {"t": "XYZ", "k": "xyz", "w": 6},
        {"t": "Clase global", "k": "clase_global", "w": 11}, {"t": "% acumulado", "k": "pct_acum", "f": "dec1"},
        {"t": "Empresa", "k": "empresa", "w": 8}, {"t": "Tienda", "k": "bodega_id", "w": 9}, {"t": "Nombre tienda", "k": "bodega_nombre", "w": 24},
        {"t": "Item", "k": "producto_id", "w": 11}, {"t": "Descripcion", "k": "descripcion", "w": 44}, {"t": "Laboratorio", "k": "laboratorio", "w": 14},
        {"t": "Unidades vendidas", "k": "cant", "f": "int"}, {"t": "Venta neta $", "k": "valor", "f": "cop"}, {"t": "Costo de lo vendido $", "k": "costo_venta", "f": "cop"},
        {"t": "Margen $", "k": "margen", "f": "cop"}, {"t": "Margen %", "k": "margen_pct", "f": "dec1"}, {"t": "Costo unitario", "k": "costo", "f": "cop"},
        {"t": "Inventario (u.)", "k": "inventario", "f": "int"}, {"t": "Inventario a costo $", "k": "inv_costo", "f": "cop"},
        {"t": "Inventario promedio (u.)", "k": "inv_prom", "f": "dec1"}, {"t": "Inventario promedio a costo $", "k": "inv_prom_costo", "f": "cop"},
        {"t": "Dias con historia de inventario", "k": "dias_hist", "f": "int"},
        {"t": "GMROI (anual)", "k": "gmroi", "f": "dec2"}, {"t": "Rotacion (uds/mes)", "k": "rotacion", "f": "dec2"},
        {"t": "Dias de inventario", "k": "dias_inv", "f": "int"}, {"t": "% dias sin stock", "k": "pct_sin_stock", "f": "dec1"},
        {"t": "Cobertura x margen % (indicador anterior, no comparable)", "k": "cob_x_margen", "f": "pct1"},
        {"t": "IV", "k": "iv", "f": "dec2"}, {"t": "ADU", "k": "adu", "f": "dec1"}, {"t": "Tiendas", "k": "tiendas", "f": "int"}]

METODOLOGIA = [
    ("Que es", "Clasificacion ABC (importancia economica) x XYZ (variabilidad de la demanda) de los items sobre la venta de una ventana de meses."),
    ("Ventana", "{desde} a {hasta} ({meses} meses, {dias} dias). Lo que traen las ventas por mes del ETL."),
    ("Venta neta $", "Venta sin IVA: valor bruto - descuento de linea - descuento global (las devoluciones restan). Facturas y POS de Siesa."),
    ("Costo de lo vendido", "Unidades vendidas x costo promedio actual por instalacion (Siesa). Es el costo de hoy, no el de la fecha de la venta."),
    ("Margen $", "Venta neta - costo de lo vendido. Margen % = margen / venta neta."),
    ("Criterio del ABC", "{criterio}. Metodo pareto (el de siempre): se ordena de mayor a menor y se acumula: A hasta el {corte_a}% del total, B hasta el {corte_b}%, C el resto. El item que cruza el corte queda en la clase mejor. Lo que no suma (margen <= 0) es C."),
    ("Infaltables (I)", "Solo con el metodo 'percentil': los items se ordenan por el criterio y se mide su posicion entre los clasificables (1 = el mejor, 0 = el peor, como PERCENTRANK de Excel). "
                        "I = percentil >= {corte_i}%, A = >= {corte_a}%, B = >= {corte_b}%, C el resto. Con el metodo 'pareto' no hay Infaltables."),
    ("XYZ", "Por el indice de variabilidad (IV) del motor: X = IV < {c1}, Y = {c1} a {c2}, Z = IV > {c2} (cortes de la tabla de factores VAR). A nivel item es el IV de sus tiendas ponderado por la venta diaria (ADU)."),
    ("D", "Sin venta en las tiendas en la ventana (no cuenta lo que el CEDI vende a wholesale o digital) PERO con inventario: lo que no vende ni tiene stock no se lista (ver Inventario a costo)."),
    ("N", "Producto nuevo: su primera venta es de {nuevo_desde} en adelante; aun no tiene historia para clasificarlo. Solo se aplica con ventanas de 6 meses o mas."),
    ("S", "Sin costo conocido en Siesa: no se puede calcular margen ni consumo a costo."),
    ("GMROI", "Margen anualizado / inventario PROMEDIO a costo. El promedio sale de la foto diaria de inventario de las tiendas dentro de la ventana (resumida por mes); donde no hay historia se usa el inventario de hoy (ver 'Dias con historia'). Cuantos pesos de margen deja cada peso invertido en inventario al año. En grupos y totales se calcula con las sumas en pesos, no promediando los de cada item."),
    ("Rotacion", "Unidades vendidas por mes en promedio en la ventana (unidades vendidas / meses de la ventana). Es la rotacion que usa el indicador anterior. En los resumenes por clase y grupo se muestra en su lugar Meses de inventario (inventario promedio a costo / costo de venta mensual), porque las unidades de items distintos no se suman. (GMROI = margen anual / inventario promedio a costo)."),
    ("Dias de inventario", "Inventario promedio / venta diaria promedio de la ventana."),
    ("% dias sin stock", "Dias-tienda de la ventana con inventario 0 / dias-tienda con historia. Un GMROI alto con muchos dias sin stock suele ser un quiebre, no eficiencia."),
    ("Cobertura x margen %", "Indicador anterior: (inventario promedio en unidades / venta mensual en unidades) x margen %. Mide meses de stock ponderados por margen, no un retorno: no es comparable con el GMROI."),
    ("Clase global", "La clase que tendria el item con todo lo que el usuario puede ver, sin los filtros de pantalla (la 'Clase' se recalcula solo con lo filtrado)."),
    ("Nombres para tablas dinamicas", "La hoja Detalle trae el codigo y el nombre del laboratorio y, si existen en Siesa, los criterios Categoria y Linea de cada item (un solo valor por item), para armar tablas dinamicas sin cruzar codigos."),
    ("Items", "Solo activos (regla solo_items_activos); los REC suman al original."),
]


def _norm(t: str | None) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", (t or "").strip().upper()) if unicodedata.category(c) != "Mn")


def _nombres_para_excel(items: list[dict], planes_sel: str | None = None) -> list[dict]:
    """Agrega a cada fila el nombre del laboratorio y los criterios CATEGORIA y LINEA (los planes de Siesa con ese nombre) para poder armar tablas dinamicas
    sin cruzar codigos a mano. Devuelve las columnas extra que si se pudieron llenar (si no existe el plan, no sale la columna)."""
    with pg.connect() as c:
        lab = dict(c.execute(text("SELECT codigo, nombre FROM ddmrp.laboratorio")).all())
        planes = {_norm(n): p for p, n in c.execute(text("SELECT plan_id, nombre FROM ddmrp.criterio_plan")).all()}
        por_plan = {}
        for clave in ("CATEGORIA", "LINEA"):
            p = next((pid for n, pid in planes.items() if n == clave), None) or next((pid for n, pid in planes.items() if n.startswith(clave)), None)
            if p:
                por_plan[clave] = dict(c.execute(text("SELECT ic.producto_id, cr.nombre FROM ddmrp.item_criterio ic JOIN ddmrp.criterio cr "
                                                      "ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id WHERE ic.plan_id = :p"), {"p": p}).all())
    for it in items:
        cod = it.get("laboratorio")
        it["lab_nombre"] = (lab.get(cod) or "").strip() or None
        for clave, mapa in por_plan.items():
            it[clave.lower()] = (mapa.get(it["producto_id"]) or "").strip() or None
    extra_pl = []
    with pg.connect() as c:    # ademas, una columna por cada criterio elegido en la pantalla (filtro o agrupar), con el valor de cada item
        for pl in dict.fromkeys(_csv(planes_sel)):
            nom = c.execute(text("SELECT nombre FROM ddmrp.criterio_plan WHERE plan_id = :p"), {"p": pl}).scalar()
            if nom is None or _norm(nom) in ("CATEGORIA", "LINEA") and _norm(nom) in por_plan:
                continue
            mapa = dict(c.execute(text("SELECT ic.producto_id, cr.nombre FROM ddmrp.item_criterio ic JOIN ddmrp.criterio cr "
                                       "ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id WHERE ic.plan_id = :p"), {"p": pl}).all())
            for it in items:
                it["crit_" + pl] = (mapa.get(it["producto_id"]) or "").strip() or None
            extra_pl.append({"t": nom.strip().capitalize(), "k": "crit_" + pl, "w": 24})
    extra = [{"t": "Nombre laboratorio", "k": "lab_nombre", "w": 28}]
    if "CATEGORIA" in por_plan:
        extra.append({"t": "Categoria", "k": "categoria", "w": 24})
    if "LINEA" in por_plan:
        extra.append({"t": "Linea", "k": "linea", "w": 24})
    return extra + extra_pl


@router.get("/excel")
def exportar(nivel: str = "item", criterio: str = "margen", meses: int = 12, corte_a: float = 80, corte_b: float = 95,
             empresa: str | None = None, bodegas: str | None = None, labs: str | None = None, crit: str | None = None, q: str | None = None,
             abc: str | None = None, xyz: str | None = None, agrupar: str | None = None, dentro: bool = False, planes: str | None = None, solo_con: bool = False, metodo: str = "pareto", corte_i: float = 93, user=Depends(usuario_actual)):
    items, meta = _calcular(user, nivel, criterio, meses, corte_a, corte_b, empresa, bodegas, labs, crit, q, planes=planes, solo_con=solo_con, metodo=metodo, corte_i=corte_i)
    m = cl.matriz(items)
    vis = _filtrar_salida(items, abc, xyz)
    vis.sort(key=lambda i: (cl.ORDEN_ABC.index(i["abc"]), i["puesto"] or 10**9, i["producto_id"]))
    cols = [c for c in COLS if nivel == "tienda_item" or c["k"] not in ("empresa", "bodega_id", "bodega_nombre")]
    extra = _nombres_para_excel(vis, planes)
    i_lab = next(i for i, c in enumerate(cols) if c["k"] == "laboratorio")
    cols = cols[:i_lab + 1] + extra + cols[i_lab + 1:]
    wb = excel.libro()
    # hoja resumen: una fila por celda de la matriz
    res_cols = [{"t": "ABC", "k": "abc", "w": 8}, {"t": "XYZ", "k": "xyz", "w": 8}, {"t": "Items", "k": "n", "f": "int"}, {"t": "Venta neta $", "k": "venta", "f": "cop"},
                {"t": "Margen $", "k": "margen", "f": "cop"}, {"t": "Inventario a costo $ (hoy)", "k": "inv_costo", "f": "cop"}, {"t": "Inventario promedio a costo $", "k": "inv_prom_costo", "f": "cop"},
                {"t": "GMROI (anual)", "k": "gmroi", "f": "dec2"}, {"t": "Meses de inventario", "k": "meses_inv", "f": "dec1"}, {"t": "Inventario (u.)", "k": "inventario", "f": "int"}]
    excel.hoja(wb, "Resumen", res_cols, m["celdas"] + [{"abc": "TOTAL", "xyz": "", **m["total"], "inventario": None}])
    pg_ = _por_grupo(items, agrupar, dentro, criterio, corte_a, corte_b, meta["nuevo_desde"], tuple(meta["cortes_iv"]), metodo, corte_i)
    if pg_:   # una fila por valor del criterio de items (categoria, linea...)
        gcols = ([{"t": pg_["plan_nombre"], "k": "nombre", "w": 30}, {"t": "Items", "k": "n", "f": "int"}]
                 + [{"t": a, "k": a, "f": "int", "w": 7} for a in cl.ORDEN_ABC]
                 + [{"t": "Venta neta $", "k": "venta", "f": "cop"}, {"t": "Margen $", "k": "margen", "f": "cop"}, {"t": "Margen %", "k": "margen_pct", "f": "dec1"},
                    {"t": "Inventario a costo $ (hoy)", "k": "inv_costo", "f": "cop"}, {"t": "GMROI (anual)", "k": "gmroi", "f": "dec2"}, {"t": "Meses de inventario", "k": "meses_inv", "f": "dec1"}])
        excel.hoja(wb, ("Por " + re.sub(r"[\\/?*\[\]:]", " ", pg_["plan_nombre"]))[:31], gcols, pg_["grupos"])
    excel.hoja(wb, "Detalle", cols, vis, fijar=5)
    ctx = {"desde": meta["desde"], "hasta": meta["hasta"], "meses": meta["meses"], "dias": meta["dias"], "criterio": meta["criterio_nombre"], "corte_a": corte_a, "corte_i": corte_i,
           "corte_b": corte_b, "c1": meta["cortes_iv"][0], "c2": meta["cortes_iv"][1], "nuevo_desde": meta["nuevo_desde"] or "(no aplica)"}
    excel.hoja_texto(wb, "Metodologia", [(k, v.format(**ctx)) for k, v in METODOLOGIA], ancho=(24, 120))
    excel.hoja_texto(wb, "Filtros", [("Reporte", "Clasificacion ABC x XYZ"), ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")),
                                     ("Usuario", f"{user.get('nombre', '')} ({user.get('id', '')})"), ("Nivel", cl.NIVELES[nivel]), ("Criterio", meta["criterio_nombre"]), ("Metodo de cortes", "Percentil (I·A·B·C)" if metodo == "percentil" else "Pareto acumulado (A·B·C)"),
                                     ("Empresa", empresa or "todas"), ("Tiendas", bodegas or "todas"), ("Laboratorios", labs or "todos"), ("Criterios de items", crit or ""), ("Excluir items sin el criterio elegido", "si" if (solo_con and planes) else "no"), ("Agrupado por", (agrupar or "") + (" (ABC recalculado dentro de cada grupo)" if agrupar and dentro else "")),
                                     ("Busqueda", q or ""), ("Clases mostradas en Detalle", f"ABC: {abc or 'todas'} · XYZ: {xyz or 'todas'}"),
                                     ("Filas en Detalle", f"{len(vis)} de {len(items)}")])
    return Response(excel.a_bytes(wb), media_type=excel.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="clasificacion_{nivel}_{criterio}_{datetime.now():%Y%m%d_%H%M}.xlsx"'})


def datos_clase(user, empresa=None, bodegas=None, labs=None, crit=None, q=None, meses: int = 12) -> dict:
    """{(empresa, bodega, producto): {clase, ranking, prom_venta, prom_unid}} por tienda x item, con los mismos filtros de una pantalla (mapa de calor).
    Si las ventas aun no traen valor en pesos usa el consumo a costo (solo necesita unidades y costo)."""
    meses = min(max(meses, 1), 12)
    items, meta = _calcular(user, "tienda_item", "margen", meses, 80, 95, empresa, bodegas, labs, crit, q, con_global=False)
    if meta["sin_valor"]:
        items, meta = _calcular(user, "tienda_item", "costo", meses, 80, 95, empresa, bodegas, labs, crit, q, con_global=False)
    m = max(meta["dias"] / 30.4375, 1.0)
    return {(i["empresa"], i["bodega_id"], i["producto_id"]): {"clase": i["clase"], "ranking": i["puesto"], "prom_venta": i["valor"] / m, "prom_unid": i["cant"] / m}
            for i in items}
