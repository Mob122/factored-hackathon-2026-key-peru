"""IdP de prueba: solo el jurado busca clientes, abre sesiones de prueba y pide códigos (POL-AUTH-11)."""

import pytest
from sqlmodel import select

from conftest import abrir_sesion_cliente, cabeceras, crear_usuario, iniciar_sesion
from gold_prueba import CLIENTE_FX, OTRO_CLIENTE
from main import app
from models.auditoria import EventoAuditoria
from security.config import BUSQUEDA_MAX_POR_MINUTO
from services import auditoria


def _llamadas(sesion_id: str):
    return [
        ("get", "/identidad/clientes", None),
        ("post", "/identidad/sesion-prueba", {"customer_id": CLIENTE_FX}),
        ("post", "/identidad/otp-prueba", {"sesion_id": sesion_id}),
    ]


def test_solo_el_jurado_llama_a_identidad(http, jurado):
    """POL-AUTH-11, POL-PII-07: un cliente, un agente, una sesión de cliente abierta por el propio jurado
    y una llamada sin token son rechazados en los tres endpoints de /identidad; el jurado no."""
    crear_usuario("cliente", "cliente@pruebas.keyperu.example", CLIENTE_FX)
    crear_usuario("agente", "agente@pruebas.keyperu.example")
    token_cliente = iniciar_sesion(http, "cliente@pruebas.keyperu.example")
    token_agente = iniciar_sesion(http, "agente@pruebas.keyperu.example")
    token_prueba, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)

    for metodo, ruta, cuerpo in _llamadas(sesion_id):
        for token in (token_cliente, token_agente, token_prueba):
            respuesta = http.request(metodo, ruta, json= cuerpo, headers= cabeceras(token))
            assert respuesta.status_code == 403, (ruta, respuesta.text)
            assert respuesta.json()["detail"]["codigo"] == "ROLE_FORBIDDEN"
        assert http.request(metodo, ruta, json= cuerpo).status_code == 401

    for metodo, ruta, cuerpo in _llamadas(sesion_id):
        assert http.request(metodo, ruta, json= cuerpo, headers= jurado).status_code in (200, 201), ruta


def test_busqueda_paginada_con_campos_minimos(http, jurado):
    """POL-AUTH-11: como mucho 20 resultados por página, ordenados por customer_id, con solo customer_id,
    país y segmento. Pedir más de 20 es un error."""
    primera = http.get("/identidad/clientes", headers= jurado).json()
    assert len(primera["resultados"]) == 20 and primera["hay_mas"]
    assert all(set(fila) == {"customer_id", "country", "segment"} for fila in primera["resultados"])
    ids = [fila["customer_id"] for fila in primera["resultados"]]
    assert ids == sorted(ids)

    segunda = http.get("/identidad/clientes", params= {"pagina": 2}, headers= jurado).json()
    assert not segunda["hay_mas"] and not set(ids) & {f["customer_id"] for f in segunda["resultados"]}

    assert http.get("/identidad/clientes", params= {"tamano": 21}, headers= jurado).status_code == 422
    filtrada = http.get("/identidad/clientes", params= {"q": "cli-x7", "pais": "Colombia"}, headers= jurado).json()
    assert [f["customer_id"] for f in filtrada["resultados"]] == [CLIENTE_FX]


def test_busqueda_con_limite_de_tasa(http, jurado):
    """POL-AUTH-11: más de TEST_SEARCH_PER_MIN búsquedas por minuto de un jurado reciben 429; otro jurado no se ve afectado."""
    for _ in range(BUSQUEDA_MAX_POR_MINUTO):
        assert http.get("/identidad/clientes", params= {"tamano": 1}, headers= jurado).status_code == 200
    assert http.get("/identidad/clientes", params= {"tamano": 1}, headers= jurado).status_code == 429

    crear_usuario("jurado", "jurado2@pruebas.keyperu.example")
    otro = cabeceras(iniciar_sesion(http, "jurado2@pruebas.keyperu.example"))
    assert http.get("/identidad/clientes", params= {"tamano": 1}, headers= otro).status_code == 200


def test_no_hay_endpoints_de_exportacion_masiva():
    """POL-AUTH-11: /identidad expone solo la búsqueda paginada, la sesión de prueba y el código de prueba."""
    rutas = {(metodo.upper(), ruta) for ruta, operaciones in app.openapi()["paths"].items() for metodo in operaciones}
    assert {r for r in rutas if r[1].startswith("/identidad")} == {
        ("GET", "/identidad/clientes"), ("POST", "/identidad/sesion-prueba"), ("POST", "/identidad/otp-prueba"),
    }


def test_sesion_de_prueba_es_l1_con_expiracion_normal(http, jurado):
    """POL-AUTH-11, POL-AUTH-03, POL-AUTH-09: la sesión de prueba es L1, con 15/60 minutos y el estado del cliente de gold."""
    respuesta = http.post("/identidad/sesion-prueba", json= {"customer_id": CLIENTE_FX, "idioma": "pt"}, headers= jurado).json()

    assert (respuesta["nivel"], respuesta["customer_status"], respuesta["idioma"]) == ("L1", "Active", "pt")
    assert "simulado" in respuesta["aviso"]
    from datetime import datetime
    inactividad = datetime.fromisoformat(respuesta["expira_inactividad_en"].replace("Z", "+00:00"))
    absoluta = datetime.fromisoformat(respuesta["expira_absoluta_en"].replace("Z", "+00:00"))
    assert round((absoluta - inactividad).total_seconds() / 60) == 45


def test_sesion_de_prueba_de_cliente_inexistente_o_mal_formado(http, jurado):
    """POL-AUTH-11: un cliente que no está en gold da 404; un id mal formado, 422."""
    assert http.post("/identidad/sesion-prueba", json= {"customer_id": "CLI-NOESTAENGOLD"}, headers= jurado).status_code == 404
    assert http.post("/identidad/sesion-prueba", json= {"customer_id": "1234"}, headers= jurado).status_code == 422


def test_suplantacion_queda_en_el_audit_log(http, bd, jurado):
    """POL-AUTH-11, POL-PII-05: cada sesión de prueba escribe un evento session con el id del jurado,
    el seudónimo del cliente (AL-P3) y la hora. El customer_id crudo no aparece en el evento."""
    jurado_id = http.get("/autenticacion/mi-perfil", headers= jurado).json()["id"]
    _, sesion_id = abrir_sesion_cliente(http, jurado, OTRO_CLIENTE)

    eventos = [e for e in bd.exec(select(EventoAuditoria)).all() if e.cuerpo.get("test_idp")]
    assert len(eventos) == 1
    cuerpo = eventos[0].cuerpo
    assert cuerpo["session_event"] == "authenticated"
    assert cuerpo["session_id"] == sesion_id
    assert cuerpo["test_idp"]["issued_by_user_id"] == jurado_id
    assert cuerpo["test_idp"]["endpoint"] == "/identidad/sesion-prueba"
    assert cuerpo["customer_ref"] == auditoria.seudonimo(OTRO_CLIENTE)
    assert cuerpo["occurred_at"].endswith("Z")
    assert OTRO_CLIENTE not in auditoria.json_canonico(cuerpo)
    assert cuerpo["pii_scan"]["blocked"] is False


def test_codigo_de_prueba_auditado_sin_el_codigo(http, bd, jurado):
    """POL-AUTH-11, POL-AUTH-04: emitir un código escribe un evento step_up_requested con el jurado, y el código no se guarda."""
    _, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    codigo = http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado).json()["codigo"]

    eventos = [e.cuerpo for e in bd.exec(select(EventoAuditoria)).all() if e.cuerpo.get("session_event") == "step_up_requested"]
    assert len(eventos) == 1
    assert eventos[0]["test_idp"]["endpoint"] == "/identidad/otp-prueba"
    assert codigo not in auditoria.json_canonico(eventos[0])


def test_codigo_de_prueba_solo_para_sesiones_de_cliente_vigentes(http, jurado):
    """POL-AUTH-11: una sesión inexistente, de un jurado o cerrada no recibe código (mismo 404)."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    sesion_jurado = http.get("/autenticacion/mi-sesion", headers= jurado).json()["sesion_id"]
    http.post("/autenticacion/cerrar-sesion", headers= cabeceras(token))

    for objetivo in ("ses_inexistente", sesion_jurado, sesion_id):
        respuesta = http.post("/identidad/otp-prueba", json= {"sesion_id": objetivo}, headers= jurado)
        assert respuesta.status_code == 404
        assert respuesta.json()["detail"]["codigo"] == "SESSION_NOT_FOUND"
