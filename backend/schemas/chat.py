from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator

from schemas.usuarios import TipoIdioma


class IniciarChat(BaseModel):
    # Con conversation_id se retoma una conversación cuya sesión venció (G-02, POL-AUTH-07).
    conversation_id: Optional[str] = Field(default= None, max_length= 64)
    idioma: Optional[TipoIdioma] = None

class MensajeChatEntrada(BaseModel):
    conversation_id: str = Field(min_length= 1, max_length= 64)
    mensaje: Optional[str] = Field(default= None, min_length= 1, max_length= 2000)
    # Código de la ventana de verificación; nunca va en el texto del chat (POL-AUTH-08).
    codigo_step_up: Optional[str] = Field(default= None, pattern= r"^\d{6}$")
    idioma: Optional[TipoIdioma] = None

    @model_validator(mode= "after")
    def un_contenido(self):
        if (self.mensaje is None) == (self.codigo_step_up is None):
            raise ValueError("Envíe mensaje o codigo_step_up, uno de los dos.")
        return self

class ConfirmacionPendiente(BaseModel):
    card_last4: str
    card_type: str
    expires_at: str

class RespuestaChat(BaseModel):
    conversation_id: str
    reply: str
    state: str
    language: str
    pending_confirmation: Optional[ConfirmacionPendiente] = None
    case_id: Optional[str] = None
    turn: int

class ResumenCaso(BaseModel):
    case_id: str
    created_at: datetime
    priority: str
    reason_rule_ids: List[str]
    language: str
    customer_id: str
    auth_level: str

class LecturaCaso(ResumenCaso):
    policy_version: str
    conversation_ref: str
    appended_messages: List[Any]
    request: Any
    verified_facts: List[Any]
    actions_taken: List[Any]
    evidence: Any
    unresolved_questions: List[Any]

class EventosAuditoria(BaseModel):
    session_id: str
    total: int
    eventos: List[Dict[str, Any]]
