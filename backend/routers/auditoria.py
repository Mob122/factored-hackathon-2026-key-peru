"""Lectura del audit log por sesión (roles agente y jurado). Los eventos ya están seudonimizados y
redactados (docs/contracts/audit_log.md sección 2); las explicaciones se reconstruyen desde aquí,
nunca desde el razonamiento de un modelo (POL-AUD-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlmodel import select

from db import SesionDependencia
from models.auditoria import EventoAuditoria
from models.identidad import SesionIdentidad
from schemas.chat import EventosAuditoria
from security.dependencias import requiere_rol

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
