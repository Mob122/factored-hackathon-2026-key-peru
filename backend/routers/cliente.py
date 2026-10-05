"""Portal del cliente: sus tarjetas, transacciones, conversaciones y casos, solo lectura (POL-PII-10).
Solo sesiones de cliente con customer_id; los demás roles reciben NOT_A_CUSTOMER_SESSION."""

from typing import List

from fastapi import APIRouter, Query

from db import SesionDependencia
from schemas.cliente import CasoCliente, ConversacionCliente, TarjetaCliente, TransaccionesCliente
from security.dependencias import ClienteDependencia, a_http
from services import portal
from services.banco import TX_DIAS_DEFECTO, TX_DIAS_MAX, ErrorHerramienta
from services.identidad import ErrorSesion

router = APIRouter(prefix= "/cliente", tags= ["Portal del cliente"])


def _http(error: ErrorHerramienta):
    return a_http(ErrorSesion(error.codigo, error.mensaje))


@router.get("/tarjetas", response_model= List[TarjetaCliente])
async def mis_tarjetas(sesion: SesionDependencia, cliente: ClienteDependencia):
    try:
        return portal.tarjetas(sesion, cliente)
    except ErrorHerramienta as error:
        raise _http(error)


@router.get("/transacciones", response_model= TransaccionesCliente)
async def mis_transacciones(sesion: SesionDependencia, cliente: ClienteDependencia,
                            dias: int = Query(TX_DIAS_DEFECTO, ge= 1, le= TX_DIAS_MAX)):
    try:
        return portal.transacciones(sesion, cliente, dias)
    except ErrorHerramienta as error:
        raise _http(error)


@router.get("/conversaciones", response_model= List[ConversacionCliente])
async def mis_conversaciones(sesion: SesionDependencia, cliente: ClienteDependencia):
    return portal.conversaciones(sesion, cliente)


@router.get("/casos", response_model= List[CasoCliente])
async def mis_casos(sesion: SesionDependencia, cliente: ClienteDependencia):
    return portal.casos(sesion, cliente)
