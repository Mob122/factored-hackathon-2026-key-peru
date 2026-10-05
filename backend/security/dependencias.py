"""Dependencias de FastAPI para la sesión actual y los roles (POL-AUTH-10 a 12, POL-PII-07)."""

from typing import Annotated, Callable

from fastapi import Depends, HTTPException

from db import SesionDependencia
from models.identidad import SesionIdentidad
from security.config import esquema_oauth2
from services import identidad
from services.identidad import ErrorSesion, SesionCliente

ESTADOS_HTTP = {
    "TOKEN_INVALID": 401,
    "SESSION_EXPIRED": 401,
    "SESSION_INVALID": 401,
    "STEP_UP_FAILED": 400,
    "ACTION_INVALID": 400,
    "NOT_A_CUSTOMER_SESSION": 403,
    "CUSTOMER_STATUS_REVIEW": 403,
    "STEP_UP_LOCKED": 403,
    "ROLE_FORBIDDEN": 403,
    "DEMO_OTP_DISABLED": 403,
    "SESSION_NOT_FOUND": 404,
    "CUSTOMER_NOT_FOUND": 404,
    "NOT_FOUND": 404,
    "NOT_IN_STEP_UP": 409,
    "RATE_LIMITED": 429,
    "GOLD_UNAVAILABLE": 503,
}


def a_http(error: ErrorSesion) -> HTTPException:
    estado = ESTADOS_HTTP.get(error.codigo, 400)
    cabeceras = {"WWW-Authenticate": "Bearer"} if estado == 401 else None
    return HTTPException(status_code= estado, detail= {"codigo": error.codigo, "mensaje": error.mensaje}, headers= cabeceras)


def get_sesion_actual(sesion: SesionDependencia, token: Annotated[str, Depends(esquema_oauth2)]) -> SesionIdentidad:
    try:
        return identidad.sesion_desde_token(sesion, token)
    except ErrorSesion as error:
        raise a_http(error)


SesionActualDependencia = Annotated[SesionIdentidad, Depends(get_sesion_actual)]


def requiere_rol(*roles: str) -> Callable[..., SesionIdentidad]:
    def dependencia(registro: SesionActualDependencia) -> SesionIdentidad:
        if registro.rol not in roles:
            raise a_http(ErrorSesion("ROLE_FORBIDDEN", "Su rol no permite esta operación."))
        return registro

    return dependencia


JuradoDependencia = Annotated[SesionIdentidad, Depends(requiere_rol("jurado"))]


def get_sesion_cliente(registro: SesionActualDependencia) -> SesionCliente:
    """Solo una sesión de cliente con customer_id; las tools toman el cliente de aquí (POL-AUTH-12)."""
    try:
        return identidad.sesion_cliente_desde(registro)
    except ErrorSesion as error:
        raise a_http(error)


ClienteDependencia = Annotated[SesionCliente, Depends(get_sesion_cliente)]
