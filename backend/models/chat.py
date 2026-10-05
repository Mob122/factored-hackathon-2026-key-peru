"""Tablas del orquestador: conversaciones y transcripción redactada (POL-PII-05)."""

from datetime import datetime
from sqlalchemy import JSON, Column, Text
from sqlmodel import SQLModel, Field
from typing import Any, Dict, Optional


class Conversacion(SQLModel, table= True):
    """Una conversación de chat. Su id es el conversation_id del audit log y sobrevive a la
    reautenticación (POL-AUTH-07); `sesion_id` es la sesión de identidad vigente."""
    __tablename__ = "conversaciones"

    id: str = Field(primary_key= True, max_length= 64)
    customer_id: str = Field(max_length= 16, index= True)
    sesion_id: str = Field(max_length= 64, index= True)
    estado: str = Field(max_length= 30) # Estados de docs/contracts/state_machine.md sección 1.
    idioma: Optional[str] = Field(default= None, max_length= 2)
    turno: int = Field(default= 0)
    case_id: Optional[str] = Field(default= None, max_length= 40)
    contexto: Dict[str, Any] = Field(sa_column= Column(JSON, nullable= False)) # state_machine.md sección 3.
    creada_en: datetime
    actualizada_en: datetime


class MensajeChat(SQLModel, table= True):
    """Transcripción: solo texto redactado (POL-PII-05). Las respuestas del asistente solo traen
    datos que el cliente de la sesión puede ver (POL-PII-03)."""
    __tablename__ = "mensajes_chat"

    id: Optional[int] = Field(default= None, primary_key= True)
    conversacion_id: str = Field(max_length= 64, index= True)
    turno: int
    rol: str = Field(max_length= 10) # "cliente" o "asistente"
    texto_redactado: str = Field(sa_column= Column(Text, nullable= False))
    creado_en: datetime
