"""IdP de prueba: identidad SIMULADA para la demo y la evaluación. No es un proveedor de identidad
real (docs/policy_cards.md, POL-AUTH-10 a 13; límites en POL-AUTH-13 y docs/operations.md sección 5).

- Sesiones del lado del servidor con expiración por inactividad y absoluta (POL-AUTH-03).
- Step-up L2 con un código de un solo uso, ligado a una tarjeta y una acción (POL-AUTH-04, 06).
- Sesiones de prueba y códigos que abre un jurado, registrados en el audit log (POL-AUTH-11).

Las tools del banco reciben un `SesionCliente`, que solo se construye desde un token verificado.
Ninguna función de este módulo ni del banco acepta un customer_id escrito por el cliente (POL-AUTH-02).
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Deque, Dict, List, Optional, Tuple

from sqlalchemy import update
from sqlmodel import Session, select

from models.identidad import CodigoOTPPrueba, SesionIdentidad, StepUp
from security.config import (
    ALGORITHM,
    BUSQUEDA_MAX_POR_MINUTO,
    OTP_PRUEBA_TTL_MIN,
    SECRET_KEY,
    SESION_INACTIVIDAD_MIN,
    SESION_MAX_MIN,
    STEP_UP_MAX_FALLOS,
    STEP_UP_TTL_MIN,
)
from services import auditoria

import hashlib
import hmac
import jwt
import secrets
import threading
import time

ROLES = ("cliente", "agente", "jurado")
ESTADOS_REVISION = {"Suspended", "Closed"} # POL-AUTH-09: solo transferencia.
ACCIONES_CON_EFECTO = {"block_card"} # La única acción con efecto (sección 4 de la política).
AVISO_IDP = "IdP de prueba simulado: no es un proveedor de identidad real (POL-AUTH-13)."
MENSAJE_SESION_VENCIDA = "La sesión expiró o se cerró. Inicie sesión de nuevo."


class ErrorSesion(Exception):
    def __init__(self, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass(frozen= True)
class SesionCliente:
    """Lo único que reciben las tools del banco. El customer_id sale del registro de sesión."""
    sesion_id: str
    customer_id: str
    customer_status: Optional[str]
    idioma: Optional[str]
    conversacion_id: str


def ahora_utc() -> datetime:
    """Hora UTC con zona (SQLModel guarda y devuelve UTC). Las pruebas la reemplazan para simular el paso del tiempo."""
    return datetime.now(timezone.utc)


def _nuevo_id(prefijo: str) -> str:
    return prefijo + secrets.token_urlsafe(24)


# --- Sesiones ------------------------------------------------------------------------------------

def crear_sesion(
    sesion: Session,
    *,
    rol: str,
    metodo: str,
    usuario_id: Optional[int] = None,
    customer_id: Optional[str] = None,
    customer_status: Optional[str] = None,
    idioma: Optional[str] = None,
    emitida_por_usuario_id: Optional[int] = None,
) -> SesionIdentidad:
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: {rol}")

    ahora = ahora_utc()
    registro = SesionIdentidad(
        id= _nuevo_id("ses_"),
        usuario_id= usuario_id,
        rol= rol,
        customer_id= customer_id,
        customer_status= customer_status,
        idioma= idioma,
        metodo= metodo,
        emitida_por_usuario_id= emitida_por_usuario_id,
        conversacion_id= "conv_" + auditoria.uuid7(),
        creada_en= ahora,
        ultima_actividad_en= ahora,
        expira_absoluta_en= ahora + timedelta(minutes= SESION_MAX_MIN),
    )
    sesion.add(registro)
    sesion.flush()

    return registro


def emitir_token(registro: SesionIdentidad) -> str:
    """JWT que solo nombra la sesión; su exp es el vencimiento absoluto, como respaldo del registro."""
    datos = {
        "sub": str(registro.usuario_id) if registro.usuario_id is not None else "",
        "sid": registro.id,
        "rol": registro.rol,
        "exp": registro.expira_absoluta_en,
    }
    return jwt.encode(datos, SECRET_KEY, algorithm= ALGORITHM)


def expira_inactividad_en(registro: SesionIdentidad) -> datetime:
    return min(registro.ultima_actividad_en + timedelta(minutes= SESION_INACTIVIDAD_MIN), registro.expira_absoluta_en)


def nivel_actual(sesion: Session, registro: SesionIdentidad) -> str:
    """L2 mientras haya un step-up vigente y sin usar en la sesión; si no, L1 (POL-AUTH-01)."""
    vigente = sesion.exec(
        select(StepUp).where(
            StepUp.sesion_id == registro.id,
            StepUp.usado_en == None, # noqa: E711
            StepUp.expira_en > ahora_utc(),
        )
    ).first()

    return "L2" if vigente else "L1"


def auditar_sesion(
    sesion: Session,
    registro: SesionIdentidad,
    session_event: str,
    *,
    rule_ids: List[str],
    state: str,
    auth_level_before: str,
    auth_level_after: str,
    expires_at: Optional[datetime] = None,
    step_up: Optional[dict] = None,
    customer_status: Optional[str] = None,
    test_idp: Optional[dict] = None,
) -> None:
    """Evento `session` (docs/contracts/audit_log.md 4.1). `test_idp` es la extensión aditiva que
    registra quién abrió una sesión o emitió un código en el IdP de prueba (docs/decisions_log.md, D-21)."""
    campos = {
        "session_event": session_event,
        "auth_level_before": auth_level_before,
        "auth_level_after": auth_level_after,
        "expires_at": auditoria.iso_utc(expires_at),
        "step_up": step_up,
        "failure_count": registro.step_up_fallos,
        "language_preference": registro.idioma,
        "customer_status": customer_status,
        "resume_intent": None,
    }
    if test_idp is not None:
        campos["test_idp"] = test_idp

    auditoria.registrar_evento(
        sesion,
        event_type= "session",
        conversation_id= registro.conversacion_id,
        session_id= registro.id,
        actor= "identity",
        auth_level= auth_level_after,
        state= state,
        rule_ids= rule_ids,
        customer_id= registro.customer_id,
        campos= campos,
        session_origin= origen_sesion(registro),
    )


def origen_sesion(registro: SesionIdentidad) -> dict:
    """Cómo se abrió la sesión, para cada evento del audit log: contraseña de un usuario sembrado o
    IdP de prueba con el id del jurado (POL-AUTH-11)."""
    if registro.metodo == "idp_prueba":
        return {"method": "test_idp", "issued_by_user_id": registro.emitida_por_usuario_id}
    return {"method": "password", "user_id": registro.usuario_id, "role": registro.rol}


def decodificar_token(token: str, *, permitir_vencido: bool = False) -> str:
    """sid del JWT. La firma siempre se verifica. Con permitir_vencido el chat puede reconocer una
    sesión cuyo JWT ya venció para responder con G-01 (pedir un nuevo inicio de sesión) sin datos."""
    try:
        datos = jwt.decode(token, SECRET_KEY, algorithms= [ALGORITHM],
                           options= {"require": ["exp", "sid"], "verify_exp": not permitir_vencido})
    except jwt.InvalidTokenError:
        raise ErrorSesion("TOKEN_INVALID", "No se pudo validar las credenciales.")

    return datos["sid"]


def comprobar_vigencia(sesion: Session, registro: SesionIdentidad, *, tocar: bool) -> None:
    """POL-AUTH-03: inactividad de SESION_INACTIVIDAD_MIN o vencimiento absoluto de SESION_MAX_MIN.
    La primera vez que se detecta, la sesión se cierra y se audita; después siempre es SESSION_EXPIRED."""
    if registro.cerrada_en is not None:
        raise ErrorSesion("SESSION_EXPIRED", MENSAJE_SESION_VENCIDA)

    ahora = ahora_utc()
    motivo = None

    if ahora >= registro.expira_absoluta_en:
        motivo = "maximo"
    elif ahora - registro.ultima_actividad_en >= timedelta(minutes= SESION_INACTIVIDAD_MIN):
        motivo = "inactividad"

    if motivo:
        nivel = nivel_actual(sesion, registro)
        registro.cerrada_en = ahora
        registro.motivo_cierre = motivo
        sesion.add(registro)
        auditar_sesion(sesion, registro, "expired", rule_ids= ["POL-AUTH-03"], state= "SESSION_EXPIRED",
                       auth_level_before= nivel, auth_level_after= "L0")
        sesion.commit()
        raise ErrorSesion("SESSION_EXPIRED", MENSAJE_SESION_VENCIDA)

    if tocar:
        registro.ultima_actividad_en = ahora
        sesion.add(registro)
        sesion.commit()


def sesion_desde_token(sesion: Session, token: str, *, tocar: bool = True) -> SesionIdentidad:
    sesion_id = decodificar_token(token)
    registro = sesion.get(SesionIdentidad, sesion_id)

    if registro is None:
        raise ErrorSesion("TOKEN_INVALID", "No se pudo validar las credenciales.")

    comprobar_vigencia(sesion, registro, tocar= tocar)
    return registro


def sesion_cliente_desde(registro: SesionIdentidad) -> SesionCliente:
    if registro.rol != "cliente" or not registro.customer_id:
        raise ErrorSesion("NOT_A_CUSTOMER_SESSION", "Esta sesión no corresponde a un cliente.")

    return SesionCliente(
        sesion_id= registro.id,
        customer_id= registro.customer_id,
        customer_status= registro.customer_status,
        idioma= registro.idioma,
        conversacion_id= registro.conversacion_id,
    )


def verificar_sesion_cliente(sesion: Session, token: str) -> SesionCliente:
    """Única entrada a las tools: token verificado → sesión vigente → cliente de esa sesión."""
    return sesion_cliente_desde(sesion_desde_token(sesion, token))


def exigir_sesion_cliente_vigente(sesion: Session, sesion_cliente: SesionCliente) -> SesionIdentidad:
    """Lo llaman las tools en cada llamada. La sesión debe existir, ser de un cliente, seguir vigente
    y estar ligada al mismo customer_id; si no, la tool no corre (POL-AUTH-03, POL-AUTH-05)."""
    if not isinstance(sesion_cliente, SesionCliente):
        raise ErrorSesion("SESSION_INVALID", "La sesión no es válida.")

    registro = sesion.get(SesionIdentidad, sesion_cliente.sesion_id)

    if registro is None or registro.rol != "cliente" or registro.customer_id != sesion_cliente.customer_id:
        raise ErrorSesion("SESSION_INVALID", "La sesión no es válida.")

    comprobar_vigencia(sesion, registro, tocar= True)
    return registro


def cerrar_sesion(sesion: Session, registro: SesionIdentidad) -> None:
    nivel = nivel_actual(sesion, registro)
    registro.cerrada_en = ahora_utc()
    registro.motivo_cierre = "cierre"
    sesion.add(registro)
    auditar_sesion(sesion, registro, "ended", rule_ids= ["POL-AUTH-03"], state= "ENDED",
                   auth_level_before= nivel, auth_level_after= "L0")
    sesion.commit()


# --- Step-up (L2) ------------------------------------------------------------------------------

def _hash_codigo(sesion_id: str, codigo: str) -> str:
    return hmac.new(SECRET_KEY.encode("utf-8"), f"{sesion_id}:{codigo}".encode("utf-8"), hashlib.sha256).hexdigest()


def _anular_codigos_pendientes(sesion: Session, sesion_id: str, ahora: datetime) -> None:
    sesion.exec(
        update(CodigoOTPPrueba)
        .where(
            CodigoOTPPrueba.sesion_id == sesion_id,
            CodigoOTPPrueba.usado_en == None, # noqa: E711
            CodigoOTPPrueba.anulado_en == None, # noqa: E711
        )
        .values(anulado_en= ahora)
    )


def step_up_valido(sesion: Session, sesion_id: str, card_id: str, accion: str) -> Optional[StepUp]:
    """Un step-up vigente, sin usar, ligado a esta tarjeta y esta acción (POL-AUTH-04)."""
    return sesion.exec(
        select(StepUp)
        .where(
            StepUp.sesion_id == sesion_id,
            StepUp.card_id == card_id,
            StepUp.accion == accion,
            StepUp.usado_en == None, # noqa: E711
            StepUp.expira_en > ahora_utc(),
        )
        .order_by(StepUp.creado_en.desc())
    ).first()


def consumir_step_up(sesion: Session, step_up: StepUp) -> bool:
    """Marca el step-up como usado de forma atómica; False si otra llamada lo usó primero."""
    resultado = sesion.exec(
        update(StepUp)
        .where(StepUp.id == step_up.id, StepUp.usado_en == None) # noqa: E711
        .values(usado_en= ahora_utc())
    )
    return resultado.rowcount == 1


def realizar_step_up(sesion: Session, registro: SesionIdentidad, codigo: str, card_id: str, accion: str) -> StepUp:
    """POST /autenticacion/step-up: el código del IdP de prueba sube la sesión a L2 por STEP_UP_TTL_MIN,
    ligada a una tarjeta y una acción. STEP_UP_MAX_FALLOS fallos bloquean el step-up de la sesión."""
    if registro.rol != "cliente" or not registro.customer_id:
        raise ErrorSesion("NOT_A_CUSTOMER_SESSION", "Esta sesión no corresponde a un cliente.")
    if registro.customer_status in ESTADOS_REVISION:
        raise ErrorSesion("CUSTOMER_STATUS_REVIEW", "Un asesor necesita revisar este caso.")
    if accion not in ACCIONES_CON_EFECTO:
        raise ErrorSesion("ACTION_INVALID", "Acción no permitida.")
    if registro.step_up_bloqueado:
        raise ErrorSesion("STEP_UP_LOCKED", "La verificación adicional está bloqueada en esta sesión.")

    ahora = ahora_utc()
    nivel = nivel_actual(sesion, registro)
    pendientes = sesion.exec(
        select(CodigoOTPPrueba).where(
            CodigoOTPPrueba.sesion_id == registro.id,
            CodigoOTPPrueba.usado_en == None, # noqa: E711
            CodigoOTPPrueba.anulado_en == None, # noqa: E711
            CodigoOTPPrueba.expira_en > ahora,
        )
    ).all()
    esperado = _hash_codigo(registro.id, codigo)
    acierto = next((c for c in pendientes if hmac.compare_digest(c.codigo_hash, esperado)), None)

    usado = False
    if acierto is not None:
        usado = sesion.exec(
            update(CodigoOTPPrueba)
            .where(CodigoOTPPrueba.id == acierto.id, CodigoOTPPrueba.usado_en == None) # noqa: E711
            .values(usado_en= ahora)
        ).rowcount == 1

    if not usado:
        registro.step_up_fallos += 1
        evento = "step_up_failed"
        if registro.step_up_fallos >= STEP_UP_MAX_FALLOS:
            registro.step_up_bloqueado = True
            _anular_codigos_pendientes(sesion, registro.id, ahora)
            evento = "step_up_locked"
        sesion.add(registro)
        auditar_sesion(sesion, registro, evento, rule_ids= ["POL-AUTH-06"], state= "STEP_UP",
                       auth_level_before= nivel, auth_level_after= nivel)
        sesion.commit()

        if registro.step_up_bloqueado:
            raise ErrorSesion("STEP_UP_LOCKED", "La verificación adicional está bloqueada en esta sesión.")
        raise ErrorSesion("STEP_UP_FAILED", "Código incorrecto o vencido.")

    step_up = StepUp(
        id= _nuevo_id("stp_"),
        sesion_id= registro.id,
        card_id= card_id,
        accion= accion,
        creado_en= ahora,
        expira_en= ahora + timedelta(minutes= STEP_UP_TTL_MIN),
    )
    sesion.add(step_up)
    registro.ultima_actividad_en = ahora
    sesion.add(registro)
    auditar_sesion(
        sesion, registro, "step_up_succeeded", rule_ids= ["POL-AUTH-04"], state= "STEP_UP",
        auth_level_before= nivel, auth_level_after= "L2", expires_at= step_up.expira_en,
        step_up= {"step_up_id": step_up.id, "card_ref": auditoria.seudonimo(card_id), "action": accion,
                  "expires_at": auditoria.iso_utc(step_up.expira_en), "used": False},
    )
    sesion.commit()
    sesion.refresh(step_up)

    return step_up


# --- IdP de prueba: acciones del jurado (POL-AUTH-11) -------------------------------------------

def _test_idp(jurado: SesionIdentidad, endpoint: str) -> dict:
    return {"idp": "mock-test-idp", "issued_by_user_id": jurado.usuario_id, "issued_by_role": jurado.rol, "endpoint": endpoint}


def abrir_sesion_prueba(
    sesion: Session, jurado: SesionIdentidad, customer_id: str, customer_status: str, idioma: Optional[str]
) -> Tuple[SesionIdentidad, str]:
    """Sesión de cliente L1 con la expiración normal. El estado del cliente lo lee quien llama en gold."""
    registro = crear_sesion(
        sesion,
        rol= "cliente",
        metodo= "idp_prueba",
        customer_id= customer_id,
        customer_status= customer_status,
        idioma= idioma,
        emitida_por_usuario_id= jurado.usuario_id,
    )
    auditar_sesion(
        sesion, registro, "authenticated", rule_ids= ["POL-AUTH-01", "POL-AUTH-11"], state= "UNAUTHENTICATED",
        auth_level_before= "L0", auth_level_after= "L1", expires_at= registro.expira_absoluta_en,
        customer_status= customer_status, test_idp= _test_idp(jurado, "/identidad/sesion-prueba"),
    )
    sesion.commit()
    sesion.refresh(registro)

    return registro, emitir_token(registro)


def emitir_otp_prueba(sesion: Session, jurado: SesionIdentidad, sesion_id: str) -> Tuple[str, CodigoOTPPrueba]:
    """Código de un solo uso para el step-up de una sesión de cliente vigente. Uno nuevo anula el anterior."""
    objetivo = sesion.get(SesionIdentidad, sesion_id)

    if objetivo is None or objetivo.rol != "cliente" or not objetivo.customer_id:
        raise ErrorSesion("SESSION_NOT_FOUND", "Sesión no encontrada o vencida.")

    try:
        comprobar_vigencia(sesion, objetivo, tocar= False) # Lo pide el jurado: no cuenta como actividad del cliente.
    except ErrorSesion:
        raise ErrorSesion("SESSION_NOT_FOUND", "Sesión no encontrada o vencida.")

    if objetivo.step_up_bloqueado:
        raise ErrorSesion("STEP_UP_LOCKED", "La verificación adicional está bloqueada en esa sesión.")
    if objetivo.customer_status in ESTADOS_REVISION:
        raise ErrorSesion("CUSTOMER_STATUS_REVIEW", "Un asesor necesita revisar ese caso.")

    ahora = ahora_utc()
    _anular_codigos_pendientes(sesion, objetivo.id, ahora)

    codigo = f"{secrets.randbelow(10 ** 6):06d}"
    registro = CodigoOTPPrueba(
        sesion_id= objetivo.id,
        codigo_hash= _hash_codigo(objetivo.id, codigo),
        emitido_por_usuario_id= jurado.usuario_id,
        creado_en= ahora,
        expira_en= ahora + timedelta(minutes= OTP_PRUEBA_TTL_MIN),
    )
    sesion.add(registro)
    nivel = nivel_actual(sesion, objetivo)
    auditar_sesion(
        sesion, objetivo, "step_up_requested", rule_ids= ["POL-AUTH-04", "POL-AUTH-11"], state= "STEP_UP",
        auth_level_before= nivel, auth_level_after= nivel, expires_at= registro.expira_en,
        test_idp= _test_idp(jurado, "/identidad/otp-prueba"),
    )
    sesion.commit()
    sesion.refresh(registro)

    return codigo, registro


class LimitadorTasa:
    """Ventana deslizante en memoria del proceso (se reinicia al reiniciar el backend, POL-AUTH-13)."""

    def __init__(self, maximo: int, ventana_seg: float = 60.0):
        self.maximo = maximo
        self.ventana_seg = ventana_seg
        self._eventos: Dict[str, Deque[float]] = {}
        self._candado = threading.Lock()

    def permitir(self, clave: str) -> bool:
        ahora = time.monotonic()
        with self._candado:
            cola = self._eventos.setdefault(clave, deque())
            while cola and ahora - cola[0] >= self.ventana_seg:
                cola.popleft()
            if len(cola) >= self.maximo:
                return False
            cola.append(ahora)
            return True

    def reiniciar(self) -> None:
        with self._candado:
            self._eventos.clear()


limitador_busqueda = LimitadorTasa(BUSQUEDA_MAX_POR_MINUTO)
