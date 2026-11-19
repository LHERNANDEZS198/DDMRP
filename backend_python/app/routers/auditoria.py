"""Auditoria del calculo: vista previa de lo que calculo el motor y descarga a Excel con las formulas (auditoria_xlsx), desde la pagina Auditoria o
de exactamente las filas que se ven en la matriz de despacho."""
import time
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from ..activos import solo_activos
from ..auditoria_xlsx import construir
from ..bitacora import evento, usuario_de
from ..consultas import anotar
from ..db import pg
from ..security import empresas_permitidas, filtro_sql_permisos, requiere
from ..modo import fijar_modo
from .control import FROM, ULTIMA, _filtros, filtros as _filtros_control

from ..reglas_empresa import todas_param
router = APIRouter(prefix="/auditoria", tags=["auditoria"])
TOPE = 20000


class Fila(BaseModel):
    b: str   # bodega
    p: str   # producto


class PedidoExcel(BaseModel):
    empresa: str
    filas: list[Fila] = Field(min_length=1)
    limite: int = Field(TOPE, ge=1, le=TOPE)


def _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido):
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, crit=crit)
    cond = [f"s.ejecucion_id = {ULTIMA}"] + cond
    if solo_sugerido:
        cond.append("(s.cantidad_sugerida > 0 OR COALESCE(s.cantidad_necesaria, 0) > 0)")
    return " AND ".join(cond), p


@router.get("/filtros", dependencies=[Depends(fijar_modo)])
def filtros_auditoria(user=Depends(requiere("ver_auditoria"))):
    """Opciones de los filtros de la pagina (tiendas, laboratorios, empresas). Son las mismas de Control, pero con el permiso de Auditoria: /control/filtros pide
    «ver_control» y un usuario que solo audita se quedaba con las listas vacias. Siempre en modo tiendas, igual que la vista."""
    return _filtros_control(user)


@router.get("/vista")
def vista(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
          empresa: str | None = None, crit: str | None = None, solo_sugerido: bool = True, limit: int = Query(300, le=1000),
          user=Depends(requiere("ver_auditoria"))):
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido)
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA} ORDER BY id LIMIT 1")).mappings().first()
        total = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, s.adu::float8 adu, s.forecast::float8 forecast, s.lead_time::float8 lead_time,
                   s.tor::float8 tor, s.toy_aj::float8 toy_aj, s.tog_aj::float8 tog_aj, s.inventario::float8 inventario, s.en_transito::float8 en_transito,
                   s.demanda_calificada::float8 demanda_calificada, s.flujo_neto::float8 flujo_neto, s.zona::text zona,
                   COALESCE(s.cantidad_necesaria, s.cantidad_sugerida)::float8 necesidad, s.stock_cedi::float8 stock_cedi,
                   s.cantidad_sugerida::float8 cantidad_sugerida, s.estado::text estado
            {FROM} WHERE {w} ORDER BY s.bodega_id, s.pct_buffer LIMIT :lim"""), {**p, "lim": limit}).mappings()]
    return {"ejecucion": dict(ej) if ej else None, "total": total, "filas": filas, "tope_excel": TOPE}


def _generar_excel(user, w: str, p: dict, limite: int, origen: str = ""):
    """Arma el Excel (con formulas) de las filas que cumplen `w` en la ultima corrida."""
    t0 = time.perf_counter()
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA} ORDER BY id LIMIT 1")).mappings().first()
        if not ej:
            return Response("No hay una corrida del motor", status_code=404)
        total, emp_aud = c.execute(text(f"SELECT count(*), min(s.empresa) {FROM} WHERE {w}"), p).one()     # una sola pasada por la vista (antes eran dos)
        emp_aud = emp_aud or "05"     # el Excel lleva las reglas de la empresa de las filas
        if not total:
            return Response("Ninguna de esas filas está en la última corrida del motor (¿cambió la corrida?). Recarga la matriz.", status_code=404)
        t1 = time.perf_counter()
        prm = todas_param(c, emp_aud)
        factores = [dict(r) for r in c.execute(text(
            "SELECT tipo, descripcion, factor::float8 factor, desde::float8 desde, hasta::float8 hasta FROM ddmrp.factor_tramo WHERE empresa = :e ORDER BY tipo, desde"), {"e": emp_aud}).mappings()]
        # filas de la vista SIN los tres cruces pesados (pronostico, cotas, promocion): con ellos en el mismo SELECT el planner recorria esas tablas completas (10 s por 687 filas);
        # se traen aparte, solo para las llaves de estas filas, igual que las ventas
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria) AS laboratorio,
                   s.lead_time::float8 lead_time, s.frecuencia::float8 frecuencia,
                   s.unidad_despacho::float8 unidad_despacho, s.vectorizacion::float8 vectorizacion, s.inventario::float8 inventario,
                   s.en_transito::float8 en_transito, s.demanda_calificada::float8 demanda_calificada, s.condenado::int condenado, COALESCE(s.regla_objetivo, 0)::int regla_objetivo,
                   s.adu::float8 adu, s.toy_aj::float8 toy_aj, s.tog_aj::float8 tog_aj, s.zona::text zona,
                   COALESCE(s.cantidad_necesaria, s.cantidad_sugerida)::float8 necesidad, s.stock_cedi::float8 stock_cedi,
                   s.cantidad_sugerida::float8 cantidad_sugerida, s.estado::text estado, s.cantidad_aprobada::float8 cantidad_aprobada, s.pct_buffer
            {FROM}
            WHERE {w} ORDER BY s.bodega_id, s.pct_buffer LIMIT :lim"""), {**p, "lim": limite}).mappings()]
        kp = {"e": [f["empresa"] for f in filas], "b": [f["bodega_id"] for f in filas], "p": [f["producto_id"] for f in filas]}
        for f in filas:
            f.update(pronostico=0.0, cota_max=0.0, cota_min=0.0, promo=0, aum_cota_max=None, aum_cota_min=None)
        if filas:
            llaves = "unnest(CAST(:e AS text[]), CAST(:b AS text[]), CAST(:p AS text[])) k(e, b, p)"
            ix0 = {(f["empresa"], f["bodega_id"], f["producto_id"]): f for f in filas}
            for em, b, pid, v in c.execute(text(f"SELECT x.empresa, x.bodega_id, x.producto_id, x.pronostico::float8 FROM ddmrp.pronostico x JOIN {llaves} ON k.e = x.empresa AND k.b = x.bodega_id AND k.p = x.producto_id"), kp):
                ix0[(em, b, pid)]["pronostico"] = v or 0.0
            for em, b, pid, mx, mn in c.execute(text(f"SELECT x.empresa, x.bodega_id, x.producto_id, x.cota_maxima::float8, x.cota_minima::float8 FROM ddmrp.abast_control_referencias x JOIN {llaves} ON k.e = x.empresa AND k.b = x.bodega_id AND k.p = x.producto_id"), kp):
                ix0[(em, b, pid)]["cota_max"] = mx or 0.0; ix0[(em, b, pid)]["cota_min"] = mn or 0.0
            promos = {(em, pid): (ind, amx, amn) for em, pid, ind, amx, amn in c.execute(text(
                "SELECT x.empresa, x.producto_id, COALESCE(x.indicativo, 0)::int, x.aum_cota_max::float8, x.aum_cota_min::float8 FROM ddmrp.promocion x "
                "WHERE (x.empresa, x.producto_id) IN (SELECT k.e, k.p FROM " + llaves + ")"), kp)}
            for f in filas:
                pr = promos.get((f["empresa"], f["producto_id"]))
                if pr:
                    f["promo"], f["aum_cota_max"], f["aum_cota_min"] = pr
        # meses de la ventana (el ultimo es el mes de la fecha de calculo) y sus ventas
        t2 = time.perf_counter()
        n = int(min(max(prm.get("meses_historia", 7), 2), 12))
        fc: date = ej["fecha_calculo"]
        meses = []
        y, m = fc.year, fc.month
        for _ in range(n):
            meses.append(f"{y:04d}{m:02d}"); m -= 1
            if m == 0: y, m = y - 1, 12
        meses.reverse()
        for f in filas:
            f["mult_max"] = 1 + f["aum_cota_max"] if f.get("aum_cota_max") is not None else prm.get("mult_cota_max_promo", 1.2)
            f["mult_min"] = 1 + f["aum_cota_min"] if f.get("aum_cota_min") is not None else prm.get("mult_cota_min_promo", 1.1)
        idx = {(f["empresa"], f["bodega_id"], f["producto_id"]): f for f in filas}
        for f in filas: f["ventas"] = [0.0] * n
        if filas:
            for em, b, pid, mes, cant in c.execute(text("""
                SELECT v.empresa, v.bodega_id, v.producto_id, v.mes, sum(v.cantidad)::float8
                FROM ddmrp.ventas_mensual v JOIN unnest(CAST(:e AS text[]), CAST(:b AS text[]), CAST(:p AS text[])) k(e, b, p) ON k.e = v.empresa AND k.b = v.bodega_id AND k.p = v.producto_id
                WHERE v.mes = ANY(:m) GROUP BY 1, 2, 3, 4"""), {"e": [f["empresa"] for f in filas], "b": [f["bodega_id"] for f in filas], "p": [f["producto_id"] for f in filas], "m": meses}):
                idx[(em, b, pid)]["ventas"][meses.index(mes)] = cant
    t3 = time.perf_counter()
    data = construir(filas, meses, prm, factores, {"id": ej["id"], "fecha": fc.isoformat()}, truncado=total if total > len(filas) else 0)
    t4 = time.perf_counter()
    anotar(ms_conteo=round((t1 - t0) * 1000), ms_filas=round((t2 - t1) * 1000), ms_ventas=round((t3 - t2) * 1000), ms_xlsx=round((t4 - t3) * 1000), filas=len(filas), mb=round(len(data) / 1e6, 1))
    evento("auditoria", usuario_de(user), f"Excel de auditoría{origen}: {len(filas):,} filas de la corrida #{ej['id']}", {"filas": len(filas), "total": total, "ejecucion_id": ej["id"]})
    h = {"Content-Disposition": f'attachment; filename="Auditoria_DDMRP_{fc:%Y%m%d}.xlsx"', "X-Filas": str(len(filas)), "X-Filas-Total": str(total)}
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=h)


@router.get("/excel")
def excel_pagina(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
                 empresa: str | None = None, crit: str | None = None, solo_sugerido: bool = True, limite: int = Query(10000, ge=1, le=TOPE),
                 user=Depends(requiere("ver_auditoria"))):
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido)
    return _generar_excel(user, w, p, limite)


@router.post("/excel")
def excel(body: PedidoExcel, user=Depends(requiere("ver_auditoria"))):
    """Excel de auditoria de EXACTAMENTE las filas (bodega, producto) que la matriz de despacho tiene en pantalla.
    Respeta los permisos del usuario (bodegas/laboratorios y empresa) y toma la ultima corrida del motor."""
    if body.empresa not in ("05", "21"):
        raise HTTPException(400, "Elige la empresa (05 o 21)")
    perm = empresas_permitidas(user["id"])
    if perm and body.empresa not in perm:
        raise HTTPException(403, f"Tu usuario no tiene asignada la empresa {body.empresa}")
    wp, p = filtro_sql_permisos(user, "s.bodega_id", "mi.categoria")
    llaves = list(dict.fromkeys((f.b, f.p) for f in body.filas))
    p.update(k_emp=body.empresa, k_b=[k[0] for k in llaves], k_p=[k[1] for k in llaves])
    w = (f"s.ejecucion_id = {ULTIMA} AND s.empresa = :k_emp AND {wp} AND {solo_activos('s')} "
         "AND (s.bodega_id, s.producto_id) IN (SELECT k.b, k.p FROM unnest(CAST(:k_b AS text[]), CAST(:k_p AS text[])) k(b, p))")
    return _generar_excel(user, w, p, body.limite, f" desde la matriz de despacho (empresa {body.empresa})")
