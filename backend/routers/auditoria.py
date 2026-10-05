"""Lectura del audit log por sesión (roles agente y jurado). Los eventos ya están seudonimizados y
redactados (docs/contracts/audit_log.md sección 2); las explicaciones se reconstruyen desde aquí,
nunca desde el razonamiento de un modelo (POL-AUD-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import select

from db import SesionDependencia
from models.auditoria import EventoAuditoria
from models.identidad import SesionIdentidad
from schemas.chat import EventosAuditoria, EventosConversacion
from security.dependencias import requiere_rol
from services import auditoria

router = APIRouter(prefix= "/auditoria", tags= ["Audit log (agente, jurado)"])
LectorDependencia = Annotated[SesionIdentidad, Depends(requiere_rol("agente", "jurado"))]


@router.get("/{session_id}", response_model= EventosAuditoria)
async def eventos_de_sesion(sesion: SesionDependencia, lector: LectorDependencia, session_id: str,
                            limite: int = Query(500, ge= 1, le= 2000)):
    eventos = sesion.exec(
        select(EventoAuditoria).where(EventoAuditoria.session_id == session_id).order_by(EventoAuditoria.id).limit(limite)
    ).all()
    return EventosAuditoria(session_id= session_id, total= len(eventos),
                            eventos= [{**e.cuerpo, "event_hash": e.event_hash} for e in eventos])


@router.get("/conversacion/{conversation_id}", response_model= EventosConversacion)
async def eventos_de_conversacion(sesion: SesionDependencia, lector: LectorDependencia, conversation_id: str,
                                  limite: int = Query(500, ge= 1, le= 2000)):
    """La cadena de una conversación (todas sus sesiones, también tras reanudar), que es la que cita el expediente
    en conversation_ref y en evidence.tool_calls[].result_ref. Dice si la cadena de hashes verifica (AT-3)."""
    eventos = sesion.exec(
        select(EventoAuditoria).where(EventoAuditoria.conversation_id == conversation_id).order_by(EventoAuditoria.id).limit(limite)
    ).all()
    return EventosConversacion(conversation_id= conversation_id, total= len(eventos),
                               cadena_valida= auditoria.verificar_cadena(sesion, conversation_id),
                               eventos= [{**e.cuerpo, "event_hash": e.event_hash} for e in eventos])
