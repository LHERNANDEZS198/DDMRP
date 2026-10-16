from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from ..auth.mysql_auth import autenticar
from ..security import crear_token, usuario_actual, asignaciones

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    u = autenticar(form.username, form.password)
    if not u:
        raise HTTPException(401, "Credenciales invalidas")
    return {"access_token": crear_token(u), "token_type": "bearer", "usuario": u["nombre"]}


@router.get("/me")
def me(user=Depends(usuario_actual)):
    return {**user, "permisos": asignaciones(user["id"])}
