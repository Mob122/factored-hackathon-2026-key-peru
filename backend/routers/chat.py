"""Chat del asistente: misma ruta para usuarios sembrados y para sesiones del IdP de prueba."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from db import SesionDependencia
from schemas.chat import IniciarChat, MensajeChatEntrada, RespuestaChat
from security.config import esquema_oauth2
from security.dependencias import SesionActualDependencia, a_http
from services.agente import orquestador
from services.agente.orquestador import ErrorChat
from services.identidad import ErrorSesion

router = APIRouter(prefix= "/chat", tags= ["Chat"])


def _http(error: ErrorChat) -> HTTPException:
    cabeceras = {"WWW-Authenticate": "Bearer"} if error.estado_http == 401 else None
    return HTTPException(status_code= error.estado_http, detail= {"codigo": error.codigo, "mensaje": error.mensaje}, headers= cabeceras)


@router.post("/sesiones", status_code= 201, response_model= RespuestaChat)
async def iniciar_chat(sesion: SesionDependencia, registro: SesionActualDependencia, entrada: IniciarChat):
    """Turno 0: abre una conversación (T-01; T-51 si el cliente está Suspended o Closed), o retoma una
    cuya sesión venció, con una sesión nueva del mismo cliente (G-02)."""
    try:
        respuesta = orquestador.iniciar_conversacion(
            sesion, registro, entrada.idioma.value if entrada.idioma else None, entrada.conversation_id
        )
    except ErrorChat as error:
        raise _http(error)
    except ErrorSesion as error:
        raise a_http(error)
    return RespuestaChat(**respuesta.__dict__)


@router.post("/mensaje", response_model= RespuestaChat)
async def enviar_mensaje(sesion: SesionDependencia, token: Annotated[str, Depends(esquema_oauth2)], entrada: MensajeChatEntrada):
    """Un turno. Con la sesión vencida responde G-01 (sin datos, pide iniciar sesión de nuevo)."""
    try:
        respuesta = orquestador.procesar(
            sesion, entrada.conversation_id, token, mensaje= entrada.mensaje, codigo_step_up= entrada.codigo_step_up,
            idioma= entrada.idioma.value if entrada.idioma else None,
        )
    except ErrorChat as error:
        raise _http(error)
    return RespuestaChat(**respuesta.__dict__)
