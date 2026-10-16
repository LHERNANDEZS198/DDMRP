"""Maestros editables desde la UI (lead time, cotas, unidad de despacho, vectorizacion, pronostico, promociones,
factores y parametros del modelo). Todo el SQL sale de esta lista blanca: el cliente nunca elige tablas ni columnas."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, exigir, asignaciones, NIVELES

router = APIRouter(prefix="/maestros", tags=["maestros"])

# tipo -> cast SQL
CAST = {"num": "numeric", "int": "smallint", "txt": "text"}

MAESTROS = {
    "bitacora": dict(
        label="Bitacora: lead time y frecuencia por bodega", tabla="ddmrp.abast_bitacora",
        llave=["empresa", "bodega_id"], editable={"frecuencia": "num", "leadtime": "num"},
        bodega="bodega_id", producto=None),
    "control-referencias": dict(
        label="Cotas maxima / minima por bodega y referencia", tabla="ddmrp.abast_control_referencias",
        llave=["empresa", "bodega_id", "producto_id"], editable={"cota_maxima": "num", "cota_minima": "num"},
        bodega="bodega_id", producto="producto_id"),
    "vectorizacion": dict(
        label="Vectorizacion (derrame)", tabla="ddmrp.abast_vectorizacion",
        llave=["empresa", "bodega_id", "producto_id"], editable={"vectorizacion": "num"},
        bodega="bodega_id", producto="producto_id"),
    "pronostico": dict(
        label="Pronostico (unidades/mes)", tabla="ddmrp.pronostico",
        llave=["empresa", "bodega_id", "producto_id"], editable={"pronostico": "num"},
        bodega="bodega_id", producto="producto_id"),
    "unidad-despacho": dict(
        label="Unidad de despacho por referencia", tabla="ddmrp.abast_unidad_despacho",
        llave=["empresa", "producto_id"], editable={"unidad_despacho": "num"},
        bodega=None, producto="producto_id", global_=True),
    "promocion": dict(
        label="Promociones (indicativo 0/1/2)", tabla="ddmrp.promocion",
        llave=["empresa", "producto_id"], editable={"indicativo": "int"},
        bodega=None, producto="producto_id", global_=True),
    "factores": dict(
        label="Factores de lead time y variabilidad", tabla="ddmrp.factor_tramo",
        llave=["tipo", "descripcion"], editable={"factor": "num", "desde": "num", "hasta": "num"},
        bodega=None, producto=None, global_=True),
    "parametros": dict(
        label="Parametros del modelo", tabla="ddmrp.parametro",
        llave=["clave"], editable={"valor": "num"}, bodega=None, producto=None, global_=True),
}


def _def(nombre: str) -> dict:
    d = MAESTROS.get(nombre)
    if not d:
        raise HTTPException(404, "Maestro desconocido")
    return d


def _es_admin(user) -> bool:
    return any(a["es_admin"] for a in asignaciones(user["id"]))


def _puede_global(user) -> bool:
    """Tablas sin bodega: admin, o edicion/aprobacion sobre todas las bodegas y categorias."""
    return any(a["es_admin"] or (a["bodega_id"] == "*" and a["categoria"] == "*" and NIVELES[a["nivel"]] >= 2)
               for a in asignaciones(user["id"]))


def _autorizar(user, d: dict, llave: dict, conn):
    if d.get("bodega"):
        cat = None
        if d.get("producto"):
            cat = conn.execute(text("SELECT categoria FROM ddmrp.maestro_item WHERE producto_id=:p"),
                               {"p": llave[d["producto"]]}).scalar()
        exigir(user, llave[d["bodega"]], cat, "edicion")
    elif d.get("global_"):
        if not _puede_global(user):
            raise HTTPException(403, "Requiere permiso de edicion sobre todas las bodegas")
    elif not _es_admin(user):
        raise HTTPException(403, "Solo administradores")


@router.get("")
def listar_maestros(user=Depends(usuario_actual)):
    return [{"clave": k, "label": v["label"], "llave": v["llave"], "editable": list(v["editable"])}
            for k, v in MAESTROS.items()]


@router.get("/{nombre}")
def leer(nombre: str, bodega_id: str | None = None, producto_id: str | None = None, limit: int = 20000,
         user=Depends(usuario_actual)):
    d = _def(nombre)
    cols = d["llave"] + [c for c in d["editable"] if c not in d["llave"]]
    sel = ", ".join(f"t.{c}" for c in cols)
    join, w, p = "", "TRUE", {}
    if d.get("bodega"):
        join = f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.{d['producto']}" if d.get("producto") else ""
        w, p = filtro_sql_permisos(user, f"t.{d['bodega']}", "mi.categoria" if d.get("producto") else "'*'")
        sel += ", mi.descripcion" if d.get("producto") else ""
        if bodega_id:
            w += f" AND t.{d['bodega']} = :b"; p["b"] = bodega_id
    elif d.get("producto"):
        join = f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.{d['producto']}"
        sel += ", mi.descripcion"
    if producto_id and d.get("producto"):
        w += f" AND t.{d['producto']} = :pr"; p["pr"] = producto_id
    sql = f"SELECT {sel} FROM {d['tabla']} t {join} WHERE {w} ORDER BY {', '.join('t.' + c for c in d['llave'])} LIMIT :lim"
    with pg.connect() as c:
        return [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]


class Cambio(BaseModel):
    llave: dict[str, str]
    campo: str
    valor: float | int | str | None


@router.patch("/{nombre}")
def editar(nombre: str, cambios: list[Cambio], user=Depends(usuario_actual)):
    d = _def(nombre)
    with pg.begin() as c:
        for ch in cambios:
            if ch.campo not in d["editable"]:
                raise HTTPException(400, f"Campo no editable: {ch.campo}")
            if set(ch.llave) != set(d["llave"]):
                raise HTTPException(400, f"La llave debe ser {d['llave']}")
            _autorizar(user, d, ch.llave, c)
            cast = CAST[d["editable"][ch.campo]]
            donde = " AND ".join(f"{k} = :k_{k}" for k in d["llave"])
            kp = {f"k_{k}": ch.llave[k] for k in d["llave"]}
            ant = c.execute(text(f"SELECT {ch.campo}::text FROM {d['tabla']} WHERE {donde}"), kp).scalar()
            r = c.execute(text(f"UPDATE {d['tabla']} SET {ch.campo} = CAST(:v AS {cast}) WHERE {donde}"),
                          {**kp, "v": ch.valor})
            if r.rowcount == 0:
                raise HTTPException(404, "Fila no encontrada")
            c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                           "VALUES (:t, :l, :c, :a, :n, :u)"),
                      {"t": nombre, "l": "|".join(ch.llave[k] for k in d["llave"]), "c": ch.campo,
                       "a": ant, "n": None if ch.valor is None else str(ch.valor), "u": user["nombre"]})
    return {"ok": True, "cambios": len(cambios)}


class Carga(BaseModel):
    filas: list[dict[str, float | int | str | None]]


@router.post("/{nombre}/carga")
def cargar(nombre: str, body: Carga, user=Depends(usuario_actual)):
    """Alta/actualizacion masiva (pegar desde Excel). Cada fila trae las columnas llave y las editables."""
    d = _def(nombre)
    if nombre in ("factores", "parametros"):
        raise HTTPException(400, "Use PATCH para factores y parametros")
    if len(body.filas) > 50_000:
        raise HTTPException(400, "Maximo 50.000 filas por carga")
    cols = d["llave"] + list(d["editable"])
    with pg.begin() as c:
        for fila in body.filas:
            faltan = [k for k in d["llave"] if not fila.get(k)]
            if faltan:
                raise HTTPException(400, f"Falta la llave {faltan} en {fila}")
            llave = {k: str(fila[k]).strip() for k in d["llave"]}
            _autorizar(user, d, llave, c)
            vals = {k: llave[k] for k in d["llave"]}
            for k, tipo in d["editable"].items():
                vals[k] = fila.get(k)
            ins = ", ".join(cols)
            val = ", ".join(f"CAST(:{k} AS {CAST[d['editable'][k]]})" if k in d["editable"] else f":{k}" for k in cols)
            upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in d["editable"])
            c.execute(text(f"INSERT INTO {d['tabla']} ({ins}) VALUES ({val}) "
                           f"ON CONFLICT ({', '.join(d['llave'])}) DO UPDATE SET {upd}"), vals)
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES (:t, '*', 'carga', NULL, :n, :u)"),
                  {"t": nombre, "n": f"{len(body.filas)} filas", "u": user["nombre"]})
    return {"ok": True, "filas": len(body.filas)}
