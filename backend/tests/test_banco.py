"""Tools del banco simulado sobre gold. Cada prueba cita las reglas que cubre."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import hashlib
import os

import duckdb
import pytest
from sqlmodel import select

import gold_prueba as g
from conftest import abrir_sesion_cliente, preparar_bloqueo, sesion_cliente, subir_a_l2
from models.auditoria import EventoAuditoria
from models.banco import EventoEstadoTarjeta
from services import banco, identidad

CAMPOS_PROHIBIDOS = {
    "card_number_hmac", "product_number", "opening_date", "expiration_date", "last_updated", "fraud_score", "is_fraud",
    "segment", "customer_status", "customer_id", "source_file", "gold_batch_id", "gold_loaded_at",
}


@pytest.fixture
def sc_fx(http, bd, jurado):
    token, _ = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    return sesion_cliente(bd, token)


def _error(llamada) -> banco.ErrorHerramienta:
    with pytest.raises(banco.ErrorHerramienta) as error:
        llamada()
    return error.value


def _claves(valor) -> set:
    if isinstance(valor, dict):
        return set(valor) | set().union(*(_claves(v) for v in valor.values()))
    if isinstance(valor, list):
        return set().union(*(_claves(v) for v in valor)) if valor else set()
    return set()


def _huellas(directorio: Path) -> dict:
    return {ruta.name: (hashlib.sha256(ruta.read_bytes()).hexdigest(), ruta.stat().st_mtime_ns) for ruta in sorted(directorio.iterdir())}


# --- Lecturas --------------------------------------------------------------------------------------

def test_list_cards_y_estado_con_campos_permitidos(bd, sc_fx):
    """POL-ANS-01, POL-ANS-02, POL-ANS-13, POL-PII-03: id interno, últimos 4, tipo y estado; nunca el
    número, su HMAC ni las fechas de vigencia."""
    tarjetas = banco.list_cards(bd, sc_fx)

    assert tarjetas == [
        {"card_id": g.TARJETA_7921, "last4": "7921", "type": "Tarjeta Crédito", "status": "Active"},
        {"card_id": g.TARJETA_9205, "last4": "9205", "type": "Tarjeta Crédito", "status": "Active"},
    ]
    assert banco.get_card_status(bd, sc_fx, g.TARJETA_9205) == {"last4": "9205", "type": "Tarjeta Crédito", "status": "Active"}


def test_ningun_resultado_trae_campos_prohibidos(bd, sc_fx):
    """POL-ANS-12, POL-ANS-13, POL-PII-02, POL-PII-03, INV-07: ninguna tool devuelve fraude, segmento,
    estado del cliente, fechas de vigencia, número o HMAC de tarjeta, ni el customer_id."""
    resultados = [
        banco.list_cards(bd, sc_fx),
        banco.get_card_status(bd, sc_fx, g.TARJETA_9205),
        banco.list_transactions(bd, sc_fx, g.TARJETA_9205),
        banco.describe_transaction(bd, sc_fx, g.id_transaccion(10)),
        banco.list_balance_products(bd, sc_fx),
        banco.get_balance(bd, sc_fx, g.TARJETA_9205),
    ]
    assert not _claves(resultados) & CAMPOS_PROHIBIDOS
    assert g.OTRO_CLIENTE not in repr(resultados) and g.TARJETA_AJENA not in repr(resultados)


def test_producto_ajeno_mismo_error_que_inexistente(http, bd, jurado, sc_fx):
    """POL-AUTH-05, POL-ANS-18, INV-07: una tarjeta, transacción o producto de otro cliente da exactamente
    el mismo error que uno que no existe, en cada tool."""
    llamadas = {
        "get_card_status": lambda card: banco.get_card_status(bd, sc_fx, card),
        "list_transactions": lambda card: banco.list_transactions(bd, sc_fx, card),
        "get_balance": lambda card: banco.get_balance(bd, sc_fx, card),
    }
    for nombre, llamada in llamadas.items():
        ajena, inexistente = _error(lambda: llamada(g.TARJETA_AJENA)), _error(lambda: llamada(g.TARJETA_INEXISTENTE))
        assert (ajena.codigo, ajena.mensaje, ajena.detalle) == (inexistente.codigo, inexistente.mensaje, inexistente.detalle) == (
            "NOT_FOUND", banco.MENSAJES["NOT_FOUND"], None), nombre

    ajena = _error(lambda: banco.describe_transaction(bd, sc_fx, g.id_transaccion(2)))
    inexistente = _error(lambda: banco.describe_transaction(bd, sc_fx, g.id_transaccion(999)))
    assert (ajena.codigo, ajena.mensaje) == (inexistente.codigo, inexistente.mensaje) == ("NOT_FOUND", banco.MENSAJES["NOT_FOUND"])

    # Con un step-up para la tarjeta ajena y para una inexistente, block_card tampoco las distingue.
    token, sesion_id = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    sc = sesion_cliente(bd, token)
    errores = []
    for card in (g.TARJETA_AJENA, g.TARJETA_INEXISTENTE):
        subir_a_l2(http, jurado, token, sesion_id, card)
        assert _error(lambda: banco.emitir_token_confirmacion(bd, sc, card)).codigo == "NOT_FOUND"
        errores.append(_error(lambda: banco.block_card(bd, sc, card, "token-cualquiera")))
    assert [(e.codigo, e.mensaje) for e in errores] == [("NOT_FOUND", banco.MENSAJES["NOT_FOUND"])] * 2
    assert bd.exec(select(EventoEstadoTarjeta)).all() == []


def test_list_transactions_ventana_por_defecto_y_topes(bd, sc_fx, http, jurado):
    """POL-ANS-03: por defecto los últimos 30 días, nunca antes de 90 días atrás, como mucho 20 filas
    (las más recientes) y con los filtros pedidos."""
    resultado = banco.list_transactions(bd, sc_fx, g.TARJETA_9205)
    assert (resultado["from"], resultado["to"], resultado["window_capped"]) == (date(2026, 5, 19), date(2026, 6, 18), False)
    ids = [t["transaction_id"] for t in resultado["transactions"]]
    assert ids[0] == g.id_transaccion(16) and g.id_transaccion(12) not in ids and g.id_transaccion(13) not in ids

    larga = banco.list_transactions(bd, sc_fx, g.TARJETA_9205, desde= date(2025, 1, 1))
    assert larga["from"] == date(2026, 3, 20) and larga["window_capped"]
    assert g.id_transaccion(12) in [t["transaction_id"] for t in larga["transactions"]]
    assert g.id_transaccion(13) not in [t["transaction_id"] for t in larga["transactions"]]

    filtrada = banco.list_transactions(bd, sc_fx, g.TARJETA_9205, comercio= "uber", estado= "Declined")
    assert [t["transaction_id"] for t in filtrada["transactions"]] == [g.id_transaccion(16), g.id_transaccion(10)]
    montos = banco.list_transactions(bd, sc_fx, g.TARJETA_9205, monto_min= Decimal("60000"), monto_max= Decimal("150000"))
    assert {t["transaction_id"] for t in montos["transactions"]} == {g.id_transaccion(14), g.id_transaccion(15)}

    token, _ = abrir_sesion_cliente(http, jurado, g.CLIENTE_ESTADOS)
    muchas = banco.list_transactions(bd, sesion_cliente(bd, token), g.TARJETA_DEBITO)
    assert len(muchas["transactions"]) == banco.TX_FILAS_MAX and muchas["truncated"]
    assert muchas["transactions"][0]["transaction_id"] == g.id_transaccion(30)


def test_list_transactions_vacia_no_es_error(bd, sc_fx):
    """POL-ANS-06: una ventana sin transacciones devuelve una lista vacía, no un error ni una inferencia."""
    resultado = banco.list_transactions(bd, sc_fx, g.TARJETA_7921)

    assert resultado["transactions"] == [] and not resultado["truncated"]


@pytest.mark.parametrize("numero, plantillas, avisos", [
    (10, ["POL-TXS-02", "POL-DEC-51"], []),
    (11, ["POL-TXS-02", "POL-DEC-90"], []),
    (14, ["POL-TXS-04", "POL-DEC-05"], []),
    (15, ["POL-TXS-03", "POL-DEC-14"], []),
    (16, ["POL-TXS-02", "POL-DEC-91"], ["POL-ESC-05"]),
    (12, ["POL-TXS-01", "POL-DEC-92"], []),
])
def test_describe_transaction_con_plantillas(bd, sc_fx, numero, plantillas, avisos):
    """POL-ANS-04: campos de la transacción, últimos 4 de la tarjeta y las plantillas fijas que aplican."""
    resultado = banco.describe_transaction(bd, sc_fx, g.id_transaccion(numero))

    assert (resultado["templates"], resultado["notices"], resultado["last4"]) == (plantillas, avisos, "9205")


def test_saldos_elegibles_y_plantillas(bd, sc_fx, http, jurado, monkeypatch):
    """POL-ANS-15, POL-ANS-16, POL-ANS-17, POL-GEN-07: solo tarjetas de crédito y cuentas de ahorro no
    cerradas; saldo y límite tal como están, con as_of en cada lectura y la plantilla que aplica."""
    productos = banco.list_balance_products(bd, sc_fx)
    assert [(p["product_id"], p["kind"]) for p in productos] == [
        (g.TARJETA_7921, "credit_card"), (g.TARJETA_9205, "credit_card"), (g.AHORRO_FX, "savings_account"),
    ]

    credito = banco.get_balance(bd, sc_fx, g.TARJETA_9205)
    assert (credito["current_balance"], credito["credit_limit"], credito["templates"]) == (Decimal("1234567.89"), Decimal("5000000.00"), ["POL-BAL-01"])
    assert credito["as_of"] == g.CARGA_BASE
    assert banco.get_balance(bd, sc_fx, g.TARJETA_7921)["templates"] == ["POL-BAL-06", "POL-BAL-04"] # Sin límite.
    ahorro = banco.get_balance(bd, sc_fx, g.AHORRO_FX)
    assert "credit_limit" not in ahorro and ahorro["templates"] == ["POL-BAL-02"]

    token, _ = abrir_sesion_cliente(http, jurado, g.OTRO_CLIENTE)
    assert banco.get_balance(bd, sesion_cliente(bd, token), g.TARJETA_AJENA)["templates"] == ["POL-BAL-06", "POL-BAL-04"] # Saldo > límite.

    token, _ = abrir_sesion_cliente(http, jurado, g.CLIENTE_ESTADOS)
    sc = sesion_cliente(bd, token)
    assert {p["product_id"] for p in banco.list_balance_products(bd, sc)} == {g.TARJETA_BLOQUEADA, g.TARJETA_SUSPENDIDA}
    assert _error(lambda: banco.get_balance(bd, sc, g.AHORRO_CERRADO)).codigo == "NOT_FOUND"
    assert _error(lambda: banco.get_balance(bd, sc, g.TARJETA_DEBITO)).codigo == "NOT_FOUND" # Débito no es elegible.

    monkeypatch.setattr(banco, "ahora_banco", lambda: g.CARGA_BASE + timedelta(hours= 25))
    assert banco.get_balance(bd, sc_fx, g.TARJETA_9205)["templates"] == ["POL-BAL-01", "POL-BAL-03"]


def test_registro_de_herramientas_sin_desbloqueo_ni_dinero():
    """POL-ACT-07, POL-ACT-08: el registro no tiene tools para desbloquear, reactivar, reemplazar ni mover dinero."""
    assert set(banco.HERRAMIENTAS) == {
        "list_cards", "get_card_status", "list_transactions", "describe_transaction",
        "list_balance_products", "get_balance", "block_card", "open_handoff",
    }
    prohibidas = ("unblock", "reactivat", "replace", "transfer", "payment", "refund", "chargeback", "limit")
    assert not [n for n in dir(banco) if any(p in n.lower() for p in prohibidas) and callable(getattr(banco, n))]


# --- Bloqueo ----------------------------------------------------------------------------------------

def test_bloqueo_sin_step_up_rechazado(http, bd, jurado, reloj):
    """POL-ACT-01, POL-AUTH-04, POL-GEN-01: sin step-up, con step-up de otra tarjeta, con step-up vencido
    o ya usado, block_card se rechaza y el overlay no cambia."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    sc = sesion_cliente(bd, token)

    assert _error(lambda: banco.block_card(bd, sc, g.TARJETA_9205, "x")).codigo == "STEP_UP_REQUIRED"
    assert _error(lambda: banco.emitir_token_confirmacion(bd, sc, g.TARJETA_9205)).codigo == "STEP_UP_REQUIRED"

    subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_7921)
    assert _error(lambda: banco.block_card(bd, sc, g.TARJETA_9205, "x")).codigo == "STEP_UP_REQUIRED"

    subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_9205)
    confirmacion = banco.emitir_token_confirmacion(bd, sc, g.TARJETA_9205)
    reloj.avanzar(minutes= 5)
    assert _error(lambda: banco.block_card(bd, sc, g.TARJETA_9205, confirmacion["confirmation_token"])).codigo == "STEP_UP_REQUIRED"

    assert bd.exec(select(EventoEstadoTarjeta)).all() == []
    assert banco.get_card_status(bd, sc, g.TARJETA_9205)["status"] == "Active"


def test_bloqueo_exige_confirmacion_valida_y_consume_el_step_up(http, bd, jurado, reloj):
    """POL-ACT-02, POL-ACT-04, POL-AUTH-04: sin token, con un token de otra tarjeta, vencido (120 s) o
    reemplazado por otro, el bloqueo se rechaza. El step-up se consume en el intento, sea cual sea el resultado."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, g.CLIENTE_FX)
    sc = sesion_cliente(bd, token)

    subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_7921)
    de_otra_tarjeta = banco.emitir_token_confirmacion(bd, sc, g.TARJETA_7921)["confirmation_token"]

    casos = [
        ("", None),
        (de_otra_tarjeta, None),
        ("vencido", 121),
        ("reemplazado", None),
    ]
    for tipo, segundos in casos:
        subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_9205)
        token_confirmacion = tipo
        if tipo in ("vencido", "reemplazado"):
            token_confirmacion = banco.emitir_token_confirmacion(bd, sc, g.TARJETA_9205)["confirmation_token"]
        if tipo == "reemplazado":
            banco.emitir_token_confirmacion(bd, sc, g.TARJETA_9205)
        if segundos:
            reloj.avanzar(seconds= segundos)

        assert _error(lambda: banco.block_card(bd, sc, g.TARJETA_9205, token_confirmacion)).codigo == "CONFIRMATION_INVALID", tipo
        assert identidad.step_up_valido(bd, sesion_id, g.TARJETA_9205, "block_card") is None, tipo # Consumido.

    assert bd.exec(select(EventoEstadoTarjeta)).all() == []


def test_bloqueo_una_sola_vez_por_token(http, bd, jurado):
    """POL-ACT-06, POL-REL-02: block_card corre como mucho una vez por token de confirmación (la clave de
    idempotencia). Un segundo intento con el mismo token se rechaza y no escribe otro evento."""
    sc, confirmacion, token, sesion_id = preparar_bloqueo(http, jurado, bd, g.CLIENTE_FX, g.TARJETA_9205)

    assert banco.block_card(bd, sc, g.TARJETA_9205, confirmacion)["accepted"] is True
    subir_a_l2(http, jurado, token, sesion_id, g.TARJETA_9205)
    assert _error(lambda: banco.block_card(bd, sc, g.TARJETA_9205, confirmacion)).codigo == "CONFIRMATION_USED"
    assert len(bd.exec(select(EventoEstadoTarjeta)).all()) == 1


@pytest.mark.parametrize("tarjeta, codigo", [
    (g.TARJETA_BLOQUEADA, "CARD_ALREADY_BLOCKED"),
    (g.TARJETA_SUSPENDIDA, "CARD_NOT_ACTIVE"),
    (g.TARJETA_CERRADA, "CARD_NOT_ACTIVE"),
])
def test_bloqueo_solo_de_tarjetas_activas(http, bd, jurado, tarjeta, codigo):
    """POL-ACT-01, POL-ESC-12: una tarjeta Blocked no se vuelve a bloquear; una Suspended o Closed se
    rechaza para transferir."""
    sc, confirmacion, _, _ = preparar_bloqueo(http, jurado, bd, g.CLIENTE_ESTADOS, tarjeta)

    assert _error(lambda: banco.block_card(bd, sc, tarjeta, confirmacion)).codigo == codigo
    assert bd.exec(select(EventoEstadoTarjeta)).all() == []


def test_bloqueo_aceptado_se_lee_bloqueado_y_queda_auditado(http, bd, jurado):
    """POL-ACT-09, POL-ACT-01: el bloqueo devuelve accepted y request_id; la relectura de estado da Blocked
    (lo que verifica el gateway, POL-ACT-05); el audit log tiene un action_result executed=true y los
    rechazos quedan como executed=false con su código."""
    sc, confirmacion, _, _ = preparar_bloqueo(http, jurado, bd, g.CLIENTE_FX, g.TARJETA_9205)
    _error(lambda: banco.block_card(bd, sc, g.TARJETA_7921, "x")) # Rechazo: sin step-up para 7921.

    resultado = banco.block_card(bd, sc, g.TARJETA_9205, confirmacion)
    assert resultado["accepted"] is True and resultado["request_id"].startswith("BLK-")
    assert banco.get_card_status(bd, sc, g.TARJETA_9205)["status"] == "Blocked"
    assert {t["card_id"]: t["status"] for t in banco.list_cards(bd, sc)}[g.TARJETA_9205] == "Blocked"
    assert {p["product_id"]: p["status"] for p in banco.list_balance_products(bd, sc)}[g.TARJETA_9205] == "Blocked"

    acciones = [e.cuerpo for e in bd.exec(select(EventoAuditoria)).all() if e.event_type == "action_result"]
    assert [(a["executed"], a["error_code"]) for a in acciones] == [("false", "STEP_UP_REQUIRED"), ("true", None)]
    assert acciones[1]["action_id"] == resultado["request_id"]
    assert acciones[1]["preconditions"]["auth_level"] == "L2" and acciones[1]["preconditions"]["pre_status"] == "Active"


def test_block_card_nunca_toca_el_parquet(http, bd, jurado, gold_de_prueba):
    """block_card escribe solo en el overlay: los archivos Parquet de gold quedan con los mismos bytes y
    la misma fecha de modificación, la fila de gold sigue Active, y la conexión DuckDB no puede escribir
    archivos (freshness_policy.md sección 5)."""
    antes = _huellas(gold_de_prueba)
    sc, confirmacion, _, _ = preparar_bloqueo(http, jurado, bd, g.CLIENTE_FX, g.TARJETA_9205)

    banco.block_card(bd, sc, g.TARJETA_9205, confirmacion)

    assert _huellas(gold_de_prueba) == antes
    assert banco.get_card_status(bd, sc, g.TARJETA_9205)["status"] == "Blocked"
    with duckdb.connect() as conexion:
        assert conexion.execute(
            f"SELECT status FROM read_parquet('{(gold_de_prueba / 'cards.parquet').as_posix()}') WHERE card_id = ?", [g.TARJETA_9205]
        ).fetchone()[0] == "Active"
    eventos = bd.exec(select(EventoEstadoTarjeta)).all()
    assert [(e.card_id, e.nuevo_estado) for e in eventos] == [(g.TARJETA_9205, "Blocked")]

    cursor = banco.lector.cursor()
    try:
        for sql in (f"COPY cards TO '{(gold_de_prueba / 'cards.parquet').as_posix()}'", "SET enable_external_access = true"):
            with pytest.raises(duckdb.Error):
                cursor.execute(sql)
    finally:
        cursor.close()
    assert _huellas(gold_de_prueba) == antes


# --- FX-6 y FX-7 (freshness_policy.md 6.4) -----------------------------------------------------------

def _gold_propio(tmp_path: Path) -> Path:
    directorio = tmp_path / "gold"
    g.escribir_gold(directorio, g.gold_base(), [g.ENTREGAS_BASE], os.environ["CARD_HASH_KEY"])
    banco.usar_gold(directorio)
    return directorio


def _bloquear_9205_el_18_a_las_16(http, bd, jurado, monkeypatch):
    monkeypatch.setattr(banco, "ahora_banco", lambda: datetime(2026, 6, 18, 16, 0))
    sc, confirmacion, _, _ = preparar_bloqueo(http, jurado, bd, g.CLIENTE_FX, g.TARJETA_9205)
    banco.block_card(bd, sc, g.TARJETA_9205, confirmacion)
    return sc


def test_fx6_el_overlay_gana_en_el_mismo_dia_habil(http, bd, jurado, monkeypatch, tmp_path):
    """FX-6: block_card sobre 9205 el 2026-06-18 a las 16:00 y luego se reprocesa la entrega del 2026-06-18.
    El estado efectivo de 9205 es Blocked, porque su fila de gold se entregó el 2026-06-17; la fila de gold
    sigue Active. La recarga también trae el bloqueo de 7921 que llegó en esa entrega."""
    directorio = _gold_propio(tmp_path)
    sc = _bloquear_9205_el_18_a_las_16(http, bd, jurado, monkeypatch)

    nuevas = g.entrega_0618(g.gold_base())
    g.escribir_gold(directorio, nuevas, [g.ENTREGAS_BASE, [(g.RUTA_PRODUCTOS_0618, date(2026, 6, 18)),
                                                            (g.RUTA_TRANSACCIONES_0618, date(2026, 6, 18))]], os.environ["CARD_HASH_KEY"])

    estados = {t["card_id"]: t["status"] for t in banco.list_cards(bd, sc)}
    assert estados == {g.TARJETA_9205: "Blocked", g.TARJETA_7921: "Blocked"}
    with duckdb.connect() as conexion:
        assert conexion.execute(
            f"SELECT status FROM read_parquet('{(directorio / 'cards.parquet').as_posix()}') WHERE card_id = ?", [g.TARJETA_9205]
        ).fetchone()[0] == "Active"
    monkeypatch.setattr(banco, "ahora_banco", lambda: datetime(2026, 6, 18, 17, 0))
    assert banco.list_transactions(bd, sc, g.TARJETA_9205)["transactions"][0]["transaction_id"] == g.id_transaccion(1)


def test_fx7_una_entrega_de_un_dia_habil_posterior_manda(http, bd, jurado, monkeypatch, tmp_path):
    """FX-7: el mismo evento del overlay y después una entrega del 2026-06-19 con 9205 Active: el estado
    efectivo es Active, porque un día hábil estrictamente posterior reemplaza al overlay."""
    directorio = _gold_propio(tmp_path)
    sc = _bloquear_9205_el_18_a_las_16(http, bd, jurado, monkeypatch)

    nuevas = g.entrega_0619_9205_activa(g.gold_base())
    g.escribir_gold(directorio, nuevas, [g.ENTREGAS_BASE, [(g.RUTA_PRODUCTOS_0619, date(2026, 6, 19))]], os.environ["CARD_HASH_KEY"])

    assert banco.get_card_status(bd, sc, g.TARJETA_9205)["status"] == "Active"


# --- Comprobación de propiedad de un número completo -------------------------------------------------

def test_comprobacion_de_propiedad_con_el_hmac_de_gold(bd, sc_fx):
    """POL-ESC-10, POL-AUTH-05, POL-PII-04: el HMAC es el de docs/findings/gold_run.md (HMAC-SHA256,
    clave y número en UTF-8, hex minúscula). Un número propio devuelve la tarjeta; uno ajeno, ningún dato
    de la otra tarjeta; unos últimos 4 solos no activan la comprobación."""
    numero = g.NUMEROS[g.TARJETA_9205]
    assert banco.hmac_numero_tarjeta(numero) == g.huella(numero, os.environ["CARD_HASH_KEY"])
    assert banco.hmac_numero_tarjeta(numero) == banco.hmac_numero_tarjeta(numero).lower() and len(banco.hmac_numero_tarjeta(numero)) == 64

    propia = banco.comprobar_numero_tarjeta(bd, sc_fx, "4000 0000 0000 9205")
    assert (propia.resultado, propia.card_id, propia.last4) == ("propia", g.TARJETA_9205, "9205")

    ajena = banco.comprobar_numero_tarjeta(bd, sc_fx, g.NUMEROS[g.TARJETA_AJENA])
    assert (ajena.resultado, ajena.card_id) == ("ajena", None)
    assert g.TARJETA_AJENA not in repr(ajena) and g.OTRO_CLIENTE not in repr(ajena)

    inexistente = banco.comprobar_numero_tarjeta(bd, sc_fx, "4000000000001234")
    assert (inexistente.resultado, inexistente.card_id) == ("no_encontrada", None)

    for corto in ("9205", "0044", "12345678"):
        with pytest.raises(ValueError):
            banco.comprobar_numero_tarjeta(bd, sc_fx, corto)


def test_gold_dir_acepta_la_carpeta_padre(tmp_path):
    """GOLD_DIR puede apuntar a 03_primary (con gold/ adentro) o a la carpeta de las tablas; sin tablas, GOLD_UNAVAILABLE."""
    directorio = tmp_path / "03_primary" / "gold"
    g.escribir_gold(directorio, g.gold_base(), [g.ENTREGAS_BASE], os.environ["CARD_HASH_KEY"])

    assert banco.resolver_directorio_gold(str(tmp_path / "03_primary")) == directorio
    assert banco.resolver_directorio_gold(str(directorio)) == directorio
    assert _error(lambda: banco.resolver_directorio_gold(str(tmp_path / "vacio"))).codigo == "GOLD_UNAVAILABLE"
