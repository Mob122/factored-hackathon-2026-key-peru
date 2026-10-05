"""Portal del cliente (/cliente/*): sus propios datos, sin ids internos y con los controles de las tools (POL-PII-10)."""

from sqlmodel import func, select

from conftest import Chat, abrir_sesion_cliente, cabeceras, crear_usuario, iniciar_sesion
from gold_prueba import CLIENTE_ESTADOS, CLIENTE_FX, CLIENTE_SUSPENDIDO, OTRO_CLIENTE
from models.auditoria import EventoAuditoria

RUTAS = ("/cliente/tarjetas", "/cliente/transacciones", "/cliente/conversaciones", "/cliente/casos")


def _eventos(bd) -> int:
    return bd.exec(select(func.count()).select_from(EventoAuditoria)).one()


def test_portal_solo_para_sesiones_de_cliente(http, jurado):
    """POL-PII-10, POL-PII-07: un agente, un jurado y un usuario registrado sin cliente reciben
    NOT_A_CUSTOMER_SESSION en todo /cliente; sin token, 401."""
    crear_usuario("agente", "agente@pruebas.keyperu.example")
    crear_usuario("cliente", "sin-cliente@pruebas.keyperu.example")
    tokens = [iniciar_sesion(http, "agente@pruebas.keyperu.example"), iniciar_sesion(http, "sin-cliente@pruebas.keyperu.example")]

    for ruta in RUTAS:
        for encabezado in [cabeceras(t) for t in tokens] + [jurado]:
            respuesta = http.get(ruta, headers= encabezado)
            assert respuesta.status_code == 403, (ruta, respuesta.text)
            assert respuesta.json()["detail"]["codigo"] == "NOT_A_CUSTOMER_SESSION"
        assert http.get(ruta).status_code == 401


def test_tarjetas_del_cliente_sin_ids_internos(http, jurado, bd):
    """POL-PII-10, POL-ANS-01, POL-AUTH-05: solo las tarjetas del cliente de la sesión, con last 4, tipo y estado,
    nombradas t1, t2 por orden de card_id; ningún card_id en la respuesta. No escribe en el audit log."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    antes = _eventos(bd)

    respuesta = http.get("/cliente/tarjetas", headers= cabeceras(token))

    assert respuesta.status_code == 200
    assert respuesta.json() == [
        {"ref": "t1", "last4": "7921", "tipo": "Tarjeta Crédito", "estado": "Active"},
        {"ref": "t2", "last4": "9205", "tipo": "Tarjeta Crédito", "estado": "Active"},
    ]
    assert "PRD-" not in respuesta.text and "0044" not in respuesta.text
    assert _eventos(bd) == antes


def test_transacciones_con_ventana_y_tope_de_filas(http, jurado):
    """POL-PII-10, POL-ANS-03, POL-ANS-10: los últimos `dias` días del reloj del banco (por defecto 30, como mucho
    TX_MAX_DAYS), como mucho TX_MAX_ROWS filas por tarjeta (las más recientes, marcadas como truncadas), solo los campos
    de POL-ANS-03 (sin código de respuesta) y ningún transaction_id."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_FX)

    datos = http.get("/cliente/transacciones", headers= cabeceras(token)).json()
    assert (datos["desde"], datos["hasta"]) == ("2026-05-19", "2026-06-18")
    t1, t2 = datos["tarjetas"]
    assert (t1["last4"], t1["transacciones"]) == ("7921", [])
    assert t2["last4"] == "9205" and not t2["truncada"]
    assert [tx["fecha"][:10] for tx in t2["transacciones"]] == [
        "2026-06-15", "2026-06-14", "2026-06-13", "2026-06-12", "2026-06-11", "2026-06-10", "2026-06-06"]
    assert t2["transacciones"][3] == {"fecha": "2026-06-12T09:00:00", "tipo": "Purchase", "monto": "50000.00", "moneda": "COP",
                                      "comercio": "Uber", "estado": "Declined"}

    noventa = http.get("/cliente/transacciones", params= {"dias": 90}, headers= cabeceras(token)).json()
    assert "2026-04-01" in [tx["fecha"][:10] for tx in noventa["tarjetas"][1]["transacciones"]]
    assert http.get("/cliente/transacciones", params= {"dias": 91}, headers= cabeceras(token)).status_code == 422
    assert "TRX-" not in str(noventa) and "PRD-" not in str(noventa)

    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_ESTADOS)
    debito = [t for t in http.get("/cliente/transacciones", headers= cabeceras(token)).json()["tarjetas"] if t["last4"] == "7777"][0]
    assert debito["truncada"] and len(debito["transacciones"]) == 20


def test_cliente_en_revision_no_lee_tarjetas_ni_transacciones(http, jurado):
    """POL-PII-10, POL-AUTH-09: un cliente Suspended recibe CUSTOMER_STATUS_REVIEW en tarjetas y transacciones,
    y solo ve la referencia de su caso, que el chat ya le dio."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_SUSPENDIDO)
    chat = Chat(http, jurado, CLIENTE_SUSPENDIDO, token= token)
    assert chat.ultima["state"] == "HANDED_OFF"

    for ruta in ("/cliente/tarjetas", "/cliente/transacciones"):
        respuesta = http.get(ruta, headers= cabeceras(token))
        assert respuesta.status_code == 403
        assert respuesta.json()["detail"]["codigo"] == "CUSTOMER_STATUS_REVIEW"
    assert [c["case_id"] for c in http.get("/cliente/casos", headers= cabeceras(token)).json()] == [chat.ultima["case_id"]]


def test_casos_y_conversaciones_propios_sin_expediente(http, jurado):
    """POL-PII-10, POL-PII-05, POL-PII-07: el cliente ve la referencia, fecha, prioridad y motivo de sus casos y el
    estado de sus conversaciones; nunca el expediente ni el customer_id. Otro cliente no los ve."""
    chat = Chat(http, jurado, CLIENTE_FX)
    assert chat.decir("Quiero hablar con un asesor.")["state"] == "HANDED_OFF"

    casos = http.get("/cliente/casos", headers= cabeceras(chat.token))
    assert casos.status_code == 200
    (caso,) = casos.json()
    assert set(caso) == {"case_id", "creado_en", "prioridad", "motivo", "tarjetas_last4", "mensajes_agregados", "conversation_id"}
    assert (caso["case_id"], caso["prioridad"], caso["motivo"]) == (chat.ultima["case_id"], "normal", "human_request")
    assert caso["conversation_id"] == chat.conversation_id
    assert CLIENTE_FX not in casos.text and "unresolved" not in casos.text and "verified" not in casos.text

    (conversacion,) = http.get("/cliente/conversaciones", headers= cabeceras(chat.token)).json()
    assert (conversacion["conversation_id"], conversacion["estado"], conversacion["case_id"]) == (
        chat.conversation_id, "HANDED_OFF", chat.ultima["case_id"])

    otro, _ = abrir_sesion_cliente(http, jurado, OTRO_CLIENTE)
    assert http.get("/cliente/casos", headers= cabeceras(otro)).json() == []
    assert http.get("/cliente/conversaciones", headers= cabeceras(otro)).json() == []
