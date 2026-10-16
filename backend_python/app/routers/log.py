"""Informe de log: cuando corrio cada cosa (motor, ETL, sincronizaciones, cargas, planos), quien la lanzo o si fue automatica,
cuanto tardo y como termino; mas el historial de cambios de configuracion (config_audit)."""
import csv, io
from datetime import date, timedelta
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from ..bitacora import TIPOS
from ..db import pg
from ..security import requiere

router = APIRouter(prefix="/log", tags=["log"], dependencies=[Depends(requiere("ver_log"))])

SELECT = """SELECT id, tipo, origen, usuario, inicio, fin, estado, mensaje, resumen, padre_id,
                   round(extract(epoch FROM COALESCE(fin, now()) - inicio))::int AS segundos
            FROM ddmrp.bitacora"""


def _filtros(tipo, origen, estado, desde, hasta, usuario, q):
    w, p = ["TRUE"], {}
    if tipo: w.append("tipo = ANY(CAST(:tipo AS text[]))"); p["tipo"] = tipo.split(",")
    if origen: w.append("origen = :origen"); p["origen"] = origen
    if estado: w.append("estado = :estado"); p["estado"] = estado
    if usuario: w.append("usuario = :usuario"); p["usuario"] = usuario
    if desde: w.append("inicio >= :desde"); p["desde"] = desde
    if hasta: w.append("inicio < CAST(:hasta AS date) + 1"); p["hasta"] = hasta
    if q: w.append("(COALESCE(mensaje,'') || ' ' || COALESCE(resumen::text,'') || ' ' || COALESCE(usuario,'')) ILIKE :q"); p["q"] = f"%{q}%"
    return " AND ".join(w), p


@router.get("")
def listar(tipo: str | None = None, origen: str | None = None, estado: str | None = None, usuario: str | None = None,
           desde: date | None = None, hasta: date | None = None, q: str | None = None, limit: int = Query(500, le=5000)):
    w, p = _filtros(tipo, origen, estado, desde or date.today() - timedelta(days=30), hasta, usuario, q)
    with pg.connect() as c:
        filas = [dict(r._mapping) for r in c.execute(text(f"{SELECT} WHERE {w} ORDER BY inicio DESC, id DESC LIMIT :l"), {**p, "l": limit})]
        usuarios = [r[0] for r in c.execute(text("SELECT DISTINCT usuario FROM ddmrp.bitacora WHERE usuario IS NOT NULL ORDER BY 1"))]
        ult = {r[0]: dict(r._mapping) for r in c.execute(text(
            "SELECT DISTINCT ON (tipo) tipo, inicio, fin, estado, origen, usuario FROM ddmrp.bitacora "
            "WHERE tipo IN ('pipeline','etl','motor') ORDER BY tipo, inicio DESC"))}
    return {"filas": filas, "tipos": TIPOS, "usuarios": usuarios, "ultimas": ult}


@router.get("/cambios")
def cambios(tabla: str | None = None, usuario: str | None = None, desde: date | None = None, hasta: date | None = None,
            q: str | None = None, limit: int = Query(500, le=5000)):
    """Cambios de configuracion: reglas, maestros editados o cargados, usuarios y perfiles."""
    w, p = ["fecha >= :desde"], {"desde": desde or date.today() - timedelta(days=30), "l": limit}
    if tabla: w.append("tabla = :tabla"); p["tabla"] = tabla
    if usuario: w.append("usuario = :usuario"); p["usuario"] = usuario
    if hasta: w.append("fecha < CAST(:hasta AS date) + 1"); p["hasta"] = hasta
    if q: w.append("(llave || ' ' || campo || ' ' || COALESCE(valor_anterior,'') || ' ' || COALESCE(valor_nuevo,'')) ILIKE :q"); p["q"] = f"%{q}%"
    with pg.connect() as c:
        filas = [dict(r._mapping) for r in c.execute(text(
            f"SELECT id, tabla, llave, campo, valor_anterior, valor_nuevo, usuario, fecha FROM ddmrp.config_audit WHERE {' AND '.join(w)} "
            "ORDER BY fecha DESC, id DESC LIMIT :l"), p)]
        tablas = [r[0] for r in c.execute(text("SELECT DISTINCT tabla FROM ddmrp.config_audit ORDER BY 1"))]
    return {"filas": filas, "tablas": tablas}


@router.get("/csv")
def descargar(tipo: str | None = None, origen: str | None = None, estado: str | None = None, usuario: str | None = None,
              desde: date | None = None, hasta: date | None = None, q: str | None = None):
    w, p = _filtros(tipo, origen, estado, desde or date.today() - timedelta(days=30), hasta, usuario, q)
    with pg.connect() as c:
        filas = c.execute(text(f"{SELECT} WHERE {w} ORDER BY inicio DESC, id DESC LIMIT 50000"), p).all()
    out = io.StringIO(); out.write("﻿"); w_ = csv.writer(out, delimiter=";")
    w_.writerow(["id", "operación", "origen", "usuario", "inicio", "fin", "segundos", "estado", "mensaje", "resumen"])
    for r in filas:
        w_.writerow([r.id, TIPOS.get(r.tipo, r.tipo), "automático" if r.origen == "auto" else "manual", r.usuario or "", r.inicio, r.fin or "",
                     r.segundos, r.estado, r.mensaje or "", r.resumen if r.resumen is None else str(r.resumen)])
    return Response(out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="log_ddmrp.csv"'})
