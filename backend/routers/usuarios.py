from typing import Annotated

from db import SesionDependencia
from schemas.identidad import LecturaSesion, RespuestaOTPDemo, RespuestaStepUp, SolicitudStepUp
from schemas.usuarios import CrearUsuario, IniciarSesionUsuario, LecturaUsuario
from security import esquema_oauth2
from security.dependencias import SesionActualDependencia, a_http
from services import identidad
from services.identidad import AVISO_SMS_SIMULADO, ErrorSesion
from services.usuarios import iniciar_sesion_usuario, registrar_usuario, get_actual_usuario
from fastapi import APIRouter, Depends, HTTPException

import os

router = APIRouter(prefix= "/autenticacion", tags= ["Autenticación"])

@router.post("/registrar", status_code= 201, response_model= LecturaUsuario)
async def registrar(sesion: SesionDependencia, usuario: CrearUsuario):
    # Registro abierto solo con ENV=development explícito; si ENV falta, queda cerrado (POL-AUTH-10).
    if os.getenv("ENV") != "development":
        raise HTTPException(status_code= 403, detail= "El registro abierto está deshabilitado en este entorno.")

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

@router.get("/mi-sesion", response_model= LecturaSesion)
async def get_mi_sesion(sesion: SesionDependencia, registro: SesionActualDependencia):
    return LecturaSesion(
        sesion_id= registro.id,
        rol= registro.rol,
        nivel= identidad.nivel_actual(sesion, registro),
        metodo= registro.metodo,
        customer_id= registro.customer_id,
        idioma= registro.idioma,
        expira_inactividad_en= identidad.expira_inactividad_en(registro),
        expira_absoluta_en= registro.expira_absoluta_en,
    )

@router.post("/step-up", status_code= 201, response_model= RespuestaStepUp)
async def step_up(sesion: SesionDependencia, registro: SesionActualDependencia, solicitud: SolicitudStepUp):
    # L2 por STEP_UP_TTL_MIN, ligado a una tarjeta y una acción, de un solo uso (POL-AUTH-04).
    try:
        paso = identidad.realizar_step_up(sesion, registro, solicitud.codigo, solicitud.card_id, solicitud.accion)
    except ErrorSesion as error:
        raise a_http(error)

    return RespuestaStepUp(
        nivel= "L2",
        step_up_id= paso.id,
        card_id_vinculada= paso.card_id,
        accion= paso.accion,
        expira_en= paso.expira_en,
    )

@router.post("/otp-demo", status_code= 201, response_model= RespuestaOTPDemo)
async def otp_demo(sesion: SesionDependencia, registro: SesionActualDependencia):
    # SMS simulado (POL-AUTH-14): solo con ENV=development y mientras la conversación de la sesión está en STEP_UP.
    try:
        codigo, emitido = identidad.emitir_otp_demo(sesion, registro)
    except ErrorSesion as error:
        raise a_http(error)

    return RespuestaOTPDemo(codigo= codigo, expira_en= emitido.expira_en, aviso= AVISO_SMS_SIMULADO)

@router.post("/cerrar-sesion", status_code= 204)
async def cerrar_sesion(sesion: SesionDependencia, registro: SesionActualDependencia):
    identidad.cerrar_sesion(sesion, registro)
