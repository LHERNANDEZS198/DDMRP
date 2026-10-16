from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..plano_siesa import co_derivado, generar_xlsx, notas_por_defecto
from ..security import usuario_actual, filtro_sql_permisos, exigir, requiere

router = APIRouter(prefix="/despacho", tags=["despacho"])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"


@router.get("/dias")
def dias(user=Depends(requiere("ver_despacho"))):
    """DIA de abastecimiento de cada tienda (maestro dias-bodega) y todas las bodegas, para armar la corrida."""
    with pg.connect() as c:
        por_dia: dict[int, list[str]] = {}
        for dia, b in c.execute(text("SELECT dia, bodega_id FROM ddmrp.bodega_dia ORDER BY dia, bodega_id")).all():
            por_dia.setdefault(dia, []).append(b)
        todas = [r[0] for r in c.execute(text("SELECT bodega_id FROM ddmrp.abast_bitacora ORDER BY bodega_id")).all()]
    return {"dias": [{"dia": k, "bodegas": v} for k, v in sorted(por_dia.items())], "bodegas": todas}


@router.get("/matriz")
def matriz(bodega_id: str | None = None, bodegas: str | None = None, solo_pendientes: bool = True,
           estado: str | None = None, user=Depends(requiere("ver_despacho"))):
    """bodegas = lista separada por comas (las tiendas elegidas para la corrida del dia)."""
    w, p = filtro_sql_permisos(user)
    f = f"s.ejecucion_id = {ULTIMA} AND s.cantidad_sugerida > 0 AND {w}"
    if bodega_id: f += " AND s.bodega_id=:b"; p["b"] = bodega_id
    if bodegas: f += " AND s.bodega_id = ANY(:bs)"; p["bs"] = [x.strip() for x in bodegas.split(",") if x.strip()]
    if estado is None:
        estado = "pendiente" if solo_pendientes else "todas"
    if estado.lower() in ("pendiente", "aprobada", "enviada"):
        f += f" AND s.estado='{estado.upper()}'"
    sql = f"""SELECT s.ejecucion_id, s.empresa, s.producto_id, mi.descripcion, mi.categoria, s.bodega_id, s.zona::text zona,
                     s.inventario, s.en_transito, s.flujo_neto, s.tor, s.toy_aj, s.tog_aj, s.unidad_despacho,
                     s.vectorizacion, s.cantidad_sugerida, s.cantidad_aprobada, s.estado::text estado
              FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi USING (producto_id)
              WHERE {f} ORDER BY s.bodega_id, s.pct_buffer"""
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), p).mappings()]


class Aprobacion(BaseModel):
    ejecucion_id: int
    producto_id: str
    bodega_id: str
    cantidad_aprobada: float
    aprobar: bool = True


@router.post("/aprobar")
def aprobar(items: list[Aprobacion], user=Depends(requiere("aprobar_despacho"))):
    with pg.begin() as c:
        for it in items:
            cat = c.execute(text("SELECT categoria FROM ddmrp.maestro_item WHERE producto_id=:p"),
                            {"p": it.producto_id}).scalar()
            exigir(user, it.bodega_id, cat, "aprobacion" if it.aprobar else "edicion")
            c.execute(text("""UPDATE ddmrp.sugerencias_envio SET cantidad_aprobada=:q,
                              estado = CASE WHEN :ap THEN 'APROBADA'::ddmrp.estado_sugerencia ELSE estado END,
                              aprobado_por=:u, aprobado_en=now()
                              WHERE ejecucion_id=:e AND producto_id=:p AND bodega_id=:b"""),
                      {"q": it.cantidad_aprobada, "ap": it.aprobar, "u": user["nombre"],
                       "e": it.ejecucion_id, "p": it.producto_id, "b": it.bodega_id})
    return {"ok": True, "n": len(items)}


class Clave(BaseModel):
    ejecucion_id: int
    producto_id: str
    bodega_id: str


@router.post("/desaprobar")
def desaprobar(items: list[Clave], user=Depends(requiere("aprobar_despacho"))):
    """Vuelta atras: las APROBADAS vuelven a PENDIENTE (y pierden la cantidad aprobada). Las ya ENVIADAS no se tocan."""
    n = 0
    with pg.begin() as c:
        for it in items:
            cat = c.execute(text("SELECT categoria FROM ddmrp.maestro_item WHERE producto_id=:p"), {"p": it.producto_id}).scalar()
            exigir(user, it.bodega_id, cat, "aprobacion")
            n += c.execute(text("""UPDATE ddmrp.sugerencias_envio SET estado='PENDIENTE'::ddmrp.estado_sugerencia, cantidad_aprobada=NULL,
                                   aprobado_por=:u, aprobado_en=now()
                                   WHERE ejecucion_id=:e AND producto_id=:p AND bodega_id=:b AND estado='APROBADA'"""),
                           {"u": user["nombre"], "e": it.ejecucion_id, "p": it.producto_id, "b": it.bodega_id}).rowcount
    return {"ok": True, "devueltas": n, "omitidas": len(items) - n}


class PlanoReq(BaseModel):
    ejecucion_id: int | None = None      # por defecto, la ultima ejecucion ok
    fecha: date | None = None            # fecha del documento (por defecto hoy)
    consec_inicial: int = 1              # consecutivo del primer documento
    notas: str | None = None             # por defecto "ABASTECIMIENTO DEL <dia> DE <MES>"
    marcar_enviadas: bool = False        # True: las filas exportadas pasan a estado ENVIADA
    bodegas: list[str] | None = None     # solo estas tiendas (las elegidas para la corrida); None = todas las aprobadas
    dia: int | None = None               # DIA de abastecimiento: se agrega a la nota por defecto


@router.post("/exportar-plano")
def exportar_plano(req: PlanoReq, user=Depends(requiere("descargar_planos"))):
    """FASE 2: archivo plano para Siesa con las sugerencias APROBADAS (una requisicion RIT por bodega)."""
    with pg.begin() as c:
        eid = req.ejecucion_id or c.execute(text("SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok'")).scalar()
        rows = c.execute(text("""SELECT s.bodega_id, s.producto_id, COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) AS q,
                                        co.id_co
                                 FROM ddmrp.sugerencias_envio s
                                 LEFT JOIN ddmrp.bodega_centro_operacion co ON co.bodega_id = s.bodega_id
                                 WHERE s.ejecucion_id = :e AND s.estado = 'APROBADA'
                                   AND COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) >= 0.5
                                   AND (CAST(:bs AS text[]) IS NULL OR s.bodega_id = ANY(CAST(:bs AS text[])))"""),
                         {"e": eid, "bs": req.bodegas or None}).all()
        if not rows:
            raise HTTPException(404, "No hay sugerencias aprobadas para exportar")
        for b in sorted({r[0] for r in rows}):
            exigir(user, b, None, "aprobacion")
        derivados = sorted({r[0] for r in rows if not r[3]})
        lineas = [(r[0], r[3] or co_derivado(r[0]), r[1], float(r[2])) for r in rows]
        fecha = req.fecha or date.today()
        data = generar_xlsx(lineas, fecha=fecha, consec_inicial=req.consec_inicial,
                            notas=req.notas or notas_por_defecto(fecha, req.dia))
        if req.marcar_enviadas:
            c.execute(text("""UPDATE ddmrp.sugerencias_envio SET estado = 'ENVIADA'::ddmrp.estado_sugerencia
                              WHERE ejecucion_id = :e AND estado = 'APROBADA'
                                AND COALESCE(cantidad_aprobada, cantidad_sugerida) >= 0.5 AND bodega_id = ANY(:b)"""),
                      {"e": eid, "b": sorted({r[0] for r in rows})})
    headers = {"Content-Disposition": f'attachment; filename="Abastecimiento_{fecha:%Y%m%d}.xlsx"'}
    if derivados:  # bodegas sin centro de operacion cargado: se uso la regla observada en el ejemplo
        headers["X-Bodegas-CO-Derivado"] = ",".join(derivados)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@router.post("/enviar-siesa")
def enviar_siesa(user=Depends(requiere("descargar_planos"))):
    """FASE 3: envio directo por web service de Siesa."""
    raise HTTPException(501, "Pendiente: integracion web service Siesa")
