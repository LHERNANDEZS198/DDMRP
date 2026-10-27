"""Ordenes de compra: crea la OC en Siesa por el web service (plano 0420/0421) desde lo elegido en «Necesidades de compra».
Una OC por proveedor y empresa. La referencia (DDMRP + id con ceros, 15 car. max) es la llave anti-duplicados: antes de enviar se consulta a Siesa si ya existe.
Un timeout deja la OC 'incierta' y NO se reenvia hasta confirmar por la referencia que Siesa no la guardo."""
import json
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from .. import siesa_oc
from ..bitacora import evento, usuario_de
from ..config import settings
from ..db import pg
from ..security import requiere
from .compras import _necesidades

router = APIRouter(prefix="/compras/oc", tags=["ordenes de compra"], dependencies=[Depends(requiere("ver_compras"))])
MAX_POR_ENVIO = 10
ESPERA_INCIERTA = timedelta(minutes=3)       # una OC 'incierta' no se reenvia antes de esto, aunque Siesa aun no la muestre


class Sel(BaseModel):
    empresa: str
    producto_id: str


class EnviarIn(BaseModel):
    items: list[Sel]
    solo_plano: bool = False      # vista previa: arma el plano y lo devuelve, sin guardar ni enviar


def _comprador(user) -> str:
    uid = str(user.get("id") or "").strip()
    if not uid or uid.startswith("prueba:"):
        raise HTTPException(400, "Estás viendo como otro perfil (modo prueba): vuelve a tu usuario para enviar órdenes de compra")
    return uid


def _grupos(user, items: list[Sel]) -> tuple[list[dict], list[str]]:
    """Recalcula en el servidor (no se confia en cantidades ni costos que mande el navegador) y arma una OC por empresa+proveedor+sucursal."""
    pedido = {(i.empresa, i.producto_id) for i in items}
    r = _necesidades(user, None, None, None, None, None, None, 20000)
    filas = {(f["empresa"], f["producto_id"]): f for f in r["filas"]}
    avisos = [f"{e}/{p}: ya no aparece en las necesidades (¿proveedor bloqueado por pedido mínimo o sin permiso?)" for (e, p) in sorted(pedido) if (e, p) not in filas]
    hoy = siesa_oc.hoy()
    dec = settings.oc_decimales_precio
    cfg = _cfg_revision()
    por: dict[tuple, dict] = {}
    for k in sorted(pedido):
        f = filas.get(k)
        if not f:
            continue
        cant = round(f["qty_pedir"] or 0)
        if cant <= 0:
            avisos.append(f"{k[1]}: cantidad a pedir 0, no se incluye"); continue
        if f["costo"] is None or f["costo"] <= 0:
            avisos.append(f"{k[1]}: sin cotización/costo, no se incluye"); continue
        g = por.setdefault((f["empresa"], f["proveedor_id"], f["sucursal"]), {
            "empresa": f["empresa"], "proveedor_id": f["proveedor_id"], "sucursal": f["sucursal"], "proveedor_nombre": f["proveedor_nombre"], "cond_pago": (f["cond_pago"] or "").strip(),
            "activo": bool(f["prov_activo"]), "pedido_minimo": f["pedido_minimo"], "lineas": []})
        costo = round(float(f["costo"]), dec)
        lt = f["lead_time"] if f["lead_time"] is not None else (f["leadtime_proveedor"] if f["leadtime_proveedor"] is not None else 8)
        g["lineas"].append({"producto_id": f["producto_id"], "descripcion": f["descripcion"], "cantidad": cant, "costo": costo, "iva_tasa": f["iva_tasa"],
                            "origen_costo": f["origen_costo"], "fecha_entrega": siesa_oc.fecha_entrega(hoy, lt),
                            "qty_calculada": f.get("qty_calculada"), "costo_ref": f.get("costo_calculado")})
    for g in por.values():
        g["valor"] = sum(l["cantidad"] * l["costo"] for l in g["lineas"])
        g["iva"] = sum(l["cantidad"] * l["costo"] * (l["iva_tasa"] or 0) / 100 for l in g["lineas"])
        g["unidades"] = sum(l["cantidad"] for l in g["lineas"])
        g["motivos"] = _motivos_revision(g, cfg)
    return list(por.values()), avisos


def _validar(g: dict) -> str | None:
    if not g["activo"]:
        return "Proveedor inactivo"
    c = g["cond_pago"]
    if not c or len(c) > 3:
        return "Falta la condición de pago del proveedor (código de Siesa de máximo 3 caracteres, ej. C30)"
    if g["pedido_minimo"] and g["pedido_minimo"] > 0 and g["valor"] < g["pedido_minimo"] and _bloquea_minimo():
        return "Está por debajo del pedido mínimo del proveedor"
    return None


def _bloquea_minimo() -> bool:
    with pg.connect() as c:
        v = c.execute(text("SELECT valor FROM ddmrp.compras_config WHERE clave = 'pedido_minimo_bloquea'")).scalar()
    return bool(v and float(v) >= 1)


def _cfg_revision() -> dict:
    """Reglas de revision desde Configuracion de compras (tabla compras_config), no del .env. Los defectos aplican si la fila no existe o esta vacia."""
    cfg = {"oc_umbral_total": 0.0, "oc_desvio_cant_pct": 30.0, "oc_desvio_cant_min": 15.0, "oc_desvio_costo_pct": 30.0}
    try:
        with pg.connect() as c:
            for k, v in c.execute(text("SELECT clave, valor::float8 FROM ddmrp.compras_config WHERE clave LIKE 'oc\\_%' AND valor IS NOT NULL")).all():
                if k in cfg:
                    cfg[k] = v
    except Exception:    # noqa: BLE001
        pass
    return cfg


def _motivos_revision(g: dict, cfg: dict) -> list[str]:
    """Por que esta OC debe pasar por revision humana (vacio = puede crearse sola)."""
    m = []
    total = g["valor"] + g["iva"]
    if cfg["oc_umbral_total"] <= 0 or total > cfg["oc_umbral_total"]:
        m.append("total sobre el umbral" if cfg["oc_umbral_total"] > 0 else "toda OC se revisa")
    for l in g["lineas"]:
        calc = l.get("qty_calculada")
        if calc is not None:
            if calc > cfg["oc_desvio_cant_min"] and abs(l["cantidad"] - calc) > calc * cfg["oc_desvio_cant_pct"] / 100:
                m.append(f"{l['producto_id']}: cantidad {l['cantidad']:.0f} vs calculada {calc:.0f}")
        ref = l.get("costo_ref")
        if ref and ref > 0 and l["costo"] > ref * (1 + cfg["oc_desvio_costo_pct"] / 100):
            m.append(f"{l['producto_id']}: costo +{(l['costo'] / ref - 1) * 100:.0f}% vs cotización")
    return m


def _oc_dict(r) -> dict:
    return {"id": r["id"], "empresa": r["empresa"], "proveedor_id": r["proveedor_id"], "sucursal": r["sucursal"], "cond_pago": r["cond_pago"],
            "comprador": r["comprador"], "fecha": r.get("fecha") or siesa_oc.hoy()}


def _al_dia(oc_id: int) -> None:
    """Lleva la OC a HOY antes de armar el plano: la fecha del documento la pone armar_plano con la fecha de hoy (Siesa la exige igual a la del sistema) y las fechas
    de entrega de las lineas se corren los mismos dias que pasaron desde que se armo el plano (se conserva el lead time). Una OC aprobada dias despues sigue valida."""
    with pg.begin() as c:
        base = c.execute(text("SELECT COALESCE(fecha_plano, (creado AT TIME ZONE 'UTC' - interval '5 hours')::date) FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).scalar()
        dias = (siesa_oc.hoy() - base).days if base else 0
        if dias > 0:
            c.execute(text("UPDATE ddmrp.orden_compra_linea SET fecha_entrega = fecha_entrega + :d WHERE oc_id = :i"), {"d": dias, "i": oc_id})
        c.execute(text("UPDATE ddmrp.orden_compra SET fecha_plano = :h WHERE id = :i"), {"h": siesa_oc.hoy(), "i": oc_id})


def _lineas_de(c, oc_id: int) -> list[dict]:
    return [dict(x) | {"cantidad": float(x["cantidad"]), "costo": float(x["costo"])} for x in
            c.execute(text("SELECT producto_id, descripcion, cantidad, costo, fecha_entrega FROM ddmrp.orden_compra_linea WHERE oc_id = :i ORDER BY nro"), {"i": oc_id}).mappings()]


def _marcar(oc_id: int, estado: str, mensaje: str, consecutivo: str | None = None, **extra) -> None:
    sets = ["estado = :e", "mensaje = :m"] + (["siesa_consecutivo = :c", "confirmado = now()"] if consecutivo else [])
    with pg.begin() as c:
        c.execute(text(f"UPDATE ddmrp.orden_compra SET {', '.join(sets)} WHERE id = :i"), {"e": estado, "m": mensaje[:1500], "c": consecutivo, "i": oc_id})


def _consecutivo(e: dict | None) -> str | None:
    return f"{e['tipo']}-{int(e['consec'])}" if e else None


def _cerrar_creada(oc_id: int, empresa: str, ref: str, mensaje: str, usuario: str | None) -> dict:
    """Siesa tiene la OC: queda creada y se sueltan las cantidades editadas de esos items (se conservaban 'hasta que se monte la OC')."""
    try:
        cons = _consecutivo(siesa_oc.buscar_en_siesa(empresa, ref))
    except Exception:
        cons = None
    _marcar(oc_id, "creada", mensaje + ("" if cons else " (el consecutivo no se pudo leer aún: se completa al reconsultar)"), cons)
    with pg.begin() as c:
        c.execute(text("DELETE FROM ddmrp.compras_cantidad cm USING ddmrp.orden_compra_linea l WHERE l.oc_id = :i AND cm.empresa = :e AND cm.producto_id = l.producto_id"), {"i": oc_id, "e": empresa})
        c.execute(text("DELETE FROM ddmrp.compras_costo cm USING ddmrp.orden_compra_linea l WHERE l.oc_id = :i AND cm.empresa = :e AND cm.producto_id = l.producto_id"), {"i": oc_id, "e": empresa})
    evento("compras", usuario, f"OC {ref} creada en Siesa" + (f" ({cons})" if cons else ""), {"oc_id": oc_id, "empresa": empresa, "consecutivo": cons})
    return {"estado": "creada", "consecutivo": cons, "mensaje": mensaje}


def _enviar(oc_id: int, usuario: str | None) -> dict:
    _al_dia(oc_id)
    with pg.connect() as c:
        r = c.execute(text("SELECT * FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
        if not r:
            raise HTTPException(404, "No existe esa OC")
        lineas = _lineas_de(c, oc_id)
    oc = _oc_dict(dict(r) | {"fecha": siesa_oc.hoy()})
    ref = r["referencia"]
    try:   # 1) ¿ya existe en Siesa? (duplicados). Si no se puede consultar, NO se envia.
        e = siesa_oc.buscar_en_siesa(r["empresa"], ref)
    except Exception as ex:
        msg = f"No se pudo verificar en Siesa si la OC ya existe, no se envió: {type(ex).__name__}"
        _marcar(oc_id, "error", msg)
        return {"estado": "error", "mensaje": msg}
    if e:
        return _cerrar_creada(oc_id, r["empresa"], ref, "Siesa ya tenía esta OC (misma referencia): no se reenvió", usuario)
    try:   # 2) plano
        plano = siesa_oc.armar_plano(oc, [dict(l) for l in lineas])
    except ValueError as ex:
        _marcar(oc_id, "error", str(ex)); return {"estado": "error", "mensaje": str(ex)}
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.orden_compra SET estado = 'enviando', intentos = intentos + 1, enviado = now(), plano = :p WHERE id = :i"), {"p": plano, "i": oc_id})
    try:   # 3) envio
        res, msg = siesa_oc.importar(plano, r["empresa"])
    except ValueError as ex:        # configuracion incompleta: no salio nada
        _marcar(oc_id, "error", str(ex)); return {"estado": "error", "mensaje": str(ex)}
    if res == "ok":
        return _cerrar_creada(oc_id, r["empresa"], ref, msg, usuario)
    if res == "incierto":
        _marcar(oc_id, "incierta", msg); return {"estado": "incierta", "mensaje": msg}
    _marcar(oc_id, "error", msg)
    evento("compras", usuario, f"Siesa rechazó la OC {ref}", {"oc_id": oc_id, "mensaje": msg[:300]})
    return {"estado": "error", "mensaje": msg}


def _enviar_bpm(oc_id: int, usuario: str | None) -> dict:
    """Modo 'bpm': DDMRP arma el plano y lo ENTREGA al BPM (202). Desde ahi el BPM aprueba, crea en Siesa, genera PDF y correo, y avisa por callback
    (/api/bpm/oc/{id}/estado). El BPM es idempotente por referencia: reenviar la misma OC no crea otra instancia."""
    if not (settings.bpm_url and settings.bpm_secret):
        msg = "Falta configurar el BPM (.env BPM_URL y BPM_SECRET)"
        _marcar(oc_id, "error", msg); return {"estado": "error", "mensaje": msg}
    _al_dia(oc_id)
    with pg.connect() as c:
        r = c.execute(text("SELECT * FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
        lineas = _lineas_de(c, oc_id)
    oc = _oc_dict(dict(r) | {"fecha": siesa_oc.hoy()})
    try:
        plano = siesa_oc.armar_plano(oc, [dict(l) for l in lineas])
    except ValueError as ex:
        _marcar(oc_id, "error", str(ex)); return {"estado": "error", "mensaje": str(ex)}
    revision = bool(r["requiere_revision"]) if r["requiere_revision"] is not None else True      # sin dato (OC vieja) = se revisa
    carga = {"id_externo": oc_id, "empresa": r["empresa"], "referencia": r["referencia"], "plano": plano, "proveedor_id": r["proveedor_id"], "sucursal": r["sucursal"],
             "proveedor_nombre": r["proveedor_nombre"], "cond_pago": r["cond_pago"], "comprador": r["comprador"], "creado_por": r["creado_por"], "valor": float(r["valor"] or 0),
             "iva": float(r["iva"] or 0), "total": float(r["total"] or 0), "items": r["items"], "requiere_revision": revision, "motivo_revision": r["motivo_revision"],
             "lineas": [{"producto_id": l["producto_id"], "descripcion": l["descripcion"], "cantidad": l["cantidad"], "costo": l["costo"], "fecha_entrega": str(l["fecha_entrega"])} for l in lineas]}
    req = urllib.request.Request(settings.bpm_url.rstrip("/") + "/api/internal/oc", data=json.dumps(carga).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-OC-Secret": settings.bpm_secret})
    try:
        with urllib.request.urlopen(req, timeout=settings.bpm_timeout) as resp:
            ans = json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        msg = f"El BPM rechazó la OC (HTTP {e.code}): {e.read().decode('utf-8', 'replace')[:300]}"
        _marcar(oc_id, "error", msg); return {"estado": "error", "mensaje": msg}
    except Exception as e:      # el BPM es idempotente por referencia: reintentar es seguro
        msg = f"No se pudo entregar al BPM ({type(e).__name__}); nada se creó en Siesa. Reintenta."
        _marcar(oc_id, "error", msg); return {"estado": "error", "mensaje": msg}
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.orden_compra SET estado = :e, mensaje = :m, bpm_id = :b, requiere_revision = :r, enviado = now(), estado_bpm_fecha = now(), intentos = intentos + 1, plano = :p WHERE id = :i"),
                  {"e": "en_bpm", "m": "Entregada al BPM" + (" (requiere revisión: " + (r["motivo_revision"] or "") + ")" if revision else " (sin revisión)"), "b": str(ans.get("instance_id") or ""), "r": revision, "p": plano, "i": oc_id})
    evento("compras", usuario, f"OC {r['referencia']} entregada al BPM", {"oc_id": oc_id, "revision": revision})
    return {"estado": "en_bpm", "mensaje": "Entregada al BPM: " + ("pasa por revisión" if revision else "se crea sin revisión")}


def _despachar(oc_id: int, usuario: str | None) -> dict:
    return _enviar_bpm(oc_id, usuario) if settings.oc_destino == "bpm" else _enviar(oc_id, usuario)


@router.get("/config")
def config_oc():
    return {"destino": settings.oc_destino, "revision": _cfg_revision()}


@router.post("/enviar")
def enviar(b: EnviarIn, user=Depends(requiere("gestionar_compras"))):
    """Crea en Siesa una OC por proveedor y empresa con los items elegidos (cantidad y costo salen del servidor). `solo_plano`: devuelve el plano sin enviar."""
    comprador = _comprador(user)
    if not b.items:
        raise HTTPException(400, "No elegiste ningún ítem")
    grupos, avisos = _grupos(user, b.items)
    if not grupos:
        raise HTTPException(400, "Nada para enviar: " + ("; ".join(avisos[:5]) or "los ítems no tienen cantidad o costo"))
    if len(grupos) > MAX_POR_ENVIO:
        raise HTTPException(400, f"Máximo {MAX_POR_ENVIO} órdenes por envío (elegiste {len(grupos)} proveedores): envíalas por tandas")
    usuario = usuario_de(user)
    salida = []
    for i, g in enumerate(grupos):
        res = {"empresa": g["empresa"], "proveedor_id": g["proveedor_id"], "proveedor_nombre": g["proveedor_nombre"], "items": len(g["lineas"]), "valor": g["valor"], "iva": g["iva"], "revision": g["motivos"]}
        falla = _validar(g)
        if falla:
            salida.append(res | {"estado": "no_enviada", "mensaje": falla}); continue
        if b.solo_plano:
            try:
                oc = {"empresa": g["empresa"], "id": 0, "comprador": comprador, "proveedor_id": g["proveedor_id"], "sucursal": g["sucursal"], "cond_pago": g["cond_pago"], "fecha": siesa_oc.hoy()}
                salida.append(res | {"estado": "plano", "mensaje": "Vista previa (nada se envió)", "plano": siesa_oc.armar_plano(oc, g["lineas"])})
            except ValueError as ex:
                salida.append(res | {"estado": "no_enviada", "mensaje": str(ex)})
            continue
        with pg.begin() as c:
            oc_id = c.execute(text("""INSERT INTO ddmrp.orden_compra (empresa, proveedor_id, sucursal, proveedor_nombre, cond_pago, comprador, bodega, referencia, valor, iva, total, items, unidades, creado_por, requiere_revision, motivo_revision)
                                      VALUES (:e, :p, :s, :n, :cp, :co, :b, 'tmp-' || gen_random_uuid()::text, :v, :iva, :t, :it, :u, :us, :rr, :mr) RETURNING id"""),
                              {"e": g["empresa"], "p": g["proveedor_id"], "s": g["sucursal"], "n": g["proveedor_nombre"], "cp": g["cond_pago"], "co": comprador, "b": siesa_oc.bodega_oc(g["empresa"]),
                               "v": g["valor"], "iva": g["iva"], "t": g["valor"] + g["iva"], "it": len(g["lineas"]), "u": g["unidades"], "us": usuario,
                               "rr": bool(g["motivos"]), "mr": "; ".join(g["motivos"])[:1000] or None}).scalar()
            c.execute(text("UPDATE ddmrp.orden_compra SET referencia = :r WHERE id = :i"), {"r": siesa_oc.referencia(oc_id), "i": oc_id})
            for n, l in enumerate(g["lineas"], start=1):
                c.execute(text("INSERT INTO ddmrp.orden_compra_linea (oc_id, nro, producto_id, descripcion, cantidad, costo, iva_tasa, origen_costo, fecha_entrega) VALUES (:i,:n,:p,:d,:q,:c,:t,:o,:f)"),
                          {"i": oc_id, "n": n, "p": l["producto_id"], "d": l["descripcion"], "q": l["cantidad"], "c": l["costo"], "t": l["iva_tasa"], "o": l["origen_costo"], "f": l["fecha_entrega"]})
        if i:
            time.sleep(1.5)          # espaciado entre creaciones: Siesa no se lleva bien con rafagas
        salida.append(res | {"oc_id": oc_id, "referencia": siesa_oc.referencia(oc_id)} | _despachar(oc_id, usuario))
    return {"ordenes": salida, "avisos": avisos}


def _sincronizar_estados() -> None:
    """Trae de Siesa el estado de las OC creadas hace menos de 90 dias (una consulta por empresa). Si Siesa la anulo, aqui queda 'anulada' (y deja de contar:
    las OC anuladas ya no entran al transito). Un fallo de Siesa no tumba el listado."""
    try:
        with pg.connect() as c:
            filas = c.execute(text("SELECT id, empresa, referencia, estado FROM ddmrp.orden_compra WHERE estado IN ('creada', 'anulada') AND confirmado > now() - interval '90 days'")).mappings().all()
        por_emp: dict[str, list] = {}
        for f in filas:
            por_emp.setdefault(f["empresa"], []).append(f)
        for emp, lst in por_emp.items():
            est = siesa_oc.estados_en_siesa(emp, [f["referencia"] for f in lst])
            with pg.begin() as c:
                for f in lst:
                    e = est.get(f["referencia"])
                    if not e:
                        continue
                    nuevo = "anulada" if e["cod"] == 9 else "creada"
                    c.execute(text("UPDATE ddmrp.orden_compra SET estado_siesa = :s, estado_siesa_fecha = now(), estado = :e, siesa_consecutivo = COALESCE(siesa_consecutivo, :c) WHERE id = :i"),
                              {"s": e["estado"], "e": nuevo, "c": e["consecutivo"], "i": f["id"]})
    except Exception:    # noqa: BLE001 -- el historial sigue sirviendo con lo ultimo que se supo
        pass


@router.get("")
def listar(empresa: str | None = None, estado: str | None = None, limit: int = 200):
    _sincronizar_estados()
    w, p = ["TRUE"], {"lim": min(max(limit, 1), 1000)}
    if empresa:
        w.append("empresa = :e"); p["e"] = empresa
    if estado:
        w.append("estado = :s"); p["s"] = estado
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(f"SELECT id, empresa, proveedor_id, sucursal, proveedor_nombre, cond_pago, comprador, estado, referencia, valor, iva, total, items, unidades, "
                                                 f"siesa_consecutivo, mensaje, intentos, creado_por, creado, enviado, confirmado, grupo, tomada_por, estado_bpm_fecha, estado_siesa, estado_siesa_fecha FROM ddmrp.orden_compra WHERE {' AND '.join(w)} "
                                                 f"ORDER BY id DESC LIMIT :lim"), p).mappings()]
    return {"datos": filas}


@router.get("/{oc_id}")
def detalle(oc_id: int):
    with pg.connect() as c:
        r = c.execute(text("SELECT * FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
        if not r:
            raise HTTPException(404, "No existe esa OC")
        return dict(r) | {"lineas": [dict(x) for x in c.execute(text("SELECT * FROM ddmrp.orden_compra_linea WHERE oc_id = :i ORDER BY nro"), {"i": oc_id}).mappings()]}


@router.post("/{oc_id}/reconsultar")
def reconsultar(oc_id: int, user=Depends(requiere("gestionar_compras"))):
    """Pregunta a Siesa por la referencia: si la OC esta, queda creada (con su consecutivo); si no, queda como estaba."""
    with pg.connect() as c:
        r = c.execute(text("SELECT empresa, referencia, estado FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
    if not r:
        raise HTTPException(404, "No existe esa OC")
    try:
        e = siesa_oc.buscar_en_siesa(r["empresa"], r["referencia"])
    except Exception as ex:
        raise HTTPException(502, f"No se pudo consultar a Siesa: {type(ex).__name__}")
    if not e:
        return {"estado": r["estado"], "mensaje": "Siesa no tiene ninguna OC (no anulada) con esa referencia"}
    return _cerrar_creada(oc_id, r["empresa"], r["referencia"], "Confirmada en Siesa por la referencia", usuario_de(user))


@router.post("/{oc_id}/reenviar")
def reenviar(oc_id: int, user=Depends(requiere("gestionar_compras"))):
    """Reintenta una OC en error o incierta. Siempre vuelve a preguntar a Siesa antes (si ya esta, no se reenvia). Una 'incierta' espera unos minutos desde el envio."""
    _comprador(user)
    with pg.connect() as c:
        r = c.execute(text("SELECT estado, enviado FROM ddmrp.orden_compra WHERE id = :i"), {"i": oc_id}).mappings().first()
    if not r:
        raise HTTPException(404, "No existe esa OC")
    if r["estado"] not in ("error", "incierta"):
        raise HTTPException(409, f"La OC está '{r['estado']}': solo se reenvían las que están en error o incierta")
    if r["estado"] == "incierta" and r["enviado"] and datetime.now(timezone.utc) - r["enviado"] < ESPERA_INCIERTA:
        raise HTTPException(409, "Espera unos minutos y reconsulta: Siesa puede estar terminando de procesar el envío anterior")
    return _despachar(oc_id, usuario_de(user))
