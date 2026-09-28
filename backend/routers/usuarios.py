from typing import Annotated

from db import SesionDependencia
from schemas.usuarios import CrearUsuario, IniciarSesionUsuario, LecturaUsuario
from security import esquema_oauth2
from services.usuarios import iniciar_sesion_usuario, registrar_usuario, get_actual_usuario
from fastapi import APIRouter, Depends, HTTPException

router = APIRouter(prefix= "/autenticacion", tags= ["Autenticación"])

from fastapi.security import OAuth2PasswordBearer

@router.post("/registrar", status_code= 201, response_model= LecturaUsuario)
async def registrar(sesion: SesionDependencia, usuario: CrearUsuario):
    db_usuario = await registrar_usuario(sesion= sesion, usuario= usuario)

    if not db_usuario:
        raise HTTPException(status_code= 400, detail= "El correo ya está registrado.")
    
    return db_usuario

@router.post("/iniciar-sesion")
async def iniciar_sesion_por_token_acceso(sesion: SesionDependencia, credenciales: IniciarSesionUsuario):
    token_acceso = await iniciar_sesion_usuario(sesion= sesion, credenciales= credenciales)

    if token_acceso is None:
        raise HTTPException(
            status_code= 401,
            detail= "Email o contraseña incorrectos.",
            headers= {"WWW-Authenticate": "Bearer"},
        )

    return token_acceso

@router.get("/mi-perfil", response_model= LecturaUsuario)
async def get_mi_perfil(sesion: SesionDependencia, token: Annotated[str, Depends(esquema_oauth2)]):
    actual_usuario = await get_actual_usuario(sesion= sesion, token= token)
    return actual_usuario