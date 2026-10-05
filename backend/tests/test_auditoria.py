"""Audit log: cadena de hashes (AT-3), seudónimos (AL-P3) y escaneo de PII (AL-P7)."""

import uuid

from sqlmodel import select

import gold_prueba as g
from conftest import abrir_sesion_cliente
from models.auditoria import EventoAuditoria
from services import auditoria


def test_cadena_de_hashes_verifica_y_detecta_una_edicion(http, bd, jurado):
    """POL-AUD-02, AT-3: los eventos de una conversación forman una cadena verificable; editar uno la rompe."""
    _, sesion_id = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado)

    evento = next(e for e in bd.exec(select(EventoAuditoria)).all() if e.cuerpo.get("session_id") == sesion_id)
    conversacion = evento.conversation_id
    assert auditoria.verificar_cadena(bd, conversacion)

    editado = dict(evento.cuerpo)
    editado["auth_level"] = "L2"
    evento.cuerpo = editado
    bd.add(evento)
    bd.commit()
    assert not auditoria.verificar_cadena(bd, conversacion)


def test_escaneo_pii_bloquea_ids_crudos_numeros_y_codigos(bd):
    """POL-PII-05, POL-PII-02, AL-P2, AL-P7: un id crudo de cliente, un número de tarjeta, un correo o un
    campo prohibido se reemplazan por [BLOCKED_PII] y se emite un evento security."""
    evento = auditoria.registrar_evento(
        bd, event_type= "message_received", conversation_id= "conv_prueba", session_id= None, actor= "orchestrator",
        auth_level= "L1", state= "IDLE", rule_ids= ["POL-PII-01"],
        campos= {"text_redacted": f"mi cliente es {g.CLIENTE_FX}", "otro": "4000000000009205", "correo": "a@b.example",
                 "codigo": "123456", "card_ref": "1234567890123456789012345678abcd"},
    )
    bd.commit()

    cuerpo = evento.cuerpo
    assert cuerpo["text_redacted"] == cuerpo["otro"] == cuerpo["correo"] == cuerpo["codigo"] == "[BLOCKED_PII]"
    assert cuerpo["card_ref"] == "1234567890123456789012345678abcd" # Un hash hex no es un número de tarjeta.
    assert cuerpo["pii_scan"]["blocked"] is True
    seguridad = bd.exec(select(EventoAuditoria).where(EventoAuditoria.event_type == "security")).all()
    assert [e.cuerpo["security_event"] for e in seguridad] == ["pii_blocked"]
    assert auditoria.verificar_cadena(bd, "conv_prueba")


def test_ids_de_evento_uuid7_ordenados():
    """AL-P3 / sección 1 del contrato: event_id es UUIDv7 y los ids sucesivos se ordenan por tiempo."""
    ids = [auditoria.uuid7() for _ in range(50)]

    assert all(uuid.UUID(i).version == 7 for i in ids)
    assert [i[:13] for i in ids] == sorted(i[:13] for i in ids)
