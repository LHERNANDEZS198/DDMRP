"""Endpoints que usa el BPM (no el navegador) para las ordenes de compra. Autenticacion: cabecera X-OC-Secret == BPM_SECRET (si no esta configurado, todo se rechaza).
  POST /api/bpm/oc/{id}/estado  -> callback de estado del BPM (en_revision, aprobada, rechazada, creada, error, incierta)
  POST /api/bpm/oc/{id}/plano/vigente -> plano con la fecha de HOY (el BPM lo pide justo antes de crear en Siesa)
  GET  /api/bpm/oc/{id}/documento -> datos de la OC ya formateados (es-CO) para la plantilla PDF del fin de proceso del BPM (el BPM los pide tras crearla en Siesa; el layout del documento vive aqui)
  POST /api/bpm/oc/{id}/plano   -> el aprobador cambio cantidades/costos: DDMRP recalcula las lineas y devuelve el plano nuevo (el formato del plano vive SOLO aqui)
Contrato completo: docs/OC_BPM_CONTRATO.md"""
import hmac
from datetime import date
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .. import siesa_oc
from ..bitacora import evento
from ..config import settings
from ..db import pg
from .compras import ULTIMA
from .oc import _al_dia, _cerrar_creada, _lineas_de, _oc_dict, _marcar


def _secreto(x_oc_secret: str | None = Header(default=None)) -> None:
    esperado = settings.bpm_secret
    if not esperado or not x_oc_secret or not hmac.compare_digest(esperado.encode(), x_oc_secret.encode()):
        raise HTTPException(401, "No autorizado")


router = APIRouter(prefix="/bpm/oc", tags=["bpm"], dependencies=[Depends(_secreto)])
ESTADOS = {"en_revision", "aprobada", "rechazada", "creada", "error", "incierta"}


class EstadoIn(BaseModel):
    estado: str
    mensaje: str | None = None
    consecutivo: str | None = None       # p.ej. OCM-1234 (si el BPM lo leyo de Siesa)
    grupo: str | None = None             # grupo aprobador asignado
    tomada_por: str | None = None
    instance_id: str | None = None


@router.post("/{oc_id}/estado")
def estado(oc_id: int, b: EstadoIn):
    if b.estado not in ESTADOS:
        raise HTTPException(400, f"Estado inválido: {b.estado}")
    with pg.connect() as c:
        r = c.execute(text("SELECT empresa, referencia, estado FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
    if not r:
        raise HTTPException(404, "No existe esa OC")
    if r["estado"] == "creada" and b.estado != "creada":      # una OC ya creada en Siesa no retrocede (llamadas repetidas o tardias del BPM)
        return {"ok": True, "ignorado": "ya estaba creada"}
    if b.estado == "creada":
        if b.consecutivo:
            _marcar(oc_id, "creada", b.mensaje or "Creada en Siesa por el BPM", b.consecutivo)
            with pg.begin() as c:   # se sueltan las cantidades editadas de esos items (se conservaban hasta montar la OC)
                c.execute(text("DELETE FROM ddmrp.compras_cantidad cm USING ddmrp.orden_compra_linea l WHERE l.oc_id = :i AND cm.empresa = :e AND cm.producto_id = l.producto_id"), {"i": oc_id, "e": r["empresa"]})
                c.execute(text("DELETE FROM ddmrp.compras_costo cm USING ddmrp.orden_compra_linea l WHERE l.oc_id = :i AND cm.empresa = :e AND cm.producto_id = l.producto_id"), {"i": oc_id, "e": r["empresa"]})
            evento("compras", b.tomada_por, f"OC {r['referencia']} creada en Siesa por el BPM ({b.consecutivo})", {"oc_id": oc_id, "consecutivo": b.consecutivo})
        else:
            _cerrar_creada(oc_id, r["empresa"], r["referencia"], b.mensaje or "Creada en Siesa por el BPM", b.tomada_por)
    else:
        _marcar(oc_id, b.estado, b.mensaje or b.estado)
    sets, p = ["estado_bpm_fecha = now()"], {"i": oc_id}
    for col, v in (("grupo", b.grupo), ("tomada_por", b.tomada_por), ("bpm_id", b.instance_id)):
        if v:
            sets.append(f"{col} = :{col}"); p[col] = v
    with pg.begin() as c:
        c.execute(text(f"UPDATE ddmrp.orden_compra SET {', '.join(sets)} WHERE id = :i"), p)
    return {"ok": True}


class LineaIn(BaseModel):
    producto_id: str
    cantidad: float
    costo: float


class PlanoIn(BaseModel):
    lineas: list[LineaIn]
    nota: str | None = None            # obligatoria si cambia algun costo (regla del flujo de aprobacion)


@router.get("/{oc_id}")
def detalle(oc_id: int):
    """La OC con sus lineas (y lo original si se edito): lo que el BPM muestra al aprobador."""
    with pg.connect() as c:
        r = c.execute(text("SELECT id, empresa, proveedor_id, proveedor_nombre, sucursal, cond_pago, comprador, estado, referencia, valor::float8 AS valor, iva::float8 AS iva, total::float8 AS total, items, "
                           "unidades::float8 AS unidades, siesa_consecutivo, mensaje, creado_por, requiere_revision, motivo_revision FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
        if not r:
            raise HTTPException(404, "No existe esa OC")
        lineas = [dict(x) for x in c.execute(text(f"""
            SELECT l.nro, l.producto_id, l.descripcion, l.cantidad::float8 AS cantidad, l.costo::float8 AS costo, l.iva_tasa::float8 AS iva_tasa,
                   l.cantidad_original::float8 AS cantidad_original, l.costo_original::float8 AS costo_original, l.fecha_entrega::text AS fecha_entrega,
                   l.cantidad_calculada::float8 AS cantidad_sugerida,                       -- lo que calculo el motor (NULL en OC anteriores a este dato)
                   COALESCE(l.cantidad_original, l.cantidad)::float8 AS cantidad_comprador, -- lo que dejo compras al montar la OC
                   l.costo_calculado::float8 AS costo_cotizado,
                   COALESCE(l.costo_original, l.costo)::float8 AS costo_comprador,
                   COALESCE(mi.categoria, '') AS lab_cod, COALESCE(lb.nombre, '') AS lab_nombre,
                   z.zona, z.inventario::float8 AS saldo_cedi, z.en_transito::float8 AS en_transito
            FROM ddmrp.orden_compra_linea l
            LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = l.producto_id
            LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = mi.categoria
            LEFT JOIN LATERAL (SELECT s.zona::text AS zona, s.inventario, s.en_transito FROM ddmrp.sugerencias_cedi s
                               WHERE s.ejecucion_id = {ULTIMA} AND s.empresa = :e AND s.producto_id = l.producto_id LIMIT 1) z ON true
            WHERE l.oc_id = :i ORDER BY l.nro"""), {"i": oc_id, "e": r["empresa"]}).mappings()]
        creado = c.execute(text("SELECT ((creado AT TIME ZONE 'UTC') - interval '5 hours')::date::text FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).scalar()
    entregas = [l["fecha_entrega"] for l in lineas if l.get("fecha_entrega")]
    extra = {"fecha_montaje": creado, "fecha_necesidad": max(entregas) if entregas else None, "fecha_necesidad_min": min(entregas) if entregas else None}
    return dict(r) | extra | {"lineas": lineas}


def _n(v) -> str:
    """Numero en formato es-CO (1.234,50): la plantilla imprime el valor tal cual."""
    return f"{float(v or 0):,.2f}".translate(str.maketrans(",.", ".,"))


def _d(iso) -> str:
    p = str(iso or "")[:10].split("-")
    return f"{p[2]}/{p[1]}/{p[0]}" if len(p) == 3 and len(p[0]) == 4 else ""


@router.get("/{oc_id}/documento")
def documento(oc_id: int):
    """Datos de la OC para la plantilla del PDF (docx con {etiquetas}): encabezado, totales y lineas, con la fecha de HOY (la de Siesa) y lo que edito el aprobador.
    Los campos de fecha y numeros vienen formateados; fechaArchivo (AAAA-MM-DD) sirve para el nombre del archivo."""
    d = detalle(oc_id)
    hoy = siesa_oc.hoy()
    iso = hoy.isoformat() if hasattr(hoy, "isoformat") else str(hoy)
    entrega = max((str(l["fecha_entrega"]) for l in d["lineas"] if l.get("fecha_entrega")), default="")
    return {
        "referencia": d["referencia"],
        "proveedor": f"{d['proveedor_id']}-{d['proveedor_nombre']}",
        "solicitante": d.get("creado_por") or "",
        "fecha": _d(iso), "fechaEntrega": _d(entrega), "fechaArchivo": iso[:10],
        "subtotal": _n(d["valor"]), "iva": _n(d["iva"]), "total": _n(d["total"]),
        "lineas": [{"referencia": l["producto_id"], "descripcion": l.get("descripcion") or "", "unidad": "UND", "cantidad": _n(l["cantidad"]),
                    "valor_u": _n(l["costo"]), "iva": _n(l["iva_tasa"]), "subtotal": _n(l["cantidad"] * l["costo"])} for l in d["lineas"]],
    }


@router.post("/{oc_id}/plano/vigente")
def plano_vigente(oc_id: int):
    """Plano de la OC tal como esta, pero con la fecha de HOY (documento y entregas). El BPM lo pide justo antes de crear en Siesa: una OC aprobada dias despues
    del envio no puede ir con la fecha vieja (Siesa: «La fecha del documento debe ser igual a la fecha del sistema»)."""
    with pg.connect() as c:
        r = c.execute(text("SELECT * FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
    if not r:
        raise HTTPException(404, "No existe esa OC")
    if r["estado"] == "creada":
        raise HTTPException(409, "La OC ya está creada en Siesa")
    _al_dia(oc_id)
    with pg.connect() as c:
        lineas = _lineas_de(c, oc_id)
    pl = siesa_oc.armar_plano(_oc_dict(dict(r) | {"fecha": siesa_oc.hoy()}), [dict(l) for l in lineas])
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.orden_compra SET plano = :p WHERE id = :i"), {"p": pl, "i": oc_id})
    return {"plano": pl}


@router.post("/{oc_id}/plano")
def plano(oc_id: int, b: PlanoIn):
    """El aprobador edito la OC. Solo se pueden cambiar cantidad y costo de las lineas que ya tiene, o quitarlas (cantidad 0); no se agregan items.
    Guarda lo nuevo (conservando lo original para auditoria) y devuelve el plano recalculado."""
    with pg.connect() as c:
        r = c.execute(text("SELECT * FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
        if not r:
            raise HTTPException(404, "No existe esa OC")
        if r["estado"] in ("creada",):
            raise HTTPException(409, "La OC ya está creada en Siesa: no se edita")
        actuales = {l["producto_id"]: l for l in _lineas_de(c, oc_id)}
    nuevas = {l.producto_id: l for l in b.lineas}
    extra = [k for k in nuevas if k not in actuales]
    if extra:
        raise HTTPException(400, f"Ítems que no estaban en la OC: {', '.join(extra)}")
    dec = settings.oc_decimales_precio
    quedan, cambia_costo = [], False
    for k, a in actuales.items():
        n = nuevas.get(k)
        if n is None or round(n.cantidad) <= 0:
            continue                                   # quitada
        if n.costo <= 0:
            raise HTTPException(400, f"{k}: el costo debe ser mayor a 0")
        costo = round(n.costo, dec)
        cambia_costo = cambia_costo or abs(costo - float(a["costo"])) > 1e-9
        quedan.append((k, a, round(n.cantidad), costo))
    if not quedan:
        raise HTTPException(400, "La OC quedaría sin líneas")
    if cambia_costo and not (b.nota or "").strip():
        raise HTTPException(400, "Cambiaste un costo: la nota es obligatoria")
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.orden_compra_linea SET cantidad_original = COALESCE(cantidad_original, cantidad), costo_original = COALESCE(costo_original, costo) WHERE oc_id = :i"), {"i": oc_id})
        c.execute(text("DELETE FROM ddmrp.orden_compra_linea WHERE oc_id = :i AND NOT (producto_id = ANY(:k))"), {"i": oc_id, "k": [q[0] for q in quedan]})
        for k, a, cant, costo in quedan:
            c.execute(text("UPDATE ddmrp.orden_compra_linea SET cantidad = :q, costo = :c WHERE oc_id = :i AND producto_id = :p"), {"q": cant, "c": costo, "i": oc_id, "p": k})
        rows = [dict(x) for x in c.execute(text("SELECT nro, producto_id, descripcion, cantidad, costo, iva_tasa, fecha_entrega FROM ddmrp.orden_compra_linea WHERE oc_id = :i ORDER BY nro"), {"i": oc_id}).mappings()]
        for n, x in enumerate(rows, start=1):     # renumerar 1..n sin huecos (nro_registro del movimiento)
            c.execute(text("UPDATE ddmrp.orden_compra_linea SET nro = :n + 100000 WHERE oc_id = :i AND nro = :o"), {"n": n, "i": oc_id, "o": x["nro"]})
        c.execute(text("UPDATE ddmrp.orden_compra_linea SET nro = nro - 100000 WHERE oc_id = :i AND nro > 100000"), {"i": oc_id})
        valor = sum(float(x["cantidad"]) * float(x["costo"]) for x in rows)
        iva = sum(float(x["cantidad"]) * float(x["costo"]) * float(x["iva_tasa"] or 0) / 100 for x in rows)
        c.execute(text("UPDATE ddmrp.orden_compra SET valor = :v, iva = :iva, total = :t, items = :it, unidades = :u, mensaje = :m WHERE id = :i"),
                  {"v": valor, "iva": iva, "t": valor + iva, "it": len(rows), "u": sum(float(x["cantidad"]) for x in rows), "i": oc_id,
                   "m": "Editada en la revisión" + (f": {b.nota.strip()}" if (b.nota or "").strip() else "")})
    with pg.connect() as c:
        lineas = _lineas_de(c, oc_id)
    pl = siesa_oc.armar_plano(_oc_dict(dict(r) | {"fecha": siesa_oc.hoy()}), [dict(l) for l in lineas])
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.orden_compra SET plano = :p WHERE id = :i"), {"p": pl, "i": oc_id})
    evento("compras", None, f"OC {r['referencia']} editada en la revisión", {"oc_id": oc_id, "nota": b.nota, "cambia_costo": cambia_costo})
    return {"plano": pl, "valor": valor, "iva": iva, "total": valor + iva, "items": len(lineas)}
