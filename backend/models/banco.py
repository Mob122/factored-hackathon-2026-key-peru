"""Tablas del banco simulado que viven en la base del backend, nunca en el Parquet de gold."""

from datetime import datetime
from sqlalchemy import JSON, Column
from pydantic import NaiveDatetime
from sqlmodel import SQLModel, Field
from typing import Any, List, Optional


class EventoEstadoTarjeta(SQLModel, table= True):
    """Overlay del banco simulado: eventos de estado escritos por block_card, solo se agregan filas
    (docs/contracts/freshness_policy.md, sección 5)."""
    __tablename__ = "eventos_estado_tarjeta"

    id: Optional[int] = Field(default= None, primary_key= True)
    card_id: str = Field(max_length= 16, index= True)
    nuevo_estado: str = Field(max_length= 20)
    hora_evento: NaiveDatetime # Reloj del banco, sin zona como los datos de gold (RELOJ_SIMULADO si está definido); define el día hábil del evento.
    registrado_en: datetime # Hora real UTC de la escritura.
    accion_id: str = Field(max_length= 40) # request_id devuelto por block_card.
    sesion_id: str = Field(max_length= 64)


class TokenConfirmacion(SQLModel, table= True):
    """Token de confirmación ligado a (sesión, tarjeta, acción), de un solo uso (POL-ACT-02, POL-ACT-06)."""
    __tablename__ = "tokens_confirmacion"

    id: str = Field(primary_key= True, max_length= 40) # Id público (confirmation_token_id); el secreto solo se guarda como hash.
    token_hash: str = Field(max_length= 64, unique= True, index= True)
    sesion_id: str = Field(max_length= 64, index= True)
    card_id: str = Field(max_length= 16)
    accion: str = Field(max_length= 20)
    creado_en: datetime
    expira_en: datetime
    usado_en: Optional[datetime] = Field(default= None)
    anulado_en: Optional[datetime] = Field(default= None)
    request_id: Optional[str] = Field(default= None, max_length= 40)


class Caso(SQLModel, table= True):
    """Expediente de transferencia a un humano. Los nombres de campo son los de la sección 8 de
    docs/policy_cards.md (POL-HND-10 a 15), porque son un contrato."""
    __tablename__ = "casos"

    case_id: str = Field(primary_key= True, max_length= 40)
    idempotency_key: str = Field(max_length= 120, unique= True, index= True) # POL-REL-02
    created_at: datetime
    policy_version: str = Field(max_length= 40)
    reason_rule_ids: List[str] = Field(sa_column= Column(JSON, nullable= False))
    language: str = Field(max_length= 2)
    customer_id: str = Field(max_length= 16, index= True) # Siempre el de la sesión.
    auth_level: str = Field(max_length= 2)
    priority: str = Field(max_length= 10)
    conversation_ref: str = Field(max_length= 64)
    appended_messages: List[Any] = Field(sa_column= Column(JSON, nullable= False))
    request: Any = Field(sa_column= Column(JSON, nullable= False))
    verified_facts: List[Any] = Field(sa_column= Column(JSON, nullable= False))
    actions_taken: List[Any] = Field(sa_column= Column(JSON, nullable= False))
    evidence: Any = Field(sa_column= Column(JSON, nullable= False))
    unresolved_questions: List[Any] = Field(sa_column= Column(JSON, nullable= False))
