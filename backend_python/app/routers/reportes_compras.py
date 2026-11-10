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
from ..bitacora import usuario_de
from ..db import pg
from ..etl.reportes_compras import config as cfg_rep, sincronizar_reportes_compras
from ..security import asignaciones, requiere

router = APIRouter(prefix="/compras/reportes", tags=["compras"], dependencies=[Depends(requiere("ver_control_compras"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
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

    def __init__(self, user, empresa=None, desde=None, hasta=None, labs=None, categorias=None, acciones=None, un=None, q=None, proveedores=None):
        cfg = cfg_rep()
        self.p: dict = {"plan_cat": _plan(cfg.get("rep_plan_categoria", 1)), "plan_acc": _plan(cfg.get("rep_plan_accion", 3))}
        self.emp = _csv(empresa)
        self.desde, self.hasta = (desde or "").strip(), (hasta or "").strip()
        for nombre, v in (("desde", self.desde), ("hasta", self.hasta)):
            if v and not (v.isdigit() and len(v) == 6):
                raise HTTPException(400, f"El periodo «{nombre}» debe ser AAAAMM (ej. 202601)")
        self.labs, self.cats, self.accs, self.un = _csv(labs), _csv(categorias), _csv(acciones), _csv(un)
        self.q, self.provs = (q or "").strip(), _csv(proveedores)
        self.perm = _labs_permitidos(user)

    def base(self, tabla: str, con_un: bool = False, con_prov: bool = False) -> tuple[str, str, dict]:
        joins = f"""FROM {tabla} x
            LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = x.producto_id
            LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
            LEFT JOIN ddmrp.item_criterio ic1 ON ic1.producto_id = x.producto_id AND ic1.plan_id = :plan_cat
            LEFT JOIN ddmrp.criterio cr1 ON cr1.plan_id = ic1.plan_id AND cr1.criterio_id = ic1.criterio_id
            LEFT JOIN ddmrp.item_criterio ic3 ON ic3.producto_id = x.producto_id AND ic3.plan_id = :plan_acc
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
        if con_un and self.un:
            w.append("x.unidad_negocio = ANY(:un)"); p["un"] = self.un
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
        labs = _filas(c, f"""SELECT DISTINCT mi.categoria AS id, COALESCE(lb.nombre, mi.categoria) AS nombre FROM ddmrp.maestro_item mi
                             LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria WHERE COALESCE(mi.categoria, '') <> '' {lab_w} ORDER BY 2""", lab_p)

        def criterios(plan: str) -> list[dict]:
            return _filas(c, """SELECT cr.criterio_id AS id, COALESCE(cr.nombre, cr.criterio_id) AS nombre, COALESCE(cc.se_compra, 1) = 1 AS se_compra
                                FROM ddmrp.criterio cr
                                LEFT JOIN ddmrp.categoria_compra cc ON cc.empresa = :e AND cc.plan_id = cr.plan_id AND cc.criterio_id = cr.criterio_id
                                WHERE cr.plan_id = :plan AND EXISTS (SELECT 1 FROM ddmrp.item_criterio ic WHERE ic.plan_id = cr.plan_id AND ic.criterio_id = cr.criterio_id)
                                ORDER BY 1""", {"plan": plan, "e": emp[0]})
        cats, accs = criterios(f.p["plan_cat"]), criterios(f.p["plan_acc"])
        unidades = [r[0] for r in c.execute(text("SELECT DISTINCT unidad_negocio FROM ddmrp.rep_venta_mes WHERE unidad_negocio <> '' ORDER BY 1")).all()]
        rango = c.execute(text("""SELECT min(periodo), max(periodo) FROM (SELECT periodo FROM ddmrp.rep_venta_mes UNION ALL SELECT periodo FROM ddmrp.rep_compra_mes) t""")).one()
        act = _actualizacion(c)
    return {"labs": labs, "categorias": cats, "acciones": accs, "unidades": unidades, "periodo_min": rango[0], "periodo_max": rango[1], "actualizacion": act}


@router.get("/ventas-producto")
def ventas_producto(empresa: str | None = None, desde: str | None = None, hasta: str | None = None, labs: str | None = None, categorias: str | None = None,
                    acciones: str | None = None, un: str | None = None, q: str | None = None, agrupar: str = "producto", limite: int = 3000,
                    user=Depends(requiere("ver_control_compras"))):
    """Ventas facturadas por producto (o por mes y producto con agrupar=mes) con inventario y rotacion, KPI del filtro y la serie mensual."""
    if agrupar not in ("producto", "mes"):
        raise HTTPException(400, "agrupar debe ser producto o mes")
    f = Filtros(user, empresa, desde, hasta, labs, categorias, acciones, un, q)
    joins, w, p = f.base("ddmrp.rep_venta_mes", con_un=True)
    lim = min(max(int(limite), 10), TOPE_FILAS)
    per = "x.periodo, " if agrupar == "mes" else ""
    with pg.connect() as c:
        kpi = _filas(c, f"""SELECT count(DISTINCT x.producto_id)::int AS items, COALESCE(SUM(x.cantidad), 0)::float8 AS cantidad, COALESCE(SUM(x.valor_bruto), 0)::float8 AS bruto,
                                   COALESCE(SUM(x.descuento), 0)::float8 AS descuento, COALESCE(SUM(x.costo), 0)::float8 AS costo {joins} WHERE {w}""", p)[0]
        serie = _filas(c, f"""SELECT x.periodo, SUM(x.cantidad)::float8 AS cantidad, SUM(x.valor_bruto - x.descuento)::float8 AS neta, SUM(x.costo)::float8 AS costo
                              {joins} WHERE {w} GROUP BY x.periodo ORDER BY x.periodo""", p)
        filas = _filas(c, f"""SELECT {per}x.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio, COALESCE(cr1.nombre, ic1.criterio_id, '') AS categoria,
                                     COALESCE(cr3.nombre, ic3.criterio_id, '') AS accion, SUM(x.cantidad)::float8 AS cantidad, SUM(x.valor_bruto)::float8 AS bruto,
                                     SUM(x.descuento)::float8 AS descuento, SUM(x.costo)::float8 AS costo
                              {joins} WHERE {w}
                              GROUP BY {per}x.producto_id, mi.descripcion, lb.nombre, mi.categoria, cr1.nombre, ic1.criterio_id, cr3.nombre, ic3.criterio_id
                              ORDER BY {'x.periodo DESC, ' if agrupar == 'mes' else ''}SUM(x.cantidad) DESC NULLS LAST, x.producto_id LIMIT :lim""", p | {"lim": lim})
        total_filas = c.execute(text(f"SELECT count(*) FROM (SELECT 1 {joins} WHERE {w} GROUP BY {per}x.producto_id) t"), p).scalar() or 0
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
        r.update(neta=neta, rent=_pct(neta - r["costo"], neta), inv_cedi=inv_cedi.get(r["producto_id"]), inv_tiendas=inv_tiendas.get(r["producto_id"]), adu=adu.get(r["producto_id"]))
    for s in serie:
        s["rent"] = _pct(s["neta"] - s["costo"], s["neta"])
    neta = kpi["bruto"] - kpi["descuento"]
    kpi.update(neta=neta, rent=_pct(neta - kpi["costo"], neta))
    return {"kpis": kpi, "serie": serie, "filas": filas, "total_filas": total_filas, "recortado": total_filas > len(filas), "actualizacion": act}


@router.get("/proveedor")
def proveedor(empresa: str | None = None, desde: str | None = None, hasta: str | None = None, labs: str | None = None, categorias: str | None = None,
              acciones: str | None = None, un: str | None = None, q: str | None = None, proveedores: str | None = None, limite: int = 3000,
              user=Depends(requiere("ver_control_compras"))):
    """Ficha de proveedor / producto terminado: compras vs ventas netas y % rent por mes, OTIF por mes, productos con su venta y su compra y los proveedores con mas compras.
    La unidad de negocio solo filtra las ventas; el proveedor solo filtra las compras y el OTIF."""
    f = Filtros(user, empresa, desde, hasta, labs, categorias, acciones, un, q, proveedores)
    jv, wv, pv = f.base("ddmrp.rep_venta_mes", con_un=True)
    jc, wc, pc = f.base("ddmrp.rep_compra_mes", con_prov=True)
    jo, wo, po = f.base("ddmrp.rep_otif", con_prov=True)
    lim = min(max(int(limite), 10), TOPE_FILAS)
    with pg.connect() as c:
        ventas = _filas(c, f"SELECT x.periodo, SUM(x.valor_bruto - x.descuento)::float8 AS ventas, SUM(x.costo)::float8 AS costo, SUM(x.cantidad)::float8 AS cant_v {jv} WHERE {wv} GROUP BY 1", pv)
        compras = _filas(c, f"SELECT x.periodo, SUM(x.valor)::float8 AS compras, SUM(x.cantidad)::float8 AS cant_c {jc} WHERE {wc} GROUP BY 1", pc)
        otif = _filas(c, f"""SELECT x.periodo, AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, count(*)::int AS lineas {jo}
                             WHERE {wo} AND x.periodo IS NOT NULL GROUP BY 1""", po)
        productos = _filas(c, f"""WITH ve AS (SELECT x.producto_id, SUM(x.cantidad) AS cant_v, SUM(x.valor_bruto - x.descuento) AS ventas, SUM(x.costo) AS costo {jv} WHERE {wv} GROUP BY 1),
                                       co AS (SELECT x.producto_id, SUM(x.cantidad) AS cant_c, SUM(x.valor) AS compras {jc} WHERE {wc} GROUP BY 1)
                                  SELECT COALESCE(ve.producto_id, co.producto_id) AS producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria, '') AS laboratorio,
                                         COALESCE(ve.cant_v, 0)::float8 AS cant_v, COALESCE(ve.ventas, 0)::float8 AS ventas, COALESCE(ve.costo, 0)::float8 AS costo,
                                         COALESCE(co.cant_c, 0)::float8 AS cant_c, COALESCE(co.compras, 0)::float8 AS compras
                                  FROM ve FULL JOIN co ON co.producto_id = ve.producto_id
                                  LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = COALESCE(ve.producto_id, co.producto_id)
                                  LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
                                  ORDER BY COALESCE(co.compras, 0) + COALESCE(ve.ventas, 0) DESC, 1 LIMIT :lim""", pv | pc | {"lim": lim})
        provs = _filas(c, f"""WITH co AS (SELECT x.proveedor_id, max(x.proveedor_nombre) AS nombre, SUM(x.valor) AS compras, count(DISTINCT x.producto_id) AS items {jc} WHERE {wc} GROUP BY 1),
                                   ot AS (SELECT x.proveedor_id, AVG(x.completa) AS infull, AVG(x.a_tiempo) AS ontime, count(*) AS lineas {jo} WHERE {wo} GROUP BY 1)
                              SELECT co.proveedor_id, co.nombre, co.compras::float8 AS compras, co.items::int AS items, ot.infull::float8 AS infull, ot.ontime::float8 AS ontime,
                                     COALESCE(ot.lineas, 0)::int AS lineas
                              FROM co LEFT JOIN ot ON ot.proveedor_id = co.proveedor_id ORDER BY co.compras DESC NULLS LAST LIMIT 15""", pc | po)
        kot = _filas(c, f"SELECT AVG(x.completa)::float8 AS infull, AVG(x.a_tiempo)::float8 AS ontime, count(*)::int AS lineas {jo} WHERE {wo}", po)[0]
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


class Actualizar(BaseModel):
    completo: bool = False


@router.post("/actualizar")
def actualizar(b: Actualizar, bg: BackgroundTasks, user=Depends(requiere("gestionar_compras", "correr_motor"))):
    """Trae de Siesa el historico de ventas, compras y OTIF, en segundo plano (la pantalla sigue el progreso). completo = relee toda la historia, no solo los ultimos meses."""
    progreso.exigir_libre()
    bg.add_task(sincronizar_reportes_compras, "manual", usuario_de(user), b.completo)
    return {"estado": "lanzado"}
