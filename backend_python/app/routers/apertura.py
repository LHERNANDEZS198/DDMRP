"""Apertura de tienda (espejo): arma una tienda nueva a partir de otra que ya vende y deja registrado cuanto dura el espejo.

El pronostico de la tienda nueva se carga en el maestro Pronostico (venta mensual de la espejo x factor, o el pronostico que ya tenga la espejo); ademas se pueden copiar
cotas, NxP, DIA de abastecimiento y el alta en la Bitacora. El motor usa ese pronostico "tal cual" durante `meses_espejo` meses de venta contados desde la primera venta de la tienda (el mes en curso cuenta)
(esta duracion se guarda por tienda en ddmrp.apertura_tienda y el motor Rust la lee; sin apertura registrada rige la regla global pron_meses_minimos).
Todo se escribe solo en tablas de DDMRP: nada de esto toca Siesa."""
from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from ..db import pg
from .. import bitacora
from ..bitacora import usuario_de
from ..security import usuario_actual, requiere
from ..apertura_calc import fin_espejo, restan_espejo, mes_de, sumar_meses, meses_entre, ventana_base, pronostico_propuesto, meses_con_venta
from .maestros import _puede_global

router = APIRouter(prefix="/apertura", tags=["apertura"])
VER = ("ver_maestros", "cargar_maestros")
MAX_FILAS = 50_000


# ---------------------------------------------------------------- modelos
class Plan(BaseModel):
    empresa: str
    espejo: str
    destino: str
    nombre: str | None = None
    factor: float = Field(1.0, gt=0, le=10)
    base: str = "venta"                  # venta = promedio mensual de la espejo; pronostico = el que la espejo ya tiene en el maestro
    base_meses: int = Field(6, ge=1, le=12)
    copiar_cotas: bool = True
    copiar_nxp: bool = True
    copiar_dia: bool = True
    copiar_bitacora: bool = True


class FilaIn(BaseModel):
    producto_id: str
    pronostico: float = Field(gt=0, le=10_000_000)


class Aplicar(Plan):
    meses_espejo: int = Field(ge=1, le=12)
    fecha_apertura: date | None = None
    modo: str = "reemplazar"             # reemplazar = deja la tienda nueva como la espejo; completar = solo agrega lo que le falte
    filas: list[FilaIn]


class Cambio(BaseModel):
    meses_espejo: int | None = Field(None, ge=1, le=12)
    activa: bool | None = None


# ---------------------------------------------------------------- utilidades con base de datos
def _exigir_global(user):
    if not _puede_global(user):
        raise HTTPException(403, "Requiere permiso de edicion sobre todas las bodegas")


def _cfg(c, empresa=None) -> dict:
    v = dict(c.execute(text("SELECT p.clave, COALESCE(e.valor, p.valor)::float8 FROM ddmrp.parametro p LEFT JOIN ddmrp.parametro_empresa e ON e.clave = p.clave AND e.empresa = :e "
                            "WHERE p.clave IN ('apertura_meses_defecto', 'apertura_factor_defecto', 'apertura_base_meses', 'meses_historia')"), {"e": empresa or ""}).all())
    # los meses de venta se cuentan dentro de la ventana de historia del motor y el historial debe alcanzar a tomar el mando el mes siguiente: maximo meses_historia - 1
    mx = max(1, min(11, int(v.get("meses_historia", 7)) - 1))
    return {"meses_defecto": max(1, min(mx, int(v.get("apertura_meses_defecto", 4)))), "factor_defecto": float(v.get("apertura_factor_defecto", 1.0)),
            "base_meses": max(1, min(12, int(v.get("apertura_base_meses", 6)))), "max_meses": mx}


def _validar(c, p: Plan) -> dict:
    """Revisa empresa / espejo / destino. Devuelve la fila de bitacora de la espejo y la del destino (None si todavia no esta)."""
    emp, esp, dst = p.empresa.strip(), p.espejo.strip(), p.destino.strip()
    if p.base not in ("venta", "pronostico"):
        raise HTTPException(400, "La base debe ser 'venta' o 'pronostico'")
    if not (emp and esp and dst):
        raise HTTPException(400, "Falta la empresa, la tienda espejo o la tienda nueva")
    if esp == dst:
        raise HTTPException(400, "La tienda nueva no puede ser la misma tienda espejo")
    e = c.execute(text("SELECT empresa, bodega_id, descripcion, leadtime::float8 AS leadtime, frecuencia::float8 AS frecuencia, cedi, id_co "
                       "FROM ddmrp.abast_bitacora WHERE empresa = :e AND bodega_id = :b"), {"e": emp, "b": esp}).mappings().first()
    if not e:
        raise HTTPException(400, "La tienda espejo no esta en la Bitacora de esa empresa")
    if c.execute(text("SELECT 1 FROM ddmrp.maestro_cedi WHERE bodega_id IN (:a, :b) LIMIT 1"), {"a": esp, "b": dst}).first():
        raise HTTPException(400, "Ni la espejo ni la tienda nueva pueden ser un CEDI")
    d = c.execute(text("SELECT empresa, bodega_id, descripcion FROM ddmrp.abast_bitacora WHERE bodega_id = :b"), {"b": dst}).mappings().first()
    if d and d["empresa"] != emp:
        raise HTTPException(400, f"La bodega {dst} ya esta en la Bitacora de otra empresa ({d['empresa']})")
    return {"espejo": dict(e), "destino": dict(d) if d else None}


def _armar(c, p: Plan) -> tuple[list[dict], dict]:
    """Filas propuestas (una por referencia) y el resumen. No escribe nada."""
    hoy = date.today(); avisos: list[str] = []; emp, esp = p.empresa.strip(), p.espejo.strip()
    resumen: dict = {"base": p.base, "factor": p.factor}
    if p.base == "venta":
        inicio = c.execute(text("SELECT min(mes) FROM ddmrp.ventas_mensual WHERE empresa = :e AND bodega_id = :b AND cantidad > 0"), {"e": emp, "b": esp}).scalar()
        desde, hasta, n = ventana_base(inicio, hoy, p.base_meses)
        if n <= 0:
            raise HTTPException(400, "La tienda espejo todavia no tiene meses cerrados con venta para promediar. Prueba con la base 'pronostico' o con otra espejo")
        if n < p.base_meses:
            avisos.append(f"La espejo solo tiene {n} mes(es) cerrado(s) con venta: se promedia sobre esos {n}, no sobre {p.base_meses}.")
        datos = c.execute(text("""SELECT v.producto_id, sum(v.cantidad)::float8 / :n AS base, mi.descripcion, mi.categoria AS lab, (mi.producto_id IS NOT NULL) AS en_maestro
                                  FROM ddmrp.ventas_mensual v LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = v.empresa AND mi.producto_id = v.producto_id
                                  WHERE v.empresa = :e AND v.bodega_id = :b AND v.mes BETWEEN :d AND :h
                                  GROUP BY v.producto_id, mi.producto_id, mi.descripcion, mi.categoria HAVING sum(v.cantidad) > 0"""),
                          {"n": n, "e": emp, "b": esp, "d": desde, "h": hasta}).mappings().all()
        resumen.update({"meses_base": n, "desde": desde, "hasta": hasta})
    else:
        datos = c.execute(text("""SELECT pr.producto_id, pr.pronostico::float8 AS base, mi.descripcion, mi.categoria AS lab, (mi.producto_id IS NOT NULL) AS en_maestro
                                  FROM ddmrp.pronostico pr LEFT JOIN ddmrp.maestro_item mi ON mi.empresa = pr.empresa AND mi.producto_id = pr.producto_id
                                  WHERE pr.empresa = :e AND pr.bodega_id = :b AND pr.pronostico > 0"""), {"e": emp, "b": esp}).mappings().all()
        if not datos:
            raise HTTPException(400, "La tienda espejo no tiene pronostico cargado en el maestro")
    cotas = {r["producto_id"]: (r["cota_maxima"], r["cota_minima"]) for r in c.execute(text(
        "SELECT producto_id, cota_maxima::float8 AS cota_maxima, cota_minima::float8 AS cota_minima FROM ddmrp.abast_control_referencias WHERE empresa = :e AND bodega_id = :b"),
        {"e": emp, "b": esp}).mappings()}
    nxp = {r[0] for r in c.execute(text("SELECT producto_id FROM ddmrp.item_condenado WHERE empresa = :e AND bodega_id = :b"), {"e": emp, "b": esp})}
    filas: list[dict] = []; sin_maestro = 0; excl_nxp = 0
    for r in datos:
        if not r["en_maestro"]:
            sin_maestro += 1; continue
        if p.copiar_nxp and r["producto_id"] in nxp:
            excl_nxp += 1; continue
        prop = pronostico_propuesto(r["base"], p.factor)
        if prop <= 0:
            continue
        cm, cn = cotas.get(r["producto_id"], (None, None))
        filas.append({"producto_id": r["producto_id"], "descripcion": r["descripcion"], "lab": r["lab"], "base": round(r["base"], 2), "pronostico": prop, "cota_max": cm, "cota_min": cn})
    filas.sort(key=lambda f: (-f["pronostico"], f["producto_id"]))
    if sin_maestro:
        avisos.append(f"{sin_maestro} referencia(s) de la espejo no estan en el maestro de items y se omiten.")
    resumen.update({"items": len(filas), "unidades_mes": sum(f["pronostico"] for f in filas), "nxp": len(nxp) if p.copiar_nxp else 0, "nxp_excluidos": excl_nxp,
                    "con_cotas": sum(1 for f in filas if f["cota_max"] is not None or f["cota_min"] is not None), "avisos": avisos})
    return filas, resumen


# ---------------------------------------------------------------- endpoints
@router.get("/opciones")
def opciones(user=Depends(requiere(*VER))):
    """Tiendas para elegir (las de la Bitacora y, para la tienda nueva, las bodegas de Siesa que aun no estan) y los valores por defecto (se cambian en Reglas)."""
    with pg.connect() as c:
        cfg = _cfg(c)
        bit = [dict(r) for r in c.execute(text("SELECT empresa, bodega_id, descripcion AS nombre, leadtime::float8 AS leadtime, frecuencia::float8 AS frecuencia, cedi "
                                               "FROM ddmrp.abast_bitacora b WHERE NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.bodega_id = b.bodega_id) "
                                               "ORDER BY empresa, bodega_id")).mappings()]
        extra = [dict(r) for r in c.execute(text("SELECT mb.empresa, mb.bodega_id, mb.descripcion AS nombre FROM ddmrp.maestro_bodega mb "
                                                 "WHERE NOT EXISTS (SELECT 1 FROM ddmrp.abast_bitacora b WHERE b.bodega_id = mb.bodega_id) "
                                                 "AND NOT EXISTS (SELECT 1 FROM ddmrp.maestro_cedi mc WHERE mc.bodega_id = mb.bodega_id) ORDER BY mb.empresa, mb.bodega_id")).mappings()]
    return {"config": cfg, "bitacora": bit, "sin_bitacora": extra}


@router.post("/vista-previa")
def vista_previa(p: Plan, user=Depends(requiere("cargar_maestros"))):
    _exigir_global(user)
    with pg.connect() as c:
        info = _validar(c, p); cfg = _cfg(c, p.empresa.strip())
        filas, resumen = _armar(c, p)
        emp, dst = p.empresa.strip(), p.destino.strip()
        resumen["destino_en_bitacora"] = info["destino"] is not None
        resumen["destino_pronosticos"] = c.execute(text("SELECT count(*) FROM ddmrp.pronostico WHERE empresa = :e AND bodega_id = :b"), {"e": emp, "b": dst}).scalar()
        ini = c.execute(text("SELECT min(mes) FROM ddmrp.ventas_mensual WHERE empresa = :e AND bodega_id = :b AND cantidad > 0"), {"e": emp, "b": dst}).scalar()
        resumen["destino_inicio_ventas"] = ini; resumen["destino_meses_venta"] = meses_con_venta(ini, date.today())
        resumen["apertura_previa"] = bool(c.execute(text("SELECT 1 FROM ddmrp.apertura_tienda WHERE empresa = :e AND bodega_id = :b AND activa"), {"e": emp, "b": dst}).first())
        e = info["espejo"]
        resumen["espejo"] = {"nombre": e["descripcion"], "leadtime": e["leadtime"], "frecuencia": e["frecuencia"], "cedi": e["cedi"]}
        if e["leadtime"] is None and e["frecuencia"] is None:
            resumen["avisos"].append("La espejo no tiene lead time ni frecuencia en la Bitacora: la tienda nueva tampoco los tendria y el motor no la calcularia hasta que se los pongas.")
    return {"config": cfg, "resumen": resumen, "filas": filas}


@router.post("/aplicar")
def aplicar(a: Aplicar, user=Depends(requiere("cargar_maestros"))):
    _exigir_global(user)
    if a.modo not in ("reemplazar", "completar"):
        raise HTTPException(400, "El modo debe ser 'reemplazar' o 'completar'")
    if not a.filas:
        raise HTTPException(400, "No hay items para cargar")
    if len(a.filas) > MAX_FILAS:
        raise HTTPException(400, f"Demasiados items ({len(a.filas)}); el maximo es {MAX_FILAS}")
    emp, esp, dst, usu = a.empresa.strip(), a.espejo.strip(), a.destino.strip(), usuario_de(user)
    with bitacora.registrar("carga", "manual", usu, f"Apertura de tienda {dst} (espejo {esp})") as reg:
        with pg.begin() as c:
            cfg = _cfg(c, a.empresa.strip())
            if a.meses_espejo > cfg["max_meses"]:
                raise HTTPException(400, f"El espejo no puede durar mas de {cfg['max_meses']} meses: son los meses de historia que mira el motor (regla 'Meses de historia de ventas')")
            info = _validar(c, a)
            nuevo = info["destino"] is None
            nombre = (a.nombre or "").strip()
            if nuevo and not nombre:
                raise HTTPException(400, "Escribe el nombre de la tienda nueva")
            por_id: dict[str, float] = {}
            for f in a.filas:
                pid = f.producto_id.strip()
                if pid and f.pronostico > 0:
                    por_id[pid] = f.pronostico
            if not por_id:
                raise HTTPException(400, "No hay items con pronostico mayor que cero")
            ids = sorted(por_id)
            ok = {r[0] for r in c.execute(text("SELECT producto_id FROM ddmrp.maestro_item WHERE empresa = :em AND producto_id = ANY(:p)"), {"p": ids, "em": emp})}
            falta = [i for i in ids if i not in ok]
            if falta:
                raise HTTPException(400, f"{len(falta)} item(s) no estan en el maestro de items, p.ej. {falta[:5]}")
            e = info["espejo"]; k = {"e": emp, "d": dst, "esp": esp}
            res: dict = {"destino": dst, "espejo": esp, "items": len(ids), "unidades_mes": round(sum(por_id.values()), 2), "meses_espejo": a.meses_espejo, "modo": a.modo}
            # 1) alta / completado en la Bitacora (una tienda sin lead time ni frecuencia no se calcula)
            if nuevo:
                c.execute(text("INSERT INTO ddmrp.abast_bitacora (empresa, bodega_id, descripcion, leadtime, frecuencia, cedi, id_co) VALUES (:e, :d, :n, :lt, :fr, :cedi, :co)"),
                          {**k, "n": nombre, "lt": e["leadtime"], "fr": e["frecuencia"], "cedi": e["cedi"], "co": e["id_co"]})
                res["bitacora"] = "alta"
            elif a.copiar_bitacora:
                c.execute(text("UPDATE ddmrp.abast_bitacora SET leadtime = COALESCE(leadtime, :lt), frecuencia = COALESCE(frecuencia, :fr), cedi = COALESCE(cedi, :cedi), "
                               "id_co = COALESCE(id_co, :co) WHERE empresa = :e AND bodega_id = :d"), {**k, "lt": e["leadtime"], "fr": e["frecuencia"], "cedi": e["cedi"], "co": e["id_co"]})
                res["bitacora"] = "completada"
            # 2) pronostico
            if a.modo == "reemplazar":
                c.execute(text("DELETE FROM ddmrp.pronostico WHERE empresa = :e AND bodega_id = :d"), k)
            c.execute(text("INSERT INTO ddmrp.pronostico (empresa, bodega_id, producto_id, pronostico) "
                           "SELECT :e, :d, x.p, x.v FROM unnest(CAST(:ps AS text[]), CAST(:vs AS numeric[])) AS x(p, v) ON CONFLICT DO NOTHING"),
                      {**k, "ps": ids, "vs": [por_id[i] for i in ids]})
            # 3) cotas de las referencias elegidas
            if a.copiar_cotas:
                if a.modo == "reemplazar":
                    c.execute(text("DELETE FROM ddmrp.abast_control_referencias WHERE empresa = :e AND bodega_id = :d"), k)
                res["cotas"] = c.execute(text("INSERT INTO ddmrp.abast_control_referencias (empresa, bodega_id, producto_id, cota_maxima, cota_minima) "
                                              "SELECT empresa, :d, producto_id, cota_maxima, cota_minima FROM ddmrp.abast_control_referencias "
                                              "WHERE empresa = :e AND bodega_id = :esp AND producto_id = ANY(:ids) ON CONFLICT DO NOTHING"), {**k, "ids": ids}).rowcount
            # 4) NxP (items condenados solo en la espejo)
            if a.copiar_nxp:
                if a.modo == "reemplazar":
                    c.execute(text("DELETE FROM ddmrp.item_condenado WHERE empresa = :e AND bodega_id = :d"), k)
                res["nxp"] = c.execute(text("INSERT INTO ddmrp.item_condenado (empresa, producto_id, bodega_id, motivo) SELECT empresa, producto_id, :d, :m FROM ddmrp.item_condenado "
                                            "WHERE empresa = :e AND bodega_id = :esp ON CONFLICT DO NOTHING"), {**k, "m": f"Apertura de tienda (espejo {esp})"}).rowcount
            # 5) DIA(s) de abastecimiento
            if a.copiar_dia:
                if a.modo == "reemplazar":
                    c.execute(text("DELETE FROM ddmrp.bodega_dia WHERE empresa = :e AND bodega_id = :d"), k)
                res["dias"] = c.execute(text("INSERT INTO ddmrp.bodega_dia (empresa, bodega_id, dia) SELECT empresa, :d, dia FROM ddmrp.bodega_dia WHERE empresa = :e AND bodega_id = :esp "
                                             "ON CONFLICT DO NOTHING"), k).rowcount
            # 6) el registro de la apertura (aqui vive la duracion del espejo que lee el motor)
            c.execute(text("""INSERT INTO ddmrp.apertura_tienda (empresa, bodega_id, espejo_bodega, factor, base, base_meses, meses_espejo, fecha_apertura, activa, items, unidades_mes, creado_por)
                              VALUES (:e, :d, :esp, :f, :b, :bm, :m, :fa, true, :n, :u, :us)
                              ON CONFLICT (empresa, bodega_id) DO UPDATE SET espejo_bodega = EXCLUDED.espejo_bodega, factor = EXCLUDED.factor, base = EXCLUDED.base,
                                base_meses = EXCLUDED.base_meses, meses_espejo = EXCLUDED.meses_espejo, fecha_apertura = EXCLUDED.fecha_apertura, activa = true,
                                items = EXCLUDED.items, unidades_mes = EXCLUDED.unidades_mes, actualizado = now(), actualizado_por = EXCLUDED.creado_por"""),
                      {**k, "f": a.factor, "b": a.base, "bm": a.base_meses if a.base == "venta" else None, "m": a.meses_espejo, "fa": a.fecha_apertura, "n": len(ids), "u": res["unidades_mes"], "us": usu})
            c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) VALUES ('apertura', :l, 'apertura', NULL, :n, :u)"),
                      {"l": f"{emp}|{dst}", "n": f"espejo {esp} x{a.factor:g}; {len(ids)} items; {a.meses_espejo} meses; modo {a.modo}", "u": (user or {}).get("nombre")})
        reg.resumen = res
    res["aviso"] = "Listo. Corre el motor (o espera el proceso nocturno) para que la tienda aparezca con su buffer."
    return res


@router.get("")
def listar(user=Depends(requiere(*VER))):
    """Aperturas registradas con su seguimiento: meses de venta de la tienda, cuanto le queda al espejo y venta real contra pronostico."""
    hoy = date.today(); mes_ant = sumar_meses(mes_de(hoy), -1); salida = []
    with pg.connect() as c:
        filas = c.execute(text("""SELECT a.*, b.descripcion AS nombre, be.descripcion AS espejo_nombre
                                  FROM ddmrp.apertura_tienda a
                                  LEFT JOIN ddmrp.abast_bitacora b ON b.empresa = a.empresa AND b.bodega_id = a.bodega_id
                                  LEFT JOIN ddmrp.abast_bitacora be ON be.empresa = a.empresa AND be.bodega_id = a.espejo_bodega
                                  ORDER BY a.activa DESC, a.creado DESC""")).mappings().all()
        for a in filas:
            k = {"e": a["empresa"], "b": a["bodega_id"]}
            n_it, pron = c.execute(text("SELECT count(*), COALESCE(sum(pronostico), 0)::float8 FROM ddmrp.pronostico WHERE empresa = :e AND bodega_id = :b AND pronostico > 0"), k).one()
            inicio = c.execute(text("SELECT min(mes) FROM ddmrp.ventas_mensual WHERE empresa = :e AND bodega_id = :b AND cantidad > 0"), k).scalar()
            transc = meses_con_venta(inicio, hoy); restan = restan_espejo(transc, a["meses_espejo"])
            n_cerr = meses_entre(inicio, mes_ant) if inicio else 0
            prom = ultimo = desvio = None
            if n_cerr >= 1:
                q = ("SELECT COALESCE(sum(v.cantidad), 0)::float8 FROM ddmrp.ventas_mensual v JOIN ddmrp.pronostico p ON p.empresa = v.empresa AND p.bodega_id = v.bodega_id "
                     "AND p.producto_id = v.producto_id AND p.pronostico > 0 WHERE v.empresa = :e AND v.bodega_id = :b AND v.mes BETWEEN :d AND :h")
                tot = c.execute(text(q), {**k, "d": inicio, "h": mes_ant}).scalar() or 0.0
                ultimo = c.execute(text(q), {**k, "d": mes_ant, "h": mes_ant}).scalar() or 0.0
                prom = tot / n_cerr
                if pron > 0:
                    desvio = (prom - pron) / pron * 100
            estado = "Cerrada" if not a["activa"] else "Sin ventas aun" if transc == 0 else "En espejo" if transc <= a["meses_espejo"] else "Terminado (manda el historial)"
            salida.append({"empresa": a["empresa"], "bodega_id": a["bodega_id"], "nombre": a["nombre"], "espejo": a["espejo_bodega"], "espejo_nombre": a["espejo_nombre"],
                           "factor": float(a["factor"]), "base": a["base"], "base_meses": a["base_meses"], "meses_espejo": a["meses_espejo"],
                           "fecha_apertura": a["fecha_apertura"], "activa": a["activa"], "items": n_it, "pronostico_total": pron, "meses_venta": transc, "restan": restan, "inicio_ventas": inicio, "fin_espejo": fin_espejo(inicio, a["meses_espejo"]),
                           "estado": estado, "venta_prom_mes": prom, "venta_ultimo_mes": ultimo, "desvio_pct": desvio, "creado": a["creado"], "creado_por": a["creado_por"]})
    return salida


@router.put("/{empresa}/{bodega}")
def cambiar(empresa: str, bodega: str, b: Cambio, user=Depends(requiere("cargar_maestros"))):
    """Extiende o acorta el espejo de una apertura, o la cierra (activa = false: el motor vuelve a la regla global de casos nuevos)."""
    _exigir_global(user)
    if b.meses_espejo is None and b.activa is None:
        raise HTTPException(400, "Nada que cambiar")
    with bitacora.registrar("carga", "manual", usuario_de(user), f"Apertura {bodega}: cambio de espejo"):
        with pg.begin() as c:
            a = c.execute(text("SELECT meses_espejo, activa FROM ddmrp.apertura_tienda WHERE empresa = :e AND bodega_id = :b"), {"e": empresa, "b": bodega}).first()
            if not a:
                raise HTTPException(404, "Apertura no encontrada")
            if b.meses_espejo is not None and b.meses_espejo > _cfg(c, empresa)["max_meses"]:
                raise HTTPException(400, f"El espejo no puede durar mas de {_cfg(c, empresa)['max_meses']} meses (meses de historia del motor)")
            c.execute(text("UPDATE ddmrp.apertura_tienda SET meses_espejo = COALESCE(:m, meses_espejo), activa = COALESCE(:a, activa), actualizado = now(), actualizado_por = :u "
                           "WHERE empresa = :e AND bodega_id = :b"), {"m": b.meses_espejo, "a": b.activa, "u": (user or {}).get("nombre"), "e": empresa, "b": bodega})
            c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) VALUES ('apertura', :l, 'meses_espejo/activa', :a, :n, :u)"),
                      {"l": f"{empresa}|{bodega}", "a": f"{a[0]}/{a[1]}", "n": f"{b.meses_espejo if b.meses_espejo is not None else a[0]}/{b.activa if b.activa is not None else a[1]}",
                       "u": (user or {}).get("nombre")})
    return {"ok": True, "aviso": "Se aplica en la proxima corrida del motor."}
