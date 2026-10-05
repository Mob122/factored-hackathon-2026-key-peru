"""open_handoff y el expediente de la sección 8 de la política (POL-HND-10 a 15)."""

import copy

import pytest
from sqlmodel import select

import gold_prueba as g
from conftest import abrir_sesion_cliente, sesion_cliente, subir_a_l2
from models.auditoria import EventoAuditoria
from models.banco import Caso
from services import auditoria, banco

EXPEDIENTE = {
    "request": {
        "last_message_redacted": "Quiero desbloquear mi tarjeta terminada en 9205.",
        "summary": "Customer asks to unblock card ending 9205.",
        "summary_generated_by": "model",
        "top_intent": "card_unblock",
        "conformal_set": ["card_unblock"],
    },
    "verified_facts": [{"fact": "card_status", "value": {"last4": "9205", "type": "Tarjeta Crédito", "status": "Active"}, "tool_call_id": "c2"}],
    "actions_taken": [],
    "evidence": {"tool_calls": [{"tool_call_id": "c2", "tool": "get_card_status", "called_at": "10:00:10", "status": "ok"}],
                 "cards": [{"card_id": g.TARJETA_9205, "last4": "9205"}], "transactions": [], "security_events": []},
    "unresolved_questions": ["Customer wants card 9205 unblocked; the assistant cannot unblock (POL-ACT-07)."],
    "reason_rule_ids": ["POL-ESC-03"],
    "priority": "normal",
    "language": "es",
    "appended_messages": [],
}


@pytest.fixture
def sc(http, bd, jurado):
    token, _ = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    return sesion_cliente(bd, token)


@pytest.mark.parametrize("campo", ["request", "verified_facts", "actions_taken", "evidence", "unresolved_questions"])
def test_open_handoff_exige_los_cinco_campos(bd, sc, campo):
    """POL-HND-10, POL-HND-11, POL-HND-12, POL-HND-13, POL-HND-14: un campo de contenido que falta es una
    violación del contrato, no un resultado vacío. Una lista vacía explícita sí se acepta."""
    incompleto = copy.deepcopy(EXPEDIENTE)
    del incompleto[campo]

    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.open_handoff(bd, sc, incompleto, idempotency_key= f"k-{campo}")
    assert error.value.codigo == "CASE_FILE_INVALID"
    assert bd.exec(select(Caso)).all() == []


@pytest.mark.parametrize("cambio", [
    {"unresolved_questions": []},
    {"verified_facts": [{"fact": "card_status", "value": "Active"}]}, # Sin tool_call_id (POL-HND-11).
    {"actions_taken": [{"action": "block_card", "executed": "maybe", "card_last4": "9205", "confirmation_token_id": "CT-1",
                        "requested_at": "x", "verified": False, "verification_tool_call_id": None}]},
    {"reason_rule_ids": []},
    {"reason_rule_ids": ["no es una regla"]},
    {"priority": "alta"},
    {"language": "en"},
    {"request": ""},
])
def test_open_handoff_valida_el_contenido(bd, sc, cambio):
    """POL-HND-11, POL-HND-12, POL-HND-14, POL-HND-15, POL-ACT-09: hechos con tool_call_id, executed en
    true/false/unknown, al menos una pregunta abierta, reglas citadas y prioridad e idioma válidos."""
    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.open_handoff(bd, sc, {**copy.deepcopy(EXPEDIENTE), **cambio}, idempotency_key= "k")
    assert error.value.codigo == "CASE_FILE_INVALID"


def test_open_handoff_pone_los_metadatos_desde_la_sesion(http, bd, jurado, sc):
    """POL-HND-15, POL-PII-05, POL-AUTH-05: customer_id, auth_level, conversation_ref, created_at y
    policy_version los pone el servidor desde la sesión. Un customer_id distinto en el expediente se rechaza."""
    ajeno = {**copy.deepcopy(EXPEDIENTE), "customer_id": g.OTRO_CLIENTE}
    with pytest.raises(banco.ErrorHerramienta):
        banco.open_handoff(bd, sc, ajeno, idempotency_key= "k-ajeno")

    resultado = banco.open_handoff(bd, sc, {**copy.deepcopy(EXPEDIENTE), "customer_id": g.CLIENTE_FX}, idempotency_key= "k-1")
    caso = bd.get(Caso, resultado["case_id"])
    assert (caso.customer_id, caso.auth_level, caso.policy_version, caso.conversation_ref) == (
        g.CLIENTE_FX, "L1", auditoria.POLICY_VERSION, sc.conversacion_id)
    assert caso.priority == "normal" and caso.reason_rule_ids == ["POL-ESC-03"]
    assert caso.verified_facts == EXPEDIENTE["verified_facts"]


def test_open_handoff_registra_l2_y_acciones_con_ejecucion_desconocida(http, bd, jurado):
    """POL-HND-12, POL-ACT-09, POL-HND-15: un bloqueo no verificado queda con executed unknown y prioridad urgent."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_9205)
    sc = sesion_cliente(bd, token)
    expediente = {**copy.deepcopy(EXPEDIENTE), "priority": "urgent", "reason_rule_ids": ["POL-ACT-05", "POL-ESC-07"],
                  "actions_taken": [{"action": "block_card", "card_last4": "9205", "confirmation_token_id": "CT-1",
                                     "requested_at": "2026-06-18T10:01:31", "executed": "unknown", "verified": False,
                                     "verification_tool_call_id": "c7-r2"}]}

    caso = bd.get(Caso, banco.open_handoff(bd, sc, expediente, idempotency_key= "k-urgente")["case_id"])

    assert (caso.auth_level, caso.priority, caso.actions_taken[0]["executed"]) == ("L2", "urgent", "unknown")


def test_open_handoff_idempotente(bd, sc):
    """POL-REL-02: reintentar open_handoff con la misma clave devuelve el mismo caso y no crea otro."""
    primero = banco.open_handoff(bd, sc, copy.deepcopy(EXPEDIENTE), idempotency_key= "S-1:t2")
    segundo = banco.open_handoff(bd, sc, copy.deepcopy(EXPEDIENTE), idempotency_key= "S-1:t2")

    assert primero == segundo
    assert len(bd.exec(select(Caso)).all()) == 1


def test_open_handoff_queda_auditado(bd, sc):
    """POL-HND-15, POL-AUD-02: el caso abierto escribe un evento handoff con los campos presentes y el digest, sin ids crudos."""
    caso = banco.open_handoff(bd, sc, copy.deepcopy(EXPEDIENTE), idempotency_key= "k-audit")

    eventos = [e.cuerpo for e in bd.exec(select(EventoAuditoria)).all() if e.event_type == "handoff"]
    assert len(eventos) == 1
    assert eventos[0]["case_id"] == caso["case_id"] and eventos[0]["handoff_event"] == "opened"
    assert all(eventos[0]["case_file_fields_present"].values())
    assert g.CLIENTE_FX not in auditoria.json_canonico(eventos[0]) and g.TARJETA_9205 not in auditoria.json_canonico(eventos[0])


def test_open_handoff_requiere_sesion_vigente(bd, sc, reloj):
    """POL-AUTH-03: con la sesión vencida tampoco se abre un caso desde la sesión (el orquestador usa la cola de respaldo, POL-REL-03)."""
    reloj.avanzar(minutes= 16)

    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.open_handoff(bd, sc, copy.deepcopy(EXPEDIENTE), idempotency_key= "k-vencida")
    assert error.value.codigo == "SESSION_EXPIRED"
