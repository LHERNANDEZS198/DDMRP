"""Usuarios y perfiles. La clave sigue viviendo en reloj (MySQL); aqui se decide QUE puede hacer cada usuario
(perfil = funciones) y SOBRE QUE (tiendas y laboratorios). El alcance se materializa en rbac_asignacion,
que es lo que ya usan control, despacho y maestros para filtrar y validar."""
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from ..config import settings
from ..db import pg, mysql_engine
from ..security import usuario_actual, requiere, permisos, PERMISOS, CLAVES_PERMISO, _bootstrap

router = APIRouter(prefix="/usuarios", tags=["usuarios"], dependencies=[Depends(requiere("admin_usuarios"))])
NIVELES = ("lectura", "edicion", "aprobacion")


def _audit(c, user, llave, campo, ant, nuevo):
    c.execute(text("INSERT INTO ddmrp.config_audit (tabla, llave, campo, valor_anterior, valor_nuevo, usuario) "
                   "VALUES ('usuarios', :l, :c, :a, :n, :u)"),
              {"l": llave, "c": campo, "a": ant, "n": nuevo, "u": user["nombre"]})


def sincronizar_rbac(c, uid: str):
    """Reescribe las filas de rbac_asignacion del usuario a partir de su perfil y alcance."""
    c.execute(text("DELETE FROM ddmrp.rbac_asignacion WHERE usuario_id = :u"), {"u": uid})
    u = c.execute(text("SELECT u.activo, u.bodegas, u.categorias, p.nivel, p.permisos FROM ddmrp.usuario u "
                       "JOIN ddmrp.perfil p ON p.perfil_id = u.perfil_id WHERE u.usuario_id = :u"), {"u": uid}).mappings().first()
    if not u or not u["activo"]:
        return
    if "admin" in (u["permisos"] or []):
        c.execute(text("INSERT INTO ddmrp.rbac_asignacion (usuario_id, bodega_id, categoria, nivel, es_admin) "
                       "VALUES (:u, '*', '*', 'aprobacion', true)"), {"u": uid})
        return
    c.execute(text("INSERT INTO ddmrp.rbac_asignacion (usuario_id, bodega_id, categoria, nivel, es_admin) "
                   "SELECT :u, b, k, CAST(:n AS ddmrp.nivel_permiso), false "
                   "FROM unnest(CAST(:b AS text[])) b, unnest(CAST(:k AS text[])) k"),
              {"u": uid, "n": u["nivel"], "b": u["bodegas"] or ["*"], "k": u["categorias"] or ["*"]})


@router.get("/catalogo")
def catalogo():
    return {"permisos": [{"clave": k, "label": l, "grupo": g} for k, l, g in PERMISOS], "niveles": list(NIVELES)}


@router.get("/opciones")
def opciones():
    """Tiendas y laboratorios para elegir el alcance."""
    with pg.connect() as c:
        t = c.execute(text("SELECT DISTINCT ON (bodega_id) bodega_id, coalesce(descripcion, '') FROM ddmrp.maestro_bodega ORDER BY 1")).all()
        if not t:
            t = c.execute(text("SELECT DISTINCT bodega_id, '' FROM ddmrp.abast_bitacora ORDER BY 1")).all()
        lb = c.execute(text("SELECT codigo, coalesce(nombre, '') FROM ddmrp.laboratorio ORDER BY 1")).all()
    return {"tiendas": [{"id": a, "nombre": b} for a, b in t], "laboratorios": [{"id": a, "nombre": b} for a, b in lb]}


@router.get("/reloj")
def buscar_reloj(q: str = ""):
    """Busca usuarios en reloj (codigo o nombre) para no escribirlos a mano. Si reloj no responde, devuelve vacio."""
    q = q.strip()
    if len(q) < 2:
        return {"usuarios": [], "disponible": True}
    try:
        with mysql_engine().connect() as c:
            r = c.execute(text(settings.auth_buscar_query), {"q": f"%{q}%"}).mappings().all()
        return {"usuarios": [{"id": str(x["id"]), "nombre": x["nombre"]} for x in r], "disponible": True}
    except Exception:
        return {"usuarios": [], "disponible": False}


# ---------- perfiles ----------
@router.get("/perfiles")
def perfiles():
    with pg.connect() as c:
        r = c.execute(text("SELECT p.perfil_id, p.nombre, p.descripcion, p.nivel, p.permisos, p.sistema, "
                           "(SELECT count(*) FROM ddmrp.usuario u WHERE u.perfil_id = p.perfil_id) AS usuarios "
                           "FROM ddmrp.perfil p ORDER BY p.sistema DESC, p.nombre")).mappings().all()
    return [dict(x) for x in r]


class PerfilIn(BaseModel):
    nombre: str
    descripcion: str = ""
    nivel: str = "lectura"
    permisos: list[str] = []


@router.put("/perfiles/{perfil_id}")
def guardar_perfil(perfil_id: str, b: PerfilIn, user=Depends(usuario_actual)):
    if not re.fullmatch(r"[a-z0-9_]{2,40}", perfil_id):
        raise HTTPException(400, "El id del perfil va en minusculas, numeros o _ (2 a 40 caracteres)")
    if not b.nombre.strip():
        raise HTTPException(400, "El perfil necesita un nombre")
    if b.nivel not in NIVELES:
        raise HTTPException(400, "Nivel invalido")
    malos = [p for p in b.permisos if p not in CLAVES_PERMISO and p != "admin"]
    if malos:
        raise HTTPException(400, f"Permisos desconocidos: {malos}")
    perm = sorted(set(b.permisos))
    with pg.begin() as c:
        ant = c.execute(text("SELECT nivel || ' ' || array_to_string(permisos, ',') FROM ddmrp.perfil WHERE perfil_id = :p"),
                        {"p": perfil_id}).scalar()
        if perfil_id == "administrador" and "admin" not in perm:
            raise HTTPException(400, "El perfil Administrador siempre tiene todo")
        # que el propio usuario no se quite el acceso a esta pantalla
        mi = c.execute(text("SELECT perfil_id FROM ddmrp.usuario WHERE usuario_id = :u"), {"u": user["id"]}).scalar()
        if mi == perfil_id and not _bootstrap(user["id"]) and "admin" not in perm and "admin_usuarios" not in perm:
            raise HTTPException(400, "No puedes quitarle 'Administrar usuarios' al perfil con el que estas entrando")
        c.execute(text("INSERT INTO ddmrp.perfil (perfil_id, nombre, descripcion, nivel, permisos) VALUES (:i, :n, :d, :v, :p) "
                       "ON CONFLICT (perfil_id) DO UPDATE SET nombre = EXCLUDED.nombre, descripcion = EXCLUDED.descripcion, "
                       "nivel = EXCLUDED.nivel, permisos = EXCLUDED.permisos"),
                  {"i": perfil_id, "n": b.nombre.strip(), "d": b.descripcion.strip(), "v": b.nivel, "p": perm})
        for (u,) in c.execute(text("SELECT usuario_id FROM ddmrp.usuario WHERE perfil_id = :p"), {"p": perfil_id}).all():
            sincronizar_rbac(c, u)
        _audit(c, user, perfil_id, "perfil", ant, f"{b.nivel} {','.join(perm)}")
    return {"ok": True}


@router.delete("/perfiles/{perfil_id}")
def borrar_perfil(perfil_id: str, user=Depends(usuario_actual)):
    with pg.begin() as c:
        p = c.execute(text("SELECT sistema FROM ddmrp.perfil WHERE perfil_id = :p"), {"p": perfil_id}).first()
        if not p:
            raise HTTPException(404, "No existe")
        if p[0]:
            raise HTTPException(400, "Los perfiles base no se borran (puedes editar sus permisos)")
        n = c.execute(text("SELECT count(*) FROM ddmrp.usuario WHERE perfil_id = :p"), {"p": perfil_id}).scalar()
        if n:
            raise HTTPException(400, f"Hay {n} usuario(s) con este perfil; cambialos de perfil primero")
        c.execute(text("DELETE FROM ddmrp.perfil WHERE perfil_id = :p"), {"p": perfil_id})
        _audit(c, user, perfil_id, "perfil", "existia", None)
    return {"ok": True}


# ---------- usuarios ----------
@router.get("")
def usuarios():
    with pg.connect() as c:
        r = c.execute(text("SELECT u.usuario_id, u.nombre, u.perfil_id, p.nombre AS perfil, u.activo, u.bodegas, u.categorias "
                           "FROM ddmrp.usuario u LEFT JOIN ddmrp.perfil p ON p.perfil_id = u.perfil_id ORDER BY u.activo DESC, u.usuario_id")).mappings().all()
    return [{**dict(x), "bootstrap": _bootstrap(x["usuario_id"])} for x in r]


class UsuarioIn(BaseModel):
    nombre: str = ""
    perfil_id: str
    activo: bool = True
    bodegas: list[str] = []      # vacio = todas las tiendas
    categorias: list[str] = []   # vacio = todos los laboratorios


@router.put("/{usuario_id}")
def guardar_usuario(usuario_id: str, b: UsuarioIn, user=Depends(usuario_actual)):
    usuario_id = usuario_id.strip()
    if not usuario_id:
        raise HTTPException(400, "Falta el codigo del usuario (el mismo con el que entra en reloj)")
    bodegas = [x for x in dict.fromkeys(b.bodegas) if x and x != "*"]
    cats = [x for x in dict.fromkeys(b.categorias) if x and x != "*"]
    with pg.begin() as c:
        p = c.execute(text("SELECT permisos FROM ddmrp.perfil WHERE perfil_id = :p"), {"p": b.perfil_id}).first()
        if not p:
            raise HTTPException(400, "Perfil inexistente")
        if usuario_id == user["id"] and not _bootstrap(user["id"]):
            if not b.activo or not ({"admin", "admin_usuarios"} & set(p[0])):
                raise HTTPException(400, "No puedes desactivarte ni quitarte el acceso a Usuarios tu mismo")
        ant = c.execute(text("SELECT perfil_id || ' ' || activo FROM ddmrp.usuario WHERE usuario_id = :u"), {"u": usuario_id}).scalar()
        c.execute(text("INSERT INTO ddmrp.usuario (usuario_id, nombre, perfil_id, activo, bodegas, categorias, actualizado) "
                       "VALUES (:u, :n, :p, :a, :b, :k, now()) ON CONFLICT (usuario_id) DO UPDATE SET nombre = EXCLUDED.nombre, "
                       "perfil_id = EXCLUDED.perfil_id, activo = EXCLUDED.activo, bodegas = EXCLUDED.bodegas, "
                       "categorias = EXCLUDED.categorias, actualizado = now()"),
                  {"u": usuario_id, "n": b.nombre.strip() or usuario_id, "p": b.perfil_id, "a": b.activo, "b": bodegas, "k": cats})
        sincronizar_rbac(c, usuario_id)
        _audit(c, user, usuario_id, "usuario", ant, f"{b.perfil_id} {b.activo} t={len(bodegas) or 'todas'} l={len(cats) or 'todos'}")
    return {"ok": True}


@router.delete("/{usuario_id}")
def borrar_usuario(usuario_id: str, user=Depends(usuario_actual)):
    if usuario_id == user["id"]:
        raise HTTPException(400, "No puedes borrarte a ti mismo")
    with pg.begin() as c:
        c.execute(text("DELETE FROM ddmrp.rbac_asignacion WHERE usuario_id = :u"), {"u": usuario_id})
        n = c.execute(text("DELETE FROM ddmrp.usuario WHERE usuario_id = :u"), {"u": usuario_id}).rowcount
        if n:
            _audit(c, user, usuario_id, "usuario", "existia", None)
    return {"ok": True, "eliminado": bool(n)}
