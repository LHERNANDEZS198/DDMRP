"""Compras: necesidades de compra del CEDI (solo lectura). Parte del buffer del CEDI de la ultima corrida del motor (ddmrp.sugerencias_cedi), deja los items que
SE COMPRAN en esa empresa (maestro «Criterios comprables») y que tienen algo que pedir, les pone proveedor, costo y multiplo de pedido de los maestros de compras
y los agrupa por proveedor. No crea ni envia nada: es lo que compras valida antes de armar ordenes."""
import math
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from .. import excel
from ..activos import solo_activos
from ..auditoria_xlsx import construir, PARAMS
from ..bitacora import evento, usuario_de
from ..db import pg
from ..orchestrator import recalcular_compras
from ..security import usuario_actual, filtro_sql_permisos, requiere

router = APIRouter(prefix="/compras", tags=["compras"], dependencies=[Depends(requiere("ver_compras"))])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
# categoria de compras = criterio del plan 001 de Siesa
CAT_ID = "(SELECT ci.criterio_id FROM ddmrp.item_criterio ci WHERE ci.producto_id = s.producto_id AND ci.plan_id = '001' LIMIT 1)"
CAT_NOM = ("(SELECT CASE WHEN cr.nombre IS NULL THEN ci.criterio_id ELSE ci.criterio_id || ' · ' || cr.nombre END FROM ddmrp.item_criterio ci "
           "LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ci.plan_id AND cr.criterio_id = ci.criterio_id WHERE ci.producto_id = s.producto_id AND ci.plan_id = '001' LIMIT 1)")
# se compra si la categoria no esta marcada como produccion propia en esa empresa (sin fila o vacio = se compra)
COMPRABLE = f"COALESCE((SELECT cc.se_compra FROM ddmrp.categoria_compra cc WHERE cc.empresa = s.empresa AND cc.plan_id = '001' AND cc.criterio_id = {CAT_ID}), 1) <> 0"
CONFIG_DEFECTO = {"pedido_minimo_bloquea": 0.0, "poca_historia_meses": 3.0}


def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def _config(c) -> dict:
    cfg = dict(CONFIG_DEFECTO)
    try:
        for k, v in c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config WHERE valor IS NOT NULL")).all():
            cfg[k] = v
    except Exception:
        pass
    return cfg


def _redondear(q: float, u: float, modo: str) -> float:
    """Cantidad al multiplo de la unidad de pedido: arriba (por defecto), cercano o abajo."""
    u = u if u and u > 0 else 1.0
    k = q / u
    n = math.floor(k + 1e-9) if modo == "abajo" else math.floor(k + 0.5) if modo == "cercano" else math.ceil(k - 1e-9)
    return float(max(n, 0) * u)


def _mes_hace(meses: int) -> str:
    t = date.today(); m = t.year * 12 + t.month - 1 - meses
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def _necesidades(user, empresa, proveedores, categorias, labs, zonas, q, limite: int = 5000) -> dict:
    w, p = filtro_sql_permisos(user, "s.bodega_id", "mi.categoria")
    # entran los que piden algo Y los que compras ya edito (la cantidad editada se conserva aunque el motor ya no pida nada)
    cond = [f"s.ejecucion_id = {ULTIMA}", "NOT s.condenado", "(s.cantidad_sugerida > 0 OR cm.cantidad IS NOT NULL)", solo_activos("s"), COMPRABLE, w]
    if _csv(empresa):
        cond.append("s.empresa = ANY(:f_emp)"); p["f_emp"] = _csv(empresa)
    if _csv(categorias):
        cond.append(f"{CAT_ID} = ANY(:f_cat)"); p["f_cat"] = _csv(categorias)
    if _csv(labs):
        cond.append("COALESCE(mi.categoria, '') = ANY(:f_lab)"); p["f_lab"] = _csv(labs)
    if _csv(zonas):
        cond.append("s.zona::text = ANY(:f_zona)"); p["f_zona"] = _csv(zonas)
    if q and q.strip():
        cond.append("(s.producto_id ILIKE :f_q OR mi.descripcion ILIKE :f_q)"); p["f_q"] = f"%{q.strip()}%"
    base = f"""WITH hist AS (
      SELECT empresa, producto_id, count(*) FILTER (WHERE q > 0)::int AS meses FROM (
        SELECT o.empresa, a.producto_id, a.mes, sum(a.cantidad) AS q
        FROM ddmrp.ventas_mensual a JOIN ddmrp.v_origen_cedi o ON o.empresa = a.empresa AND o.origen = a.bodega_id
        WHERE a.mes >= :mes12 GROUP BY 1, 2, 3) x GROUP BY 1, 2)
      SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, COALESCE(mi.categoria, '') AS lab_cod, lb.nombre AS lab_nombre, {CAT_NOM} AS categoria,
             ic.proveedor_id, ic.sucursal, pv.nombre AS proveedor_nombre, COALESCE(pv.activo, 1) AS prov_activo, COALESCE(pv.redondeo, 'arriba') AS redondeo,
             pv.pedido_minimo::float8 AS pedido_minimo,
             s.frecuencia::float8 AS frecuencia, s.unidad_despacho::float8 AS unidad_despacho, s.demanda_calificada::float8 AS demanda_calificada,
             COALESCE(s.regla_objetivo, 0)::int AS regla_objetivo, s.condenado::int AS condenado,
             s.adu::float8 AS adu, s.lead_time::float8 AS lead_time, s.inventario::float8 AS inventario, s.en_transito::float8 AS en_transito, s.flujo_neto::float8 AS flujo_neto,
             s.tor::float8 AS tor, s.toy_aj::float8 AS toy_aj, s.tog_aj::float8 AS tog_aj, s.pct_buffer::float8 AS pct_buffer, s.zona::text AS zona, s.cantidad_sugerida::float8 AS qty_buffer,
             COALESCE(NULLIF(ic.unidad_pedido, 0), 1)::float8 AS unidad_pedido, COALESCE(NULLIF(ic.unidad_empaque, 0), 1)::float8 AS unidad_empaque,
             COALESCE(ic.cotizacion, ic.cotizacion_siesa, ic.ultimo_costo)::float8 AS costo,
             CASE WHEN ic.cotizacion IS NOT NULL THEN 'Manual' WHEN ic.cotizacion_siesa IS NOT NULL THEN 'Cotización' WHEN ic.ultimo_costo IS NOT NULL THEN 'Última compra' END AS origen_costo,
             CASE WHEN ic.cotizacion IS NOT NULL THEN NULL WHEN ic.cotizacion_siesa IS NOT NULL THEN ic.cotizacion_fecha ELSE ic.ultimo_costo_fecha END AS costo_fecha,
             ic.iva_tasa::float8 AS iva_tasa, COALESCE(h.meses, 0) AS meses_venta, pv.leadtime::float8 AS leadtime_proveedor,
             cm.cantidad::float8 AS qty_manual, cm.nota AS qty_nota, cm.usuario AS qty_usuario, cm.actualizado AS qty_fecha
      FROM ddmrp.sugerencias_cedi s
      JOIN ddmrp.item_compra ic ON ic.empresa = s.empresa AND ic.producto_id = s.producto_id
      LEFT JOIN ddmrp.compras_cantidad cm ON cm.empresa = s.empresa AND cm.producto_id = s.producto_id
      LEFT JOIN ddmrp.proveedor pv ON pv.empresa = ic.empresa AND pv.proveedor_id = ic.proveedor_id AND pv.sucursal = ic.sucursal
      LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id
      LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
      LEFT JOIN hist h ON h.empresa = s.empresa AND h.producto_id = s.producto_id"""
    p["mes12"] = _mes_hace(11)
    prov_cond = _csv(proveedores)
    with pg.connect() as c:
        cfg = _config(c)
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        con_prov = " AND ".join(cond + ["ic.proveedor_id IS NOT NULL"] + (["ic.proveedor_id = ANY(:f_prov)"] if prov_cond else []))
        if prov_cond:
            p["f_prov"] = prov_cond
        filas = [dict(r) for r in c.execute(text(f"{base} WHERE {con_prov} ORDER BY CASE s.zona::text WHEN 'ROJA' THEN 0 WHEN 'AMARILLA' THEN 1 WHEN 'VERDE' THEN 2 ELSE 3 END, s.pct_buffer NULLS FIRST, s.producto_id LIMIT :lim"), {**p, "lim": limite + 1}).mappings()]
        sin_cond = " AND ".join(cond + ["ic.proveedor_id IS NULL"])
        sin = [dict(r) for r in c.execute(text(f"{base} WHERE {sin_cond} ORDER BY s.pct_buffer NULLS FIRST, s.producto_id LIMIT 1000"), p).mappings()]
        n_sin = c.execute(text(f"SELECT count(*) FROM ddmrp.sugerencias_cedi s JOIN ddmrp.item_compra ic ON ic.empresa = s.empresa AND ic.producto_id = s.producto_id "
                               f"LEFT JOIN ddmrp.compras_cantidad cm ON cm.empresa = s.empresa AND cm.producto_id = s.producto_id "
                               f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = s.producto_id WHERE {sin_cond}"), {k: v for k, v in p.items() if k != "mes12"}).scalar()
    truncado = len(filas) > limite
    filas = filas[:limite]
    poca = cfg.get("poca_historia_meses", 3.0)
    grupos: dict[tuple, dict] = {}
    for f in filas:
        f["qty_calculada"] = _redondear(f["qty_buffer"], f["unidad_pedido"], f["redondeo"])
        f["editada"] = f["qty_manual"] is not None
        f["qty_pedir"] = f["qty_manual"] if f["editada"] else f["qty_calculada"]   # lo que compras edito manda sobre el calculo
        costo = f["costo"]
        f["valor"] = f["qty_pedir"] * costo if costo is not None else None
        f["iva"] = f["valor"] * f["iva_tasa"] / 100 if f["valor"] is not None and f["iva_tasa"] is not None else None
        f["total"] = (f["valor"] + (f["iva"] or 0)) if f["valor"] is not None else None
        a = (f["adu"] or 0) / 30
        f["cobertura_dias"] = f["inventario"] / a if a > 0 else None
        alertas = []
        if costo is None: alertas.append("Sin cotización")
        if f["meses_venta"] < poca: alertas.append(f"Poca historia ({f['meses_venta']} m)")
        if not f["prov_activo"]: alertas.append("Proveedor inactivo")
        if f["editada"]:
            alertas.append(f"Cantidad editada (el buffer pedía {round(f['qty_buffer']):,})".replace(",", "."))
            u = f["unidad_pedido"]
            if u > 1 and abs(f["qty_manual"] / u - round(f["qty_manual"] / u)) > 1e-9: alertas.append("No es múltiplo de la unidad de pedido")
            if f["qty_manual"] > 2 * max(f["qty_buffer"], 1): alertas.append("Más del doble de lo que pide el buffer")
        elif f["qty_pedir"] <= 0: alertas.append("Redondeo a 0")
        f["alertas"] = "; ".join(alertas)
        k = (f["empresa"], f["proveedor_id"], f["sucursal"])
        g = grupos.setdefault(k, {"empresa": f["empresa"], "proveedor_id": f["proveedor_id"], "sucursal": f["sucursal"], "proveedor_nombre": f["proveedor_nombre"],
                                  "activo": bool(f["prov_activo"]), "redondeo": f["redondeo"], "pedido_minimo": f["pedido_minimo"],
                                  "leadtime": f["leadtime_proveedor"], "items": 0, "unidades": 0.0, "valor": 0.0, "iva": 0.0, "total": 0.0, "sin_costo": 0, "poca_historia": 0, "editadas": 0})
        g["items"] += 1; g["unidades"] += f["qty_pedir"]
        if f["editada"]: g["editadas"] += 1
        if f["valor"] is None: g["sin_costo"] += 1
        else: g["valor"] += f["valor"]; g["iva"] += f["iva"] or 0; g["total"] += f["total"]
        if f["meses_venta"] < poca: g["poca_historia"] += 1
    provs = []
    for g in grupos.values():
        pm = g["pedido_minimo"]
        g["bajo_minimo"] = bool(pm and pm > 0 and g["items"] > g["sin_costo"] and g["valor"] < pm)
        g["estado"] = ("Bajo el pedido mínimo" if g["bajo_minimo"] else "Incompleto (ítems sin cotización)" if g["sin_costo"] else "Proveedor inactivo" if not g["activo"] else "OK")
        provs.append(g)
    bloquea = cfg.get("pedido_minimo_bloquea", 0) >= 1
    bloqueados = [g for g in provs if g["bajo_minimo"]] if bloquea else []
    if bloqueados:   # «bloquear y no mostrar»: los proveedores bajo su pedido minimo salen de la lista (y de los totales)
        quitar = {(g["empresa"], g["proveedor_id"], g["sucursal"]) for g in bloqueados}
        filas = [f for f in filas if (f["empresa"], f["proveedor_id"], f["sucursal"]) not in quitar]
        provs = [g for g in provs if (g["empresa"], g["proveedor_id"], g["sucursal"]) not in quitar]
    provs.sort(key=lambda g: -g["total"])
    tot = {"proveedores": len(provs), "items": len(filas), "unidades": sum(f["qty_pedir"] for f in filas), "valor": sum(g["valor"] for g in provs),
           "iva": sum(g["iva"] for g in provs), "total": sum(g["total"] for g in provs), "sin_costo": sum(1 for f in filas if f["costo"] is None),
           "poca_historia": sum(1 for f in filas if f["meses_venta"] < poca), "editadas": sum(1 for f in filas if f["editada"]), "bajo_minimo": sum(1 for g in provs if g["bajo_minimo"]), "bloqueados": len(bloqueados)}
    aviso = None if ej else "Aún no hay una corrida del motor con el buffer del CEDI: corre el motor."
    return {"config": cfg, "ejecucion": dict(ej) if ej else None, "aviso": aviso, "filas": filas, "proveedores": provs, "bloqueados": bloqueados,
            "sin_proveedor": {"total": n_sin, "filas": sin}, "totales": tot, "truncado": truncado}


@router.get("/necesidades")
def necesidades(empresa: str | None = None, proveedores: str | None = None, categorias: str | None = None, labs: str | None = None, zonas: str | None = None,
                q: str | None = None, limit: int = Query(5000, ge=1, le=20000), user=Depends(usuario_actual)):
    """Necesidades de compra del CEDI: items a pedir con proveedor, cantidad (al multiplo de pedido), costo y valor; resumen por proveedor; y los items que se compran
    pero no tienen proveedor. Filtros: empresa, proveedores (NIT), categorias (codigos del plan 001), labs, zonas, texto."""
    return _necesidades(user, empresa, proveedores, categorias, labs, zonas, q, limit)


class CantidadIn(BaseModel):
    empresa: str
    producto_id: str
    cantidad: float | None = None    # None = quitar la edicion (vuelve al calculo)
    nota: str | None = None


@router.put("/cantidad")
def guardar_cantidad(b: CantidadIn, user=Depends(requiere("gestionar_compras"))):
    """Guarda la cantidad a pedir que compras edito para un item (o la quita). Vive aparte del calculo: sobrevive a las corridas del motor y se conserva hasta que se monte la OC."""
    if b.cantidad is not None and not (b.cantidad >= 0 and b.cantidad < 1e9):
        raise HTTPException(400, "La cantidad debe ser un número mayor o igual a 0")
    with pg.begin() as c:
        if not c.execute(text("SELECT 1 FROM ddmrp.item_compra WHERE empresa = :e AND producto_id = :p"), {"e": b.empresa, "p": b.producto_id}).first():
            raise HTTPException(404, "Ese ítem no existe en los maestros de compras de esa empresa")
        if b.cantidad is None:
            c.execute(text("DELETE FROM ddmrp.compras_cantidad WHERE empresa = :e AND producto_id = :p"), {"e": b.empresa, "p": b.producto_id})
        else:
            c.execute(text("""INSERT INTO ddmrp.compras_cantidad (empresa, producto_id, cantidad, nota, usuario, actualizado) VALUES (:e, :p, :q, :n, :u, now())
                              ON CONFLICT (empresa, producto_id) DO UPDATE SET cantidad = EXCLUDED.cantidad, nota = COALESCE(EXCLUDED.nota, ddmrp.compras_cantidad.nota),
                                                                              usuario = EXCLUDED.usuario, actualizado = now()"""),
                      {"e": b.empresa, "p": b.producto_id, "q": b.cantidad, "n": (b.nota or "").strip() or None, "u": usuario_de(user)})
    evento("compras", usuario_de(user), f"Cantidad a pedir de {b.empresa}/{b.producto_id}: " + ("restablecida al cálculo" if b.cantidad is None else f"{b.cantidad:g}"),
           {"empresa": b.empresa, "producto_id": b.producto_id, "cantidad": b.cantidad})
    return {"ok": True}


@router.post("/recalcular")
def recalcular(user=Depends(requiere("gestionar_compras"))):
    """Recalcula las necesidades de compra SIN correr el motor completo: inventario fresco y OC abiertas del CEDI + buffer del CEDI. No toca las tiendas ni los despachos;
    las cantidades editadas se conservan."""
    try:
        return recalcular_compras("manual", usuario_de(user))
    except RuntimeError as e:
        raise HTTPException(400, str(e))


@router.get("/necesidades/excel")
def necesidades_excel(empresa: str | None = None, proveedores: str | None = None, categorias: str | None = None, labs: str | None = None, zonas: str | None = None,
                      q: str | None = None, user=Depends(usuario_actual)):
    """Excel de las necesidades (lo filtrado): resumen por proveedor, detalle, ítems sin proveedor y, como en la Auditoría, la hoja «Cálculo CEDI» con TODO el cálculo
    como fórmulas vivas de Excel (ventas de los últimos meses → ADU → zonas → necesidad del buffer → cantidad a pedir → valor e IVA) y la hoja de parámetros."""
    r = _necesidades(user, empresa, proveedores, categorias, labs, zonas, q, 20000)
    wb = excel.libro()
    excel.hoja(wb, "Por proveedor", [
        {"t": "NIT", "k": "proveedor_id", "w": 13}, {"t": "Proveedor", "k": "proveedor_nombre", "w": 36}, {"t": "Empresa", "k": "empresa", "w": 9}, {"t": "Sucursal", "k": "sucursal", "w": 9},
        {"t": "Ítems", "k": "items", "f": "int", "w": 8}, {"t": "Unidades", "k": "unidades", "f": "int", "w": 11}, {"t": "Valor sin IVA", "k": "valor", "f": "cop", "w": 15},
        {"t": "IVA estimado", "k": "iva", "f": "cop", "w": 14}, {"t": "Total", "k": "total", "f": "cop", "w": 15}, {"t": "Lead time (d)", "k": "leadtime", "f": "int", "w": 10}, {"t": "Pedido mínimo", "k": "pedido_minimo", "f": "cop", "w": 14},
        {"t": "Ítems sin cotización", "k": "sin_costo", "f": "int", "w": 12}, {"t": "Poca historia", "k": "poca_historia", "f": "int", "w": 11},
        {"t": "Redondeo", "k": "redondeo", "w": 10}, {"t": "Estado", "k": "estado", "w": 30}], r["proveedores"], fijar=2)
    excel.hoja(wb, "Detalle", [
        {"t": "Producto (SKU)", "k": "producto_id", "w": 12}, {"t": "Descripción", "k": "descripcion", "w": 40}, {"t": "Empresa", "k": "empresa", "w": 9},
        {"t": "NIT", "k": "proveedor_id", "w": 13}, {"t": "Proveedor", "k": "proveedor_nombre", "w": 32}, {"t": "Categoría", "k": "categoria", "w": 24}, {"t": "Laboratorio", "k": "lab_nombre", "w": 20},
        {"t": "Zona", "k": "zona", "w": 11, "zona": True}, {"t": "ADU (u/mes)", "k": "adu", "f": "dec1", "w": 11}, {"t": "Lead time (d)", "k": "lead_time", "f": "int", "w": 9},
        {"t": "Inventario", "k": "inventario", "f": "int", "w": 11}, {"t": "Tránsito", "k": "en_transito", "f": "int", "w": 10}, {"t": "Flujo neto", "k": "flujo_neto", "f": "int", "w": 11},
        {"t": "TOG aj.", "k": "tog_aj", "f": "int", "w": 10}, {"t": "Cobertura (días)", "k": "cobertura_dias", "f": "dec1", "w": 11},
        {"t": "Pide el buffer", "k": "qty_buffer", "f": "int", "w": 11}, {"t": "Unidad de pedido", "k": "unidad_pedido", "f": "dec2", "w": 10}, {"t": "A pedir", "k": "qty_pedir", "f": "int", "w": 10},
        {"t": "Calculada", "k": "qty_calculada", "f": "int", "w": 10}, {"t": "Editada por compras", "k": "qty_manual", "f": "int", "w": 11},
        {"t": "Costo", "k": "costo", "f": "dec2", "w": 12}, {"t": "Origen del costo", "k": "origen_costo", "w": 14}, {"t": "Costo vigente desde", "k": "costo_fecha", "w": 14},
        {"t": "Valor sin IVA", "k": "valor", "f": "cop", "w": 14}, {"t": "IVA % (est.)", "k": "iva_tasa", "f": "dec1", "w": 9}, {"t": "Total", "k": "total", "f": "cop", "w": 14}, {"t": "Alertas", "k": "alertas", "w": 34}], r["filas"], fijar=2)
    excel.hoja(wb, "Sin proveedor", [
        {"t": "Producto (SKU)", "k": "producto_id", "w": 12}, {"t": "Descripción", "k": "descripcion", "w": 40}, {"t": "Empresa", "k": "empresa", "w": 9}, {"t": "Categoría", "k": "categoria", "w": 24},
        {"t": "Laboratorio", "k": "lab_nombre", "w": 20}, {"t": "Zona", "k": "zona", "w": 11, "zona": True}, {"t": "ADU (u/mes)", "k": "adu", "f": "dec1", "w": 11},
        {"t": "Flujo neto", "k": "flujo_neto", "f": "int", "w": 11}, {"t": "Pide el buffer", "k": "qty_buffer", "f": "int", "w": 11}], r["sin_proveedor"]["filas"], fijar=2)
    cfg = r["config"]; t = r["totales"]
    excel.hoja_texto(wb, "Filtros", [
        ("Reporte", "Necesidades de compra del CEDI"), ("Generado", datetime.now().strftime("%Y-%m-%d %H:%M")), ("Usuario", f"{user.get('nombre', '')} ({user.get('id', '')})"),
        ("Corrida del motor", f"{r['ejecucion']['fecha_calculo']} (ejecución {r['ejecucion']['id']})" if r["ejecucion"] else ""),
        ("Empresa", empresa or "ambas"), ("Proveedores", proveedores or ""), ("Categorías", categorias or ""), ("Laboratorios", labs or ""), ("Zonas", zonas or ""), ("Texto", q or ""),
        ("Pedido mínimo", "los proveedores bajo su mínimo NO se muestran" if cfg.get("pedido_minimo_bloquea", 0) >= 1 else "se muestran con alerta (no se bloquean)"),
        ("Poca historia", f"menos de {cfg.get('poca_historia_meses', 3):g} meses con venta (solo alerta)"),
        ("Ítems / unidades / valor / total", f"{t['items']} / {t['unidades']:,.0f} / ${t['valor']:,.0f} / ${t['total']:,.0f}"),
        ("Hoja «Cálculo CEDI»", "El cálculo completo como fórmulas de Excel (hasta 10.000 ítems, los más críticos): ventas por mes → ADU → zonas → necesidad → a pedir → valor e IVA. Mira «Cómo leerlo»."),
        ("Cantidades editadas", f"{t['editadas']} ítems: en «Detalle», «A pedir» es la cantidad que compras editó y «Calculada» la del sistema. En «Cálculo CEDI», A PEDIR es siempre el cálculo."),
        ("Nota", "Los ítems sin cotización quedan con valor vacío y no suman a los totales. El IVA es una tarifa estimada: Siesa lo calcula al crear la OC.")])
    if r["ejecucion"] and r["filas"]:
        _hoja_calculo(wb, r)
    return Response(excel.a_bytes(wb), media_type=excel.XLSX,
                    headers={"Content-Disposition": f'attachment; filename="necesidades_compra_{datetime.now():%Y%m%d_%H%M}.xlsx"'})


def _hoja_calculo(wb, r: dict, tope: int = 10000) -> None:
    """Agrega al libro la hoja de calculo en formulas (la misma de la Auditoria, para el CEDI) con las ventas de los ultimos meses de cada item."""
    filas = r["filas"][:tope]
    fc = r["ejecucion"]["fecha_calculo"]
    with pg.connect() as c:
        prm = {k: float(v) for k, v in c.execute(text("SELECT clave, valor FROM ddmrp.parametro"))}
        factores = [dict(x) for x in c.execute(text("SELECT tipo, descripcion, factor::float8 factor, desde::float8 desde, hasta::float8 hasta FROM ddmrp.factor_tramo ORDER BY tipo, desde")).mappings()]
        n = int(min(max(prm.get("meses_historia", 7), 2), 12))
        meses, y, m = [], fc.year, fc.month
        for _ in range(n):
            meses.append(f"{y:04d}{m:02d}"); m -= 1
            if m == 0: y, m = y - 1, 12
        meses.reverse()
        idx = {(f["empresa"], f["producto_id"]): f for f in filas}
        for f in filas:
            f["ventas"] = [0.0] * n; f["pronostico"] = 0.0
        e, p = [f["empresa"] for f in filas], [f["producto_id"] for f in filas]
        for em, pid, mes, cant in c.execute(text("""
            SELECT o.empresa, a.producto_id, a.mes, sum(a.cantidad)::float8
            FROM ddmrp.ventas_mensual a JOIN ddmrp.v_origen_cedi o ON o.empresa = a.empresa AND o.origen = a.bodega_id
            JOIN unnest(CAST(:e AS text[]), CAST(:p AS text[])) k(e, p) ON k.e = o.empresa AND k.p = a.producto_id
            WHERE a.mes = ANY(:m) GROUP BY 1, 2, 3"""), {"e": e, "p": p, "m": meses}):
            if (em, pid) in idx:
                idx[(em, pid)]["ventas"][meses.index(mes)] = cant
        for em, pid, pr in c.execute(text("""
            SELECT o.empresa, pn.producto_id, sum(pn.pronostico)::float8 FROM ddmrp.pronostico pn JOIN ddmrp.v_origen_cedi o ON o.empresa = pn.empresa AND o.origen = pn.bodega_id
            JOIN unnest(CAST(:e AS text[]), CAST(:p AS text[])) k(e, p) ON k.e = o.empresa AND k.p = pn.producto_id GROUP BY 1, 2"""), {"e": e, "p": p}):
            if (em, pid) in idx:
                idx[(em, pid)]["pronostico"] = pr
    for f in filas:   # lo que espera la hoja de calculo (las claves del motor): el CEDI no tiene cotas, promocion, vectorizacion ni reparto
        f.update(laboratorio=f.get("lab_nombre") or f.get("lab_cod"), cota_max=0.0, cota_min=0.0, promo=0, vectorizacion=0.0,
                 toy_aj=f["toy_aj"], necesidad=f["qty_buffer"], cantidad_sugerida=f["qty_buffer"], stock_cedi=None, estado=None, cantidad_aprobada=None)
    ejec = {"id": r["ejecucion"]["id"], "fecha": fc.isoformat()}
    construir(filas, meses, {k: prm.get(k, d) for k, _, d in PARAMS}, factores, ejec, truncado=len(r["filas"]) if len(r["filas"]) > len(filas) else 0,
              wb=wb, titulo_hoja="Cálculo CEDI", es_cedi=True, compras=True)
