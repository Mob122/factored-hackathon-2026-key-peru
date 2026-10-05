"""Tabla del audit log (docs/contracts/audit_log.md, sección 1). Solo se agregan filas: la aplicación
no tiene ruta para editar ni borrar eventos."""

from datetime import datetime
from sqlalchemy import JSON, Column
from sqlmodel import SQLModel, Field
from typing import Any, Dict, Optional


class EventoAuditoria(SQLModel, table= True):
    __tablename__ = "audit_events" # Nombre fijado por el contrato.

    id: Optional[int] = Field(default= None, primary_key= True)
    event_id: str = Field(max_length= 36, unique= True, index= True) # UUIDv7
    conversation_id: str = Field(max_length= 64, index= True)
    event_type: str = Field(max_length= 30)
    occurred_at: datetime
    event_hash: str = Field(max_length= 64)
    cuerpo: Dict[str, Any] = Field(sa_column= Column(JSON, nullable= False)) # El evento completo sin event_hash (incluye prev_event_hash).
