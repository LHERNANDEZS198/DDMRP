import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from ..auth.mysql_auth import autenticar
from ..security import crear_token, usuario_actual, asignaciones, permisos

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger("auth")


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    try:
        u = autenticar(form.username, form.password)
    except Exception as e:  # reloj inalcanzable, columna inexistente, etc.: no es una clave mala
        log.exception("Fallo consultando el MySQL de reloj")
        raise HTTPException(503, f"No se pudo consultar reloj ({type(e).__name__}). Revisa AUTH_MYSQL_* y los logs del backend.")
    if not u:
        raise HTTPException(401, "Credenciales invalidas")
    return {"access_token": crear_token(u), "token_type": "bearer", "usuario": u["nombre"]}


@router.get("/me")
def me(user=Depends(usuario_actual)):
    a = asignaciones(user["id"])
    return {**user, "funciones": sorted(permisos(user["id"])), "es_admin": any(x["es_admin"] for x in a), "alcance": a}
