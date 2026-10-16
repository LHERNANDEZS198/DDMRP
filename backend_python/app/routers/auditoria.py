"""Auditoria del calculo: vista previa de lo que calculo el motor y descarga a Excel con las formulas (auditoria_xlsx)."""
from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from ..auditoria_xlsx import construir, PARAMS
from ..bitacora import evento, usuario_de
from ..db import pg
from ..security import requiere
from .control import FROM, ULTIMA, _filtros

router = APIRouter(prefix="/auditoria", tags=["auditoria"])
TOPE = 20000


def _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido):
    cond, p = _filtros(user, bodegas, labs, q, zonas, dia, empresa, crit=crit)
    cond = [f"s.ejecucion_id = {ULTIMA}"] + cond
    if solo_sugerido:
        cond.append("(s.cantidad_sugerida > 0 OR COALESCE(s.cantidad_necesaria, 0) > 0)")
    return " AND ".join(cond), p


@router.get("/vista")
def vista(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
          empresa: str | None = None, crit: str | None = None, solo_sugerido: bool = True, limit: int = Query(300, le=1000),
          user=Depends(requiere("ver_auditoria"))):
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido)
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        total = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, s.adu::float8 adu, s.forecast::float8 forecast, s.lead_time::float8 lead_time,
                   s.tor::float8 tor, s.toy_aj::float8 toy_aj, s.tog_aj::float8 tog_aj, s.inventario::float8 inventario, s.en_transito::float8 en_transito,
                   s.demanda_calificada::float8 demanda_calificada, s.flujo_neto::float8 flujo_neto, s.zona::text zona,
                   COALESCE(s.cantidad_necesaria, s.cantidad_sugerida)::float8 necesidad, s.stock_cedi::float8 stock_cedi,
                   s.cantidad_sugerida::float8 cantidad_sugerida, s.estado::text estado
            {FROM} WHERE {w} ORDER BY s.bodega_id, s.pct_buffer LIMIT :lim"""), {**p, "lim": limit}).mappings()]
    return {"ejecucion": dict(ej) if ej else None, "total": total, "filas": filas, "tope_excel": TOPE}


@router.get("/excel")
def excel(bodegas: str | None = None, labs: str | None = None, q: str | None = None, zonas: str | None = None, dia: int | None = None,
          empresa: str | None = None, crit: str | None = None, solo_sugerido: bool = True, limite: int = Query(10000, ge=1, le=TOPE),
          user=Depends(requiere("ver_auditoria"))):
    w, p = _donde(user, bodegas, labs, q, zonas, dia, empresa, crit, solo_sugerido)
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        if not ej:
            return Response("No hay una corrida del motor", status_code=404)
        total = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
        prm = {r[0]: float(r[1]) for r in c.execute(text("SELECT clave, valor FROM ddmrp.parametro"))}
        factores = [dict(r) for r in c.execute(text(
            "SELECT tipo, descripcion, factor::float8 factor, desde::float8 desde, hasta::float8 hasta FROM ddmrp.factor_tramo ORDER BY tipo, desde")).mappings()]
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria) AS laboratorio,
                   COALESCE(pn.pronostico, 0)::float8 AS pronostico, s.lead_time::float8 lead_time, s.frecuencia::float8 frecuencia,
                   s.unidad_despacho::float8 unidad_despacho, COALESCE(cr.cota_maxima, 0)::float8 cota_max, COALESCE(cr.cota_minima, 0)::float8 cota_min,
                   COALESCE(pr.indicativo, 0)::int promo, s.vectorizacion::float8 vectorizacion, s.inventario::float8 inventario,
                   s.en_transito::float8 en_transito, s.demanda_calificada::float8 demanda_calificada, s.condenado::int condenado,
                   s.adu::float8 adu, s.toy_aj::float8 toy_aj, s.tog_aj::float8 tog_aj, s.zona::text zona,
                   COALESCE(s.cantidad_necesaria, s.cantidad_sugerida)::float8 necesidad, s.stock_cedi::float8 stock_cedi,
                   s.cantidad_sugerida::float8 cantidad_sugerida, s.estado::text estado, s.cantidad_aprobada::float8 cantidad_aprobada
            {FROM}
            LEFT JOIN ddmrp.pronostico pn ON pn.empresa = s.empresa AND pn.bodega_id = s.bodega_id AND pn.producto_id = s.producto_id
            LEFT JOIN ddmrp.abast_control_referencias cr ON cr.empresa = s.empresa AND cr.bodega_id = s.bodega_id AND cr.producto_id = s.producto_id
            LEFT JOIN ddmrp.promocion pr ON pr.empresa = s.empresa AND pr.producto_id = s.producto_id
            WHERE {w} ORDER BY s.bodega_id, s.pct_buffer LIMIT :lim"""), {**p, "lim": limite}).mappings()]
        # meses de la ventana (el ultimo es el mes de la fecha de calculo) y sus ventas
        n = int(min(max(prm.get("meses_historia", 7), 2), 12))
        fc: date = ej["fecha_calculo"]
        meses = []
        y, m = fc.year, fc.month
        for _ in range(n):
            meses.append(f"{y:04d}{m:02d}"); m -= 1
            if m == 0: y, m = y - 1, 12
        meses.reverse()
        idx = {(f["bodega_id"], f["producto_id"]): f for f in filas}
        for f in filas: f["ventas"] = [0.0] * n
        if filas:
            for b, pid, mes, cant in c.execute(text("""
                SELECT v.bodega_id, v.producto_id, v.mes, sum(v.cantidad)::float8
                FROM ddmrp.ventas_mensual v JOIN unnest(CAST(:b AS text[]), CAST(:p AS text[])) k(b, p) ON k.b = v.bodega_id AND k.p = v.producto_id
                WHERE v.mes = ANY(:m) GROUP BY 1, 2, 3"""), {"b": [f["bodega_id"] for f in filas], "p": [f["producto_id"] for f in filas], "m": meses}):
                idx[(b, pid)]["ventas"][meses.index(mes)] = cant
    data = construir(filas, meses, prm, factores, {"id": ej["id"], "fecha": fc.isoformat()}, truncado=total if total > len(filas) else 0)
    evento("auditoria", usuario_de(user), f"Excel de auditoría: {len(filas):,} filas de la corrida #{ej['id']}", {"filas": len(filas), "total": total, "ejecucion_id": ej["id"]})
    h = {"Content-Disposition": f'attachment; filename="Auditoria_DDMRP_{fc:%Y%m%d}.xlsx"', "X-Filas": str(len(filas)), "X-Filas-Total": str(total)}
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=h)
