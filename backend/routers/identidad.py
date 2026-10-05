"""IdP de prueba (identidad SIMULADA). Solo el rol jurado. No es un proveedor de identidad real:
sirve para la demo y la evaluación (POL-AUTH-11, POL-AUTH-13). No hay endpoints de exportación masiva."""

from typing import Optional

from fastapi import APIRouter, Query

from db import SesionDependencia
from schemas.identidad import (
    ClienteEncontrado,
    CrearOTPPrueba,
    CrearSesionPrueba,
    PaginaClientes,
    RespuestaOTPPrueba,
    RespuestaSesionPrueba,
)
from security.config import BUSQUEDA_MAX_RESULTADOS
from security.dependencias import JuradoDependencia, a_http
from services import banco, identidad
from services.identidad import AVISO_IDP, ErrorSesion

router = APIRouter(prefix= "/identidad", tags= ["IdP de prueba (simulado, solo jurado)"])


def _estado_en_gold(customer_id: str) -> Optional[str]:
    try:
        return banco.estado_cliente(customer_id)
    except banco.ErrorHerramienta:
        raise a_http(ErrorSesion("GOLD_UNAVAILABLE", "Los datos del banco no están disponibles."))


@router.get("/clientes", response_model= PaginaClientes)
async def buscar_clientes(
    jurado: JuradoDependencia,
    q: Optional[str] = Query(None, max_length= 16, description= "Prefijo del customer_id"),
    pais: Optional[str] = Query(None, max_length= 20),
    segmento: Optional[str] = Query(None, max_length= 20),
    estado_cliente: Optional[str] = Query(None, max_length= 20),
    pagina: int = Query(1, ge= 1),
    tamano: int = Query(BUSQUEDA_MAX_RESULTADOS, ge= 1, le= BUSQUEDA_MAX_RESULTADOS),
):
    if not identidad.limitador_busqueda.permitir(str(jurado.usuario_id)):
        raise a_http(ErrorSesion("RATE_LIMITED", "Demasiadas búsquedas. Espere un minuto."))

    try:
        filas, hay_mas = banco.buscar_clientes(
            q= q, pais= pais, segmento= segmento, estado= estado_cliente, pagina= pagina, tamano= tamano
        )
    except banco.ErrorHerramienta:
        raise a_http(ErrorSesion("GOLD_UNAVAILABLE", "Los datos del banco no están disponibles."))

    return PaginaClientes(
        pagina= pagina,
        tamano= tamano,
        hay_mas= hay_mas,
        resultados= [ClienteEncontrado(**fila) for fila in filas],
        aviso= AVISO_IDP,
    )


@router.post("/sesion-prueba", status_code= 201, response_model= RespuestaSesionPrueba)
async def crear_sesion_prueba(sesion: SesionDependencia, jurado: JuradoDependencia, solicitud: CrearSesionPrueba):
    customer_status = _estado_en_gold(solicitud.customer_id)

    if customer_status is None:
        raise a_http(ErrorSesion("CUSTOMER_NOT_FOUND", "Cliente no encontrado."))

    registro, token = identidad.abrir_sesion_prueba(
        sesion, jurado, solicitud.customer_id, customer_status, solicitud.idioma.value if solicitud.idioma else None
    )

    return RespuestaSesionPrueba(
        token= token,
        sesion_id= registro.id,
        customer_id= registro.customer_id,
        customer_status= customer_status,
        nivel= "L1",
        idioma= registro.idioma,
        expira_inactividad_en= identidad.expira_inactividad_en(registro),
        expira_absoluta_en= registro.expira_absoluta_en,
        aviso= AVISO_IDP,
    )


@router.post("/otp-prueba", status_code= 201, response_model= RespuestaOTPPrueba)
async def crear_otp_prueba(sesion: SesionDependencia, jurado: JuradoDependencia, solicitud: CrearOTPPrueba):
    try:
        codigo, registro = identidad.emitir_otp_prueba(sesion, jurado, solicitud.sesion_id)
    except ErrorSesion as error:
        raise a_http(error)

    return RespuestaOTPPrueba(sesion_id= registro.sesion_id, codigo= codigo, expira_en= registro.expira_en, aviso= AVISO_IDP)
