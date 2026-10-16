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


def asignaciones(usuario_id: str) -> list[dict]:
    with pg.connect() as c:
        r = c.execute(text("SELECT bodega_id, categoria, nivel, es_admin FROM ddmrp.rbac_asignacion "
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
