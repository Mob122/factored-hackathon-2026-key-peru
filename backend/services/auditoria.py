"""Audit log (docs/contracts/audit_log.md, audit-0.2).

Escribe eventos con el sobre común (sección 3), cadena de hashes por conversación (sección 1) y
seudónimos con clave para clientes, tarjetas y transacciones (AL-P3). Antes de guardar, un escaneo
de PII reemplaza valores prohibidos por [BLOCKED_PII] (AL-P7).

Mientras no exista el orquestador, los eventos del IdP de prueba y de las tools usan turn_index 0
y trace_id/span_id generados aquí (docs/decisions_log.md, D-21).
"""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from sqlmodel import Session, select

from models.auditoria import EventoAuditoria
from security.config import AUDIT_KEY

import hashlib
import hmac
import json
import re
import secrets
import time
import uuid

SCHEMA_VERSION = "audit-0.2"
POLICY_VERSION = "cards-synthetic-0.8"
STATE_MACHINE_VERSION = "sm-0.4"

# AL-P7: secuencias de 13 a 19 dígitos que no forman parte de un token alfanumérico (un hash hex no cuenta).
_PATRON_PAN = re.compile(r"(?<![0-9A-Za-z])\d{13,19}(?![0-9A-Za-z])")
_PATRON_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# AL-P3: los ids de cliente, tarjeta y transacción solo se guardan como seudónimos.
_PATRON_ID_CRUDO = re.compile(r"\b(?:CLI-[A-Z0-9]{12}|PRD-[A-Z0-9]{12}|TRX-[A-Z0-9]{20})\b")
# AL-P2 y POL-PII-02: campos que nunca se guardan.
_CAMPOS_PROHIBIDOS = {
    "credit_score", "estimated_monthly_income", "gender", "marital_status", "education_level",
    "occupation", "fraud_score", "is_fraud", "password", "codigo", "otp", "code",
}


# Turno en curso (trace_id, turn_index): lo fija el orquestador para que los eventos de las tools
# del mismo turno compartan trace_id (contrato sección 3).
_turno_actual: ContextVar[Optional[Dict[str, Any]]] = ContextVar("turno_auditado", default= None)


@contextmanager
def turno_auditado(trace_id: str, turn_index: int):
    marca = _turno_actual.set({"trace_id": trace_id, "turn_index": turn_index})
    try:
        yield
    finally:
        _turno_actual.reset(marca)


def iso_utc(momento: Optional[datetime]) -> Optional[str]:
    """Fecha y hora UTC en ISO 8601 con sufijo Z, para los campos de los eventos."""
    if momento is None:
        return None
    return momento.astimezone(timezone.utc).isoformat(timespec= "milliseconds").replace("+00:00", "Z")


def uuid7() -> str:
    """UUIDv7: 48 bits de milisegundos y el resto aleatorio, así los ids se ordenan por tiempo."""
    milisegundos = time.time_ns() // 1_000_000
    aleatorio = secrets.randbits(74)
    valor = (milisegundos & ((1 << 48) - 1)) << 80
    valor |= 0x7 << 76 # versión 7
    valor |= ((aleatorio >> 62) & 0xFFF) << 64
    valor |= 0b10 << 62 # variante RFC 4122
    valor |= aleatorio & ((1 << 62) - 1)
    return str(uuid.UUID(int= valor))


def seudonimo(valor: str) -> str:
    """customer_ref, card_ref o transaction_ref: HMAC-SHA256(AUDIT_KEY, valor), 32 caracteres hex (AL-P3)."""
    return hmac.new(AUDIT_KEY.encode("utf-8"), valor.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def json_canonico(objeto: Any) -> str:
    return json.dumps(objeto, sort_keys= True, separators= (",", ":"), ensure_ascii= False, default= str)


def _escanear(valor: Any, conteo: Dict[str, int]) -> Any:
    """Devuelve una copia con los valores prohibidos reemplazados; cuenta lo bloqueado en `conteo`."""
    if isinstance(valor, dict):
        limpio = {}
        for clave, contenido in valor.items():
            if clave in _CAMPOS_PROHIBIDOS:
                conteo["campo"] = conteo.get("campo", 0) + 1
                limpio[clave] = "[BLOCKED_PII]"
            else:
                limpio[clave] = _escanear(contenido, conteo)
        return limpio

    if isinstance(valor, list):
        return [_escanear(contenido, conteo) for contenido in valor]

    if isinstance(valor, str):
        for nombre, patron in (("pan", _PATRON_PAN), ("email", _PATRON_EMAIL), ("id_crudo", _PATRON_ID_CRUDO)):
            if patron.search(valor):
                conteo[nombre] = conteo.get(nombre, 0) + 1
                return "[BLOCKED_PII]"

    return valor


def ultimo_hash(sesion: Session, conversation_id: str) -> Optional[str]:
    ultimo = sesion.exec(
        select(EventoAuditoria)
        .where(EventoAuditoria.conversation_id == conversation_id)
        .order_by(EventoAuditoria.id.desc())
    ).first()

    return ultimo.event_hash if ultimo else None


def registrar_evento(
    sesion: Session,
    *,
    event_type: str,
    conversation_id: str,
    session_id: Optional[str],
    actor: str,
    auth_level: str,
    state: str,
    rule_ids: Iterable[str],
    customer_id: Optional[str] = None,
    turn_index: Optional[int] = None,
    campos: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    session_origin: Optional[Dict[str, Any]] = None,
) -> EventoAuditoria:
    """Agrega un evento a la sesión de base de datos. Quien llama hace commit junto con el cambio
    que el evento registra, así ambos se guardan o ninguno (sección 1: falla cerrado).

    `trace_id` es el del turno (todos los eventos de un turno lo comparten; se genera si falta).
    `session_origin` es la extensión aditiva que dice cómo se abrió la sesión: contraseña de un
    usuario sembrado o IdP de prueba con el id del jurado (docs/decisions_log.md, D-21 y D-27)."""
    ahora = datetime.now(timezone.utc)
    turno = _turno_actual.get() or {}
    trace_id = trace_id or turno.get("trace_id")
    turn_index = turn_index if turn_index is not None else turno.get("turn_index", 0)

    sobre = {
        "schema_version": SCHEMA_VERSION,
        "event_id": uuid7(),
        "event_type": event_type,
        "occurred_at": iso_utc(ahora),
        "conversation_id": conversation_id,
        "session_id": session_id,
        "turn_index": turn_index,
        "trace_id": trace_id or secrets.token_hex(16),
        "span_id": secrets.token_hex(8),
        "actor": actor,
        "customer_ref": seudonimo(customer_id) if customer_id else None,
        "auth_level": auth_level,
        "state": state,
        "policy_version": POLICY_VERSION,
        "state_machine_version": STATE_MACHINE_VERSION,
        "rule_ids": list(rule_ids),
    }
    if session_origin is not None:
        sobre["session_origin"] = session_origin

    conteo: Dict[str, int] = {}
    cuerpo = {**sobre, **_escanear(campos or {}, conteo)}
    cuerpo["pii_scan"] = {"blocked": bool(conteo), "placeholders": {}, "hits": conteo}
    cuerpo["prev_event_hash"] = ultimo_hash(sesion, conversation_id)

    evento = EventoAuditoria(
        event_id= sobre["event_id"],
        conversation_id= conversation_id,
        event_type= event_type,
        occurred_at= ahora,
        session_id= session_id,
        trace_id= sobre["trace_id"],
        turn_index= turn_index,
        event_hash= hashlib.sha256(json_canonico(cuerpo).encode("utf-8")).hexdigest(),
        cuerpo= cuerpo,
    )
    sesion.add(evento)
    sesion.flush() # El siguiente evento de la misma conversación ya ve este hash.

    if conteo and event_type != "security":
        registrar_evento(
            sesion,
            event_type= "security",
            conversation_id= conversation_id,
            session_id= session_id,
            actor= actor,
            auth_level= auth_level,
            state= state,
            rule_ids= ["POL-PII-05"],
            turn_index= turn_index,
            trace_id= sobre["trace_id"],
            session_origin= session_origin,
            campos= {"security_event": "pii_blocked", "subtype": None, "detector": "al-p7-scan-v1",
                     "evidence": {"blocked_event_id": sobre["event_id"], "hits": conteo}, "effect": "ignored_continue"},
        )

    return evento


def verificar_cadena(sesion: Session, conversation_id: str) -> bool:
    """AT-3: recalcula cada hash y el enlace con el evento anterior de la conversación."""
    eventos: List[EventoAuditoria] = list(sesion.exec(
        select(EventoAuditoria)
        .where(EventoAuditoria.conversation_id == conversation_id)
        .order_by(EventoAuditoria.id)
    ).all())

    anterior = None
    for evento in eventos:
        if evento.cuerpo.get("prev_event_hash") != anterior:
            return False
        if hashlib.sha256(json_canonico(evento.cuerpo).encode("utf-8")).hexdigest() != evento.event_hash:
            return False
        anterior = evento.event_hash

    return True
