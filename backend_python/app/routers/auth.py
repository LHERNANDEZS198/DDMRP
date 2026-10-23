import logging
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from ..auth.mysql_auth import autenticar, sigue_activo
from ..security import crear_token, usuario_actual, asignaciones, permisos, empresas_permitidas, EMPRESAS, activo_en_app, olvidar

router = APIRouter(prefix="/auth", tags=["auth"])
from ..config import settings
log = logging.getLogger("auth")


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    try:
        u = autenticar(form.username, form.password)
    except Exception as e:  # reloj inalcanzable, columna inexistente, etc.: no es una clave mala
        log.exception("Fallo consultando el MySQL de reloj")
        raise HTTPException(503, f"No se pudo consultar reloj ({type(e).__name__}). Revisa AUTH_MYSQL_* y los logs del backend.")
    if not u or str(u["id"]).startswith("prueba:"):
        raise HTTPException(401, "Credenciales invalidas")
    olvidar(u["id"])       # al entrar se pregunta de nuevo (no se confia en lo recordado)
    if not activo_en_app(u["id"]):
        raise HTTPException(403, "Tu usuario esta inactivo o no tiene acceso a esta aplicacion: pide que te habiliten en Usuarios")
    if settings.auth_activo_query.strip() and sigue_activo(u["id"]) is False:
        raise HTTPException(403, "Tu usuario ya no esta activo en reloj")
    return {"access_token": crear_token(u), "token_type": "bearer", "usuario": u["nombre"]}


@router.get("/me")
def me(user=Depends(usuario_actual)):
    a = asignaciones(user["id"])
    return {**user, "funciones": sorted(permisos(user["id"])), "es_admin": any(x["es_admin"] for x in a), "alcance": a,
            "empresas": empresas_permitidas(user["id"]) or list(EMPRESAS)}


@router.post("/salir-prueba")
def salir_prueba(user=Depends(usuario_actual)):
    """Termina un 'Ver como perfil': borra el usuario temporal. Solo actua sobre usuarios 'prueba:*'."""
    from sqlalchemy import text
    from ..db import pg
    if not str(user["id"]).startswith("prueba:"):
        return {"ok": True, "eliminado": False}
    with pg.begin() as c:
        c.execute(text("DELETE FROM ddmrp.rbac_asignacion WHERE usuario_id = :u"), {"u": user["id"]})
        c.execute(text("DELETE FROM ddmrp.vista_guardada WHERE usuario_id = :u"), {"u": user["id"]})
        c.execute(text("DELETE FROM ddmrp.usuario WHERE usuario_id = :u"), {"u": user["id"]})
    olvidar(user["id"])
    return {"ok": True, "eliminado": True}
