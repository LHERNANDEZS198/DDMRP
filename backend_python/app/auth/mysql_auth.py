"""Autenticacion contra MySQL 'reloj'. El query se parametriza por .env (AUTH_USER_QUERY)
hasta conocer el esquema real. Ajustar verify_password al hash que use esa base."""
from sqlalchemy import text
from passlib.context import CryptContext
from ..config import settings
from ..db import mysql_engine

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain: str, stored: str) -> bool:
    try:
        if stored.startswith("$2"):
            return _pwd.verify(plain, stored)
    except Exception:
        return False
    return False  # TODO: soportar el formato real del hash de reloj (md5/sha/etc.)


def autenticar(usuario: str, clave: str) -> dict | None:
    with mysql_engine().connect() as c:
        row = c.execute(text(settings.auth_user_query), {"usuario": usuario}).mappings().first()
    if not row or not verify_password(clave, row["password_hash"]):
        return None
    return {"id": str(row["id"]), "nombre": row["nombre"]}
