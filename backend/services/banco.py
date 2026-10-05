"""Banco simulado sobre gold (docs/contracts/gold_tables.md, gold-0.2).

Tools con los contratos de docs/proposal.md sección 8: list_cards, get_card_status, list_transactions,
describe_transaction, list_balance_products, get_balance, block_card y open_handoff.

- Gold se lee con DuckDB en memoria: las tablas se copian del Parquet de GOLD_DIR y después se
  desactiva el acceso a archivos y se bloquea la configuración. Desde ese momento DuckDB no puede
  leer ni escribir ningún archivo, así que el Parquet nunca se modifica.
- block_card escribe en el overlay (tabla eventos_estado_tarjeta de la base del backend); las
  lecturas de estado aplican el overlay según docs/contracts/freshness_policy.md sección 5.
- Todas las tools reciben un SesionCliente verificado y toman el customer_id de esa sesión. Ninguna
  tiene un parámetro customer_id (POL-AUTH-02, POL-AUTH-05, POL-AUTH-12).
- Una tarjeta, transacción o producto de otro cliente da el mismo error que uno que no existe:
  la consulta filtra por el cliente de la sesión y nunca pregunta si el id existe (POL-ANS-18).
"""

from dataclasses import dataclass
from datetime import date, datetime, time as hora_del_dia, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import update
from sqlmodel import Session, select

from models.banco import Caso, EventoEstadoTarjeta, TokenConfirmacion
from security.config import CARD_HASH_KEY
from services import auditoria, identidad
from services.identidad import ErrorSesion, SesionCliente

import duckdb
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

# Parámetros (docs/policy_cards.md, sección 11).
TX_DIAS_DEFECTO = 30 # TX_DEFAULT_DAYS
TX_DIAS_MAX = 90 # TX_MAX_DAYS
TX_FILAS_MAX = 20 # TX_MAX_ROWS
CONFIRMACION_TTL_SEG = 120 # CONFIRM_TTL_SEC
SALDO_ANTIGUEDAD_MAX_H = 24 # BALANCE_SNAPSHOT_MAX_AGE_H
CORTE_DIA_HABIL = timedelta(hours= 6) # Corte de las 06:00 (freshness_policy.md sección 1).

MENSAJES = {
    "NOT_FOUND": "No encuentro ese producto entre los suyos.",
    "SESSION_INVALID": "La sesión no es válida.",
    "CUSTOMER_STATUS_REVIEW": "Un asesor necesita revisar este caso.",
    "STEP_UP_REQUIRED": "Esta acción necesita una verificación adicional vigente para esta tarjeta.",
    "CONFIRMATION_INVALID": "La confirmación no es válida o venció.",
    "CONFIRMATION_USED": "Esta confirmación ya se usó.",
    "CARD_ALREADY_BLOCKED": "La tarjeta ya está bloqueada.",
    "CARD_NOT_ACTIVE": "El estado de la tarjeta no permite esta acción.",
    "ACTION_INVALID": "Acción no permitida.",
    "CASE_FILE_INVALID": "El expediente no cumple el contrato de la sección 8 de la política.",
    "GOLD_UNAVAILABLE": "Los datos del banco no están disponibles.",
}


class ErrorHerramienta(Exception):
    """Rechazo de una tool. `codigo` es para el orquestador; `mensaje` nunca distingue si un producto
    de otro cliente existe."""

    def __init__(self, codigo: str, mensaje: Optional[str] = None, detalle: Optional[str] = None):
        self.codigo = codigo
        self.mensaje = mensaje or MENSAJES.get(codigo, codigo)
        self.detalle = detalle # Solo para errores de contrato del llamador, nunca con datos de otro cliente.
        super().__init__(self.mensaje)


# --- Reloj del banco -----------------------------------------------------------------------------

_INICIO_PROCESO = time.monotonic()


def ahora_banco() -> datetime:
    """Hora del banco, sin zona (como los datos). Con RELOJ_SIMULADO (por ejemplo 2026-06-18T10:00:00,
    el reloj de las conversaciones golden) avanza desde ese valor; si no, es la hora UTC real."""
    base = os.getenv("RELOJ_SIMULADO")

    if base:
        return datetime.fromisoformat(base) + timedelta(seconds= time.monotonic() - _INICIO_PROCESO)

    return datetime.now(timezone.utc).replace(tzinfo= None)


def dia_habil(momento: datetime) -> date:
    return (momento - CORTE_DIA_HABIL).date()


# --- Lector de gold ------------------------------------------------------------------------------

# Solo las columnas que usan las tools. Las fechas de vigencia y last_updated no se cargan, así que
# ninguna tool puede mostrarlas (POL-ANS-13).
COLUMNAS_GOLD = {
    "customers": "customer_id, country, segment, customer_status",
    "cards": "card_id, customer_id, last4, card_number_hmac, product_type, status, source_file",
    "card_transactions": (
        "transaction_id, card_id, customer_id, transaction_datetime, transaction_type, amount, currency, "
        "merchant_name, status, response_code"
    ),
    "balance_products": (
        "product_id, customer_id, kind, last4, status, currency, current_balance, credit_limit, source_file, gold_loaded_at"
    ),
}
INDICES_GOLD = [
    ("cards", "customer_id"),
    ("cards", "card_number_hmac"),
    ("card_transactions", "customer_id"),
    ("balance_products", "customer_id"),
]
_PATRON_FECHA_RUTA = re.compile(r"year=(\d{4})/month=(\d{2})/day=(\d{2})")


def _literal(ruta: Path) -> str:
    return "'" + str(ruta).replace("'", "''") + "'"


def resolver_directorio_gold(valor: Optional[str]) -> Path:
    """GOLD_DIR puede ser la carpeta de las tablas o su carpeta padre (03_primary, que contiene gold/)."""
    if not valor:
        raise ErrorHerramienta("GOLD_UNAVAILABLE", detalle= "GOLD_DIR no está definido.")

    base = Path(valor)
    for candidato in (base, base / "gold"):
        if (candidato / "_load_log.parquet").is_file():
            return candidato

    raise ErrorHerramienta("GOLD_UNAVAILABLE", detalle= f"No hay tablas gold en {base}.")


class LectorGold:
    """Copia gold en una base DuckDB en memoria y la deja sin acceso a archivos. Se recarga cuando
    cambia _load_log.parquet (una carga publicada nueva, freshness_policy.md sección 3, paso 6)."""

    def __init__(self, directorio: Optional[Path] = None):
        self._directorio_fijo = Path(directorio) if directorio else None
        self._conexion: Optional[duckdb.DuckDBPyConnection] = None
        self._firma: Optional[Tuple[str, int, int]] = None
        self._candado = threading.Lock()

    def directorio(self) -> Path:
        return self._directorio_fijo or resolver_directorio_gold(os.getenv("GOLD_DIR"))

    def cursor(self) -> duckdb.DuckDBPyConnection:
        directorio = self.directorio()
        estado = (directorio / "_load_log.parquet").stat()
        firma = (str(directorio), estado.st_mtime_ns, estado.st_size)

        with self._candado:
            if self._conexion is None or firma != self._firma:
                nueva = self._cargar(directorio)
                if self._conexion is not None:
                    self._conexion.close()
                self._conexion, self._firma = nueva, firma
            return self._conexion.cursor()

    @staticmethod
    def _cargar(directorio: Path) -> duckdb.DuckDBPyConnection:
        conexion = duckdb.connect(":memory:")
        try:
            for tabla, columnas in COLUMNAS_GOLD.items():
                conexion.execute(
                    f"CREATE TABLE {tabla} AS SELECT {columnas} FROM read_parquet({_literal(directorio / f'{tabla}.parquet')})"
                )
            # Fecha de entrega de cada archivo fuente, de las cargas publicadas (freshness_policy.md sección 4).
            conexion.execute(
                "CREATE TABLE entregas AS SELECT f.path AS source_file, max(f.process_date) AS fecha_entrega "
                f"FROM (SELECT unnest(input_files) AS f FROM read_parquet({_literal(directorio / '_load_log.parquet')}) "
                "WHERE status = 'published') GROUP BY 1"
            )
            for tabla, columna in INDICES_GOLD:
                conexion.execute(f"CREATE INDEX idx_{tabla}_{columna} ON {tabla} ({columna})")
            # Desde aquí DuckDB no puede tocar el sistema de archivos, ni volver a permitirlo.
            conexion.execute("SET enable_external_access = false")
            conexion.execute("SET lock_configuration = true")
        except duckdb.Error as error:
            conexion.close()
            raise ErrorHerramienta("GOLD_UNAVAILABLE", detalle= str(error)) from error

        return conexion


lector = LectorGold()


def usar_gold(directorio: Optional[Path] = None) -> None:
    """Cambia el lector (las pruebas apuntan a un gold de prueba). Sin argumento vuelve a GOLD_DIR."""
    global lector
    lector = LectorGold(directorio)


def _consultar(sql: str, parametros: Optional[list] = None) -> List[Dict[str, Any]]:
    cursor = lector.cursor()
    try:
        cursor.execute(sql, parametros or [])
        columnas = [descripcion[0] for descripcion in cursor.description]
        return [dict(zip(columnas, fila)) for fila in cursor.fetchall()]
    finally:
        cursor.close()


# --- Overlay de estado (freshness_policy.md sección 5) -------------------------------------------

def _fecha_de_ruta(source_file: Optional[str]) -> Optional[date]:
    coincidencia = _PATRON_FECHA_RUTA.search(source_file or "")
    return date(*map(int, coincidencia.groups())) if coincidencia else None


def _ultimos_eventos(sesion: Session, ids: List[str]) -> Dict[str, EventoEstadoTarjeta]:
    if not ids:
        return {}

    eventos = sesion.exec(
        select(EventoEstadoTarjeta).where(EventoEstadoTarjeta.card_id.in_(ids)).order_by(EventoEstadoTarjeta.id)
    ).all()

    return {evento.card_id: evento for evento in eventos} # El último de cada tarjeta queda al final.


def _aplicar_overlay(sesion: Session, filas: List[Dict[str, Any]], clave: str) -> None:
    """El último evento del overlay manda si su día hábil es igual o posterior a la fecha de entrega
    de la fila de gold; si no, manda gold. Sin fecha de entrega conocida, manda el overlay (lo
    conservador para un bloqueo)."""
    ultimos = _ultimos_eventos(sesion, [fila[clave] for fila in filas])

    for fila in filas:
        evento = ultimos.get(fila[clave])
        if evento is None:
            continue
        entrega = fila.get("fecha_entrega") or _fecha_de_ruta(fila.get("source_file"))
        if entrega is None or dia_habil(evento.hora_evento) >= entrega:
            fila["status"] = evento.nuevo_estado


def _tarjetas_del_cliente(sesion: Session, customer_id: str, card_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = (
        "SELECT c.card_id, c.last4, c.product_type, c.status, c.source_file, e.fecha_entrega "
        "FROM cards c LEFT JOIN entregas e ON e.source_file = c.source_file WHERE c.customer_id = ?"
    )
    parametros: list = [customer_id]
    if card_id is not None:
        if not isinstance(card_id, str):
            return []
        sql += " AND c.card_id = ?"
        parametros.append(card_id)

    filas = _consultar(sql + " ORDER BY c.card_id", parametros)
    _aplicar_overlay(sesion, filas, "card_id")
    return filas


def _productos_saldo(sesion: Session, customer_id: str, product_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = (
        "SELECT b.product_id, b.kind, b.last4, b.status, b.currency, b.current_balance, b.credit_limit, "
        "b.source_file, e.fecha_entrega FROM balance_products b "
        "LEFT JOIN entregas e ON e.source_file = b.source_file WHERE b.customer_id = ?"
    )
    parametros: list = [customer_id]
    if product_id is not None:
        if not isinstance(product_id, str):
            return []
        sql += " AND b.product_id = ?"
        parametros.append(product_id)

    filas = _consultar(sql + " ORDER BY b.kind, b.product_id", parametros)
    _aplicar_overlay(sesion, filas, "product_id") # Una tarjeta de crédito tiene el mismo id en cards (GQ-28).
    return filas


# --- Consultas del IdP de prueba (no son tools) --------------------------------------------------

def estado_cliente(customer_id: str) -> Optional[str]:
    """customer_status de gold, para el inicio de sesión (POL-AUTH-09). None si el cliente no existe."""
    filas = _consultar("SELECT customer_status FROM customers WHERE customer_id = ?", [customer_id])
    return filas[0]["customer_status"] if filas else None


def pais_cliente(customer_id: str) -> Optional[str]:
    """País del cliente, solo para el formato de números de las plantillas (política 3b; gold_tables.md
    sección 2). Nunca se usa para decidir nada ni para inferir el idioma (POL-GEN-03)."""
    filas = _consultar("SELECT country FROM customers WHERE customer_id = ?", [customer_id])
    return filas[0]["country"] if filas else None


def buscar_clientes(
    *, q: Optional[str], pais: Optional[str], segmento: Optional[str], estado: Optional[str], pagina: int, tamano: int
) -> Tuple[List[Dict[str, Any]], bool]:
    """Búsqueda paginada del jurado (POL-AUTH-11): solo customer_id, país y segmento. Gold no tiene
    nombres (gold_tables.md sección 2), así que no hay nombre enmascarado que mostrar."""
    condiciones, parametros = [], []
    if q:
        condiciones.append("starts_with(customer_id, ?)")
        parametros.append(q.strip().upper())
    if pais:
        condiciones.append("country = ?")
        parametros.append(pais)
    if segmento:
        condiciones.append("segment = ?")
        parametros.append(segmento)
    if estado:
        condiciones.append("customer_status = ?")
        parametros.append(estado)

    donde = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
    filas = _consultar(
        f"SELECT customer_id, country, segment FROM customers{donde} ORDER BY customer_id LIMIT ? OFFSET ?",
        parametros + [tamano + 1, (pagina - 1) * tamano],
    )

    return filas[:tamano], len(filas) > tamano


# --- Tools ---------------------------------------------------------------------------------------

def _preparar(sesion: Session, sesion_cliente: SesionCliente, *, permitir_revision: bool = False):
    """Controles comunes: sesión de cliente vigente (POL-AUTH-03, 05) y estado del cliente (POL-AUTH-09)."""
    try:
        registro = identidad.exigir_sesion_cliente_vigente(sesion, sesion_cliente)
    except ErrorSesion as error:
        raise ErrorHerramienta(error.codigo, error.mensaje) from error

    if not permitir_revision and registro.customer_status in identidad.ESTADOS_REVISION:
        raise ErrorHerramienta("CUSTOMER_STATUS_REVIEW")

    return registro


def list_cards(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    """POL-ANS-01: id interno, últimos 4, tipo y estado (con el overlay aplicado)."""
    registro = _preparar(sesion, sesion_cliente)

    return [
        {"card_id": fila["card_id"], "last4": fila["last4"], "type": fila["product_type"], "status": fila["status"]}
        for fila in _tarjetas_del_cliente(sesion, registro.customer_id)
    ]


def get_card_status(sesion: Session, sesion_cliente: SesionCliente, card_id: str) -> Dict[str, Any]:
    """POL-ANS-02: estado actual con tipo y últimos 4. Sin historial, fecha ni causa."""
    registro = _preparar(sesion, sesion_cliente)
    filas = _tarjetas_del_cliente(sesion, registro.customer_id, card_id)

    if not filas:
        raise ErrorHerramienta("NOT_FOUND")

    return {"last4": filas[0]["last4"], "type": filas[0]["product_type"], "status": filas[0]["status"]}


def _transaccion_publica(fila: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "transaction_id": fila["transaction_id"],
        "date": fila["transaction_datetime"],
        "type": fila["transaction_type"],
        "amount": fila["amount"],
        "currency": fila["currency"],
        "merchant": fila["merchant_name"],
        "status": fila["status"],
        "response_code": fila["response_code"],
    }


def list_transactions(
    sesion: Session,
    sesion_cliente: SesionCliente,
    card_id: str,
    desde: Optional[date] = None,
    hasta: Optional[date] = None,
    comercio: Optional[str] = None,
    estado: Optional[str] = None,
    tipo: Optional[str] = None,
    monto_min: Optional[Decimal] = None,
    monto_max: Optional[Decimal] = None,
) -> Dict[str, Any]:
    """POL-ANS-03: transacciones de una tarjeta del cliente, por defecto los últimos TX_DIAS_DEFECTO
    días, nunca antes de TX_DIAS_MAX días atrás ni más de TX_FILAS_MAX filas (las más recientes)."""
    registro = _preparar(sesion, sesion_cliente)

    if not _tarjetas_del_cliente(sesion, registro.customer_id, card_id):
        raise ErrorHerramienta("NOT_FOUND")

    hoy = ahora_banco().date()
    limite = hoy - timedelta(days= TX_DIAS_MAX)
    hasta = min(hasta or hoy, hoy)
    desde = desde or hoy - timedelta(days= TX_DIAS_DEFECTO)
    recortada = desde < limite
    desde = max(desde, limite)

    sql = (
        "SELECT transaction_id, transaction_datetime, transaction_type, amount, currency, merchant_name, status, "
        "response_code FROM card_transactions WHERE customer_id = ? AND card_id = ? "
        "AND transaction_datetime >= ? AND transaction_datetime < ?"
    )
    parametros: list = [
        registro.customer_id, card_id,
        datetime.combine(desde, hora_del_dia.min), datetime.combine(hasta + timedelta(days= 1), hora_del_dia.min),
    ]
    for condicion, valor in (
        ("contains(lower(merchant_name), lower(?))", comercio),
        ("status = ?", estado),
        ("transaction_type = ?", tipo),
        ("amount >= ?", monto_min),
        ("amount <= ?", monto_max),
    ):
        if valor is not None:
            sql += f" AND {condicion}"
            parametros.append(valor)

    filas = _consultar(sql + " ORDER BY transaction_datetime DESC, transaction_id LIMIT ?", parametros + [TX_FILAS_MAX + 1])

    return {
        "card_id": card_id,
        "from": desde,
        "to": hasta,
        "window_capped": recortada, # Pidió historia anterior a TX_DIAS_MAX: decirlo y ofrecer transferencia.
        "truncated": len(filas) > TX_FILAS_MAX,
        "transactions": [_transaccion_publica(fila) for fila in filas[:TX_FILAS_MAX]],
    }


PLANTILLA_ESTADO = {"Approved": "POL-TXS-01", "Declined": "POL-TXS-02", "Pending": "POL-TXS-03", "Reversed": "POL-TXS-04"}
CODIGOS_DEC = {"05", "14", "51", "54"}


def plantillas_transaccion(estado: Optional[str], codigo: Optional[str]) -> Tuple[List[str], List[str]]:
    """Plantillas de la sección 6 que aplican, y reglas que el orquestador debe aplicar (avisos)."""
    plantillas: List[str] = []
    avisos: List[str] = []

    if estado in PLANTILLA_ESTADO:
        plantillas.append(PLANTILLA_ESTADO[estado])
    else:
        avisos.append("POL-ESC-05") # Estado desconocido (GQ-15).

    if estado == "Approved":
        if codigo in (None, "00"):
            plantillas.append("POL-DEC-92")
        else:
            avisos.append("POL-ESC-05") # Estado y código no concuerdan (GQ-17).
    elif codigo is None:
        plantillas.append("POL-DEC-90")
    elif codigo in CODIGOS_DEC:
        plantillas.append(f"POL-DEC-{codigo}")
    else:
        plantillas.append("POL-DEC-91")
        avisos.append("POL-ESC-05")

    return plantillas, avisos


def describe_transaction(sesion: Session, sesion_cliente: SesionCliente, transaction_id: str) -> Dict[str, Any]:
    """POL-ANS-04: campos de la transacción, últimos 4 de su tarjeta y plantillas fijas que aplican."""
    registro = _preparar(sesion, sesion_cliente)

    if not isinstance(transaction_id, str):
        raise ErrorHerramienta("NOT_FOUND")

    filas = _consultar(
        "SELECT t.transaction_id, t.card_id, c.last4, t.transaction_datetime, t.transaction_type, t.amount, t.currency, "
        "t.merchant_name, t.status, t.response_code FROM card_transactions t JOIN cards c ON c.card_id = t.card_id "
        "WHERE t.transaction_id = ? AND t.customer_id = ? AND c.customer_id = ?",
        [transaction_id, registro.customer_id, registro.customer_id],
    )
    if not filas:
        raise ErrorHerramienta("NOT_FOUND")

    fila = filas[0]
    plantillas, avisos = plantillas_transaccion(fila["status"], fila["response_code"])

    return {**_transaccion_publica(fila), "card_id": fila["card_id"], "last4": fila["last4"], "templates": plantillas, "notices": avisos}


def list_balance_products(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    """POL-ANS-17: tarjetas de crédito y cuentas de ahorro que no están Closed."""
    registro = _preparar(sesion, sesion_cliente)

    return [
        {"product_id": fila["product_id"], "kind": fila["kind"], "last4": fila["last4"], "status": fila["status"]}
        for fila in _productos_saldo(sesion, registro.customer_id)
        if fila["status"] != "Closed"
    ]


def _as_of_saldos() -> datetime:
    """as_of = max(gold_loaded_at) de balance_products (política sección 3b)."""
    return _consultar("SELECT max(gold_loaded_at) AS as_of FROM balance_products")[0]["as_of"]


def plantillas_saldo(tipo: str, saldo: Decimal, limite: Optional[Decimal], as_of: datetime, ahora: datetime) -> List[str]:
    if tipo == "credit_card":
        plantillas = ["POL-BAL-06", "POL-BAL-04"] if limite is None or saldo > limite else ["POL-BAL-01"]
    else:
        plantillas = ["POL-BAL-02"]

    if ahora - as_of > timedelta(hours= SALDO_ANTIGUEDAD_MAX_H):
        plantillas.append("POL-BAL-03")

    return plantillas


def get_balance(sesion: Session, sesion_cliente: SesionCliente, product_id: str) -> Dict[str, Any]:
    """POL-ANS-15, 16: saldo y límite registrados, con as_of. Se lee en cada llamada (POL-GEN-07 b)."""
    registro = _preparar(sesion, sesion_cliente)
    filas = [fila for fila in _productos_saldo(sesion, registro.customer_id, product_id) if fila["status"] != "Closed"]

    if not filas:
        raise ErrorHerramienta("NOT_FOUND")

    fila = filas[0]
    as_of = _as_of_saldos()
    resultado = {
        "product_id": fila["product_id"],
        "kind": fila["kind"],
        "last4": fila["last4"],
        "status": fila["status"],
        "currency": fila["currency"],
        "current_balance": fila["current_balance"],
        "as_of": as_of,
    }
    if fila["kind"] == "credit_card":
        resultado["credit_limit"] = fila["credit_limit"] # Puede ser nulo (POL-BAL-06).

    resultado["templates"] = plantillas_saldo(fila["kind"], fila["current_balance"], fila["credit_limit"], as_of, ahora_banco())
    return resultado


# --- Acción con efecto: bloqueo ------------------------------------------------------------------

def _hash_token(secreto: str) -> str:
    return hashlib.sha256(secreto.encode("utf-8")).hexdigest()


def emitir_token_confirmacion(sesion: Session, sesion_cliente: SesionCliente, card_id: str, accion: str = "block_card") -> Dict[str, Any]:
    """El gateway emite el token cuando muestra el aviso de confirmación (T-27, T-28). Requiere un
    step-up vigente para esta tarjeta. Ligado a (sesión, tarjeta, acción), CONFIRMACION_TTL_SEG
    segundos, un solo uso; un token nuevo anula el anterior de la misma tarjeta (POL-ACT-02)."""
    registro = _preparar(sesion, sesion_cliente)

    if accion not in identidad.ACCIONES_CON_EFECTO:
        raise ErrorHerramienta("ACTION_INVALID")
    if identidad.step_up_valido(sesion, registro.id, card_id, accion) is None:
        raise ErrorHerramienta("STEP_UP_REQUIRED")

    tarjetas = _tarjetas_del_cliente(sesion, registro.customer_id, card_id)
    if not tarjetas:
        raise ErrorHerramienta("NOT_FOUND")

    ahora = identidad.ahora_utc()
    sesion.exec(
        update(TokenConfirmacion)
        .where(
            TokenConfirmacion.sesion_id == registro.id,
            TokenConfirmacion.card_id == card_id,
            TokenConfirmacion.accion == accion,
            TokenConfirmacion.usado_en == None, # noqa: E711
            TokenConfirmacion.anulado_en == None, # noqa: E711
        )
        .values(anulado_en= ahora)
    )

    secreto = secrets.token_urlsafe(24)
    token = TokenConfirmacion(
        id= "CT-" + secrets.token_hex(8).upper(),
        token_hash= _hash_token(secreto),
        sesion_id= registro.id,
        card_id= card_id,
        accion= accion,
        creado_en= ahora,
        expira_en= ahora + timedelta(seconds= CONFIRMACION_TTL_SEG),
    )
    sesion.add(token)
    auditoria.registrar_evento(
        sesion, event_type= "confirmation", conversation_id= registro.conversacion_id, session_id= registro.id,
        actor= "action_gateway", auth_level= "L2", state= "AWAIT_CONFIRMATION", rule_ids= ["POL-ACT-02"],
        customer_id= registro.customer_id, session_origin= identidad.origen_sesion(registro),
        campos= {
            "confirmation_event": "requested", "confirmation_token_id": token.id, "action": accion,
            "card_ref": auditoria.seudonimo(card_id), "last4": tarjetas[0]["last4"], "card_type": tarjetas[0]["product_type"],
            "prompt_turn_index": 0, "expires_at": auditoria.iso_utc(token.expira_en), "outcome": None, "answer_turn_index": None,
        },
    )
    sesion.commit()

    return {"confirmation_token": secreto, "confirmation_token_id": token.id, "expires_at": token.expira_en}


def _consumir_token(
    sesion: Session, sesion_id: str, card_id: str, secreto: Any, ahora: datetime
) -> Tuple[Optional[TokenConfirmacion], Optional[str]]:
    if not isinstance(secreto, str) or not secreto:
        return None, "CONFIRMATION_INVALID"

    token = sesion.exec(select(TokenConfirmacion).where(TokenConfirmacion.token_hash == _hash_token(secreto))).first()

    # Un token de otra sesión, otra tarjeta u otra acción no sirve (POL-ACT-02, POL-ACT-04, POL-AUTH-07).
    if token is None or token.sesion_id != sesion_id or token.card_id != card_id or token.accion != "block_card":
        return None, "CONFIRMATION_INVALID"
    if token.usado_en is not None:
        return token, "CONFIRMATION_USED"
    if token.anulado_en is not None or token.expira_en <= ahora:
        return token, "CONFIRMATION_INVALID"

    consumido = sesion.exec(
        update(TokenConfirmacion)
        .where(TokenConfirmacion.id == token.id, TokenConfirmacion.usado_en == None) # noqa: E711
        .values(usado_en= ahora)
    ).rowcount == 1

    return token, None if consumido else "CONFIRMATION_USED"


def block_card(sesion: Session, sesion_cliente: SesionCliente, card_id: str, token_confirmacion: str) -> Dict[str, Any]:
    """Bloquea una tarjeta en el overlay. Hace cumplir por sí misma POL-ACT-01, 02 y 06
    (docs/contracts/state_machine.md sección 2):

    1. step-up vigente, sin usar, ligado a esta tarjeta y a block_card; se consume aquí, sea cual
       sea el resultado (POL-AUTH-04);
    2. la tarjeta es del cliente de la sesión; si no, el mismo error que una inexistente (POL-AUTH-05);
    3. token de confirmación válido para (sesión, tarjeta, acción), de un solo uso (POL-ACT-02, 06);
    4. estado efectivo actual Active (POL-ACT-01 c).

    Devuelve solo la aceptación. El action gateway verifica releyendo get_card_status (POL-ACT-05).
    Nunca escribe en el Parquet de gold.
    """
    registro = _preparar(sesion, sesion_cliente)
    ahora = identidad.ahora_utc()
    accion_id = "BLK-" + secrets.token_hex(6).upper()
    precondiciones = {
        "auth_level": identidad.nivel_actual(sesion, registro),
        "step_up_valid": False,
        "owner_match": None,
        "pre_status": None,
        "pre_status_tool_call_id": None,
    }
    contexto: Dict[str, Optional[str]] = {"step_up_id": None, "token_id": None, "last4": None}

    def auditar(executed: str, error_code: Optional[str]) -> None:
        auditoria.registrar_evento(
            sesion, event_type= "action_result", conversation_id= registro.conversacion_id, session_id= registro.id,
            actor= "action_gateway", auth_level= precondiciones["auth_level"], state= "EXECUTING",
            rule_ids= ["POL-ACT-01", "POL-ACT-02", "POL-ACT-06", "POL-ACT-09"], customer_id= registro.customer_id,
            session_origin= identidad.origen_sesion(registro),
            campos= {
                "action_id": accion_id, "action": "block_card", "card_ref": auditoria.seudonimo(str(card_id)),
                "last4": contexto["last4"], "confirmation_token_id": contexto["token_id"], "step_up_id": contexto["step_up_id"],
                "preconditions": precondiciones, "tool_call_id": None, "requested_at": auditoria.iso_utc(ahora),
                "executed": executed, "error_code": error_code,
            },
        )

    def rechazar(codigo: str) -> ErrorHerramienta:
        auditar("false", codigo)
        sesion.commit() # Guarda lo consumido (step-up, token) aunque la acción no corra.
        return ErrorHerramienta(codigo)

    step_up = identidad.step_up_valido(sesion, registro.id, card_id, "block_card") if isinstance(card_id, str) else None
    if step_up is None or not identidad.consumir_step_up(sesion, step_up):
        raise rechazar("STEP_UP_REQUIRED")
    precondiciones["step_up_valid"] = True
    contexto["step_up_id"] = step_up.id

    tarjetas = _tarjetas_del_cliente(sesion, registro.customer_id, card_id)
    precondiciones["owner_match"] = bool(tarjetas)
    if not tarjetas:
        raise rechazar("NOT_FOUND")
    contexto["last4"] = tarjetas[0]["last4"]

    token, codigo = _consumir_token(sesion, registro.id, card_id, token_confirmacion, ahora)
    contexto["token_id"] = token.id if token else None
    if codigo:
        raise rechazar(codigo)

    precondiciones["pre_status"] = tarjetas[0]["status"]
    if tarjetas[0]["status"] == "Blocked":
        raise rechazar("CARD_ALREADY_BLOCKED")
    if tarjetas[0]["status"] != "Active":
        raise rechazar("CARD_NOT_ACTIVE") # Suspended o Closed: transferir (POL-ESC-12).

    sesion.add(EventoEstadoTarjeta(
        card_id= card_id,
        nuevo_estado= "Blocked",
        hora_evento= ahora_banco(),
        registrado_en= ahora,
        accion_id= accion_id,
        sesion_id= registro.id,
    ))
    token.request_id = accion_id
    sesion.add(token)
    auditar("true", None)
    sesion.commit()

    return {"accepted": True, "request_id": accion_id}


# --- Transferencia a humano ----------------------------------------------------------------------

CAMPOS_CONTENIDO = ("request", "verified_facts", "actions_taken", "evidence", "unresolved_questions")
PRIORIDADES = {"urgent", "security", "normal"}
CLAVES_HECHO = {"fact", "value", "tool_call_id"}
CLAVES_ACCION = {"action", "card_last4", "confirmation_token_id", "requested_at", "executed", "verified", "verification_tool_call_id"}
_PATRON_REGLA = re.compile(r"^POL-[A-Z]+-\d{2}$")


def _json_default(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    raise TypeError(f"Tipo no serializable en el expediente: {type(valor).__name__}")


def _validar_expediente(expediente: Any, customer_id: str) -> None:
    def invalido(detalle: str) -> ErrorHerramienta:
        return ErrorHerramienta("CASE_FILE_INVALID", detalle= detalle)

    if not isinstance(expediente, dict):
        raise invalido("El expediente debe ser un objeto.")

    faltan = [campo for campo in CAMPOS_CONTENIDO if campo not in expediente]
    if faltan:
        raise invalido(f"Faltan campos de contenido: {faltan}. Una lista vacía se permite, pero explícita.")

    if not (isinstance(expediente["request"], dict) and expediente["request"]) and not (
        isinstance(expediente["request"], str) and expediente["request"].strip()
    ):
        raise invalido("request debe describir lo que pide el cliente (POL-HND-10).")
    if not isinstance(expediente["verified_facts"], list) or any(
        not isinstance(hecho, dict) or not CLAVES_HECHO <= hecho.keys() for hecho in expediente["verified_facts"]
    ):
        raise invalido("verified_facts: lista de {fact, value, tool_call_id} (POL-HND-11).")
    if not isinstance(expediente["actions_taken"], list) or any(
        not isinstance(accion, dict) or not CLAVES_ACCION <= accion.keys() or str(accion["executed"]).lower() not in {"true", "false", "unknown"}
        for accion in expediente["actions_taken"]
    ):
        raise invalido("actions_taken: campos de POL-HND-12 y executed en true, false o unknown (POL-ACT-09).")
    if not isinstance(expediente["evidence"], (dict, list)):
        raise invalido("evidence debe ser un objeto o una lista (POL-HND-13).")
    if not isinstance(expediente["unresolved_questions"], list) or not expediente["unresolved_questions"] or any(
        not isinstance(pregunta, str) or not pregunta.strip() for pregunta in expediente["unresolved_questions"]
    ):
        raise invalido("unresolved_questions: al menos una pregunta, siempre con el motivo (POL-HND-14).")

    reglas = expediente.get("reason_rule_ids")
    if not isinstance(reglas, list) or not reglas or any(not isinstance(r, str) or not _PATRON_REGLA.match(r) for r in reglas):
        raise invalido("reason_rule_ids: lista no vacía de ids POL-… (POL-HND-15).")
    if expediente.get("priority") not in PRIORIDADES:
        raise invalido("priority debe ser urgent, security o normal (POL-HND-15).")
    if expediente.get("language") not in ("es", "pt"):
        raise invalido("language debe ser es o pt.")
    if "customer_id" in expediente and expediente["customer_id"] != customer_id:
        raise invalido("customer_id no coincide con la sesión; se toma siempre de la sesión.")


def open_handoff(sesion: Session, sesion_cliente: SesionCliente, expediente: Dict[str, Any], idempotency_key: str) -> Dict[str, str]:
    """Abre un caso con el expediente de la sección 8 (POL-HND-10 a 15). Se permite también a clientes
    Suspended o Closed (POL-AUTH-09). Reintentar con la misma clave devuelve el mismo caso (POL-REL-02).
    customer_id, auth_level, conversation_ref, created_at y policy_version los pone el servidor."""
    registro = _preparar(sesion, sesion_cliente, permitir_revision= True)

    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        raise ErrorHerramienta("CASE_FILE_INVALID", detalle= "Falta la clave de idempotencia.")

    existente = sesion.exec(select(Caso).where(Caso.idempotency_key == idempotency_key)).first()
    if existente is not None:
        if existente.customer_id != registro.customer_id:
            raise ErrorHerramienta("CASE_FILE_INVALID", detalle= "La clave de idempotencia ya se usó.")
        return {"case_id": existente.case_id}

    _validar_expediente(expediente, registro.customer_id)
    limpio = json.loads(json.dumps(expediente, default= _json_default))

    caso = Caso(
        case_id= "CASE-" + secrets.token_hex(6).upper(),
        idempotency_key= idempotency_key,
        created_at= identidad.ahora_utc(),
        policy_version= auditoria.POLICY_VERSION,
        reason_rule_ids= limpio["reason_rule_ids"],
        language= limpio["language"],
        customer_id= registro.customer_id,
        auth_level= identidad.nivel_actual(sesion, registro),
        priority= limpio["priority"],
        conversation_ref= registro.conversacion_id,
        appended_messages= limpio.get("appended_messages", []),
        request= limpio["request"],
        verified_facts= limpio["verified_facts"],
        actions_taken= limpio["actions_taken"],
        evidence= limpio["evidence"],
        unresolved_questions= limpio["unresolved_questions"],
    )
    sesion.add(caso)
    auditoria.registrar_evento(
        sesion, event_type= "handoff", conversation_id= registro.conversacion_id, session_id= registro.id,
        actor= "handoff_service", auth_level= caso.auth_level, state= "HANDOFF",
        rule_ids= ["POL-HND-10", "POL-HND-11", "POL-HND-12", "POL-HND-13", "POL-HND-14", "POL-HND-15"],
        customer_id= registro.customer_id, session_origin= identidad.origen_sesion(registro),
        campos= {
            "handoff_event": "opened", "case_id": caso.case_id, "idempotency_key": idempotency_key,
            "priority": caso.priority, "reason_rule_ids": caso.reason_rule_ids,
            "case_file_fields_present": {campo: True for campo in CAMPOS_CONTENIDO},
            "case_file_digest": hashlib.sha256(auditoria.json_canonico(limpio).encode("utf-8")).hexdigest(),
            "counts": {
                "verified_facts": len(caso.verified_facts), "actions_taken": len(caso.actions_taken),
                "evidence": len(caso.evidence), "unresolved_questions": len(caso.unresolved_questions),
            },
        },
    )
    sesion.commit()

    return {"case_id": caso.case_id}


ORDEN_PRIORIDAD = {"normal": 0, "security": 1, "urgent": 2} # POL-HND-15: urgent > security > normal.


def anexar_mensaje_caso(
    sesion: Session, sesion_cliente: SesionCliente, case_id: str, mensaje_redactado: str,
    reglas: List[str], prioridad: Optional[str] = None,
) -> Dict[str, Any]:
    """T-38 (POL-HND-06): después de la transferencia, cada mensaje del cliente se agrega a su caso,
    con las reglas ESC que el mensaje dispara y, si corresponde, una prioridad más alta. No es una
    tool: no lee datos del banco. Solo el caso del cliente de la sesión."""
    registro = _preparar(sesion, sesion_cliente, permitir_revision= True)
    caso = sesion.get(Caso, case_id)
    if caso is None or caso.customer_id != registro.customer_id:
        raise ErrorHerramienta("NOT_FOUND")

    caso.appended_messages = [*caso.appended_messages, {"text_redacted": mensaje_redactado,
                                                        "received_at": identidad.ahora_utc().isoformat()}]
    nuevas = [r for r in reglas if r not in caso.reason_rule_ids]
    if nuevas:
        caso.reason_rule_ids = [*caso.reason_rule_ids, *nuevas]
    subio = prioridad is not None and ORDEN_PRIORIDAD[prioridad] > ORDEN_PRIORIDAD[caso.priority]
    if subio:
        caso.priority = prioridad
    sesion.add(caso)

    for evento in ["message_appended"] + (["priority_raised"] if subio else []):
        auditoria.registrar_evento(
            sesion, event_type= "handoff", conversation_id= registro.conversacion_id, session_id= registro.id,
            actor= "handoff_service", auth_level= identidad.nivel_actual(sesion, registro), state= "HANDED_OFF",
            rule_ids= ["POL-HND-06", *reglas], customer_id= registro.customer_id,
            session_origin= identidad.origen_sesion(registro),
            campos= {"handoff_event": evento, "case_id": caso.case_id, "idempotency_key": caso.idempotency_key,
                     "priority": caso.priority, "reason_rule_ids": caso.reason_rule_ids},
        )
    sesion.commit()
    return {"case_id": caso.case_id, "priority": caso.priority}


# --- Comprobación de propiedad de un número completo (POL-ESC-10) --------------------------------

def hmac_numero_tarjeta(numero: str) -> str:
    """card_number_hmac de gold: HMAC-SHA256 con los bytes UTF-8 de CARD_HASH_KEY como clave y los
    bytes UTF-8 del número como mensaje, en hex minúscula (docs/findings/gold_run.md, desviación 9)."""
    return hmac.new(CARD_HASH_KEY.encode("utf-8"), numero.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen= True)
class ResultadoPropiedad:
    """Solo para el contador de seguridad y el audit log, nunca para una respuesta ni el LLM (POL-AUTH-05).
    De una tarjeta ajena no se devuelve ningún dato: ni su id."""
    resultado: str # "propia", "ajena" o "no_encontrada"
    card_id: Optional[str] # Solo si es propia.
    card_number_hmac: str # Para el audit log (AL-P5).
    last4: str


def comprobar_numero_tarjeta(sesion: Session, sesion_cliente: SesionCliente, numero_tecleado: str) -> ResultadoPropiedad:
    """La única consulta fuera del cliente de la sesión. Exige un número completo: unos últimos 4
    coinciden con miles de tarjetas y nunca activan la comprobación (POL-ESC-10)."""
    registro = _preparar(sesion, sesion_cliente)
    digitos = re.sub(r"[\s-]", "", numero_tecleado or "")

    if not re.fullmatch(r"\d{13,19}", digitos):
        raise ValueError("La comprobación de propiedad solo acepta un número completo de 13 a 19 dígitos.")

    huella = hmac_numero_tarjeta(digitos)
    filas = _consultar("SELECT card_id, customer_id FROM cards WHERE card_number_hmac = ?", [huella])

    if not filas:
        return ResultadoPropiedad("no_encontrada", None, huella, digitos[-4:])
    if filas[0]["customer_id"] == registro.customer_id:
        return ResultadoPropiedad("propia", filas[0]["card_id"], huella, digitos[-4:])
    return ResultadoPropiedad("ajena", None, huella, digitos[-4:])


# Registro de tools del banco. No hay tool para desbloquear, reactivar ni reemplazar tarjetas
# (POL-ACT-07), ni para mover dinero (POL-ACT-08). authenticate y step_up son del IdP de prueba.
HERRAMIENTAS = {
    "list_cards": list_cards,
    "get_card_status": get_card_status,
    "list_transactions": list_transactions,
    "describe_transaction": describe_transaction,
    "list_balance_products": list_balance_products,
    "get_balance": get_balance,
    "block_card": block_card,
    "open_handoff": open_handoff,
}
