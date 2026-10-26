import logging, threading, time
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWTError as JWTError
from sqlalchemy import text
from .config import settings
from .db import pg

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
NIVELES = {"lectura": 1, "edicion": 2, "aprobacion": 3}


def crear_token(user: dict, minutos: int | None = None) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=minutos or settings.jwt_expire_minutes)
    return jwt.encode({"sub": user["id"], "nombre": user["nombre"], "exp": exp}, settings.jwt_secret, algorithm="HS256")


log = logging.getLogger("sesion")
_cache_app: dict[str, tuple[float, bool]] = {}
_cache_reloj: dict[str, tuple[float, bool, float]] = {}
_lock = threading.Lock()
TTL_APP = 20          # segundos que se recuerda el estado en esta app (un cambio de perfil/baja se nota en ese tiempo; `olvidar` lo corta al instante)
TTL_RELOJ_CAIDO = 60  # si reloj no responde se reintenta cada minuto, sin sacar a nadie


def olvidar(usuario_id: str | None = None) -> None:
    """Descarta lo recordado de un usuario (o de todos): lo llama la pantalla de Usuarios al cambiarlo, para que la baja valga ya."""
    with _lock:
        for c in (_cache_app, _cache_reloj):
            c.pop(usuario_id, None) if usuario_id else c.clear()


def activo_en_app(usuario_id: str) -> bool:
    """El usuario existe en esta app y esta activo. Sin fila solo pasan los de ADMIN_BOOTSTRAP (los demas no tienen acceso a nada)."""
    ahora = time.monotonic()
    with _lock:
        v = _cache_app.get(usuario_id)
    if v and ahora - v[0] < TTL_APP:
        return v[1]
    if _bootstrap(usuario_id):
        ok = True
    else:
        with pg.connect() as c:
            r = c.execute(text("SELECT activo FROM ddmrp.usuario WHERE usuario_id = :u"), {"u": usuario_id}).scalar()
        ok = bool(r)
    with _lock:
        _cache_app[usuario_id] = (ahora, ok)
    return ok


def activo_en_reloj(usuario_id: str) -> bool:
    """Revalida contra reloj cada AUTH_REVALIDAR_MINUTOS: si lo dieron de baja alla, la sesion abierta se cierra. Si reloj no responde, deja pasar."""
    minutos = settings.auth_revalidar_minutos
    if minutos <= 0 or not settings.auth_mysql_host or usuario_id.startswith("prueba:"):
        return True
    ahora = time.monotonic()
    with _lock:
        v = _cache_reloj.get(usuario_id)          # (cuando, resultado, segundos que vale)
    if v and ahora - v[0] < v[2]:
        return v[1]
    from .auth.mysql_auth import sigue_activo
    r = sigue_activo(usuario_id)
    if r is None:       # reloj no responde: se conserva lo ultimo que se supo (o activo) y se reintenta en un minuto
        log.warning("Reloj no respondio al revalidar a %s: se deja pasar", usuario_id)
        r, vale = (v[1] if v else True), TTL_RELOJ_CAIDO
    else:
        vale = minutos * 60
        if not r:
            log.warning("Sesion cerrada: %s ya no esta activo en reloj", usuario_id)
    with _lock:
        _cache_reloj[usuario_id] = (ahora, r, vale)
    return r


def usuario_actual(token: str = Depends(oauth2)) -> dict:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        u = {"id": p["sub"], "nombre": p["nombre"]}
    except (JWTError, KeyError):
        raise HTTPException(401, "Token invalido")
    if not activo_en_app(u["id"]):
        raise HTTPException(401, "Tu usuario esta inactivo o no tiene acceso a esta aplicacion")
    if not activo_en_reloj(u["id"]):
        raise HTTPException(401, "Tu usuario ya no esta activo en reloj")
    return u


# Funciones que se pueden dar a un perfil (clave, etiqueta, grupo). 'admin' = todo.
PERMISOS = [
    ("ver_control", "Ver Control DDMRP (foto, cambios, tendencia)", "Consultar"),
    ("ver_alertas", "Ver alertas de zona roja", "Consultar"),
    ("ver_auditoria", "Auditar el cálculo y descargarlo a Excel con fórmulas", "Consultar"),
    ("ver_despacho", "Ver la matriz de despacho", "Despacho"),
    ("aprobar_despacho", "Aprobar / ajustar cantidades a despachar", "Despacho"),
    ("descargar_planos", "Descargar planos de Siesa", "Despacho"),
    ("ver_compras", "Ver los informes y maestros de compras (CEDI, proveedores, órdenes de compra)", "Compras"),
    ("cargar_maestros_compras", "Cargar / editar / eliminar en los maestros de compras", "Compras"),
    ("gestionar_compras", "Editar las cantidades a pedir, recalcular las necesidades de compra y enviar órdenes de compra", "Compras"),
    ("ver_maestros", "Ver y descargar los maestros", "Configurar"),
    ("cargar_maestros", "Cargar / editar / eliminar en los maestros", "Configurar"),
    ("editar_reglas", "Cambiar las reglas de pedido", "Configurar"),
    ("correr_motor", "Correr motor, ETL y pipeline completo", "Operar"),
    ("sincronizar_siesa", "Traer tiendas e items desde Siesa", "Operar"),
    ("admin_usuarios", "Administrar usuarios y perfiles", "Administrar"),
    ("ver_log", "Ver el log de operaciones (motor, ETL, cargas, planos)", "Administrar"),
    ("ver_diagnostico", "Diagnóstico: consultas, tiempos, consultas en curso y estado de la base", "Administrar"),
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


EMPRESAS = ("05", "21")     # Funat y Stores


def empresas_permitidas(usuario_id: str) -> list[str] | None:
    """Empresas que el usuario puede ver. None = todas (administrador, ADMIN_BOOTSTRAP o sin restriccion). Se aplica por las bodegas de cada empresa."""
    if _bootstrap(usuario_id):
        return None
    with pg.connect() as c:
        r = c.execute(text("SELECT u.empresas, p.permisos FROM ddmrp.usuario u LEFT JOIN ddmrp.perfil p ON p.perfil_id = u.perfil_id "
                           "WHERE u.usuario_id = :u"), {"u": usuario_id}).first()
    if not r or not r[0] or "admin" in (r[1] or []):
        return None
    return [e for e in r[0] if e in EMPRESAS] or None


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
    emp = empresas_permitidas(user["id"])
    extra = ""
    if emp:      # solo las tiendas de sus empresas (una tienda pertenece a la empresa en la que esta en el maestro de bodegas)
        params["emp_perm"] = emp
        extra = (f" AND ({alias_bodega} IN (SELECT bodega_id FROM ddmrp.maestro_bodega WHERE empresa = ANY(:emp_perm))"
                 f" OR {alias_bodega} IN (SELECT bodega_id FROM ddmrp.maestro_cedi WHERE empresa = ANY(:emp_perm)))")
    return "(" + " OR ".join(partes) + ")" + extra, params
