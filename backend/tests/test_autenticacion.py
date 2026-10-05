"""Autenticación, sesiones y step-up del IdP de prueba. Cada prueba cita las reglas que cubre."""

from datetime import datetime, timedelta, timezone

import inspect
import os
import subprocess
import sys

import jwt
import pytest
from sqlmodel import select

from conftest import (
    CLAVE, RAIZ_BACKEND, abrir_sesion_cliente, cabeceras, crear_usuario, iniciar_sesion, sesion_cliente, subir_a_l2,
)
from gold_prueba import CLIENTE_FX, CLIENTE_SUSPENDIDO, OTRO_CLIENTE, TARJETA_7921, TARJETA_9205, TARJETA_SUSPENDIDO
from models.auditoria import EventoAuditoria
from services import banco, identidad
from services.identidad import ErrorSesion, SesionCliente


@pytest.mark.parametrize("secreto", ["SECRET_KEY", "CARD_HASH_KEY", "AUDIT_KEY"])
def test_sin_secretos_el_backend_no_arranca(tmp_path, secreto):
    """POL-AUTH-10: SECRET_KEY, CARD_HASH_KEY y AUDIT_KEY no tienen valor por defecto; sin ellos el
    backend no arranca. Se corre en una carpeta sin .env."""
    entorno = {k: v for k, v in os.environ.items() if k != secreto}
    entorno["PYTHONPATH"] = str(RAIZ_BACKEND)
    resultado = subprocess.run([sys.executable, "-c", "import main"], cwd= tmp_path, env= entorno, capture_output= True, text= True)

    assert resultado.returncode != 0
    assert secreto in resultado.stderr


def test_secret_key_sin_valor_por_defecto_en_el_codigo():
    """POL-AUTH-10: el código no trae una SECRET_KEY de respaldo."""
    import security.config as configuracion
    fuente = inspect.getsource(configuracion)

    assert 'getenv("SECRET_KEY",' not in fuente
    assert "8888" not in fuente


@pytest.mark.parametrize("entorno", ["production", "staging", None])
def test_registro_cerrado_fuera_de_development(http, monkeypatch, entorno):
    """POL-AUTH-10: el registro abierto solo existe con ENV=development; si ENV falta, queda cerrado."""
    if entorno is None:
        monkeypatch.delenv("ENV", raising= False)
    else:
        monkeypatch.setenv("ENV", entorno)

    respuesta = http.post("/autenticacion/registrar", json= {"nombre": "X", "correo_electronico": "x@pruebas.keyperu.example", "password": CLAVE})

    assert respuesta.status_code == 403


def test_registro_en_development_crea_cliente_sin_datos(http, bd):
    """POL-AUTH-10, POL-AUTH-02, POL-PII-07: aunque el cuerpo pida rol jurado y un customer_id, el
    registro crea un cliente sin customer_id, que no puede leer datos ni usar el IdP de prueba."""
    respuesta = http.post("/autenticacion/registrar", json= {
        "nombre": "Intruso", "correo_electronico": "intruso@pruebas.keyperu.example", "password": CLAVE,
        "rol": "jurado", "customer_id": CLIENTE_FX,
    })
    assert respuesta.status_code == 201
    assert respuesta.json()["rol"] == "cliente"
    assert respuesta.json()["customer_id"] is None

    token = iniciar_sesion(http, "intruso@pruebas.keyperu.example")
    assert http.get("/identidad/clientes", headers= cabeceras(token)).status_code == 403
    with pytest.raises(ErrorSesion) as error:
        sesion_cliente(bd, token)
    assert error.value.codigo == "NOT_A_CUSTOMER_SESSION"


def test_numero_de_cliente_solo_no_autentica(http, bd, jurado):
    """POL-AUTH-02, POL-AUTH-12, POL-AUTH-01: un customer_id solo no prueba identidad (requisito B-8).
    No sirve como token, ni como contraseña, ni como campo de inicio de sesión, ni en una tool."""
    crear_usuario("cliente", "fx@pruebas.keyperu.example", CLIENTE_FX)

    for ruta in ("/autenticacion/mi-perfil", "/autenticacion/mi-sesion", "/identidad/clientes"):
        assert http.get(ruta, headers= cabeceras(CLIENTE_FX)).status_code == 401
        assert http.get(ruta).status_code == 401
    assert http.post("/autenticacion/step-up", json= {"codigo": "000000", "card_id": TARJETA_9205},
                     headers= cabeceras(CLIENTE_FX)).status_code == 401
    assert http.post("/identidad/sesion-prueba", json= {"customer_id": CLIENTE_FX}).status_code == 401

    assert http.post("/autenticacion/iniciar-sesion", json= {"correo_electronico": "fx@pruebas.keyperu.example",
                                                             "password": CLIENTE_FX}).status_code == 401
    assert http.post("/autenticacion/iniciar-sesion", json= {"customer_id": CLIENTE_FX}).status_code == 422

    # Las tools no tienen parámetro customer_id: el cliente sale siempre de la sesión verificada.
    for nombre, herramienta in banco.HERRAMIENTAS.items():
        assert "customer_id" not in inspect.signature(herramienta).parameters, nombre

    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.list_cards(bd, CLIENTE_FX)
    assert error.value.codigo == "SESSION_INVALID"

    with pytest.raises(banco.ErrorHerramienta):
        banco.list_cards(bd, SesionCliente("ses_inventada", CLIENTE_FX, "Active", None, "conv_x"))

    # Un SesionCliente con un id de sesión real pero otro customer_id tampoco sirve.
    token, sesion_id = abrir_sesion_cliente(http, jurado, OTRO_CLIENTE)
    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.list_cards(bd, SesionCliente(sesion_id, CLIENTE_FX, "Active", None, "conv_x"))
    assert error.value.codigo == "SESSION_INVALID"


def test_inicio_de_sesion_con_contrasena_liga_al_cliente(http, bd):
    """POL-AUTH-01, POL-AUTH-05, POL-AUTH-09: un usuario cliente sembrado inicia sesión en L1, ligado
    a su customer_id, con el customer_status leído de gold."""
    crear_usuario("cliente", "fx@pruebas.keyperu.example", CLIENTE_FX)
    token = iniciar_sesion(http, "fx@pruebas.keyperu.example")

    sesion = http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).json()
    assert (sesion["rol"], sesion["nivel"], sesion["customer_id"]) == ("cliente", "L1", CLIENTE_FX)
    assert "customer_status" not in sesion # El cliente no ve su estado (INV-14).
    assert sesion_cliente(bd, token).customer_status == "Active"
    assert {t["card_id"] for t in banco.list_cards(bd, sesion_cliente(bd, token))} == {TARJETA_9205, TARJETA_7921}


def test_cliente_sin_estado_en_gold_no_inicia_sesion(http):
    """POL-AUTH-09: si el estado del cliente no se puede leer en gold, no hay sesión (falla cerrado)."""
    crear_usuario("cliente", "fantasma@pruebas.keyperu.example", "CLI-NOESTAENGOLD")

    respuesta = http.post("/autenticacion/iniciar-sesion", json= {"correo_electronico": "fantasma@pruebas.keyperu.example", "password": CLAVE})

    assert respuesta.status_code == 503


def test_sesion_expira_por_inactividad(http, bd, jurado, reloj):
    """POL-AUTH-03, POL-AUTH-12: 15 minutos sin actividad cierran la sesión; después ninguna tool corre
    y la sesión responde SESSION_EXPIRED. El cierre queda auditado."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    sc = sesion_cliente(bd, token)

    reloj.avanzar(minutes= 14)
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).status_code == 200
    reloj.avanzar(minutes= 15)

    respuesta = http.get("/autenticacion/mi-sesion", headers= cabeceras(token))
    assert respuesta.status_code == 401
    assert respuesta.json()["detail"]["codigo"] == "SESSION_EXPIRED"
    for llamada in (lambda: banco.list_cards(bd, sc), lambda: banco.get_card_status(bd, sc, TARJETA_9205)):
        with pytest.raises(banco.ErrorHerramienta) as error:
            llamada()
        assert error.value.codigo == "SESSION_EXPIRED"

    eventos = bd.exec(select(EventoAuditoria).where(EventoAuditoria.conversation_id == sc.conversacion_id)).all()
    assert [e.cuerpo["session_event"] for e in eventos if e.event_type == "session"][-1] == "expired"


def test_sesion_expira_a_los_60_minutos_aunque_haya_actividad(http, bd, jurado, reloj):
    """POL-AUTH-03: el vencimiento absoluto corta la sesión aunque haya actividad cada 10 minutos."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    sc = sesion_cliente(bd, token)

    for _ in range(5):
        reloj.avanzar(minutes= 10)
        assert banco.list_cards(bd, sc)
    reloj.avanzar(minutes= 10)

    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.list_cards(bd, sc)
    assert error.value.codigo == "SESSION_EXPIRED"


def test_token_vencido_alterado_o_sin_firma(http, jurado):
    """POL-AUTH-12, POL-AUTH-03: un JWT vencido, firmado con otra clave o sin firma no da acceso."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    clave = os.environ["SECRET_KEY"]
    pasado = datetime.now(timezone.utc) - timedelta(minutes= 1)

    vencido = jwt.encode({"sid": sesion_id, "sub": "", "exp": pasado}, clave, algorithm= "HS256")
    otra_clave = jwt.encode({"sid": sesion_id, "sub": "", "exp": pasado + timedelta(hours= 1)}, "otra-clave-cualquiera-de-32-bytes!!", algorithm= "HS256")
    sin_firma = jwt.encode({"sid": sesion_id, "sub": "", "exp": pasado + timedelta(hours= 1)}, None, algorithm= "none")

    for falso in (vencido, otra_clave, sin_firma):
        assert http.get("/autenticacion/mi-sesion", headers= cabeceras(falso)).status_code == 401
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).status_code == 200


def test_cierre_de_sesion_invalida_el_token(http, bd, jurado):
    """POL-AUTH-12: después de cerrar sesión, el mismo token ya no sirve ni para las tools."""
    token, _ = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    sc = sesion_cliente(bd, token)

    assert http.post("/autenticacion/cerrar-sesion", headers= cabeceras(token)).status_code == 204
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).status_code == 401
    with pytest.raises(banco.ErrorHerramienta):
        banco.list_cards(bd, sc)


def test_step_up_da_l2_ligado_a_una_tarjeta_y_una_accion(http, bd, jurado, reloj):
    """POL-AUTH-04, POL-AUTH-01: el código sube la sesión a L2 por 5 minutos, solo para esa tarjeta y
    block_card. Otra tarjeta no queda habilitada; al vencer, la sesión vuelve a L1."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).json()["nivel"] == "L1"

    paso = subir_a_l2(http, jurado, token, sesion_id, TARJETA_9205)
    assert (paso["nivel"], paso["card_id_vinculada"], paso["accion"], paso["uso_unico"]) == ("L2", TARJETA_9205, "block_card", True)
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).json()["nivel"] == "L2"
    assert identidad.step_up_valido(bd, sesion_id, TARJETA_9205, "block_card") is not None
    assert identidad.step_up_valido(bd, sesion_id, TARJETA_7921, "block_card") is None

    reloj.avanzar(minutes= 5)
    assert identidad.step_up_valido(bd, sesion_id, TARJETA_9205, "block_card") is None
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).json()["nivel"] == "L1"


def test_codigo_de_prueba_un_solo_uso_y_con_vencimiento(http, jurado, reloj):
    """POL-AUTH-04, POL-AUTH-11: el código sirve una vez, vence a los 5 minutos y uno nuevo anula el anterior."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    pedir = lambda: http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado).json()["codigo"]
    usar = lambda codigo: http.post("/autenticacion/step-up", json= {"codigo": codigo, "card_id": TARJETA_9205}, headers= cabeceras(token))

    codigo = pedir()
    assert usar(codigo).status_code == 201
    assert usar(codigo).status_code == 400 # Ya usado.

    viejo = pedir()
    nuevo = pedir()
    assert usar(viejo).status_code == 400 # Anulado por el nuevo.
    assert usar(nuevo).status_code == 201

    vence = pedir()
    reloj.avanzar(minutes= 5, seconds= 1)
    assert http.get("/autenticacion/mi-sesion", headers= cabeceras(token)).status_code == 200 # Sigue vigente (actividad).
    assert usar(vence).status_code in (400, 403) # Código vencido; puede ser el tercer fallo (bloqueo).


def test_tres_fallos_bloquean_el_step_up(http, jurado):
    """POL-AUTH-06: después de 3 códigos fallidos, el step-up queda bloqueado en la sesión, incluso con
    el código correcto, y el IdP de prueba no emite más códigos para ella."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    correcto = http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado).json()["codigo"]
    incorrecto = "000000" if correcto != "000000" else "111111"

    respuestas = [http.post("/autenticacion/step-up", json= {"codigo": incorrecto, "card_id": TARJETA_9205}, headers= cabeceras(token))
                  for _ in range(3)]
    assert [r.status_code for r in respuestas] == [400, 400, 403]
    assert respuestas[-1].json()["detail"]["codigo"] == "STEP_UP_LOCKED"

    assert http.post("/autenticacion/step-up", json= {"codigo": correcto, "card_id": TARJETA_9205}, headers= cabeceras(token)).status_code == 403
    assert http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado).status_code == 403


def test_reautenticar_no_hereda_step_up_ni_confirmaciones(http, bd, jurado):
    """POL-AUTH-07: una sesión nueva del mismo cliente no hereda el step-up ni el token de confirmación
    de la anterior."""
    token_a, sesion_a = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    subir_a_l2(http, jurado, token_a, sesion_a, TARJETA_9205)
    confirmacion = banco.emitir_token_confirmacion(bd, sesion_cliente(bd, token_a), TARJETA_9205)
    http.post("/autenticacion/cerrar-sesion", headers= cabeceras(token_a))

    token_b, sesion_b = abrir_sesion_cliente(http, jurado, CLIENTE_FX)
    assert identidad.step_up_valido(bd, sesion_b, TARJETA_9205, "block_card") is None
    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.block_card(bd, sesion_cliente(bd, token_b), TARJETA_9205, confirmacion["confirmation_token"])
    assert error.value.codigo == "STEP_UP_REQUIRED"

    subir_a_l2(http, jurado, token_b, sesion_b, TARJETA_9205)
    with pytest.raises(banco.ErrorHerramienta) as error:
        banco.block_card(bd, sesion_cliente(bd, token_b), TARJETA_9205, confirmacion["confirmation_token"])
    assert error.value.codigo == "CONFIRMATION_INVALID"


def test_cliente_suspendido_solo_recibe_transferencia(http, bd, jurado):
    """POL-AUTH-09, INV-14: un cliente Suspended inicia sesión, pero ninguna tool de lectura ni el step-up
    corren; solo open_handoff."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, CLIENTE_SUSPENDIDO)
    sc = sesion_cliente(bd, token)
    assert sc.customer_status == "Suspended"

    for llamada in (
        lambda: banco.list_cards(bd, sc),
        lambda: banco.get_card_status(bd, sc, TARJETA_SUSPENDIDO),
        lambda: banco.list_balance_products(bd, sc),
        lambda: banco.list_transactions(bd, sc, TARJETA_SUSPENDIDO),
    ):
        with pytest.raises(banco.ErrorHerramienta) as error:
            llamada()
        assert error.value.codigo == "CUSTOMER_STATUS_REVIEW"

    assert http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado).status_code == 403

    caso = banco.open_handoff(bd, sc, {
        "request": "no request yet (handoff at sign-in)",
        "verified_facts": [{"fact": "customer_status", "value": "Suspended", "tool_call_id": "c1"}],
        "actions_taken": [], "evidence": {"tool_calls": []},
        "unresolved_questions": ["customer status requires human review"],
        "reason_rule_ids": ["POL-AUTH-09"], "priority": "normal", "language": "es",
    }, idempotency_key= f"{sesion_id}:t51")
    assert caso["case_id"].startswith("CASE-")
