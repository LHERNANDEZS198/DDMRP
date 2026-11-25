"""Solicitudes de cambio: un grupo con el permiso «solicitar_cambios» pide agregar o quitar NxP (condenados) y/o compras (items que se compran) a nivel de
laboratorio o item, y NxP tambien por tienda-item; otro grupo con «aprobar_cambios» las aprueba o rechaza. Al aprobar, el cambio se aplica solo y queda en config_audit."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import permisos, requiere, EMPRESAS

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])

TIPOS = ("nxp", "compras")
ACCIONES = ("agregar", "quitar")
NIVELES = ("laboratorio", "item", "tienda_item")


class Item(BaseModel):
    tipo: str                      # nxp | compras
    accion: str                    # agregar | quitar
    nivel: str                     # laboratorio | item | tienda_item (solo NxP)
    laboratorio: str | None = None
    producto_id: str | None = None
    bodega_id: str | None = None
    empresa: str | None = None


class Nueva(BaseModel):
    items: list[Item]
    motivo: str = ""


class Resolver(BaseModel):
    ids: list[int]
    accion: str                    # aprobar | rechazar
    nota: str = ""


def _empresas(e: str | None) -> list[str]:
    if e and e not in ("*", ""):
        return [x for x in e.split(",") if x]
    return list(EMPRESAS)


@router.post("")
def crear(b: Nueva, user=Depends(requiere("solicitar_cambios"))):
    if not b.items:
        raise HTTPException(400, "No hay nada que solicitar")
    if len(b.items) > 2000:
        raise HTTPException(400, "Demasiadas filas en una solicitud (maximo 2000)")
    filas: list[dict] = []
    for it in b.items:
        if it.tipo not in TIPOS or it.accion not in ACCIONES or it.nivel not in NIVELES:
            raise HTTPException(400, "Solicitud invalida (tipo, accion o nivel)")
        if it.tipo == "compras" and it.nivel == "tienda_item":
            raise HTTPException(400, "Compras solo se pide por laboratorio o por item (no por tienda)")
        if it.nivel == "laboratorio" and not it.laboratorio:
            raise HTTPException(400, "Falta el laboratorio")
        if it.nivel in ("item", "tienda_item") and not it.producto_id:
            raise HTTPException(400, "Falta el item")
        if it.nivel == "tienda_item" and not it.bodega_id:
            raise HTTPException(400, "Falta la tienda")
        for e in _empresas(it.empresa):
            filas.append({"e": e, "t": it.tipo, "a": it.accion, "n": it.nivel,
                          "l": it.laboratorio if it.nivel == "laboratorio" else None,
                          "p": it.producto_id if it.nivel != "laboratorio" else None,
                          "b": it.bodega_id if it.nivel == "tienda_item" else None})
    nuevas = repetidas = 0
    ya_nxp: list[str] = []
    with pg.begin() as c:
        for f in filas:
            if f["t"] == "nxp" and f["a"] == "agregar":   # lo que ya esta en NxP no se vuelve a pedir: solo se puede pedir quitarlo
                if f["n"] == "laboratorio":
                    esta = c.execute(text("SELECT 1 FROM ddmrp.laboratorio_sin_envio WHERE empresa = :e AND laboratorio = :l"), f).first()
                elif f["n"] == "item":
                    esta = c.execute(text("SELECT 1 FROM ddmrp.item_condenado WHERE empresa = :e AND producto_id = :p AND bodega_id = '*'"), f).first()
                else:   # tienda-item: ya condenado en esa tienda o en todas
                    esta = c.execute(text("SELECT 1 FROM ddmrp.item_condenado WHERE empresa = :e AND producto_id = :p AND bodega_id IN (:b, '*')"), f).first()
                if esta:
                    ya_nxp.append(f"{f['e']}/{f['l'] or ''}{f['b'] + ' ' if f['b'] else ''}{f['p'] or ''}".strip("/ "))
                    continue
            r = c.execute(text("""INSERT INTO ddmrp.solicitud_cambio (empresa, tipo, accion, nivel, laboratorio, producto_id, bodega_id, motivo, solicitante)
                                  SELECT :e, :t, :a, :n, :l, :p, :b, :m, :u
                                  WHERE NOT EXISTS (SELECT 1 FROM ddmrp.solicitud_cambio s WHERE s.estado = 'pendiente' AND s.empresa = :e AND s.tipo = :t AND s.accion = :a
                                                    AND s.nivel = :n AND COALESCE(s.laboratorio, '') = COALESCE(:l, '') AND COALESCE(s.producto_id, '') = COALESCE(:p, '')
                                                    AND COALESCE(s.bodega_id, '') = COALESCE(:b, ''))"""),
                          {**f, "m": b.motivo.strip(), "u": user["id"]})
            nuevas += r.rowcount; repetidas += 1 - r.rowcount
    if ya_nxp and not nuevas and not repetidas:
        raise HTTPException(400, f"Ya están en NxP ({len(ya_nxp)}): no se pueden agregar de nuevo, solicita quitarlos. Ej.: " + ", ".join(ya_nxp[:5]))
    return {"ok": True, "creadas": nuevas, "ya_pendientes": repetidas, "ya_en_nxp": len(ya_nxp), "ejemplos_ya_en_nxp": ya_nxp[:5]}


def _puede(user) -> tuple[bool, list[str]]:
    """(puede solicitar, tipos que puede aprobar): NxP con «aprobar_cambios» y compras con «aprobar_compras» (grupos distintos)."""
    p = permisos(user["id"])
    return "solicitar_cambios" in p, [t for t, k in (("nxp", "aprobar_cambios"), ("compras", "aprobar_compras")) if k in p]


@router.get("")
def listar(estado: str = "pendiente", user=Depends(requiere("solicitar_cambios", "aprobar_cambios", "aprobar_compras"))):
    solicita, aprueba = _puede(user)
    w, p = ["TRUE"], {}
    if estado in ("pendiente", "aprobada", "rechazada", "cancelada"):
        w.append("s.estado = :est"); p["est"] = estado
    # ve lo suyo y, si aprueba, todo lo de los tipos que aprueba (compras no le llega al grupo de NxP y viceversa)
    w.append("(s.solicitante = :u OR s.tipo = ANY(CAST(:tp AS text[])))"); p["u"] = user["id"]; p["tp"] = aprueba
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(f"""
            SELECT s.id, s.empresa, s.tipo, s.accion, s.nivel, s.laboratorio, s.producto_id, s.bodega_id, s.motivo, s.estado, s.solicitante, s.fecha_solicitud,
                   s.resuelto_por, s.fecha_resuelto, s.nota_resolucion, s.aplicado, s.visto_solicitante,
                   COALESCE(mi.descripcion, lb.nombre) AS descripcion, mb.descripcion AS bodega_nombre,
                   COALESCE(NULLIF(us.nombre, ''), s.solicitante) AS solicitante_nombre, COALESCE(NULLIF(ur.nombre, ''), s.resuelto_por) AS resuelto_por_nombre
            FROM ddmrp.solicitud_cambio s
            LEFT JOIN ddmrp.usuario us ON us.usuario_id = s.solicitante
            LEFT JOIN ddmrp.usuario ur ON ur.usuario_id = s.resuelto_por
            LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = s.empresa AND mi.producto_id = s.producto_id
            LEFT JOIN ddmrp.laboratorio lb ON lb.codigo = s.laboratorio
            LEFT JOIN ddmrp.maestro_bodega mb ON mb.empresa = s.empresa AND mb.bodega_id = s.bodega_id
            WHERE {' AND '.join(w)} ORDER BY s.id DESC LIMIT 2000"""), p).mappings()]
    for f in filas:
        for k in ("fecha_solicitud", "fecha_resuelto"):
            if f.get(k) is not None:
                f[k] = f[k].isoformat(sep=" ", timespec="minutes")
    return {"filas": filas, "puede_aprobar": aprueba, "puede_solicitar": solicita}


@router.get("/contadores")
def contadores(user=Depends(requiere("solicitar_cambios", "aprobar_cambios", "aprobar_compras"))):
    solicita, aprueba = _puede(user)
    with pg.connect() as c:
        pend = c.execute(text("SELECT count(*) FROM ddmrp.solicitud_cambio WHERE estado = 'pendiente' AND tipo = ANY(CAST(:tp AS text[]))"), {"tp": aprueba}).scalar() if aprueba else 0
        mias = c.execute(text("SELECT count(*) FROM ddmrp.solicitud_cambio WHERE estado = 'pendiente' AND solicitante = :u"), {"u": user["id"]}).scalar() if solicita else 0
        nuevas = c.execute(text("SELECT count(*) FROM ddmrp.solicitud_cambio WHERE solicitante = :u AND estado IN ('aprobada', 'rechazada') AND NOT visto_solicitante"),
                           {"u": user["id"]}).scalar() if solicita else 0
    return {"pendientes": pend, "mias_pendientes": mias, "resueltas_sin_ver": nuevas, "total": pend + nuevas}


@router.post("/vistas")
def marcar_vistas(user=Depends(requiere("solicitar_cambios", "aprobar_cambios", "aprobar_compras"))):
    with pg.begin() as c:
        c.execute(text("UPDATE ddmrp.solicitud_cambio SET visto_solicitante = TRUE WHERE solicitante = :u AND estado IN ('aprobada', 'rechazada')"), {"u": user["id"]})
    return {"ok": True}


@router.post("/cancelar")
def cancelar(b: Resolver, user=Depends(requiere("solicitar_cambios", "aprobar_cambios", "aprobar_compras"))):
    _, aprueba = _puede(user)
    with pg.begin() as c:
        r = c.execute(text("""UPDATE ddmrp.solicitud_cambio SET estado = 'cancelada', resuelto_por = :u, fecha_resuelto = now(), visto_solicitante = TRUE
                              WHERE id = ANY(:ids) AND estado = 'pendiente' AND (solicitante = :u OR tipo = ANY(CAST(:tp AS text[])))"""), {"ids": b.ids, "u": user["id"], "tp": aprueba})
    return {"ok": True, "canceladas": r.rowcount}


def _audit(c, s: dict, user, detalle: str):
    llave = "/".join(x for x in (s["empresa"], s["laboratorio"], s["producto_id"], s["bodega_id"]) if x)
    c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) VALUES (:t, :l, :c, NULL, :n, :u)"),
              {"t": "solicitud_" + s["tipo"], "l": llave, "c": f"{s['accion']} ({s['nivel']})", "n": f"#{s['id']} solicitada por {s['solicitante']}: {detalle}", "u": user["nombre"]})


def _aplicar(c, s: dict, user) -> str:
    e, ag = s["empresa"], s["accion"] == "agregar"
    motivo = f"Solicitud #{s['id']} de {s['solicitante']}" + (f": {s['motivo']}" if s["motivo"] else "")
    p = {"e": e, "l": s["laboratorio"], "p": s["producto_id"], "b": s["bodega_id"], "m": motivo[:300]}
    if s["tipo"] == "nxp":
        if s["nivel"] == "laboratorio":
            if ag:
                n = c.execute(text("INSERT INTO ddmrp.laboratorio_sin_envio (empresa, laboratorio, motivo) VALUES (:e, :l, :m) ON CONFLICT (empresa, laboratorio) DO NOTHING"), p).rowcount
            else:
                n = c.execute(text("DELETE FROM ddmrp.laboratorio_sin_envio WHERE empresa = :e AND laboratorio = :l"), p).rowcount
            det = "laboratorio " + ("sin envio" if ag else "vuelve a enviarse")
        elif s["nivel"] == "item":      # item en todas las tiendas: una fila con bodega '*'; al quitar se limpian tambien las filas por tienda
            if ag:
                n = c.execute(text("INSERT INTO ddmrp.item_condenado (empresa, producto_id, bodega_id, motivo) VALUES (:e, :p, '*', :m) ON CONFLICT (empresa, producto_id, bodega_id) DO NOTHING"), p).rowcount
            else:
                n = c.execute(text("DELETE FROM ddmrp.item_condenado WHERE empresa = :e AND producto_id = :p"), p).rowcount
            det = "item " + ("condenado en todas las tiendas" if ag else "sale de NxP en todas las tiendas")
        else:
            if ag:
                n = c.execute(text("INSERT INTO ddmrp.item_condenado (empresa, producto_id, bodega_id, motivo) VALUES (:e, :p, :b, :m) ON CONFLICT (empresa, producto_id, bodega_id) DO NOTHING"), p).rowcount
            else:
                n = c.execute(text("DELETE FROM ddmrp.item_condenado WHERE empresa = :e AND producto_id = :p AND bodega_id = :b"), p).rowcount
            det = "tienda-item " + ("condenado" if ag else "sale de NxP")
    else:                                # compras: activo 1 = se compra · 0 = no se compra
        v = 1 if ag else 0
        if s["nivel"] == "laboratorio":
            n = c.execute(text("""UPDATE ddmrp.item_compra ic SET activo = :v FROM ddmrp.maestro_item mi
                                  WHERE mi.empresa = ic.empresa AND mi.producto_id = ic.producto_id AND ic.empresa = :e AND mi.categoria = :l AND COALESCE(ic.activo, 1) <> :v"""), {**p, "v": v}).rowcount
        else:
            n = c.execute(text("UPDATE ddmrp.item_compra SET activo = :v WHERE empresa = :e AND producto_id = :p AND COALESCE(activo, 1) <> :v"), {**p, "v": v}).rowcount
        det = ("se vuelve a comprar" if ag else "deja de comprarse") + f" ({n} items)"
    msg = det + ("" if n else " · sin cambios (ya estaba asi)")
    _audit(c, s, user, msg)
    return msg


@router.post("/resolver")
def resolver(b: Resolver, user=Depends(requiere("aprobar_cambios", "aprobar_compras"))):
    if b.accion not in ("aprobar", "rechazar"):
        raise HTTPException(400, "Accion invalida")
    if not b.ids:
        raise HTTPException(400, "Elige al menos una solicitud")
    hechas = 0
    _, tipos = _puede(user)
    with pg.begin() as c:
        pend = [dict(r) for r in c.execute(text("SELECT * FROM ddmrp.solicitud_cambio WHERE id = ANY(:ids) AND estado = 'pendiente' AND tipo = ANY(CAST(:tp AS text[])) ORDER BY id FOR UPDATE"),
                                            {"ids": b.ids, "tp": tipos}).mappings()]
        for s in pend:
            if b.accion == "aprobar":
                aplicado = _aplicar(c, s, user); est = "aprobada"
            else:
                aplicado, est = None, "rechazada"
            c.execute(text("""UPDATE ddmrp.solicitud_cambio SET estado = :est, resuelto_por = :u, fecha_resuelto = now(), nota_resolucion = :n, aplicado = :a, visto_solicitante = FALSE
                              WHERE id = :id"""), {"est": est, "u": user["id"], "n": b.nota.strip(), "a": aplicado, "id": s["id"]})
            hechas += 1
    return {"ok": True, "resueltas": hechas, "ya_resueltas": len(b.ids) - hechas}
