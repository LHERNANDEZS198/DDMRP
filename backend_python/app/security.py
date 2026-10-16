from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy import text
from .config import settings
from .db import pg

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
NIVELES = {"lectura": 1, "edicion": 2, "aprobacion": 3}


def crear_token(user: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    return jwt.encode({"sub": user["id"], "nombre": user["nombre"], "exp": exp}, settings.jwt_secret, "HS256")


def usuario_actual(token: str = Depends(oauth2)) -> dict:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return {"id": p["sub"], "nombre": p["nombre"]}
    except JWTError:
        raise HTTPException(401, "Token invalido")


# Funciones que se pueden dar a un perfil (clave, etiqueta, grupo). 'admin' = todo.
PERMISOS = [
    ("ver_control", "Ver Control DDMRP (foto, cambios, tendencia)", "Consultar"),
    ("ver_alertas", "Ver alertas de zona roja", "Consultar"),
    ("ver_auditoria", "Auditar el cálculo y descargarlo a Excel con fórmulas", "Consultar"),
    ("ver_despacho", "Ver la matriz de despacho", "Despacho"),
    ("aprobar_despacho", "Aprobar / ajustar cantidades a despachar", "Despacho"),
    ("descargar_planos", "Descargar planos de Siesa", "Despacho"),
    ("ver_maestros", "Ver y descargar los maestros", "Configurar"),
    ("cargar_maestros", "Cargar / editar / eliminar en los maestros", "Configurar"),
    ("editar_reglas", "Cambiar las reglas de pedido", "Configurar"),
    ("correr_motor", "Correr motor, ETL y pipeline completo", "Operar"),
    ("sincronizar_siesa", "Traer tiendas e items desde Siesa", "Operar"),
    ("admin_usuarios", "Administrar usuarios y perfiles", "Administrar"),
    ("ver_log", "Ver el log de operaciones (motor, ETL, cargas, planos)", "Administrar"),
]
CLAVES_PERMISO = [p[0] for p in PERMISOS]


def _bootstrap(usuario_id: str) -> bool:
    return usuario_id in {x.strip() for x in settings.admin_bootstrap.split(",") if x.strip()}


def permisos(usuario_id: str) -> set[str]:
    """Funciones habilitadas para el usuario segun su perfil. Admin (o ADMIN_BOOTSTRAP) = todas."""
    if _bootstrap(usuario_id):
        return set(CLAVES_PERMISO)
    with pg.connect() as c:
        r = c.execute(text("SELECT p.permisos FROM ddmrp.usuario u JOIN ddmrp.perfil p ON p.perfil_id = u.perfil_id "
                           "WHERE u.usuario_id = :u AND u.activo"), {"u": usuario_id}).scalar()
    p = set(r or [])
    return set(CLAVES_PERMISO) if "admin" in p else p


def requiere(*claves: str):
    """Dependencia de FastAPI: deja pasar si el usuario tiene alguna de las funciones."""
    def dep(user: dict = Depends(usuario_actual)) -> dict:
        if not permisos(user["id"]).intersection(claves):
            nombres = " o ".join(dict((k, l) for k, l, _ in PERMISOS)[k] for k in claves)
            raise HTTPException(403, f"Tu perfil no tiene permiso para: {nombres}")
        return user
    return dep


def asignaciones(usuario_id: str) -> list[dict]:
    if _bootstrap(usuario_id):
        return [{"bodega_id": "*", "categoria": "*", "nivel": "aprobacion", "es_admin": True}]
    with pg.connect() as c:
        r = c.execute(text("SELECT bodega_id, categoria, nivel::text AS nivel, es_admin FROM ddmrp.rbac_asignacion "
                           "WHERE usuario_id = :u"), {"u": usuario_id})
        return [dict(x) for x in r.mappings()]


def nivel_efectivo(asigs: list[dict], bodega: str, categoria: str | None) -> int:
    """Maximo nivel entre las asignaciones que aplican a (bodega, categoria)."""
    best = 0
    for a in asigs:
        if a["es_admin"]:
            return 3
        if a["bodega_id"] in ("*", bodega) and a["categoria"] in ("*", categoria):
            best = max(best, NIVELES[a["nivel"]])
    return best


def exigir(user: dict, bodega: str, categoria: str | None, minimo: str):
    if nivel_efectivo(asignaciones(user["id"]), bodega, categoria) < NIVELES[minimo]:
        raise HTTPException(403, f"Requiere permiso de {minimo} en bodega {bodega}")


def filtro_sql_permisos(user: dict, alias_bodega="s.bodega_id", alias_cat="mi.categoria"):
    """Fragmento WHERE + params que limita filas a lo que el usuario puede al menos leer."""
    asigs = asignaciones(user["id"])
    if any(a["es_admin"] for a in asigs):
        return "TRUE", {}
    if not asigs:
        return "FALSE", {}
    partes, params = [], {}
    for i, a in enumerate(asigs):
        p = []
        if a["bodega_id"] != "*":
            params[f"b{i}"] = a["bodega_id"]; p.append(f"{alias_bodega} = :b{i}")
        if a["categoria"] != "*":
            params[f"c{i}"] = a["categoria"]; p.append(f"{alias_cat} = :c{i}")
        partes.append("(" + (" AND ".join(p) or "TRUE") + ")")
    return "(" + " OR ".join(partes) + ")", params
