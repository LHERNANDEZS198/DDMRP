"""Auditoria del calculo: Excel con las formulas (auditoria_xlsx) de las filas que se ven en la matriz de despacho."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import text
from ..activos import solo_activos
from ..auditoria_xlsx import construir
from ..bitacora import evento, usuario_de
from ..db import pg
from ..security import empresas_permitidas, filtro_sql_permisos, requiere
from .control import FROM, ULTIMA

router = APIRouter(prefix="/auditoria", tags=["auditoria"])
TOPE = 20000


class Fila(BaseModel):
    b: str   # bodega
    p: str   # producto


class PedidoExcel(BaseModel):
    empresa: str
    filas: list[Fila] = Field(min_length=1)
    limite: int = Field(TOPE, ge=1, le=TOPE)


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
    limite = body.limite
    with pg.connect() as c:
        ej = c.execute(text(f"SELECT id, fecha_calculo FROM ddmrp.ejecucion_motor WHERE id = {ULTIMA}")).mappings().first()
        if not ej:
            return Response("No hay una corrida del motor", status_code=404)
        total = c.execute(text(f"SELECT count(*) {FROM} WHERE {w}"), p).scalar()
        if not total:
            return Response("Ninguna de esas filas está en la última corrida del motor (¿cambió la corrida?). Recarga la matriz.", status_code=404)
        prm = {r[0]: float(r[1]) for r in c.execute(text("SELECT clave, valor FROM ddmrp.parametro"))}
        factores = [dict(r) for r in c.execute(text(
            "SELECT tipo, descripcion, factor::float8 factor, desde::float8 desde, hasta::float8 hasta FROM ddmrp.factor_tramo ORDER BY tipo, desde")).mappings()]
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.empresa, s.bodega_id, s.producto_id, mi.descripcion, COALESCE(lb.nombre, mi.categoria) AS laboratorio,
                   COALESCE(pn.pronostico, 0)::float8 AS pronostico, s.lead_time::float8 lead_time, s.frecuencia::float8 frecuencia,
                   s.unidad_despacho::float8 unidad_despacho, COALESCE(cr.cota_maxima, 0)::float8 cota_max, COALESCE(cr.cota_minima, 0)::float8 cota_min,
                   COALESCE(pr.indicativo, 0)::int promo, s.vectorizacion::float8 vectorizacion, s.inventario::float8 inventario,
                   s.en_transito::float8 en_transito, s.demanda_calificada::float8 demanda_calificada, s.condenado::int condenado, COALESCE(s.regla_objetivo, 0)::int regla_objetivo,
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
        idx = {(f["empresa"], f["bodega_id"], f["producto_id"]): f for f in filas}
        for f in filas: f["ventas"] = [0.0] * n
        if filas:
            for em, b, pid, mes, cant in c.execute(text("""
                SELECT v.empresa, v.bodega_id, v.producto_id, v.mes, sum(v.cantidad)::float8
                FROM ddmrp.ventas_mensual v JOIN unnest(CAST(:e AS text[]), CAST(:b AS text[]), CAST(:p AS text[])) k(e, b, p) ON k.e = v.empresa AND k.b = v.bodega_id AND k.p = v.producto_id
                WHERE v.mes = ANY(:m) GROUP BY 1, 2, 3, 4"""), {"e": [f["empresa"] for f in filas], "b": [f["bodega_id"] for f in filas], "p": [f["producto_id"] for f in filas], "m": meses}):
                idx[(em, b, pid)]["ventas"][meses.index(mes)] = cant
    data = construir(filas, meses, prm, factores, {"id": ej["id"], "fecha": fc.isoformat()}, truncado=total if total > len(filas) else 0)
    evento("auditoria", usuario_de(user), f"Excel de auditoría desde la matriz de despacho (empresa {body.empresa}): {len(filas):,} filas de la corrida #{ej['id']}", {"filas": len(filas), "total": total, "ejecucion_id": ej["id"]})
    h = {"Content-Disposition": f'attachment; filename="Auditoria_DDMRP_{fc:%Y%m%d}.xlsx"', "X-Filas": str(len(filas)), "X-Filas-Total": str(total)}
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=h)
