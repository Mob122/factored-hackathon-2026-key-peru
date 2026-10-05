"""Producto seleccionado entre pedidos y mensajes en SELECT_CARD que no eligen un producto (D-35, D-36).
Clasificador real y gold de las conversaciones golden."""

import gold_golden as G
from conftest import Chat
from services import auditoria

D10_7042 = "PRD-261UZFW569GS" # Tarjeta de crédito 7042 del cliente del diálogo 10; su product_id es el mismo card_id.


def _productos_leidos(chat, herramienta):
    """Seudónimos (card_ref) de los productos que leyó la tool en el último turno."""
    return [e["args"]["card_ref"] for e in chat.eventos("tool_call", chat.ultima["turn"]) if e["tool"] == herramienta]


def test_movimientos_de_esa_tarjeta_retoman_la_tarjeta_del_saldo(http, jurado, agente):
    """POL-ANS-07, POL-GEN-07, POL-ANS-03: la tarjeta de crédito elegida para el saldo queda como selected_card_id; "esa
    tarjeta" en el pedido siguiente no vuelve a preguntar. La tarjeta se toma de list_cards (lectura fresca), por su id."""
    chat = Chat(http, jurado, G.D10, idioma= "es")
    assert chat.decir("¿Cuál es mi saldo?")["state"] == "SELECT_CARD"
    assert "terminada en 7042" in chat.decir("La terminada en 7042.")["reply"]

    r = chat.decir("¿Qué movimientos tuvo esa tarjeta en el último mes?")
    assert r["state"] == "IDLE"
    assert "Farmacia Salud" in r["reply"] and "7042" in r["reply"] and "0044" not in r["reply"]
    assert _productos_leidos(chat, "list_transactions") == [auditoria.seudonimo(D10_7042)]
    assert "T-05" not in chat.decision()["transitions"]


def test_saldo_de_esa_tarjeta_retoma_la_tarjeta_de_los_movimientos(http, jurado, agente):
    """POL-ANS-07, POL-ANS-15, POL-GEN-07: al revés, la tarjeta de crédito de una consulta de movimientos sirve para el
    saldo siguiente; el saldo se lee en el mismo turno."""
    chat = Chat(http, jurado, G.D10, idioma= "es")
    assert chat.decir("Muéstrame los movimientos de mi tarjeta terminada en 7042.")["state"] == "IDLE"

    r = chat.decir("¿Y cuál es el saldo de esa tarjeta?")
    assert r["state"] == "IDLE" and "terminada en 7042" in r["reply"] and "0044" not in r["reply"]
    assert _productos_leidos(chat, "get_balance") == [auditoria.seudonimo(D10_7042)]


def test_cuenta_de_ahorros_no_se_retoma_para_movimientos(http, jurado, agente):
    """POL-ANS-07: una cuenta de ahorros no tiene tarjeta; los movimientos piden elegir entre las tarjetas."""
    chat = Chat(http, jurado, G.D11, idioma= "es")
    chat.decir("¿Cuál es mi saldo?")
    assert "1317" in chat.decir("La cuenta de ahorros.")["reply"]

    r = chat.decir("¿Qué movimientos tuvo mi tarjeta?")
    assert r["state"] == "SELECT_CARD" and "1317" not in r["reply"]


def test_otro_tipo_de_producto_no_reusa_la_seleccion(http, jurado, agente):
    """POL-ANS-07, POL-ANS-16: un producto elegido solo por sus últimos 4 no se reusa cuando el pedido siguiente nombra
    otro tipo de producto."""
    chat = Chat(http, jurado, G.D11, idioma= "es")
    chat.decir("¿Cuál es mi saldo?")
    assert "cuenta de ahorros terminada en 1317" in chat.decir("La 1317.")["reply"]

    r = chat.decir("¿Y el saldo de mi tarjeta de crédito?")
    assert "tarjeta de crédito terminada en 5070" in r["reply"] and "1317" not in r["reply"]


def test_cierre_en_select_card_termina_la_conversacion(http, jurado, agente):
    """POL-GEN-01, POL-ACT-03: un cierre mientras se espera el producto termina la conversación (T-31 y T-11), sin
    repetir la pregunta y sin transferir."""
    chat = Chat(http, jurado, G.D10, idioma= "es")
    assert chat.decir("¿Cuál es mi saldo?")["state"] == "SELECT_CARD"

    r = chat.decir("Gracias, eso es todo.")
    assert r["state"] == "ENDED" and r["reply"] == "Con gusto. Hasta luego."
    assert chat.decision()["transitions"][-2:] == ["T-31", "T-11"]


def test_cierre_en_select_card_en_portugues(http, jurado, agente):
    """POL-GEN-01, POL-GEN-03: lo mismo en portugués."""
    chat = Chat(http, jurado, G.D12, idioma= "pt")
    assert chat.decir("Quais foram as últimas compras no meu cartão?")["state"] == "SELECT_CARD"

    r = chat.decir("Obrigado, era isso.")
    assert r["state"] == "ENDED" and r["reply"] == "Por nada. Até logo."


def test_otro_pedido_en_select_card_se_rutea_desde_idle(http, jurado, agente):
    """POL-ANS-01, POL-ACT-03: un pedido nuevo en lugar del producto deja la selección (T-31) y se atiende en el mismo
    turno desde IDLE."""
    chat = Chat(http, jurado, G.D10, idioma= "es")
    assert chat.decir("¿Cuál es mi saldo?")["state"] == "SELECT_CARD"

    r = chat.decir("¿Qué tarjetas tengo?")
    assert r["state"] == "IDLE" and "0044" in r["reply"] and "7042" in r["reply"]
    assert "T-31" in chat.decision()["transitions"] and "saldo" not in r["reply"]


def test_mensaje_que_no_elige_ni_cambia_de_pedido_repite_la_pregunta(http, jurado, agente):
    """POL-ANS-07, POL-ESC-06: un mensaje que no nombra producto ni es otro pedido repite la pregunta, como antes."""
    chat = Chat(http, jurado, G.D10, idioma= "es")
    chat.decir("¿Cuál es mi saldo?")

    r = chat.decir("¿Cuál es mi saldo?")
    assert r["state"] == "SELECT_CARD" and "0044" in r["reply"] and "7042" in r["reply"]
