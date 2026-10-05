"""Audit log: cadena de hashes (AT-3), seudónimos (AL-P3) y escaneo de PII (AL-P7)."""

import uuid

from sqlmodel import select

import gold_golden as G
import gold_prueba as g
from conftest import Chat, abrir_sesion_cliente, cabeceras, crear_usuario, iniciar_sesion
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


def test_hechos_del_policy_decision_van_con_seudonimos(http, jurado, agente):
    """POL-PII-05, POL-AUD-01, AL-P3, AL-P4: los hechos de una transacción o de una lista de transacciones llegan al
    policy_decision con transaction_ref, no con el id crudo, así que AL-P7 no bloquea nada ni emite un security."""
    chat = Chat(http, jurado, G.D1, idioma= "es")
    chat.decir("Hola, hace unos días me rechazaron un pago en Uber con mi tarjeta terminada en 6873. ¿Qué pasó?")
    transaccion = next(h["value"] for h in chat.decision()["facts_used"] if h["fact"] == "transaction")
    assert transaccion["transaction_ref"] == auditoria.seudonimo("TRX-0OQVC3BDVLGG2VDSXTFM")
    assert "transaction_id" not in transaccion and transaccion["merchant"] == "Uber" and transaccion["response_code"] == "54"
    assert chat.eventos("security") == []

    chat = Chat(http, jurado, G.D10, idioma= "es")
    chat.decir("Muéstrame los movimientos de mi tarjeta terminada en 7042.")
    lista = next(h["value"] for h in chat.decision()["facts_used"] if h["fact"] == "transactions")
    assert [f["transaction_ref"] for f in lista] == [auditoria.seudonimo("TRX-FIXTUREG000000000104")]
    assert "transaction_id" not in lista[0] and lista[0]["merchant"] == "Farmacia Salud"
    assert chat.eventos("security") == []


def test_agente_lee_la_cadena_de_la_conversacion_de_un_caso(http, jurado, agente):
    """POL-PII-07, POL-AUD-02, AT-3: desde el expediente (conversation_ref) el agente lee la cadena completa de la
    conversación, con la verificación de hashes; un cliente no puede leerla."""
    crear_usuario("agente", "agente@pruebas.keyperu.example")
    token_agente = iniciar_sesion(http, "agente@pruebas.keyperu.example")
    chat = Chat(http, jurado, G.D5, idioma= "es")
    chat.decir("No reconozco un cobro de Empresa Telefónica en mi tarjeta de crédito terminada en 4950. Quiero reclamarlo.")
    chat.decir("Sí, ese.")
    assert chat.decir("No, por ahora solo quiero el reclamo.")["state"] == "HANDED_OFF"
    caso = http.get(f"/casos/{chat.ultima['case_id']}", headers= cabeceras(token_agente)).json()

    r = http.get(f"/auditoria/conversacion/{caso['conversation_ref']}", headers= cabeceras(token_agente))
    assert r.status_code == 200 and r.json()["cadena_valida"] is True
    eventos = r.json()["eventos"]
    assert r.json()["total"] == len(eventos) and {e["conversation_id"] for e in eventos} == {caso["conversation_ref"]}
    assert "handoff" in [e["event_type"] for e in eventos]
    assert http.get(f"/auditoria/conversacion/{caso['conversation_ref']}", headers= cabeceras(chat.token)).status_code == 403


def test_ids_de_evento_uuid7_ordenados():
    """AL-P3 / sección 1 del contrato: event_id es UUIDv7 y los ids sucesivos se ordenan por tiempo."""
    ids = [auditoria.uuid7() for _ in range(50)]

    assert all(uuid.UUID(i).version == 7 for i in ids)
    assert [i[:13] for i in ids] == sorted(i[:13] for i in ids)
