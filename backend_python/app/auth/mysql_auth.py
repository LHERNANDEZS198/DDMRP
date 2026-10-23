"""Autenticacion contra MySQL de reloj (solo usuario y clave; perfiles/permisos viven en esta app).
Misma logica que admin/Log.php: USUARIOS.CODIGO + USUARIOS.CLAVE, donde CLAVE es md5 (32 hex) o hash PHP password_hash
(bcrypt $2y$). Solo lectura: no se migra ni se reescribe la clave desde aqui."""
import hashlib, hmac
from sqlalchemy import text
from passlib.hash import bcrypt
from ..config import settings
from ..db import mysql_engine


def verify_password(plain: str, stored: str) -> bool:
    stored = (stored or "").strip()
    if stored.startswith(("$2y$", "$2a$", "$2b$")):
        try:
            return bcrypt.verify(plain, stored.replace("$2y$", "$2b$", 1))
        except ValueError:
            return False
    if len(stored) == 32:
        return hmac.compare_digest(hashlib.md5(plain.encode()).hexdigest(), stored.lower())
    return False


def sigue_activo(usuario: str) -> bool | None:
    """True/False si reloj dice que el usuario sigue activo (AUTH_ACTIVO_QUERY, o que su CODIGO exista si no hay consulta). None = no se pudo preguntar."""
    q = settings.auth_activo_query.strip() or "SELECT 1 FROM USUARIOS WHERE CODIGO = :usuario"
    try:
        with mysql_engine().connect() as c:
            return c.execute(text(q), {"usuario": usuario}).first() is not None
    except Exception:       # noqa: BLE001  reloj caido: no se saca a nadie por eso
        return None


def autenticar(usuario: str, clave: str) -> dict | None:
    with mysql_engine().connect() as c:
        row = c.execute(text(settings.auth_user_query), {"usuario": usuario}).mappings().first()
    if not row or not verify_password(clave, row["password_hash"]):
        return None
    return {"id": str(row["id"]), "nombre": row["nombre"]}
