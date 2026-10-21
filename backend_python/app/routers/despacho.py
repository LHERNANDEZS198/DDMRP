from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from ..db import pg
from .. import reparto, bitacora
from ..plano_siesa import co_derivado, generar_xlsx, notas_por_defecto
from ..activos import solo_activos
from ..security import usuario_actual, filtro_sql_permisos, exigir, requiere, empresas_permitidas

router = APIRouter(prefix="/despacho", tags=["despacho"])
ULTIMA = "(SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok')"
# lo que NO se sugiere ni se envia: laboratorios sin envio (maestro) e items sin stock en el CEDI de su empresa
SIN_ENVIO = "NOT EXISTS (SELECT 1 FROM ddmrp.maestro_item mi_x JOIN ddmrp.laboratorio_sin_envio ls_x ON ls_x.laboratorio = mi_x.categoria WHERE mi_x.producto_id = s.producto_id)"
CON_CEDI = "(s.stock_cedi IS NULL OR s.stock_cedi > 0)"
ACTIVO = solo_activos("s")   # items inactivos o bloqueados en Siesa no se sugieren ni se envian (regla solo_items_activos)


@router.get("/dias")
def dias(empresa: str | None = None, user=Depends(requiere("ver_despacho"))):
    """DIA de abastecimiento de cada tienda (maestro dias-bodega) y todas las bodegas, para armar la corrida. Con `empresa`, solo las de esa
    empresa (un mismo codigo de bodega puede existir en las dos)."""
    with pg.connect() as c:
        por_dia: dict[int, list[str]] = {}
        for dia, b in c.execute(text("SELECT dia, bodega_id FROM ddmrp.bodega_dia WHERE (CAST(:e AS text) IS NULL OR empresa = :e) ORDER BY dia, bodega_id"), {"e": empresa}).all():
            por_dia.setdefault(dia, []).append(b)
        todas = [r[0] for r in c.execute(text("SELECT bodega_id FROM ddmrp.abast_bitacora WHERE (CAST(:e AS text) IS NULL OR empresa = :e) ORDER BY bodega_id"), {"e": empresa}).all()]
        emp = {b: e for b, e in c.execute(text("SELECT bodega_id, empresa FROM ddmrp.abast_bitacora WHERE (CAST(:e AS text) IS NULL OR empresa = :e)"), {"e": empresa}).all()}
    return {"dias": [{"dia": k, "bodegas": v} for k, v in sorted(por_dia.items())], "bodegas": todas, "empresa_de": emp}


@router.get("/matriz")
def matriz(empresa: str, bodega_id: str | None = None, bodegas: str | None = None, solo_pendientes: bool = True,
           estado: str | None = None, user=Depends(requiere("ver_despacho"))):
    """empresa (05 o 21) es obligatoria: cada empresa tiene su CEDI y su matriz. bodegas = lista separada por comas (las tiendas
    elegidas para la corrida del dia). No se sugieren los items sin stock en el CEDI ni los laboratorios sin envio."""
    if empresa not in ("05", "21"):
        raise HTTPException(400, "Elige la empresa (05 o 21)")
    perm = empresas_permitidas(user["id"])
    if perm and empresa not in perm:
        raise HTTPException(403, f"Tu usuario no tiene asignada la empresa {empresa}")
    w, p = filtro_sql_permisos(user)
    f = f"s.ejecucion_id = {ULTIMA} AND s.empresa = :emp AND (s.cantidad_sugerida > 0 OR s.cantidad_necesaria > 0) AND {w} AND {CON_CEDI} AND {SIN_ENVIO} AND {ACTIVO}"
    p["emp"] = empresa
    if bodega_id: f += " AND s.bodega_id=:b"; p["b"] = bodega_id
    if bodegas: f += " AND s.bodega_id = ANY(:bs)"; p["bs"] = [x.strip() for x in bodegas.split(",") if x.strip()]
    if estado is None:
        estado = "pendiente" if solo_pendientes else "todas"
    if estado.lower() in ("pendiente", "aprobada", "enviada"):
        f += f" AND s.estado='{estado.upper()}'"
    sql = f"""SELECT s.ejecucion_id, s.empresa, s.producto_id, mi.descripcion, mi.categoria, s.bodega_id, s.zona::text zona,
                     s.inventario, s.en_transito, s.flujo_neto, s.tor, s.toy_aj, s.tog_aj, s.unidad_despacho,
                     s.vectorizacion, s.cantidad_sugerida::float8 cantidad_sugerida, s.cantidad_aprobada, s.estado::text estado, s.cantidad_necesaria::float8 cantidad_necesaria, s.stock_cedi::float8 stock_cedi,
                     ci.costo::float8 AS costo, s.regla_objetivo
              FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.maestro_item mi USING (producto_id)
                   LEFT JOIN ddmrp.costo_item ci ON ci.producto_id = s.producto_id
              WHERE {f} ORDER BY s.bodega_id, s.pct_buffer"""
    # Lo que se reparte de cada item (suma de lo sugerido a todas las tiendas de la empresa) se calcula aparte y se cruza aqui: dentro del mismo SELECT, con
    # estadisticas viejas Postgres repetia esa agregacion de ~400 mil filas por cada fila de la matriz (consultas de 20 minutos y 504).
    sql_tot = f"SELECT producto_id, SUM(cantidad_sugerida)::float8 FROM ddmrp.sugerencias_envio WHERE ejecucion_id = {ULTIMA} AND empresa = :emp AND NOT condenado GROUP BY producto_id"
    with pg.connect() as c:
        c.execute(text("SET LOCAL statement_timeout = 50000"))        # menos que el timeout de nginx (60 s): falla con mensaje en vez de dejar consultas colgadas
        try:
            tot = dict(c.execute(text(sql_tot), {"emp": empresa}).all())
            filas = [dict(r) for r in c.execute(text(sql), p).mappings()]
        except DBAPIError as e:
            if "statement timeout" in str(e):
                raise HTTPException(503, "La matriz tardo demasiado en calcularse. Elige una tienda en 'Corrida' o avisa a sistemas (estadisticas de la base).")
            raise
        for f in filas:
            f["cedi_despues"] = None if f["stock_cedi"] is None else float(f["stock_cedi"]) - tot.get(f["producto_id"], 0.0)
        for f in filas:   # lo asignado ya viene repartido por el motor (cantidad_sugerida); necesario = lo que pedia el buffer
            f["cantidad_necesaria"] = float(f["cantidad_necesaria"] if f["cantidad_necesaria"] is not None else f["cantidad_sugerida"])
            f["limitado"] = f["cantidad_sugerida"] + 1e-9 < f["cantidad_necesaria"]
        return filas


@router.get("/cedi")
def cedi(user=Depends(requiere("ver_despacho"))):
    """Estado del inventario del CEDI y la regla de reparto, para mostrarlo en la matriz."""
    from ..config import settings
    with pg.connect() as c:
        n, con, corte = c.execute(text("SELECT count(*), count(*) FILTER (WHERE disponible > 0), max(fecha_corte) FROM ddmrp.inventario_cedi")).first()
        por_empresa = [dict(r) for r in c.execute(text("SELECT empresa, count(*) AS productos, count(*) FILTER (WHERE disponible > 0) AS con_stock, max(fecha_corte) AS corte FROM ddmrp.inventario_cedi GROUP BY empresa ORDER BY empresa")).mappings()]
        regla = reparto.regla_actual(c)
        ult = c.execute(text(f"SELECT count(*) FILTER (WHERE cantidad_necesaria > cantidad_sugerida) FROM ddmrp.sugerencias_envio WHERE ejecucion_id = {ULTIMA}")).scalar()
        res = c.execute(text("SELECT count(*) FROM ddmrp.reserva_cedi WHERE porcentaje > 0")).scalar()
        minimo = float(c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'valor_minimo_envio'")).scalar() or 0)
        con_costos = c.execute(text("SELECT count(*) FROM ddmrp.costo_item")).scalar()
        dias_reparto = reparto.dias_alcance(c)
    return {"minimo_envio": minimo, "con_costos": con_costos, "dias_reparto": dias_reparto, "bodega": settings.siesa_cedi_bodega, "por_empresa": por_empresa, "productos": n, "con_stock": con, "corte": corte, "regla": regla,
            "regla_nombre": reparto.REGLAS.get(regla, "?"), "items_con_reserva": res, "limitadas": ult, "activo": regla != 0 and n > 0}


class Aprobacion(BaseModel):
    ejecucion_id: int
    producto_id: str
    bodega_id: str
    empresa: str | None = None           # una misma tienda puede existir en las dos empresas: el front la manda siempre
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
                              WHERE ejecucion_id=:e AND producto_id=:p AND bodega_id=:b AND (CAST(:em AS text) IS NULL OR empresa = :em)"""),
                      {"q": it.cantidad_aprobada, "ap": it.aprobar, "u": user["nombre"],
                       "e": it.ejecucion_id, "p": it.producto_id, "b": it.bodega_id, "em": it.empresa})
    bitacora.evento("aprobacion", bitacora.usuario_de(user),
                    f"{'Aprobó' if items and items[0].aprobar else 'Guardó cantidades de'} {len(items)} filas", {"filas": len(items), "ejecucion_id": items[0].ejecucion_id if items else None})
    return {"ok": True, "n": len(items)}


class Clave(BaseModel):
    ejecucion_id: int
    producto_id: str
    bodega_id: str
    empresa: str | None = None


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
                                   WHERE ejecucion_id=:e AND producto_id=:p AND bodega_id=:b AND estado='APROBADA'
                                     AND (CAST(:em AS text) IS NULL OR empresa = :em)"""),
                           {"u": user["nombre"], "e": it.ejecucion_id, "p": it.producto_id, "b": it.bodega_id, "em": it.empresa}).rowcount
    bitacora.evento("aprobacion", bitacora.usuario_de(user), f"Devolvió a pendiente {n} filas", {"devueltas": n, "omitidas": len(items) - n})
    return {"ok": True, "devueltas": n, "omitidas": len(items) - n}


def tiendas_bajo_minimo(c, eid: int, bodegas: list[str] | None = None, empresa: str | None = None) -> tuple[dict[str, float], float, bool]:
    """Tiendas cuyo despacho APROBADO vale menos que el minimo (regla valor_minimo_envio), a costo promedio.
    Devuelve ({tienda: valor}, minimo, hay_costos). Sin costos cargados o con minimo 0 la regla no se aplica."""
    minimo = float(c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave = 'valor_minimo_envio'")).scalar() or 0)
    hay = bool(c.execute(text("SELECT EXISTS (SELECT 1 FROM ddmrp.costo_item)")).scalar())
    if minimo <= 0 or not hay:
        return {}, minimo, hay
    rows = c.execute(text("""SELECT s.bodega_id, COALESCE(SUM(COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) * COALESCE(ci.costo, 0)), 0)::float8
                             FROM ddmrp.sugerencias_envio s LEFT JOIN ddmrp.costo_item ci ON ci.producto_id = s.producto_id
                             WHERE s.ejecucion_id = :e AND s.estado = 'APROBADA' AND COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) >= 0.5
                               AND (CAST(:bs AS text[]) IS NULL OR s.bodega_id = ANY(CAST(:bs AS text[]))) AND (CAST(:em AS text) IS NULL OR s.empresa = :em)
                             GROUP BY s.bodega_id"""), {"e": eid, "bs": bodegas or None, "em": empresa}).all()
    return {b: v for b, v in rows if v < minimo}, minimo, True


def consumir_derrame(c, eid, empresa, bodegas):
    """Regla 'vectorizacion_un_solo_uso' = 1: el derrame (vectorizacion) se pone en 0 en el maestro al marcar la fila como ENVIADA,
    para que no se vuelva a sumar en la siguiente corrida. Con 0 (por defecto) el derrame se sigue sumando mientras exista en el maestro."""
    if not (c.execute(text("SELECT valor FROM ddmrp.parametro WHERE clave='vectorizacion_un_solo_uso'")).scalar() or 0) >= 1 or not bodegas:
        return 0
    return c.execute(text("""UPDATE ddmrp.abast_vectorizacion v SET vectorizacion = 0
                             FROM ddmrp.sugerencias_envio s
                             WHERE s.ejecucion_id = :e AND s.estado = 'APROBADA' AND s.empresa = :emp AND s.bodega_id = ANY(:b)
                               AND COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) >= 0.5
                               AND v.empresa = s.empresa AND v.bodega_id = s.bodega_id AND v.producto_id = s.producto_id AND v.vectorizacion <> 0"""),
                     {"e": eid, "emp": empresa, "b": list(bodegas)}).rowcount


class MarcarReq(BaseModel):
    ejecucion_id: int | None = None
    bodegas: list[str] | None = None     # solo estas tiendas; None = todas las que tengan aprobadas
    empresa: str                         # 05 o 21


@router.post("/marcar-enviadas")
def marcar_enviadas(req: MarcarReq, user=Depends(requiere("aprobar_despacho", "descargar_planos"))):
    """APROBADAS -> ENVIADAS sin bajar el plano (p.ej. el plano ya se subio a Siesa). Una tienda cuyo despacho vale menos que el
    minimo no se deja enviar: queda aprobada y se informa."""
    with pg.begin() as c:
        eid = req.ejecucion_id or c.execute(text(f"SELECT {ULTIMA}")).scalar()
        if req.empresa not in ("05", "21"):
            raise HTTPException(400, "Elige la empresa (05 o 21)")
        tiendas = [r[0] for r in c.execute(text("""SELECT DISTINCT bodega_id FROM ddmrp.sugerencias_envio WHERE ejecucion_id = :e AND estado = 'APROBADA' AND empresa = :emp
                                                   AND (CAST(:bs AS text[]) IS NULL OR bodega_id = ANY(CAST(:bs AS text[])))"""),
                                      {"e": eid, "bs": req.bodegas or None, "emp": req.empresa}).all()]
        if not tiendas:
            raise HTTPException(404, "No hay sugerencias aprobadas para marcar como enviadas")
        for b in tiendas:
            exigir(user, b, None, "aprobacion")
        bajo, minimo, _ = tiendas_bajo_minimo(c, eid, req.bodegas, req.empresa)
        ok = [b for b in tiendas if b not in bajo]
        consumir_derrame(c, eid, req.empresa, ok)
        n = c.execute(text("""UPDATE ddmrp.sugerencias_envio SET estado = 'ENVIADA'::ddmrp.estado_sugerencia
                              WHERE ejecucion_id = :e AND estado = 'APROBADA' AND bodega_id = ANY(:b) AND empresa = :emp"""), {"e": eid, "b": ok, "emp": req.empresa}).rowcount if ok else 0
    bitacora.evento("aprobacion", bitacora.usuario_de(user), f"Marcó como enviadas {n} filas de {len(ok)} tiendas" + (f"; {len(bajo)} tiendas bajo el mínimo no se enviaron" if bajo else ""),
                    {"enviadas": n, "tiendas": len(ok), "bajo_minimo": len(bajo), "ejecucion_id": eid})
    return {"ok": True, "enviadas": n, "tiendas": len(ok), "minimo": minimo,
            "bloqueadas": [{"bodega_id": b, "valor": round(v)} for b, v in sorted(bajo.items())]}


class PlanoReq(BaseModel):
    ejecucion_id: int | None = None      # por defecto, la ultima ejecucion ok
    fecha: date | None = None            # fecha del documento (por defecto hoy)
    consec_inicial: int = 1              # consecutivo del primer documento
    notas: str | None = None             # por defecto "ABASTECIMIENTO DEL <dia> DE <MES>"
    marcar_enviadas: bool = False        # True: las filas exportadas pasan a estado ENVIADA
    bodegas: list[str] | None = None     # solo estas tiendas (las elegidas para la corrida); None = todas las aprobadas
    dia: int | None = None               # DIA de abastecimiento: se agrega a la nota por defecto
    empresa: str                         # 05 o 21: el plano es de una sola empresa


@router.post("/exportar-plano")
def exportar_plano(req: PlanoReq, user=Depends(requiere("descargar_planos"))):
    """FASE 2: archivo plano para Siesa con las sugerencias APROBADAS (una requisicion RIT por bodega)."""
    with pg.begin() as c:
        eid = req.ejecucion_id or c.execute(text("SELECT max(id) FROM ddmrp.ejecucion_motor WHERE estado='ok'")).scalar()
        if req.empresa not in ("05", "21"):
            raise HTTPException(400, "Elige la empresa (05 o 21)")
        rows = c.execute(text(f"""SELECT s.bodega_id, s.producto_id, COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) AS q,
                                        co.id_co
                                 FROM ddmrp.sugerencias_envio s
                                 LEFT JOIN ddmrp.abast_bitacora co ON co.bodega_id = s.bodega_id AND co.empresa = s.empresa
                                 WHERE s.ejecucion_id = :e AND s.estado = 'APROBADA' AND s.empresa = :emp
                                   AND COALESCE(s.cantidad_aprobada, s.cantidad_sugerida) >= 0.5 AND {CON_CEDI} AND {SIN_ENVIO} AND {ACTIVO}
                                   AND (CAST(:bs AS text[]) IS NULL OR s.bodega_id = ANY(CAST(:bs AS text[])))"""),
                         {"e": eid, "bs": req.bodegas or None, "emp": req.empresa}).all()
        if not rows:
            raise HTTPException(404, "No hay sugerencias aprobadas para exportar")
        bajo, minimo, _ = tiendas_bajo_minimo(c, eid, req.bodegas, req.empresa)
        if bajo:   # no se dejan enviar: quedan aprobadas y no entran al plano
            rows = [r for r in rows if r[0] not in bajo]
            if not rows:
                raise HTTPException(409, f"Ninguna tienda llega al valor mínimo de envío (${minimo:,.0f}): " +
                                    ", ".join(f"{b} ${v:,.0f}" for b, v in sorted(bajo.items())[:8]))
        for b in sorted({r[0] for r in rows}):
            exigir(user, b, None, "aprobacion")
        derivados = sorted({r[0] for r in rows if not r[3]})
        lineas = [(r[0], r[3] or co_derivado(r[0]), r[1], float(r[2])) for r in rows]
        fecha = req.fecha or date.today()
        data = generar_xlsx(lineas, fecha=fecha, consec_inicial=req.consec_inicial,
                            notas=req.notas or notas_por_defecto(fecha, req.dia))
        if req.marcar_enviadas:
            consumir_derrame(c, eid, req.empresa, sorted({r[0] for r in rows}))
            c.execute(text("""UPDATE ddmrp.sugerencias_envio SET estado = 'ENVIADA'::ddmrp.estado_sugerencia
                              WHERE ejecucion_id = :e AND estado = 'APROBADA'
                                AND COALESCE(cantidad_aprobada, cantidad_sugerida) >= 0.5 AND bodega_id = ANY(:b)
                                AND empresa = :emp"""),
                      {"e": eid, "b": sorted({r[0] for r in rows}), "emp": req.empresa})
    bitacora.evento("plano", bitacora.usuario_de(user),
                    f"Plano del {fecha:%Y-%m-%d}: {len(lineas)} líneas, {len({r[0] for r in rows})} tiendas" + (", marcadas como enviadas" if req.marcar_enviadas else ""),
                    {"ejecucion_id": eid, "lineas": len(lineas), "tiendas": len({r[0] for r in rows}), "consec_inicial": req.consec_inicial,
                     "marcar_enviadas": req.marcar_enviadas, "dia": req.dia})
    headers = {"Content-Disposition": f'attachment; filename="Abastecimiento_{fecha:%Y%m%d}.xlsx"'}
    if bajo:
        headers["X-Bodegas-Bajo-Minimo"] = ",".join(f"{b}:{round(v)}" for b, v in sorted(bajo.items()))
    if derivados:  # bodegas sin centro de operacion cargado: se uso la regla observada en el ejemplo
        headers["X-Bodegas-CO-Derivado"] = ",".join(derivados)
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers=headers)


@router.post("/enviar-siesa")
def enviar_siesa(user=Depends(requiere("descargar_planos"))):
    """FASE 3: envio directo por web service de Siesa."""
    raise HTTPException(501, "Pendiente: integracion web service Siesa")
