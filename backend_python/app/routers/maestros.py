"""Maestros editables desde la UI (lead time, cotas, unidad de despacho, vectorizacion, pronostico, promociones,
factores y parametros del modelo). Todo el SQL sale de esta lista blanca: el cliente nunca elige tablas ni columnas."""
import csv, io, unicodedata
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from ..db import pg
from ..security import usuario_actual, filtro_sql_permisos, exigir, asignaciones, nivel_efectivo, NIVELES, requiere

router = APIRouter(prefix="/maestros", tags=["maestros"])

# tipo -> cast SQL
CAST = {"num": "numeric", "int": "smallint", "txt": "text"}
# tipo de las columnas llave que no son texto
TIPO_LLAVE = {"dia": "int"}
# columnas llave cuyo valor numerico de Excel pierde ceros a la izquierda -> se rellenan
ANCHO = {"producto_id": 6, "empresa": 2}

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
        label="Vectorizacion (derrame); NxP = condenar item en esa tienda", tabla="ddmrp.abast_vectorizacion",
        llave=["empresa", "bodega_id", "producto_id"], editable={"vectorizacion": "num"},
        bodega="bodega_id", producto="producto_id", nxp=True),   # NxP en vectorizacion = condenado (item x tienda): va al maestro de condenados
    "condenados": dict(
        label="Condenados: items que no se despachan (todas las tiendas o solo una)", tabla="ddmrp.item_condenado",
        llave=["bodega_id", "producto_id"], editable={"motivo": "txt"}, bodega="bodega_id", producto="producto_id", todas="*"),
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
        llave=["clave"], editable={"valor": "num"}, bodega=None, producto=None, global_=True,
        solo_existentes=True, sin_reemplazo=True),
    "dias-bodega": dict(
        label="DIA de abastecimiento por tienda", tabla="ddmrp.bodega_dia",
        llave=["bodega_id", "dia"], editable={}, bodega="bodega_id", producto=None),
    "items": dict(
        label="Items: descripcion y laboratorio (los criterios vienen de Siesa)", tabla="ddmrp.maestro_item",
        llave=["producto_id"], editable={"descripcion": "txt", "categoria": "txt"},
        bodega=None, producto=None, global_=True, defecto={"descripcion": "producto_id"}),
    "centro-operacion": dict(
        label="Centro de operacion por bodega (archivo plano)", tabla="ddmrp.bodega_centro_operacion",
        llave=["bodega_id"], editable={"id_co": "txt"}, bodega="bodega_id", producto=None),
    "demanda-calificada": dict(
        label="Demanda calificada (pedidos abiertos / picos)", tabla="ddmrp.demanda_calificada",
        llave=["bodega_id", "producto_id"], editable={"cantidad": "num"},
        bodega="bodega_id", producto="producto_id"),
    "ventas-mensual": dict(
        label="Ventas por mes (unidades)", tabla="ddmrp.ventas_mensual",
        llave=["mes", "bodega_id", "producto_id"], editable={"cantidad": "num"},
        bodega="bodega_id", producto="producto_id"),
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
def listar_maestros(user=Depends(requiere("ver_maestros", "cargar_maestros"))):
    return [{"clave": k, "label": v["label"], "llave": v["llave"], "editable": list(v["editable"]),
             "tipos": v["editable"], "sin_reemplazo": bool(v.get("sin_reemplazo")), "todas": bool(v.get("todas"))}
            for k, v in MAESTROS.items()]


@router.get("/{nombre}")
def leer(nombre: str, bodega_id: str | None = None, producto_id: str | None = None, limit: int = 20000,
         user=Depends(requiere("ver_maestros", "cargar_maestros"))):
    d = _def(nombre)
    cols = d["llave"] + [c for c in d["editable"] if c not in d["llave"]]
    sel = ", ".join(f"t.{c}" for c in cols)
    join, w, p = "", "TRUE", {}
    if d.get("bodega"):
        join = f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.{d['producto']}" if d.get("producto") else ""
        w, p = filtro_sql_permisos(user, f"t.{d['bodega']}", "mi.categoria" if d.get("producto") else "'*'")
        sel += ", mi.descripcion" if d.get("producto") else ""
        join += f" LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = t.{d['bodega']}"
        sel += ", mb.descripcion AS bodega_nombre"
        if bodega_id:
            w += f" AND t.{d['bodega']} = :b"; p["b"] = bodega_id
    elif d.get("producto"):
        join = f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.{d['producto']}"
        sel += ", mi.descripcion"
    if producto_id and d.get("producto"):
        w += f" AND t.{d['producto']} = :pr"; p["pr"] = producto_id
    sql = f"SELECT {sel} FROM {d['tabla']} t {join} WHERE {w} ORDER BY {', '.join('t.' + c for c in d['llave'])} LIMIT :lim"
    with pg.connect() as c:
        filas = [dict(r) for r in c.execute(text(sql), {**p, "lim": limit}).mappings()]
        if nombre == "items" and filas:
            # una columna por plan de criterios (CATEGORIA, LINEA, ...) con el nombre del criterio como valor
            planes = c.execute(text("SELECT ic.plan_id, coalesce(pl.nombre, ic.plan_id) FROM (SELECT DISTINCT plan_id FROM ddmrp.item_criterio) ic "
                                    "LEFT JOIN ddmrp.criterio_plan pl ON pl.plan_id = ic.plan_id ORDER BY ic.plan_id")).all()
            nom = {pid: n.strip().upper() for pid, n in planes}
            vals = {}
            for pr, pid, cid, cn in c.execute(text("SELECT ic.producto_id, ic.plan_id, ic.criterio_id, cr.nombre FROM ddmrp.item_criterio ic "
                                                    "LEFT JOIN ddmrp.criterio cr ON cr.plan_id = ic.plan_id AND cr.criterio_id = ic.criterio_id")):
                vals.setdefault(pr, {})[pid] = (cn or cid).strip()
            for f in filas:
                v = vals.get(f["producto_id"], {})
                for pid, n in nom.items():
                    f[n] = v.get(pid)
        return filas


class Cambio(BaseModel):
    llave: dict[str, str]
    campo: str
    valor: float | int | str | None


@router.patch("/{nombre}")
def editar(nombre: str, cambios: list[Cambio], user=Depends(requiere("cargar_maestros"))):
    d = _def(nombre)
    with pg.begin() as c:
        for ch in cambios:
            if ch.campo not in d["editable"]:
                raise HTTPException(400, f"Campo no editable: {ch.campo}")
            if set(ch.llave) != set(d["llave"]):
                raise HTTPException(400, f"La llave debe ser {d['llave']}")
            _autorizar(user, d, ch.llave, c)
            cast = CAST[d["editable"][ch.campo]]
            donde = " AND ".join(f"{k} = CAST(:k_{k} AS {CAST[TIPO_LLAVE.get(k, 'txt')]})" for k in d["llave"])
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


# ---------------------------------------------------------------------------------------------------------
# Carga masiva (pegar / Excel / CSV) y descarga a Excel
# ---------------------------------------------------------------------------------------------------------
MAX_FILAS = 1_000_000


TODAS = {"*", "TODAS", "TODO", "TODOS", "ALL"}
NXP = {"nxp", "n x p", "condenado", "condenar"}
EMPRESA_ALIAS = {"funat": "05", "stores": "21", "store": "21", "tiendas": "21"}


def _valor_llave(col: str, v) -> str:
    """Normaliza una celda llave. Excel convierte '019901' en 19901: se recuperan los ceros."""
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    t = str(v).strip()
    if col == "empresa" and t and not t.isdigit():   # nombres en vez de codigo: Funat -> 05, Stores -> 21
        t = EMPRESA_ALIAS.get(t.lower(), t)
        if not t.isdigit():
            raise ValueError(f"empresa {t!r} no reconocida: usa 05 (Funat) o 21 (Stores)")
    if isinstance(v, int) and col in ANCHO:
        t = t.zfill(ANCHO[col])
    return t


def _valor_num(v, tipo: str):
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, str):
        v = v.strip().replace(" ", "")
        if v.endswith("%"):                              # 20% -> 0.2 (las cotas se guardan como fraccion del TOG)
            return _valor_num(v[:-1], tipo) / 100 if tipo != "int" else int(float(v[:-1].replace(",", ".")))
        if v.count(",") == 1 and v.count(".") == 0:   # 1,5 -> 1.5
            v = v.replace(",", ".")
    x = float(v)
    return int(x) if tipo == "int" else x


def _leer_archivo(nombre_archivo: str, datos: bytes) -> list[dict]:
    """Primera hoja del Excel (o CSV): fila 1 = encabezados. Devuelve filas como dict {encabezado_en_minusculas: valor}."""
    if nombre_archivo.lower().endswith((".csv", ".txt")):
        txt = datos.decode("utf-8-sig", errors="replace")
        sep = max(",;\t", key=lambda c: txt.split("\n", 1)[0].count(c))
        filas = list(csv.reader(io.StringIO(txt), delimiter=sep))
    else:
        try:
            wb = load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
        except Exception:
            raise HTTPException(400, "No pude leer el archivo: debe ser .xlsx o .csv")
        filas = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
    filas = [r for r in filas if r and any(c not in (None, "") for c in r)]
    if len(filas) < 2:
        raise HTTPException(400, "El archivo no tiene datos (fila 1 = encabezados, desde la fila 2 los datos)")
    cab = [str(c).strip().lower() if c is not None else "" for c in filas[0]]
    return [{c: (r[i] if i < len(r) else None) for i, c in enumerate(cab) if c} for r in filas[1:]]


BOD_COD = ("bodega_id", "bodega", "codigo_bodega", "cod_bodega")
BOD_NOM = ("bodega_nombre", "nombre_bodega", "tienda", "nombre")


def _norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower()
    return " ".join(t.split())


def _mapa_bodegas():
    """(por codigo, por nombre) desde ddmrp.maestro_bodega (que el ETL trae de Siesa t150)."""
    with pg.connect() as c:
        rows = c.execute(text("SELECT bodega_id, empresa, descripcion FROM ddmrp.maestro_bodega")).all()
    return ({r[0].strip().upper(): (r[0], r[1]) for r in rows},
            {_norm(r[2]): (r[0], r[1]) for r in rows if r[2]},
            sorted({r[1] for r in rows}))


def _preparar(d: dict, filas: list[dict], omitir: bool = False, malas_out: list | None = None, cond_out: list | None = None) -> tuple[list[str], list[dict]]:
    """Valida y normaliza. La tienda se identifica por codigo (SV021) o por nombre y la empresa se deduce de la tienda.
    Devuelve (columnas editables presentes, filas listas)."""
    presentes = set().union(*[f.keys() for f in filas]) if filas else set()
    cod_h = next((h for h in BOD_COD if h in presentes), None)
    nom_h = next((h for h in BOD_NOM if h in presentes), None)
    con_bodega = bool(d.get("bodega"))
    otras = [k for k in d["llave"] if k != "empresa" and not (con_bodega and k == d["bodega"])]
    faltan = [k for k in otras if k not in presentes]
    if con_bodega and not (cod_h or nom_h):
        faltan.insert(0, "bodega_id (codigo, ej. SV021) o bodega_nombre")
    if faltan:
        amigable = ([d["bodega"]] if con_bodega else []) + otras + list(d["editable"])
        raise HTTPException(400, f"Faltan columnas: {faltan}. Encabezados: {amigable}")
    cols = [c for c in d["editable"] if c in presentes]
    # "NxP" (condenar) en la columna vectorizacion: la referencia no se despacha a esa tienda (va al maestro de condenados)
    es_nxp = lambda v: isinstance(v, str) and v.strip().lower() in NXP
    por_cod, por_nom, empresas = _mapa_bodegas() if ("empresa" in d["llave"] or con_bodega) else ({}, {}, [])
    malas, out = [], []
    for n, f in enumerate(filas, start=2):
        try:
            llave: dict[str, str] = {}
            if con_bodega:
                cod = _valor_llave("bodega_id", f.get(cod_h)) if cod_h else ""
                hit = por_cod.get(cod.upper()) if cod else None
                if d.get("todas") and not hit and (cod.upper() in TODAS or (not cod and not (nom_h and f.get(nom_h)))):
                    hit = (d["todas"], None)   # el item queda condenado en todas las tiendas
                if not hit and (cod or nom_h):
                    hit = por_nom.get(_norm(cod)) or (por_nom.get(_norm(f.get(nom_h))) if nom_h else None)
                if not hit:
                    if cod and (not por_cod or _valor_llave("empresa", f.get("empresa"))):
                        hit = (cod, None)   # maestro vacio o empresa indicada en el archivo: se acepta el codigo tal cual
                    else:
                        raise ValueError(f"tienda no reconocida: {cod or f.get(nom_h)!r}")
                llave[d["bodega"]] = hit[0]
                if "empresa" in d["llave"]:
                    emp = _valor_llave("empresa", f.get("empresa")) or hit[1] or ""
                    if not emp:
                        raise ValueError("no se pudo deducir la empresa de la tienda: agrega la columna empresa")
                    llave["empresa"] = emp
            for k in otras:
                llave[k] = _valor_llave(k, f.get(k))
                if TIPO_LLAVE.get(k) == "int" and llave[k]:
                    llave[k] = str(int(float(llave[k])))
            if "empresa" in d["llave"] and "empresa" not in llave:   # tabla por producto: sin empresa = todas
                emp = _valor_llave("empresa", f.get("empresa"))
                llave["empresa"] = emp
            if not all(v for k, v in llave.items() if k != "empresa"):
                raise ValueError("llave vacia")
            fila_base = dict(llave)
            cond_nxp = bool(d.get("nxp")) and es_nxp(f.get("vectorizacion"))
            if cond_nxp and cond_out is not None:
                cond_out.append((llave[d["bodega"]], llave[d["producto"]]))
            for c in cols:
                t = d["editable"][c]
                if cond_nxp and c == "vectorizacion":
                    fila_base[c] = 0
                    continue
                fila_base[c] = _valor_num(f.get(c), t) if t in ("num", "int") else (str(f[c]).strip() if f.get(c) not in (None, "") else None)
            if "empresa" in d["llave"] and not fila_base.get("empresa"):
                if not empresas:
                    raise ValueError("falta la columna empresa (y aun no hay bodegas cargadas para deducirla)")
                for emp in empresas:
                    out.append({**fila_base, "empresa": emp})
            else:
                out.append(fila_base)
        except (ValueError, TypeError) as e:
            malas.append(f"fila {n}: {e}")
    if malas and omitir:
        if malas_out is not None:
            malas_out.extend(malas)
    elif malas:
        raise HTTPException(400, f"{len(malas)} fila(s) invalidas, p.ej.: " + "; ".join(malas[:5]))
    if len(out) > MAX_FILAS:
        raise HTTPException(400, f"Maximo {MAX_FILAS:,} filas por carga")
    return cols, out


def _autorizar_lote(user, d: dict, filas: list[dict], conn, reemplazo: bool):
    if reemplazo and not _puede_global(user):
        raise HTTPException(403, "Reemplazar un maestro completo requiere admin o permiso de edicion sobre todas las bodegas")
    if d.get("bodega"):
        cats: dict[str, str | None] = {}
        if d.get("producto"):
            prods = sorted({f[d["producto"]] for f in filas})
            cats = dict(conn.execute(text("SELECT producto_id, categoria FROM ddmrp.maestro_item WHERE producto_id = ANY(:p)"),
                                     {"p": prods}).all())
        asigs = asignaciones(user["id"])
        pares = {(f[d["bodega"]], cats.get(f[d["producto"]]) if d.get("producto") else None) for f in filas}
        malos = [p for p in pares if nivel_efectivo(asigs, p[0], p[1]) < NIVELES["edicion"]]
        if malos:
            raise HTTPException(403, f"Sin permiso de edicion en {len(malos)} combinacion(es) bodega/laboratorio, p.ej. {malos[:3]}")
    elif d.get("global_"):
        if not _puede_global(user):
            raise HTTPException(403, "Requiere permiso de edicion sobre todas las bodegas")
    elif not _es_admin(user):
        raise HTTPException(403, "Solo administradores")


def _importar(nombre: str, d: dict, filas: list[dict], modo: str, user, omitir: bool = False) -> dict:
    try:
        return _importar_(nombre, d, filas, modo, user, omitir)
    except DBAPIError as e:  # p.ej. NOT NULL o valor fuera de rango: es error del archivo, no del servidor
        raise HTTPException(400, "El archivo tiene datos que la base rechaza: " + str(e.orig).splitlines()[0][:300])


def _importar_(nombre: str, d: dict, filas: list[dict], modo: str, user, omitir: bool = False) -> dict:
    if modo not in ("actualizar", "reemplazar"):
        raise HTTPException(400, "modo debe ser 'actualizar' o 'reemplazar'")
    reemplazo = modo == "reemplazar"
    if reemplazo and d.get("sin_reemplazo"):
        raise HTTPException(400, "Este maestro no admite reemplazo total: usa 'actualizar'")
    malas: list[str] = []
    cond_nxp: list[tuple[str, str]] = []
    cols, filas = _preparar(d, filas, omitir, malas, cond_nxp)
    if not filas:
        raise HTTPException(400, "El archivo no trae filas")
    llave, tabla = d["llave"], d["tabla"]
    defecto = d.get("defecto", {})
    with pg.begin() as c:
        _autorizar_lote(user, d, filas, c, reemplazo)
        todas = llave + cols
        c.execute(text("CREATE TEMP TABLE stg_carga (_n serial, " + ", ".join(f"{k} text" for k in todas) + ") ON COMMIT DROP"))
        raw = c.connection
        with raw.cursor() as cur, cur.copy(f"COPY stg_carga ({', '.join(todas)}) FROM STDIN") as cp:
            for f in filas:
                cp.write_row([None if f[k] is None else str(f[k]) for k in todas])
        uniq = (f"(SELECT DISTINCT ON ({', '.join(llave)}) * FROM stg_carga ORDER BY {', '.join(llave)}, _n DESC) s")
        tipos = {**{k: TIPO_LLAVE.get(k, "txt") for k in llave}, **d["editable"]}
        def expr(k):
            e = f"CAST(NULLIF(s.{k}, '') AS {CAST[tipos[k]]})"
            return f"COALESCE({e}, s.{defecto[k]})" if k in defecto and k in cols else e
        ins_cols = list(todas) + [k for k in defecto if k not in cols]
        ins_val = [expr(k) if k in todas else f"s.{defecto[k]}" for k in ins_cols]
        if d.get("solo_existentes"):
            sel_where = f"WHERE EXISTS (SELECT 1 FROM {tabla} t WHERE " + " AND ".join(f"t.{k} = s.{k}" for k in llave) + ")"
        else:
            sel_where = ""
        n_unicas = c.execute(text(f"SELECT count(*) FROM {uniq}")).scalar()
        existentes = c.execute(text(f"SELECT count(*) FROM {uniq} JOIN {tabla} t ON " +
                                    " AND ".join(f"t.{k} = CAST(s.{k} AS {CAST[tipos[k]]})" for k in llave))).scalar()
        if reemplazo:
            c.execute(text(f"DELETE FROM {tabla}"))
            existentes = 0
        upd = ", ".join(f"{k} = EXCLUDED.{k}" for k in cols)
        c.execute(text(f"INSERT INTO {tabla} ({', '.join(ins_cols)}) SELECT {', '.join(ins_val)} FROM {uniq} {sel_where} "
                       f"ON CONFLICT ({', '.join(llave)}) " + (f"DO UPDATE SET {upd}" if upd else "DO NOTHING")))
        if d.get("solo_existentes"):
            ignoradas = n_unicas - existentes
            creadas = 0
        else:
            ignoradas, creadas = 0, n_unicas - existentes
        if cond_nxp:
            c.execute(text("INSERT INTO ddmrp.item_condenado (bodega_id, producto_id, motivo) SELECT * FROM unnest(CAST(:b AS text[]), CAST(:p AS text[]), CAST(:m AS text[])) "
                           "ON CONFLICT (producto_id, bodega_id) DO NOTHING"),
                      {"b": [x[0] for x in cond_nxp], "p": [x[1] for x in cond_nxp], "m": ["NxP (carga de vectorizacion)"] * len(cond_nxp)})
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES (:t, '*', :m, NULL, :n, :u)"),
                  {"t": nombre, "m": "carga_" + modo, "n": f"{len(filas)} filas ({creadas} nuevas)", "u": user["nombre"]})
    return {"ok": True, "modo": modo, "filas": len(filas), "unicas": n_unicas, "creadas": creadas,
            "actualizadas": 0 if reemplazo else existentes, "ignoradas": ignoradas, "condenados_nxp": len(cond_nxp),
            "omitidas": len(malas), "ejemplos_omitidas": malas[:5]}


class Carga(BaseModel):
    filas: list[dict[str, float | int | str | None]]
    modo: str = "actualizar"
    omitir_invalidas: bool = False


@router.post("/{nombre}/carga")
def cargar(nombre: str, body: Carga, user=Depends(requiere("cargar_maestros"))):
    """Alta/actualizacion masiva (pegar desde Excel). Cada fila trae las columnas llave y las editables."""
    d = _def(nombre)
    return _importar(nombre, d, [{str(k).strip().lower(): v for k, v in f.items()} for f in body.filas], body.modo, user, body.omitir_invalidas)


@router.post("/{nombre}/excel")
async def subir_excel(nombre: str, archivo: UploadFile = File(...), modo: str = Query("actualizar"),
                      omitir_invalidas: bool = Query(False), user=Depends(requiere("cargar_maestros"))):
    """Carga un .xlsx / .csv. modo=actualizar: crea las filas nuevas y actualiza las existentes (solo las columnas
    que vengan en el archivo). modo=reemplazar: borra el maestro y deja exactamente lo del archivo."""
    d = _def(nombre)
    datos = await archivo.read()
    if len(datos) > 60_000_000:
        raise HTTPException(400, "Archivo demasiado grande")
    return _importar(nombre, d, _leer_archivo(archivo.filename or "", datos), modo, user, omitir_invalidas)


@router.get("/{nombre}/excel")
def bajar_excel(nombre: str, user=Depends(requiere("ver_maestros", "cargar_maestros"))):
    """Descarga lo que el usuario puede ver, con los mismos encabezados que acepta la carga (sirve de plantilla).
    Maestros por tienda: la tienda va con su codigo y su nombre (la empresa se deduce) y, si el maestro es solo por
    tienda (bitacora, centro de operacion), vienen todas las tiendas aunque aun no tengan datos."""
    d = _def(nombre)
    bod = d.get("bodega")
    llave_xl = [k for k in d["llave"] if not (bod and k in ("empresa", bod))]
    cols_t = [k for k in d["llave"] if not (bod and k == "empresa")] if bod else d["llave"]
    sel = ", ".join(f"t.{c}" for c in cols_t + list(d["editable"]))
    join, w, p = "", "TRUE", {}
    solo_tienda = bool(bod) and not llave_xl and not d.get("producto")
    if bod:
        join = f"LEFT JOIN ddmrp.maestro_item mi ON mi.producto_id = t.{d['producto']}" if d.get("producto") else ""
        join += f" LEFT JOIN ddmrp.maestro_bodega mb ON mb.bodega_id = t.{bod}"
        w, p = filtro_sql_permisos(user, f"t.{bod}", "mi.categoria" if d.get("producto") else "'*'")
        sel = f"t.{bod}, mb.descripcion AS bodega_nombre" + "".join(f", t.{c}" for c in cols_t if c != bod) + "".join(f", t.{c}" for c in d["editable"])
        cab = [bod, "bodega_nombre"] + [c for c in cols_t if c != bod] + list(d["editable"])
    else:
        cab = cols_t + list(d["editable"])
    with pg.connect() as c:
        if solo_tienda:   # plantilla con todas las tiendas del maestro de bodegas
            w2, p2 = filtro_sql_permisos(user, "mb.bodega_id", "'*'")
            ed = "".join(f", t.{c}" for c in d["editable"])
            filas = c.execute(text(f"SELECT mb.bodega_id, mb.descripcion{ed} FROM ddmrp.maestro_bodega mb "
                                   f"LEFT JOIN {d['tabla']} t ON t.{bod} = mb.bodega_id WHERE {w2} ORDER BY mb.bodega_id"), p2).all()
        else:
            filas = c.execute(text(f"SELECT {sel} FROM {d['tabla']} t {join} WHERE {w} ORDER BY "
                                   + ", ".join("t." + k for k in d["llave"]) + " LIMIT 1000000"), p).all()
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Datos")
    ws.append(cab)
    for r in filas:
        ws.append([float(v) if hasattr(v, "as_tuple") else v for v in r])
    ins = wb.create_sheet("Instrucciones")
    lineas = [d["label"], "", "Fila 1 = encabezados (no los cambies). Desde la fila 2, los datos."]
    if bod:
        lineas += ["Tienda: usa el codigo de Siesa (bodega_id, ej. SV021) o, si prefieres, solo el nombre (bodega_nombre). La empresa se deduce sola.",
                   "La columna bodega_nombre es informativa."]
    elif "empresa" in d["llave"]:
        lineas.append("Empresa (05 Funat, 21 Store): opcional; si la dejas vacia aplica a todas.")
    otras = [k for k in d["llave"] if k not in ("empresa",) and k != bod]
    if otras:
        lineas.append("Otras columnas llave: " + ", ".join(otras))
    lineas += ["Columnas a cargar: " + (", ".join(d["editable"]) or "(ninguna: la existencia de la fila es el dato)"),
               "Actualizar: crea las filas nuevas y actualiza las existentes; solo toca las columnas que vengan en el archivo.",
               "Reemplazar: borra el maestro y deja exactamente lo del archivo (solo admin / edicion en todas las bodegas)."]
    if "producto_id" in d["llave"]:
        lineas.append("Las referencias van como texto de 6 digitos (ej. 019901).")
    for l in lineas:
        ins.append([l])
    buf = io.BytesIO(); wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}.xlsx"'})


class Eliminar(BaseModel):
    llaves: list[dict[str, str]]


@router.post("/{nombre}/eliminar")
def eliminar(nombre: str, body: Eliminar, user=Depends(requiere("cargar_maestros"))):
    """Borra filas por su llave (p.ej. quitar una tienda de un DIA). No aplica a factores ni parametros."""
    d = _def(nombre)
    if d.get("sin_reemplazo") or nombre == "factores":
        raise HTTPException(400, "Este maestro no admite eliminar filas")
    if len(body.llaves) > 5000:
        raise HTTPException(400, "Maximo 5.000 filas por eliminacion")
    n = 0
    with pg.begin() as c:
        for ll in body.llaves:
            if set(ll) != set(d["llave"]):
                raise HTTPException(400, f"La llave debe ser {d['llave']}")
            _autorizar(user, d, ll, c)
            donde = " AND ".join(f"{k} = CAST(:k_{k} AS {CAST[TIPO_LLAVE.get(k, 'txt')]})" for k in d["llave"])
            n += c.execute(text(f"DELETE FROM {d['tabla']} WHERE {donde}"), {f"k_{k}": ll[k] for k in d["llave"]}).rowcount
        c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                       "VALUES (:t, '*', 'eliminar', :n, NULL, :u)"), {"t": nombre, "n": f"{n} filas", "u": user["nombre"]})
    return {"ok": True, "eliminadas": n}
