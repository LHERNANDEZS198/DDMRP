"""Reportes de compras (solo lectura): «Ventas por producto» y «Proveedor / PT», los dos informes que compras tenia en el Power BI (BI_Compras_2022).
Leen el historico mensual que trae etl/reportes_compras.py (ddmrp.rep_venta_mes, rep_compra_mes, rep_otif) y lo cruzan con los maestros del app: laboratorio
(maestro_item.categoria), categoria (plan 001) y accion (plan 003) de item_criterio, inventario del CEDI y rotacion (ADU) del buffer del CEDI.
Cifras (igual que las medidas del Power BI):
  venta neta = valor bruto - descuento de linea      % rent = (venta neta - costo) / venta neta
  % a tiempo / % completo = promedio de las lineas de OC con entrada (ver rep_otif_* en Reglas de compras)
Los filtros se mandan como listas separadas por coma; los periodos son AAAAMM. El usuario solo ve los laboratorios que su perfil permite."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .. import progreso
import logging
import re
import time
from datetime import date, timedelta
from .. import gmroi as gm
from ..bitacora import usuario_de
from ..db import pg
from ..etl.reportes_compras import config as cfg_rep, sincronizar_reportes_compras
from ..modo import fijar_modo, solo_cedi
from ..security import asignaciones, requiere

log = logging.getLogger(__name__)
PRESUPUESTO_S = 50      # segundos para todo el informe de indicadores (el nginx corta a los 60)

router = APIRouter(prefix="/compras/reportes", tags=["compras"], dependencies=[Depends(requiere("ver_control_compras"))])
ULTIMA = "ANY (SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok' GROUP BY empresa)"   # la ultima corrida buena de CADA empresa (sus filas solo existen bajo su propia corrida)
TOPE_FILAS = 20000


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _plan(valor: float) -> str:
    return f"{int(valor):03d}"


def _labs_permitidos(user) -> list[str] | None:
    """None = todos los laboratorios; lista = solo esos (el perfil limita por laboratorio/categoria). Sin asignaciones = ninguno, como el tablero de compras."""
    asigs = asignaciones(user["id"])
    if any(a["es_admin"] or a["categoria"] == "*" for a in asigs):
        return None
    return sorted({a["categoria"] for a in asigs})


class Filtros:
    """Filtros comunes. `base()` arma el FROM y el WHERE de una tabla de hechos (alias x: empresa, periodo, producto_id) con los maestros de item unidos."""

    def __init__(self, user, empresa=None, desde=None, hasta=None, labs=None, categorias=None, acciones=None, un=None, q=None, proveedores=None, crit=None, skus=None, canales=None):
        cfg = cfg_rep()
        self.p: dict = {"plan_cat": _plan(cfg.get("rep_plan_categoria", 1)), "plan_acc": _plan(cfg.get("rep_plan_accion", 3))}
        self.emp = _csv(empresa)
        self.desde, self.hasta = (desde or "").strip(), (hasta or "").strip()
        for nombre, v in (("desde", self.desde), ("hasta", self.hasta)):
            if v and not (v.isdigit() and len(v) == 6):
                raise HTTPException(400, f"El periodo «{nombre}» debe ser AAAAMM (ej. 202601)")
        self.labs, self.cats, self.accs, self.un = _csv(labs), _csv(categorias), _csv(acciones), _csv(un)
        self.q, self.provs = (q or "").strip(), _csv(proveedores)
        self.canales = _csv(canales)    # canal (tipo de cliente) de la venta; solo aplica a rep_venta_mes (con_un)
        self.skus = _csv(skus)      # SKU exactos elegidos (a diferencia de `q`, que busca por texto y trae tambien 2192970 al buscar 192970)
        self.crit: dict[str, list[str]] = {}     # criterios de items (cualquier plan de Siesa): «plan:valor,plan:valor»; valores del mismo plan = O, planes distintos = Y
        for x in _csv(crit):
            if ":" in x:
                pl, cr = x.split(":", 1)
                self.crit.setdefault(pl, []).append(cr)
        self.perm = _labs_permitidos(user)

    def base(self, tabla: str, con_un: bool = False, con_prov: bool = False) -> tuple[str, str, dict]:
        joins = f"""FROM {tabla} x
            LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = x.empresa AND mi.producto_id = x.producto_id
            LEFT JOIN ddmrp.laboratorio lb ON lb.empresa = mi.empresa AND lb.codigo = mi.categoria
            LEFT JOIN ddmrp.item_criterio ic1 ON ic1.empresa = x.empresa AND ic1.producto_id = x.producto_id AND ic1.plan_id = :plan_cat
            LEFT JOIN ddmrp.criterio cr1 ON cr1.plan_id = ic1.plan_id AND cr1.criterio_id = ic1.criterio_id
            LEFT JOIN ddmrp.item_criterio ic3 ON ic3.empresa = x.empresa AND ic3.producto_id = x.producto_id AND ic3.plan_id = :plan_acc
            LEFT JOIN ddmrp.criterio cr3 ON cr3.plan_id = ic3.plan_id AND cr3.criterio_id = ic3.criterio_id"""
        w, p = ["TRUE"], dict(self.p)
        if self.emp:
            w.append("x.empresa = ANY(:emp)"); p["emp"] = self.emp
        if self.desde:
            w.append("x.periodo >= :desde"); p["desde"] = self.desde
        if self.hasta:
            w.append("x.periodo <= :hasta"); p["hasta"] = self.hasta
        if self.labs:
            w.append("mi.categoria = ANY(:labs)"); p["labs"] = self.labs
        if self.cats:
            w.append("ic1.criterio_id = ANY(:cats)"); p["cats"] = self.cats
        if self.accs:
            w.append("ic3.criterio_id = ANY(:accs)"); p["accs"] = self.accs
        if self.q:
            w.append("(x.producto_id ILIKE :q OR mi.descripcion ILIKE :q)"); p["q"] = f"%{self.q}%"
        if self.skus:
            w.append("x.producto_id = ANY(:skus)"); p["skus"] = self.skus
        for i, (pl, crs) in enumerate(self.crit.items()):
            w.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio icx{i} WHERE icx{i}.empresa = x.empresa AND icx{i}.producto_id = x.producto_id AND icx{i}.plan_id = :cp{i} AND icx{i}.criterio_id = ANY(:cc{i}))")
            p[f"cp{i}"] = pl; p[f"cc{i}"] = crs
        if con_un and self.un:
            w.append("x.unidad_negocio = ANY(:un)"); p["un"] = self.un
        if con_un and self.canales:
            w.append("x.canal = ANY(:canales)"); p["canales"] = self.canales
        if con_prov and self.provs:
            w.append("x.proveedor_id = ANY(:provs)"); p["provs"] = self.provs
        if self.perm is not None:
            w.append("mi.categoria = ANY(:perm)"); p["perm"] = self.perm
        return joins, " AND ".join(w), p


def _filas(c, sql: str, p: dict) -> list[dict]:
    return [dict(r) for r in c.execute(text(sql), p).mappings()]


def _pct(num, den):
    return None if not den else float(num or 0) / float(den)


def _actualizacion(c) -> list[dict]:
    return _filas(c, "SELECT empresa, tarea, fecha, filas, desde, mensaje FROM ddmrp.rep_actualizacion ORDER BY tarea, empresa", {})


@router.get("/opciones")
def opciones(empresa: str | None = None, user=Depends(requiere("ver_control_compras"))):
    """Listas de los filtros y cuando se actualizo cada tarea. La categoria trae `se_compra` (la que la empresa compra) para preseleccionarla."""
    f = Filtros(user, empresa)
    emp = f.emp or ["05"]
    with pg.connect() as c:
        lab_w, lab_p = ("AND mi.categoria = ANY(:perm)", {"perm": f.perm}) if f.perm is not None else ("", {})
        if f.emp:   # los items son de cada empresa: las listas son las de la empresa elegida
            lab_w += " AND mi.empresa = ANY(:emp_l)"; lab_p = {**lab_p, "emp_l": f.emp}
        labs = _filas(c, f"""SELECT DISTINCT mi.categoria AS id, COALESCE(mi.categoria || ' - ' || NULLIF(lb.nombre, ''), mi.categoria) AS nombre FROM ddmrp.maestro_item mi
                             LEFT JOIN ddmrp.laboratorio lb ON lb.empresa = mi.empresa AND lb.codigo = mi.categoria WHERE COALESCE(mi.categoria, '') <> '' {lab_w} ORDER BY 1""", lab_p)

        def criterios(plan: str) -> list[dict]:
            return _filas(c, """SELECT cr.criterio_id AS id, COALESCE(cr.nombre, cr.criterio_id) AS nombre, COALESCE(cc.se_compra, 1) = 1 AS se_compra
                                FROM ddmrp.criterio cr
                                LEFT JOIN ddmrp.categoria_compra cc ON cc.empresa = :e AND cc.plan_id = cr.plan_id AND cc.criterio_id = cr.criterio_id
                                WHERE cr.plan_id = :plan AND EXISTS (SELECT 1 FROM ddmrp.item_criterio ic WHERE ic.empresa = ANY(:emps) AND ic.plan_id = cr.plan_id AND ic.criterio_id = cr.criterio_id)
                                ORDER BY 1""", {"plan": plan, "e": emp[0], "emps": f.emp or ["05", "21"]})
        cats, accs = criterios(f.p["plan_cat"]), criterios(f.p["plan_acc"])
        # los datos de las listas son los de la empresa elegida en la barra (vacio = ambas)
        pe = {"emp": f.emp} if f.emp else {}
        fe = "AND empresa = ANY(:emp)" if f.emp else ""
        unidades = [r[0] for r in c.execute(text(f"SELECT DISTINCT unidad_negocio FROM ddmrp.rep_venta_mes WHERE unidad_negocio <> '' {fe} ORDER BY 1"), pe).all()]
        canales = [r[0] for r in c.execute(text(f"SELECT DISTINCT canal FROM ddmrp.rep_venta_mes WHERE canal <> '' {fe} ORDER BY 1"), pe).all()]
        rango = c.execute(text(f"""SELECT min(periodo), max(periodo) FROM (SELECT periodo FROM ddmrp.rep_venta_mes WHERE TRUE {fe} UNION ALL
                                   SELECT periodo FROM ddmrp.rep_compra_mes WHERE TRUE {fe} UNION ALL
                                   SELECT mes FROM ddmrp.ventas_mensual WHERE TRUE {fe}) t"""), pe).one()
        act = _actualizacion(c)
        # criterios de items (mismos planes que los filtros de Clasificacion); categoria y accion ya tienen su propio filtro
        crit_rows = c.execute(text("""SELECT ic.plan_id, COALESCE(p.nombre, ic.plan_id), ic.criterio_id, COALESCE(cr.nombre, ic.criterio_id), count(*)
                                      FROM ddmrp.item_criterio ic LEFT JOIN ddmrp.criterio_plan p ON p.empresa = ic.empresa AND p.plan_id = ic.plan_id
                                      LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id
                                      WHERE COALESCE(p.en_filtros, 1) = 1 AND ic.plan_id <> ALL(:excl) AND ic.empresa = ANY(:emp_c) GROUP BY 1, 2, 3, 4 ORDER BY 1, 3"""),
                              {"excl": [f.p["plan_cat"], f.p["plan_acc"]], "emp_c": f.emp or ["05", "21"]}).all()
    por_plan: dict[str, dict] = {}
    for pid, pnom, cid, cnom, n in crit_rows:
        por_plan.setdefault(pid, {"plan_id": pid, "nombre": pnom, "valores": []})["valores"].append({"id": cid, "nombre": cnom, "items": n})
    # empresas con datos traidos: la pantalla avisa si la elegida en la barra aun no tiene
    con_datos = sorted({a["empresa"] for a in act if a.get("fecha") and not a.get("mensaje")})
    return {"labs": labs, "categorias": cats, "acciones": accs, "unidades": unidades, "canales": canales, "periodo_min": rango[0], "periodo_max": rango[1], "actualizacion": act,
            "criterios": list(por_plan.values()), "empresas_con_datos": con_datos, "plan_categoria": f.p["plan_cat"], "plan_accion": f.p["plan_acc"]}


@router.get("/skus")
def buscar_skus(buscar: str = "", empresa: str | None = None, user=Depends(requiere("ver_control_compras"))):
    """Sugerencias para el selector de SKU de los reportes: por codigo o por descripcion, con el codigo EXACTO y los que empiezan por el texto primero.
    El filtro que se guarda es siempre el SKU completo (`skus`), no un texto: buscar 192970 y elegirlo no trae el 2192970."""
    b = (buscar or "").strip()
    if len(b) < 2:
        return []
    f = Filtros(user, empresa)
    w, p = ["(mi.producto_id ILIKE :b OR mi.descripcion ILIKE :b)"], {"b": f"%{b}%", "ex": b, "pre": f"{b}%"}
    if f.emp:
        w.append("mi.empresa = ANY(:emp)"); p["emp"] = f.emp
    if f.perm is not None:
        w.append("mi.categoria = ANY(:perm)"); p["perm"] = f.perm
    with pg.connect() as c:
        return _filas(c, f"""SELECT mi.producto_id AS id, min(mi.descripcion) AS descripcion FROM ddmrp.maestro_item mi WHERE {' AND '.join(w)}
                             GROUP BY mi.producto_id ORDER BY (mi.producto_id = :ex) DESC, (mi.producto_id ILIKE :pre) DESC, mi.producto_id LIMIT 30""", p)


@router.get("/ventas-producto")
def ventas_producto(empresa: str | None = None, desde: str | None = None, hasta: str | None = None, labs: str | None = None, categorias: str | None = None,
                    acciones: str | None = None, un: str | None = None, q: str | None = None, crit: str | None = None, skus: str | None = None, canales: str | None = None, agrupar: str = "producto", limite: int = 3000,
                    user=Depends(requiere("ver_control_compras"))):
    """Ventas facturadas por producto (o por mes y producto con agrupar=mes) con inventario y rotacion, KPI del filtro y la serie mensual."""
    if agrupar not in ("producto", "mes", "canal"):
        raise HTTPException(400, "agrupar debe ser producto, mes o canal")
    f = Filtros(user, empresa, desde, hasta, labs, categorias, acciones, un, q, crit=crit, skus=skus, canales=canales)
    joins, w, p = f.base("ddmrp.rep_venta_mes", con_un=True)
    lim = min(max(int(limite), 10), TOPE_FILAS)
    per = "x.periodo, " if agrupar == "mes" else "x.canal, " if agrupar == "canal" else ""
    with pg.connect() as c:
        kpi = _filas(c, f"""SELECT count(DISTINCT x.producto_id)::int AS items, COALESCE(SUM(x.cantidad), 0)::float8 AS cantidad, COALESCE(SUM(x.valor_bruto), 0)::float8 AS bruto,
                                   COALESCE(SUM(x.descuento), 0)::float8 AS descuento, COALESCE(SUM(x.costo), 0)::float8 AS costo {joins} WHERE {w}""", p)[0]
        serie = _filas(c, f"""SELECT x.periodo, SUM(x.cantidad)::float8 AS cantidad, SUM(x.valor_bruto - x.descuento)::float8 AS neta, SUM(x.costo)::float8 AS costo
                              {joins} WHERE {w} GROUP BY x.periodo ORDER BY x.periodo""", p)
        filas = _filas(c, f"""SELECT {per}x.producto_id, mi.descripcion, COALESCE(mi.categoria || ' - ' || NULLIF(lb.nombre, ''), mi.categoria, '') AS laboratorio, COALESCE(cr1.nombre, ic1.criterio_id, '') AS categoria,
                                     COALESCE(cr3.nombre, ic3.criterio_id, '') AS accion, SUM(x.cantidad)::float8 AS cantidad, SUM(x.valor_bruto)::float8 AS bruto,
                                     SUM(x.descuento)::float8 AS descuento, SUM(x.costo)::float8 AS costo
                              {joins} WHERE {w}
                              GROUP BY {per}x.producto_id, mi.descripcion, lb.nombre, mi.categoria, cr1.nombre, ic1.criterio_id, cr3.nombre, ic3.criterio_id
                              ORDER BY {'x.periodo DESC, ' if agrupar == 'mes' else 'x.canal, ' if agrupar == 'canal' else ''}SUM(x.cantidad) DESC NULLS LAST, x.producto_id LIMIT :lim""", p | {"lim": lim})
        total_filas = c.execute(text(f"SELECT count(*) FROM (SELECT 1 {joins} WHERE {w} GROUP BY {per}x.producto_id) t"), p).scalar() or 0
        # resumen por canal de lo filtrado (siempre: es barato y la pantalla lo muestra al elegir «Por canal»)
        resumen_canal = _filas(c, f"""SELECT x.canal, count(DISTINCT x.producto_id)::int AS items, SUM(x.cantidad)::float8 AS cantidad, SUM(x.valor_bruto)::float8 AS bruto,
                                             SUM(x.descuento)::float8 AS descuento, SUM(x.costo)::float8 AS costo {joins} WHERE {w} GROUP BY x.canal ORDER BY SUM(x.valor_bruto - x.descuento) DESC NULLS LAST""", p)
        ids = sorted({r["producto_id"] for r in filas})
        inv_cedi, inv_tiendas, adu = {}, {}, {}
        if ids:
            fe = " AND empresa = ANY(:emp)" if f.emp else ""
            pe = {"ids": ids} | ({"emp": f.emp} if f.emp else {})
            inv_cedi = dict(c.execute(text(f"SELECT producto_id, SUM(disponible)::float8 FROM ddmrp.inventario_cedi WHERE producto_id = ANY(:ids){fe} GROUP BY 1"), pe).all())
            inv_tiendas = dict(c.execute(text(f"SELECT producto_id, SUM(disponible)::float8 FROM ddmrp.inventario_actual WHERE producto_id = ANY(:ids){fe} GROUP BY 1"), pe).all())
            adu = dict(c.execute(text(f"SELECT producto_id, SUM(adu)::float8 FROM ddmrp.sugerencias_cedi WHERE ejecucion_id = {ULTIMA} AND producto_id = ANY(:ids){fe} GROUP BY 1"), pe).all())
        act = _actualizacion(c)
    for r in filas:
        neta = r["bruto"] - r["descuento"]
        cant = r["cantidad"]
        # unitarios del periodo: costo total / unidades y venta neta (ya sin descuento) / unidades; sin unidades vendidas (o devoluciones que las dejan en 0 o negativas) no hay unitario
        r.update(costo_unit=(r["costo"] / cant) if cant and cant > 0 else None, precio_unit=(neta / cant) if cant and cant > 0 else None)
        r.update(neta=neta, rent=_pct(neta - r["costo"], neta), inv_cedi=inv_cedi.get(r["producto_id"]), inv_tiendas=inv_tiendas.get(r["producto_id"]), adu=adu.get(r["producto_id"]))
    for s in serie:
        s["rent"] = _pct(s["neta"] - s["costo"], s["neta"])
    neta = kpi["bruto"] - kpi["descuento"]
    kpi.update(neta=neta, rent=_pct(neta - kpi["costo"], neta))
    for rc in resumen_canal:
        n = rc["bruto"] - rc["descuento"]
        rc.update(neta=n, margen=n - rc["costo"], rent=_pct(n - rc["costo"], n), part=_pct(n, neta),
                  costo_unit=(rc["costo"] / rc["cantidad"]) if rc["cantidad"] and rc["cantidad"] > 0 else None,
                  precio_unit=(n / rc["cantidad"]) if rc["cantidad"] and rc["cantidad"] > 0 else None)
    for r in filas:
        r["margen"] = r["neta"] - r["costo"]
    return {"kpis": kpi, "serie": serie, "resumen_canal": resumen_canal, "filas": filas, "total_filas": total_filas, "recortado": total_filas > len(filas), "actualizacion": act}


@router.get("/proveedor")
def proveedor(empresa: str | None = None, desde: str | None = None, hasta: str | None = None, labs: str | None = None, categorias: str | None = None,
              acciones: str | None = None, un: str | None = None, q: str | None = None, proveedores: str | None = None, crit: str | None = None, skus: str | None = None, limite: int = 3000,
              user=Depends(requiere("ver_control_compras"))):
    """Ficha de proveedor / producto terminado: compras vs ventas netas y % rent por mes, OTIF por mes, productos con su venta y su compra y los proveedores con mas compras.
    La unidad de negocio solo filtra las ventas; el proveedor solo filtra las compras y el OTIF."""
    f = Filtros(user, empresa, desde, hasta, labs, categorias, acciones, un, q, proveedores, crit=crit, skus=skus)
    jv, wv, pv = f.base("ddmrp.rep_venta_mes", con_un=True)
    jc, wc, pc = f.base("ddmrp.rep_compra_mes", con_prov=True)
    jo, wo, po = f.base("ddmrp.rep_otif", con_prov=True)
    lim = min(max(int(limite), 10), TOPE_FILAS)
    with pg.connect() as c:
        ventas = _filas(c, f"SELECT x.periodo, SUM(x.valor_bruto - x.descuento)::float8 AS ventas, SUM(x.costo)::float8 AS costo, SUM(x.cantidad)::float8 AS cant_v {jv} WHERE {wv} GROUP BY 1", pv)
        compras = _filas(c, f"SELECT x.periodo, SUM(x.valor)::float8 AS compras, SUM(x.cantidad)::float8 AS cant_c {jc} WHERE {wc} GROUP BY 1", pc)
        otif = _filas(c, f"""SELECT x.periodo, AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, AVG((x.completa * x.a_tiempo)::int)::float8 AS otif, count(*)::int AS lineas {jo}
                             WHERE {wo} AND x.periodo IS NOT NULL GROUP BY 1""", po)
        productos = _filas(c, f"""WITH ve AS (SELECT x.empresa, x.producto_id, SUM(x.cantidad) AS cant_v, SUM(x.valor_bruto - x.descuento) AS ventas, SUM(x.costo) AS costo {jv} WHERE {wv} GROUP BY 1, 2),
                                       co AS (SELECT x.empresa, x.producto_id, SUM(x.cantidad) AS cant_c, SUM(x.valor) AS compras {jc} WHERE {wc} GROUP BY 1, 2)
                                  SELECT COALESCE(ve.empresa, co.empresa) AS empresa, COALESCE(ve.producto_id, co.producto_id) AS producto_id, mi.descripcion, COALESCE(mi.categoria || ' - ' || NULLIF(lb.nombre, ''), mi.categoria, '') AS laboratorio,
                                         COALESCE(ve.cant_v, 0)::float8 AS cant_v, COALESCE(ve.ventas, 0)::float8 AS ventas, COALESCE(ve.costo, 0)::float8 AS costo,
                                         COALESCE(co.cant_c, 0)::float8 AS cant_c, COALESCE(co.compras, 0)::float8 AS compras
                                  FROM ve FULL JOIN co ON co.empresa = ve.empresa AND co.producto_id = ve.producto_id
                                  LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = COALESCE(ve.empresa, co.empresa) AND mi.producto_id = COALESCE(ve.producto_id, co.producto_id)
                                  LEFT JOIN ddmrp.laboratorio lb ON lb.empresa = mi.empresa AND lb.codigo = mi.categoria
                                  ORDER BY COALESCE(co.compras, 0) + COALESCE(ve.ventas, 0) DESC, 1 LIMIT :lim""", pv | pc | {"lim": lim})
        provs = _filas(c, f"""WITH co AS (SELECT x.proveedor_id, max(x.proveedor_nombre) AS nombre, SUM(x.valor) AS compras, count(DISTINCT x.producto_id) AS items {jc} WHERE {wc} GROUP BY 1),
                                   ot AS (SELECT x.proveedor_id, AVG(x.completa) AS infull, AVG(x.a_tiempo) AS ontime, count(*) AS lineas {jo} WHERE {wo} GROUP BY 1)
                              SELECT co.proveedor_id, co.nombre, co.compras::float8 AS compras, co.items::int AS items, ot.infull::float8 AS infull, ot.ontime::float8 AS ontime,
                                     COALESCE(ot.lineas, 0)::int AS lineas
                              FROM co LEFT JOIN ot ON ot.proveedor_id = co.proveedor_id ORDER BY co.compras DESC NULLS LAST LIMIT 15""", pc | po)
        kot = _filas(c, f"SELECT AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, AVG((x.completa * x.a_tiempo)::int)::float8 AS otif, count(*)::int AS lineas {jo} WHERE {wo}", po)[0]
        act = _actualizacion(c)
    por = {}
    for fila in ventas:
        por.setdefault(fila["periodo"], {})["v"] = fila
    for fila in compras:
        por.setdefault(fila["periodo"], {})["c"] = fila
    for fila in otif:
        por.setdefault(fila["periodo"], {})["o"] = fila
    serie = []
    for per in sorted(por):
        v, co, o = por[per].get("v"), por[per].get("c"), por[per].get("o")
        ven, cos = (v["ventas"] if v else 0.0), (v["costo"] if v else 0.0)
        serie.append({"periodo": per, "ventas": ven, "compras": co["compras"] if co else 0.0, "rent": _pct(ven - cos, ven), "infull": o["infull"] if o else None,
                      "ontime": o["ontime"] if o else None, "lineas_otif": o["lineas"] if o else 0})
    tv, tc = sum(s["ventas"] for s in serie), sum(s["compras"] for s in serie)
    tcosto = sum(r["costo"] for r in ventas)
    for r in productos:
        r["rent"] = _pct(r["ventas"] - r["costo"], r["ventas"])
    return {"serie": serie, "productos": productos, "proveedores": provs, "recortado": len(productos) >= lim, "actualizacion": act,
            "kpis": {"compras": tc, "ventas": tv, "rent": _pct(tv - tcosto, tv), "compras_sobre_ventas": _pct(tc, tv), "infull": kot["infull"], "ontime": kot["ontime"], "lineas_otif": kot["lineas"]}}


def _meses_atras(p: str, n: int) -> str:
    t = int(p[:4]) * 12 + int(p[4:]) - 1 - n
    return f"{t // 12}{t % 12 + 1:02d}"


def _meses(desde: str, hasta: str) -> list[str]:
    """Periodos AAAAMM de desde a hasta (maximo 60)."""
    out, y, m = [], int(desde[:4]), int(desde[4:])
    while f"{y:04d}{m:02d}" <= hasta and len(out) < 60:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _dias_mes(p: str, hoy: date) -> int:
    """Dias del mes; el mes en curso cuenta solo hasta hoy (la venta y el inventario llegan hasta hoy)."""
    y, m = int(p[:4]), int(p[4:])
    fin = date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)
    return ((min(fin, hoy) - date(y, m, 1)).days + 1) if date(y, m, 1) <= hoy else 0


@router.get("/indicadores", dependencies=[Depends(fijar_modo)])
def indicadores(empresa: str | None = None, desde: str | None = None, hasta: str | None = None, labs: str | None = None, categorias: str | None = None,
                acciones: str | None = None, crit: str | None = None, q: str | None = None, skus: str | None = None, agrupar: str = "laboratorio", limite: int = 3000,
                user=Depends(requiere("ver_control_compras"))):
    """Indicadores de compras por mes en el periodo elegido: GMROI, OTIF (completo y a tiempo) y % de abastecimiento (el «disponible» de la tendencia del Control: todas las
    zonas menos la roja), mas margen e inventario a costo. El GMROI usa el MISMO calculo de la Clasificacion (venta de las tiendas, costo promedio actual e inventario promedio
    de la foto mensual), asi las cifras coinciden; con ?solo_cedi=true mide el CEDI. Del periodo completo salen las bandas segun el minimo y la meta de Reglas de compras, el
    capital en cada banda, el inventario que sobra para llegar a la meta, los grupos por laboratorio o criterio y los productos. El GMROI y el abastecimiento solo existen
    donde hay inventario mensual guardado (13 meses): antes de eso el mes queda sin dato."""
    from sqlalchemy.exc import DBAPIError
    from .. import clasificacion as cl
    if agrupar != "laboratorio" and not re.fullmatch(r"\w{1,10}", agrupar):
        raise HTTPException(400, "agrupar debe ser laboratorio o el codigo de un plan de criterios")
    f = Filtros(user, empresa, desde, hasta, labs, categorias, acciones, None, q, None, crit=crit, skus=skus)
    hoy = date.today()
    h_p = f.hasta or f"{hoy:%Y%m}"
    d_p = f.desde or _meses_atras(h_p, 11)
    if d_p > h_p:
        d_p, h_p = h_p, d_p
    periodos = _meses(d_p, h_p)
    cr = [f"{f.p['plan_cat']}:{x}" for x in f.cats] + [f"{f.p['plan_acc']}:{x}" for x in f.accs] + [f"{pl}:{v}" for pl, vs in f.crit.items() for v in vs]
    crit_s = ",".join(cr)
    cfg = cfg_rep()
    minimo, objetivo = float(cfg.get("rep_gmroi_minimo", 1.0)), float(cfg.get("rep_gmroi_meta", 3.2))
    cedi = solo_cedi()
    alc = "cedi" if cedi else "tiendas"
    f.desde, f.hasta = d_p, h_p       # el OTIF se limita al mismo periodo
    jo, wo, po = f.base("ddmrp.rep_otif")
    t0 = time.monotonic()
    avisos: list[str] = []
    w_emp = " AND m.empresa = ANY(:emp)" if f.emp else ""
    base_p = {"alc": alc, "per_d": d_p, "per_h": h_p, **({"emp": f.emp} if f.emp else {})}

    def paso(nombre, fn, defecto, critico=False):
        """Cada bloque con su propia conexion y con el tiempo que queda del presupuesto (menos que el limite de 60 s del nginx). Si un bloque no alcanza, el resto igual se
        muestra y el aviso dice cual fallo; solo el primero (los productos del filtro) es indispensable."""
        resto = max(3, int(PRESUPUESTO_S - (time.monotonic() - t0)))
        t1 = time.monotonic()
        try:
            with pg.connect() as c:
                c.execute(text(f"SET LOCAL statement_timeout = {resto * 1000}"))
                r = fn(c)
            log.info("indicadores · %s: %.1f s", nombre, time.monotonic() - t1)
            return r
        except DBAPIError as e:
            if "statement timeout" not in str(e):
                raise
            log.warning("indicadores · %s: sin tiempo tras %.1f s", nombre, time.monotonic() - t1)
            if critico:
                raise HTTPException(503, "El informe tardo demasiado. Acorta el periodo o acota con un laboratorio.")
            avisos.append(nombre)
            return defecto

    def _ids(c):
        # los filtros de item (y los laboratorios que el perfil permite) se resuelven UNA vez a la lista de productos; el calculo diario ya dejo solo items activos del maestro
        wi, pi = ["true"], {}
        if f.emp:
            wi.append("mi2.empresa = ANY(:i_emp)"); pi["i_emp"] = f.emp
        if f.perm is not None:
            wi.append("mi2.categoria = ANY(:i_perm)"); pi["i_perm"] = f.perm
        if f.labs:
            wi.append("COALESCE(mi2.categoria, '') = ANY(:i_lab)"); pi["i_lab"] = [("" if x == "(sin laboratorio)" else x) for x in f.labs]
        if f.q:
            wi.append("(mi2.producto_id ILIKE :i_q OR mi2.descripcion ILIKE :i_q)"); pi["i_q"] = f"%{f.q}%"
        if f.skus:
            wi.append("mi2.producto_id = ANY(:i_sk)"); pi["i_sk"] = f.skus
        por_plan: dict[str, list[str]] = {}
        for x in cr:
            pl, v = x.split(":", 1); por_plan.setdefault(pl, []).append(v)
        for i, (pl, vs) in enumerate(por_plan.items()):
            wi.append(f"EXISTS (SELECT 1 FROM ddmrp.item_criterio xc{i} WHERE xc{i}.empresa = mi2.empresa AND xc{i}.producto_id = mi2.producto_id AND xc{i}.plan_id = :xp{i} AND xc{i}.criterio_id = ANY(:xv{i}))")
            pi[f"xp{i}"] = pl; pi[f"xv{i}"] = vs
        ids_ = list({r[0] for r in c.execute(text("SELECT mi2.producto_id FROM ddmrp.maestro_item mi2 WHERE " + " AND ".join(wi)), pi)})
        pr, ca = c.execute(text("SELECT min(mes) FILTER (WHERE dias > 0), max(calculado) FROM ddmrp.rep_indicadores_mes WHERE alcance = :a"), {"a": alc}).one()
        return ids_, pr, ca

    ids, primer, calculado = paso("productos del filtro", _ids, ([], None, None), critico=True)
    base_p["ids"] = ids
    d_g = max(d_p, primer) if primer else d_p          # el inventario promedio solo existe desde que hay foto mensual: antes se usaria el de hoy y distorsiona
    dias_g = max((min(date(int(h_p[:4]) + (h_p[4:] == "12"), 1 if h_p[4:] == "12" else int(h_p[4:]) + 1, 1) - timedelta(days=1), hoy) - date(int(d_g[:4]), int(d_g[4:]), 1)).days + 1, 1)

    # todo sale de ddmrp.rep_indicadores_mes / rep_indicadores_item, que se calculan aparte (corrida diaria de reportes o boton «Recalcular»): aqui solo se suma
    mensual = paso("serie por mes", lambda c: {r["mes"]: dict(r) for r in c.execute(text(f"""
        SELECT m.mes, SUM(m.valor)::float8 AS venta, SUM(CASE WHEN ci.costo IS NOT NULL THEN m.valor - m.cant * ci.costo END)::float8 AS margen,
               SUM(CASE WHEN ci.costo IS NOT NULL THEN m.cant * ci.costo END)::float8 AS costo_venta,
               SUM(CASE WHEN m.dias > 0 AND ci.costo IS NOT NULL THEN m.inv_prom * ci.costo END)::float8 AS inv_costo,
               SUM(m.dias_roja)::float8 AS roja, SUM(m.dias_ag)::float8 AS ag, SUM(m.dias_z)::float8 AS dz
        FROM ddmrp.rep_indicadores_mes m LEFT JOIN ddmrp.costo_item ci ON ci.empresa = m.empresa AND ci.producto_id = m.producto_id
        WHERE m.alcance = :alc AND m.mes BETWEEN :per_d AND :per_h AND m.producto_id = ANY(:ids){w_emp} GROUP BY m.mes"""), base_p).mappings()}, {})
    inv = ven = mensual
    ot = paso("OTIF por mes", lambda c: {r["mes"]: dict(r) for r in c.execute(text(f"""
        SELECT x.periodo AS mes, AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, AVG((x.completa * x.a_tiempo)::int)::float8 AS otif, count(*)::int AS lineas
        {jo} WHERE {wo} AND x.periodo IS NOT NULL GROUP BY 1"""), po).mappings()}, {})
    kot = paso("OTIF del periodo", lambda c: dict(c.execute(text(f"SELECT AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, AVG((x.completa * x.a_tiempo)::int)::float8 AS otif, count(*)::int AS lineas {jo} WHERE {wo} AND x.periodo IS NOT NULL"), po).mappings().one()),
               {"infull": None, "ontime": None, "otif": None, "lineas": 0})

    def _nombres(c):
        nl = dict(c.execute(text("SELECT codigo, nombre FROM ddmrp.laboratorio")).all())
        if agrupar == "laboratorio":
            return nl, None, {}, "Laboratorio"
        gn = c.execute(text("SELECT min(nombre) FROM ddmrp.criterio_plan WHERE plan_id = :p"), {"p": agrupar}).scalar() or agrupar
        v = {(e, p): cr_id for e, p, cr_id in c.execute(text("SELECT empresa, producto_id, criterio_id FROM ddmrp.item_criterio WHERE plan_id = :p"), {"p": agrupar}).all()}
        return nl, v, dict(c.execute(text("SELECT criterio_id, nombre FROM ddmrp.criterio WHERE plan_id = :p"), {"p": agrupar}).all()), gn
    nom_lab, val, nom, grupo_nombre = paso("nombres", _nombres, ({}, None, {}, "Laboratorio" if agrupar == "laboratorio" else agrupar))

    def _items(c):
        w_s = " AND empresa = ANY(:emp)" if f.emp else ""
        return [dict(r) for r in c.execute(text(f"""
            WITH a AS (
              SELECT m.empresa, m.producto_id, SUM(m.cant)::float8 AS cant, SUM(m.valor)::float8 AS valor, SUM(m.dias)::int AS dias, SUM(m.inv_prom * m.dias)::float8 AS inv_pd,
                     SUM(m.dias_tot)::int AS dt, SUM(m.dias_cero)::int AS dc, MIN(m.mes) FILTER (WHERE m.cant > 0) AS primer_mes
              FROM ddmrp.rep_indicadores_mes m
              WHERE m.alcance = :alc AND m.mes BETWEEN :d_g AND :per_h AND m.producto_id = ANY(:ids){w_emp} GROUP BY 1, 2),
            s AS (SELECT empresa, producto_id, inventario FROM ddmrp.rep_indicadores_item WHERE alcance = :alc AND producto_id = ANY(:ids){w_s}),
            k AS (SELECT COALESCE(a.empresa, s.empresa) AS empresa, COALESCE(a.producto_id, s.producto_id) AS producto_id, a.cant, a.valor, a.dias, a.inv_pd, a.dt, a.dc, a.primer_mes, s.inventario
                  FROM a FULL JOIN s ON s.empresa = a.empresa AND s.producto_id = a.producto_id)
            SELECT k.*, mi.descripcion, COALESCE(mi.categoria, '(sin laboratorio)') AS laboratorio, ci.costo::float8 AS costo
            FROM k LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = k.empresa AND mi.producto_id = k.producto_id
                   LEFT JOIN ddmrp.costo_item ci ON ci.empresa = k.empresa AND ci.producto_id = k.producto_id
            WHERE COALESCE(k.cant, 0) > 0 OR COALESCE(k.valor, 0) > 0 OR COALESCE(k.inventario, 0) > 0"""), {**base_p, "d_g": d_g}).mappings()]
    filas = paso("productos", _items, [])
    items = []
    for r in filas:
        dias, inv_hoy = int(r["dias"] or 0), max(float(r["inventario"] or 0.0), 0.0)
        items.append({"producto_id": r["producto_id"], "empresa": r["empresa"], "bodega_id": None, "descripcion": r["descripcion"], "laboratorio": r["laboratorio"], "costo": r["costo"],
                      "cant": float(r["cant"] or 0.0), "valor": float(r["valor"] or 0.0), "inventario": inv_hoy, "dias_hist": dias, "primer_mes": r["primer_mes"], "adu": 0.0, "iv": None,
                      "inv_prom": (float(r["inv_pd"] or 0.0) / dias) if dias > 0 else inv_hoy,      # sin foto mensual en el periodo (item nuevo) se usa el inventario de hoy
                      "pct_sin_stock": None if not r["dt"] else 100.0 * (r["dc"] or 0) / r["dt"]})
    if items:
        cl.calcular(items, dias_g)
        cl.clasificar(items, "margen", 80, 95, None, (0.5, 0.8), "pareto", 93.0)
        gm.enriquecer(items, dias_g, minimo, objetivo)
    serie = gm.unir_series(periodos, {p: _dias_mes(p, hoy) for p in periodos}, ven, inv, ot)
    etq_lab = lambda k: k if k.startswith("(") or not (nom_lab.get(k) or "").strip() else f"{k} - {nom_lab[k].strip()}"      # noqa: E731
    if val is None:
        grupos = gm.por_grupo(items, lambda it: it.get("laboratorio") or "(sin laboratorio)", etq_lab)
    else:
        grupos = gm.por_grupo(items, lambda it: val.get((it["empresa"], it["producto_id"])) or "", lambda k: ((nom.get(k) or k).strip() if k else "(sin valor)"))
    kp = gm.agregar(items)
    bandas = gm.por_banda(items)
    kp["capital_bajo"] = sum(b["inv_prom_costo"] for b in bandas if b["banda"] == "bajo")
    kp["capital_sin_venta"] = sum(b["inv_prom_costo"] for b in bandas if b["banda"] == "sin_venta")
    kp["pct_capital_bajo"] = None if kp["inv_prom_costo"] <= 0 else 100.0 * kp["capital_bajo"] / kp["inv_prom_costo"]
    dz = sum(i.get("dz") or 0 for i in inv.values())
    kp["abast"] = None if dz <= 0 else 1.0 - sum(i.get("roja") or 0 for i in inv.values()) / dz
    kp["agot"] = None if dz <= 0 else sum(i.get("ag") or 0 for i in inv.values()) / dz      # % agotado: combinaciones con buffer e inventario 0 (la linea punteada del Control)
    kp.update(infull=kot["infull"], ontime=kot["ontime"], otif=kot["otif"], lineas_otif=kot["lineas"])
    lim = min(max(int(limite), 10), TOPE_FILAS)
    orden = sorted(items, key=lambda it: (-(it.get("inv_prom_costo") or 0.0), it["producto_id"]))
    campos = ("producto_id", "descripcion", "abc", "cant", "valor", "margen", "margen_pct", "inv_costo", "inv_prom_costo", "gmroi", "rot", "meses_inv", "pct_sin_stock", "dias_hist", "banda", "capital_exceso")
    filas_out = [{**{k: it.get(k) for k in campos}, "laboratorio": etq_lab(it.get("laboratorio") or "(sin laboratorio)")} for it in orden[:lim]]
    sin_hist = sum(1 for it in items if (it.get("inv_prom_costo") or 0) > 0 and not it.get("dias_hist"))
    return {"meta": {"desde": d_p, "hasta": h_p, "desde_gmroi": d_g, "dias": dias_g, "minimo": minimo, "objetivo": objetivo, "alcance": "cedi" if cedi else "tiendas",
                     "items_sin_historia": sin_hist, "primer_mes_inventario": primer, "avisos": avisos, "calculado": calculado.isoformat() if calculado else None},
            "serie": serie, "kpis": kp, "bandas": bandas, "grupo_nombre": grupo_nombre, "grupos": grupos, "puntos": gm.puntos(items), "filas": filas_out,
            "total_filas": len(items), "recortado": len(items) > len(filas_out)}


class Actualizar(BaseModel):
    completo: bool = False


@router.post("/actualizar")
def actualizar(b: Actualizar, bg: BackgroundTasks, user=Depends(requiere("gestionar_compras", "correr_motor"))):
    """Trae de Siesa el historico de ventas, compras y OTIF, en segundo plano (la pantalla sigue el progreso). completo = relee toda la historia, no solo los ultimos meses."""
    progreso.exigir_libre()
    bg.add_task(_actualizar_y_calcular, usuario_de(user), b.completo)
    return {"estado": "lanzado"}


def _actualizar_y_calcular(usuario, completo: bool) -> None:
    """El boton «Actualizar datos»: trae de Siesa y, al terminar (aunque la descarga falle), recalcula los indicadores con lo guardado."""
    from ..etl.reportes_compras import calcular_indicadores
    try:
        sincronizar_reportes_compras("manual", usuario, completo)
    finally:
        calcular_indicadores("manual", usuario)


@router.post("/indicadores/recalcular")
def recalcular_indicadores(bg: BackgroundTasks, user=Depends(requiere("gestionar_compras", "correr_motor"))):
    """Recalcula en segundo plano los indicadores de compras (sin ir a Siesa): lo mismo que hace la corrida diaria. La pantalla sigue el progreso."""
    from ..etl.reportes_compras import calcular_indicadores
    progreso.exigir_libre()
    bg.add_task(calcular_indicadores, "manual", usuario_de(user))
    return {"estado": "lanzado"}
