"""Tablero de compras: foto del momento para el equipo de compras (solo lectura). Junta lo que ya calculan Necesidades de compra, las OC y los transitos:
que pedir hoy, OC en vuelo, lo pedido y no recibido, riesgo de desabastecimiento, exceso y cumplimiento del proceso. Los umbrales viven en ddmrp.compras_config."""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from ..db import pg
from ..security import requiere, filtro_sql_permisos
from .compras import _necesidades, ULTIMA, CONSIG
from .oc import _cfg_revision

router = APIRouter(prefix="/compras/tablero", tags=["compras"], dependencies=[Depends(requiere("ver_compras"))])
CFG_DEFECTO = {"tablero_dias_trabada": 2.0, "tablero_dias_cumplimiento": 30.0, "tablero_leadtime_defecto": 30.0, "tablero_top": 30.0}
COSTO = "COALESCE(ic.cotizacion, ic.cotizacion_siesa, ic.ultimo_costo)"


def _cfg() -> dict:
    cfg = dict(CFG_DEFECTO)
    try:
        with pg.connect() as c:
            for k, v in c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config WHERE clave LIKE 'tablero\\_%' AND valor IS NOT NULL")).all():
                if k in cfg:
                    cfg[k] = v
    except Exception:    # noqa: BLE001
        pass
    return cfg


def _filas(c, sql: str, p: dict | None = None) -> list[dict]:
    return [dict(r) for r in c.execute(text(sql), p or {}).mappings()]


@router.get("")
def tablero(user=Depends(requiere("ver_compras"))):
    cfg = _cfg()
    top = int(cfg["tablero_top"])
    # ---- 1. Que pedir hoy (lo mismo que ve Necesidades de compra) ----
    r = _necesidades(user, None, None, None, None, None, None, 20000)
    filas = [f for f in r["filas"] if (f["qty_pedir"] or 0) > 0]
    zonas: dict[str, dict] = {}
    for f in filas:
        z = zonas.setdefault(f["zona"], {"zona": f["zona"], "items": 0, "valor": 0.0})
        z["items"] += 1; z["valor"] += f["valor"] or 0
    cons = [f for f in filas if f.get("consignacion")]
    pedir = {
        "totales": r["totales"], "aviso": r["aviso"], "ejecucion": r["ejecucion"],
        "zonas": sorted(zonas.values(), key=lambda z: {"ROJA": 0, "AMARILLA": 1, "VERDE": 2}.get(z["zona"], 3)),
        "consignacion": {"items": len(cons), "valor": sum(f["valor"] or 0 for f in cons)},
        "sin_proveedor": r["sin_proveedor"]["total"],
        "proveedores": [{k: g[k] for k in ("empresa", "proveedor_id", "proveedor_nombre", "items", "unidades", "total", "estado", "bajo_minimo", "sin_costo")} for g in r["proveedores"][:top]],
        "con_problema": sum(1 for g in r["proveedores"] if g["estado"] != "OK"),
    }
    w, pw = filtro_sql_permisos(user, "s.bodega_id", "mi.categoria")
    with pg.connect() as c:
        # ---- 2. OC en vuelo ----
        estados = _filas(c, """SELECT estado, count(*)::int AS ocs, COALESCE(sum(total), 0)::float8 AS total,
                                      COALESCE(max(EXTRACT(EPOCH FROM now() - COALESCE(estado_bpm_fecha, enviado, creado)) / 86400), 0)::float8 AS dias_max
                               FROM ddmrp.orden_compra WHERE creado > now() - interval '90 days' GROUP BY estado ORDER BY 2 DESC""")
        trabadas = _filas(c, """SELECT id, empresa, referencia, proveedor_nombre, estado, total::float8 AS total, consignacion, left(COALESCE(mensaje, ''), 200) AS mensaje,
                                       (EXTRACT(EPOCH FROM now() - COALESCE(estado_bpm_fecha, enviado, creado)) / 86400)::float8 AS dias
                                FROM ddmrp.orden_compra
                                WHERE estado IN ('borrador', 'enviando', 'incierta', 'error', 'en_bpm') AND creado > now() - interval '90 days'
                                  AND now() - COALESCE(estado_bpm_fecha, enviado, creado) > make_interval(days => :d)
                                ORDER BY dias DESC LIMIT :t""", {"d": int(cfg["tablero_dias_trabada"]), "t": top})
        # ---- 3. Pedido y no recibido ----
        vencidas = _filas(c, """SELECT o.id, o.empresa, o.referencia, o.siesa_consecutivo, o.proveedor_nombre, o.total::float8 AS total, o.consignacion, o.estado_siesa,
                                       (EXTRACT(EPOCH FROM now() - o.confirmado) / 86400)::float8 AS dias,
                                       COALESCE(pv.leadtime, :ld)::float8 AS leadtime
                                FROM ddmrp.orden_compra o
                                LEFT JOIN ddmrp.proveedor pv ON pv.empresa = o.empresa AND pv.proveedor_id = o.proveedor_id AND pv.sucursal = o.sucursal
                                WHERE o.estado = 'creada' AND o.confirmado IS NOT NULL AND COALESCE(o.estado_siesa, '') NOT ILIKE 'cumpl%'
                                  AND o.confirmado > now() - interval '90 days'
                                  AND now() - o.confirmado > make_interval(days => COALESCE(pv.leadtime, :ld)::int)
                                ORDER BY dias DESC LIMIT :t""", {"ld": int(cfg["tablero_leadtime_defecto"]), "t": top})
        en_transito = _filas(c, """SELECT count(DISTINCT t.documento)::int AS documentos, COALESCE(sum(t.cantidad), 0)::float8 AS unidades
                                   FROM ddmrp.transitos t WHERE t.documento LIKE 'OC-%'""")[0]
        rit = _filas(c, """SELECT a.empresa, a.producto_id, mi.descripcion, a.bodega_id, a.documento, a.saldo::float8 AS saldo, (current_date - a.fecha)::int AS dias
                           FROM ddmrp.rit_alerta a LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = a.producto_id
                           ORDER BY dias DESC LIMIT :t""", {"t": top})
        n_rit = c.execute(text("SELECT count(*) FROM ddmrp.rit_alerta")).scalar() or 0
        # ---- 4. Riesgo de desabastecimiento (zona roja sin nada en camino) ----
        base = f"""FROM ddmrp.sugerencias_cedi s JOIN ddmrp.item_compra ic ON ic.empresa = s.empresa AND ic.producto_id = s.producto_id
                   LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id
                   WHERE s.ejecucion_id = {ULTIMA} AND {w}"""
        riesgo = _filas(c, f"""SELECT s.empresa, s.producto_id, mi.descripcion, s.inventario::float8 AS inventario, s.en_transito::float8 AS en_transito, s.adu::float8 AS adu,
                                      s.lead_time::float8 AS lead_time, {CONSIG} AS consignacion,
                                      CASE WHEN s.adu > 0 THEN (s.inventario / (s.adu / 30))::float8 END AS cobertura_dias
                               {base} AND s.zona::text = 'ROJA' AND COALESCE(s.en_transito, 0) <= 0
                               ORDER BY cobertura_dias NULLS LAST, s.producto_id LIMIT :t""", pw | {"t": top})
        n_riesgo = c.execute(text(f"SELECT count(*) {base} AND s.zona::text = 'ROJA' AND COALESCE(s.en_transito, 0) <= 0"), pw).scalar() or 0
        agotados = c.execute(text(f"SELECT count(*) {base} AND COALESCE(s.inventario, 0) <= 0 AND COALESCE(s.adu, 0) > 0"), pw).scalar() or 0
        # ---- 5. Exceso ----
        exceso = _filas(c, f"""SELECT s.empresa, s.producto_id, mi.descripcion, s.inventario::float8 AS inventario,
                                      GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0)::float8 AS sobran,
                                      (GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0) * COALESCE({COSTO}, 0))::float8 AS valor,
                                      CASE WHEN s.adu > 0 THEN (s.inventario / (s.adu / 30))::float8 END AS cobertura_dias
                               {base} AND s.zona::text = 'EXCESO'
                               ORDER BY valor DESC LIMIT :t""", pw | {"t": top})
        ex_tot = _filas(c, f"""SELECT count(*)::int AS items, COALESCE(sum(GREATEST(s.flujo_neto - GREATEST(s.tog_aj, 0), 0) * COALESCE({COSTO}, 0)), 0)::float8 AS valor
                               {base} AND s.zona::text = 'EXCESO'""", pw)[0]
        # ---- 6. Cumplimiento del proceso ----
        dias = int(cfg["tablero_dias_cumplimiento"])
        rv = _cfg_revision()
        cum = _filas(c, """SELECT count(*)::int AS ocs, COALESCE(sum(total), 0)::float8 AS total,
                                  count(*) FILTER (WHERE requiere_revision)::int AS con_revision,
                                  count(*) FILTER (WHERE consignacion)::int AS consignacion,
                                  (avg(EXTRACT(EPOCH FROM confirmado - enviado) / 3600) FILTER (WHERE confirmado IS NOT NULL AND enviado IS NOT NULL))::float8 AS horas_envio_a_siesa
                           FROM ddmrp.orden_compra WHERE estado = 'creada' AND creado > now() - make_interval(days => :d)""", {"d": dias})[0]
        lin = _filas(c, """SELECT count(*)::int AS lineas,
                                  count(*) FILTER (WHERE l.cantidad_calculada IS NOT NULL AND l.cantidad_calculada > :cmin AND abs(l.cantidad - l.cantidad_calculada) > l.cantidad_calculada * :pct / 100)::int AS desv_cant,
                                  count(*) FILTER (WHERE l.costo_calculado > 0 AND l.costo > l.costo_calculado * (1 + :cpct / 100))::int AS desv_costo
                           FROM ddmrp.orden_compra_linea l JOIN ddmrp.orden_compra o ON o.id = l.oc_id
                           WHERE o.estado = 'creada' AND o.creado > now() - make_interval(days => :d)""",
                    {"d": dias, "cmin": rv["oc_desvio_cant_min"], "pct": rv["oc_desvio_cant_pct"], "cpct": rv["oc_desvio_costo_pct"]})[0]
        por_prov = _filas(c, """SELECT proveedor_nombre, count(*)::int AS ocs, sum(total)::float8 AS total FROM ddmrp.orden_compra
                                WHERE estado = 'creada' AND creado > now() - make_interval(days => :d) GROUP BY proveedor_nombre ORDER BY 3 DESC LIMIT 8""", {"d": dias})
        por_lab = _filas(c, """SELECT COALESCE(lb.nombre, mi.categoria, '(sin laboratorio)') AS laboratorio, sum(l.cantidad * l.costo)::float8 AS valor
                               FROM ddmrp.orden_compra_linea l JOIN ddmrp.orden_compra o ON o.id = l.oc_id
                               LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = l.producto_id LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
                               WHERE o.estado = 'creada' AND o.creado > now() - make_interval(days => :d) GROUP BY 1 ORDER BY 2 DESC LIMIT 8""", {"d": dias})
    return {
        "config": cfg,
        "pedir": pedir,
        "vuelo": {"estados": estados, "trabadas": trabadas},
        "no_recibido": {"vencidas": vencidas, "oc_en_transito": en_transito, "rit": rit, "rit_total": n_rit},
        "riesgo": {"total": n_riesgo, "agotados": agotados, "filas": riesgo},
        "exceso": {"total": ex_tot, "filas": exceso},
        "cumplimiento": {"dias": dias, "oc": cum, "lineas": lin, "por_proveedor": por_prov, "por_laboratorio": por_lab},
    }
