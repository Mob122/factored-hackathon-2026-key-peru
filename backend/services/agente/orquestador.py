"""Orquestador: la máquina de estados de docs/contracts/state_machine.md (sm-0.4) como código.

Cada turno sigue los pasos de la sección 4: sesión (1), redacción (2), idioma (3), controles de
seguridad (4), clasificación (5, solo en IDLE y CLARIFY_INTENT), transición (6), respuesta con
grounding check (7) y evento policy_decision (8). El LLM nunca elige un estado, una transición ni
una tool: solo reformula oraciones que este código ya escribió con hechos verificados (POL-GEN-01).

Cada decisión cita su regla de docs/policy_cards.md. La precedencia de POL-GEN-05 (autenticación >
privacidad > abstención/transferencia > acciones > respuestas) es el orden de los pasos: la sesión
se revisa primero, la redacción después, los controles de seguridad y G-03 antes de cualquier
acción, y las acciones antes de las respuestas de lectura.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

import copy
import json
import logging
import re
import secrets
import time

from sqlmodel import Session, select

from models.chat import Conversacion, MensajeChat
from models.identidad import SesionIdentidad
from services import auditoria, banco, identidad
from services.agente import clasificador, cola_respaldo, seguridad, textos
from services.agente.gateway import Gateway, Llamada, NoPermitidaEnEstado, SesionVencida, seudonimizar_ids
from services.agente.llm import cliente_llm, respaldada
from services.identidad import ErrorSesion

logger = logging.getLogger(__name__)

TRANSITORIOS = {"ANSWERING", "ACTION_PRECHECK", "EXECUTING", "HANDOFF"}

# Parámetros (docs/policy_cards.md sección 11).
FACT_MAX_AGE_SEC = 120
MAX_CLARIFY_TURNS = 2
CONFORMAL_MAX_SET = 2
CARD_MISS_MAX = 2
SESSION_TOOL_FAIL_MAX = 2
LLM_FAIL_MAX = 2

LECTURA = {"balance_inquiry", "card_list", "card_status", "transaction_list", "transaction_detail"}
TRANSFERENCIA = {"charge_dispute", "block_reason", "card_unblock", "human_request"}
# Intenciones que, dichas en SELECT_CARD en lugar del producto, dejan la selección (T-31, D-36).
CAMBIAN_DE_PEDIDO = LECTURA | TRANSFERENCIA | {"card_block", "conversation_end"}
TIPOS_TARJETA = {"credit_card": "Tarjeta Crédito", "debit_card": "Tarjeta Débito"}
# Tipos de producto que sirve cada intención (docs/intents.md sección 2; si no, POL-ANS-14 por T-10).
SIRVE = {
    "balance_inquiry": {None, "card", "credit_card", "savings_account"},
    "transaction_list": {None, "card", "credit_card", "debit_card"},
    "transaction_detail": {None, "card", "credit_card", "debit_card"},
    "card_status": {None, "card", "credit_card", "debit_card"},
    "card_list": {None, "card", "credit_card", "debit_card"},
    "card_block": {None, "card", "credit_card", "debit_card"},
    "charge_dispute": {None, "card", "credit_card", "debit_card"},
    "block_reason": {None, "card", "credit_card", "debit_card"},
    "card_unblock": {None, "card", "credit_card", "debit_card"},
}
# Productos elegibles por intención (POL-ANS-07, tabla de la política).
ELEGIBLES_ESTADO = {"card_block": {"Active"}, "block_reason": {"Blocked", "Suspended"}, "card_unblock": {"Blocked"}}


class ErrorChat(Exception):
    def __init__(self, estado_http: int, codigo: str, mensaje: str):
        super().__init__(mensaje)
        self.estado_http = estado_http
        self.codigo = codigo
        self.mensaje = mensaje


@dataclass
class Segmento:
    texto: str
    tipo: str # "plantilla" (política), "fija" (frase fija de política) o "libre" (el LLM puede reformularla)
    regla: Optional[str] = None


@dataclass
class RespuestaTurno:
    conversation_id: str
    reply: str
    state: str
    language: str
    pending_confirmation: Optional[Dict[str, Any]]
    case_id: Optional[str]
    turn: int


def _contexto_inicial() -> Dict[str, Any]:
    return {
        "pendiente": None, "reanudar": None, "reanudar_ofrecido": False, "oferta_oos": None,
        "producto_sel": None, "candidatos": [], "tipo_candidatos": None, "disputa": None,
        "accion": None, "luego_transferir": False, "transferencia": None, "hechos": {},
        "contadores": {"clarify_turns": 0, "card_misses": 0, "stepup_fails": 0, "tool_fail_rounds": 0,
                       "llm_fails": 0, "injection_hits": 0, "unauthorized_hits": 0},
        "evidencia": {"tool_calls": [], "cards": [], "transactions": [], "security_events": []},
        "hechos_verificados": [], "acciones": [], "ultimo_mensaje": None, "pedido": None,
        "ultima_lectura": None, "codigo_descrito": None, "aclaracion": None, "tool_seq": 0,
        "idioma_preguntado": False, "ultima_accion_en": None,
    }


class Turno:
    """Un turno del cliente. Junta la respuesta, las reglas aplicadas y las transiciones."""

    def __init__(self, bd: Session, conv: Conversacion, registro: SesionIdentidad, dormir: Callable[[float], None] = time.sleep):
        self.bd = bd
        self.conv = conv
        self.registro = registro
        self.ctx: Dict[str, Any] = copy.deepcopy(conv.contexto)
        self.estado_antes = conv.estado
        self.estado = conv.estado
        self.idioma = conv.idioma or "es"
        self.turno = conv.turno + 1
        self.trace_id = secrets.token_hex(16)
        self.segmentos: List[Segmento] = []
        self.reglas: List[str] = []
        self.transiciones: List[str] = []
        self.decision = "none"
        self.intencion: Optional[str] = None
        self.texto_redactado: Optional[str] = None
        self.case_id: Optional[str] = conv.case_id
        try:
            self.pais = banco.pais_cliente(conv.customer_id) if conv.customer_id else None
        except banco.ErrorHerramienta:
            self.pais = None # Solo afecta el formato de números; las lecturas fallarán con POL-ESC-07.
        self.gw = Gateway(bd, conv, registro, self.ctx, lambda: self.estado, dormir= dormir)
        self.llm_ids: List[str] = []

    # --- utilidades -----------------------------------------------------------------------------

    def regla(self, *ids: str) -> None:
        for i in ids:
            if i not in self.reglas:
                self.reglas.append(i)

    def transicion(self, tid: str, destino: str, *reglas: str) -> None:
        self.transiciones.append(tid)
        self.estado = destino
        self.regla(*reglas)

    def decir(self, clave: str, clase: str = "fija", regla: Optional[str] = None, **valores) -> None:
        """Agrega una plantilla ("plantilla") o una frase fija ("fija"); `valores` llena sus marcadores."""
        self.segmentos.append(Segmento(textos.texto(clave, self.idioma, **valores), clase, regla))

    def libre(self, texto_: str, regla: Optional[str] = None) -> None:
        self.segmentos.append(Segmento(texto_, "libre", regla))

    def contador(self, nombre: str, delta: int = 1) -> int:
        self.ctx["contadores"][nombre] = self.ctx["contadores"].get(nombre, 0) + delta
        return self.ctx["contadores"][nombre]

    def hecho_verificado(self, hecho: str, valor: Any, tool_call_id: str) -> None:
        """POL-HND-11: solo hechos que vienen de un resultado de tool de esta sesión."""
        entrada = {"fact": hecho, "value": json.loads(json.dumps(valor, default= str)), "tool_call_id": tool_call_id}
        if entrada not in self.ctx["hechos_verificados"]:
            self.ctx["hechos_verificados"].append(entrada)

    def evento_seguridad(self, tipo: str, subtipo: Optional[str], efecto: str, evidencia: Optional[dict] = None) -> None:
        ocurrencia = sum(1 for e in self.ctx["evidencia"]["security_events"] if e["type"] == tipo) + 1
        self.ctx["evidencia"]["security_events"].append({"turn": self.turno, "type": tipo, **({"subtype": subtipo} if subtipo else {})})
        auditoria.registrar_evento(
            self.bd, event_type= "security", conversation_id= self.conv.id, session_id= self.registro.id,
            actor= "orchestrator", auth_level= identidad.nivel_actual(self.bd, self.registro), state= self.estado,
            rule_ids= ["POL-ESC-08"] if tipo == "injection_suspected" else ["POL-ESC-10", "POL-AUTH-05"],
            customer_id= self.conv.customer_id, session_origin= identidad.origen_sesion(self.registro),
            campos= {"security_event": tipo, "subtype": subtipo, "occurrence": ocurrencia,
                     "detector": "orquestador-v1", "evidence": evidencia or {}, "effect": efecto},
        )

    # --- hechos con lectura fresca (POL-GEN-07) -------------------------------------------------

    def tarjetas(self) -> Optional[List[Dict[str, Any]]]:
        """list_cards con un hecho de menos de FACT_MAX_AGE_SEC, o una lectura nueva (POL-GEN-07 a)."""
        hecho = self.gw.hecho_fresco("tarjetas", FACT_MAX_AGE_SEC)
        if hecho:
            return hecho["valor"]
        llamada = self.gw.llamar("list_cards")
        if not llamada.ok:
            return None
        self.gw.registrar_hecho("tarjetas", llamada.valor or [], llamada.tool_call_id)
        self.ctx["hechos"]["tarjetas"]["tool_call_id"] = llamada.tool_call_id
        return llamada.valor or []

    def id_hecho(self, clave: str) -> Optional[str]:
        return self.ctx["hechos"].get(clave, {}).get("tool_call_id")

    def productos_saldo(self) -> Optional[List[Dict[str, Any]]]:
        hecho = self.gw.hecho_fresco("productos_saldo", FACT_MAX_AGE_SEC)
        if hecho:
            return hecho["valor"]
        llamada = self.gw.llamar("list_balance_products")
        if not llamada.ok:
            return None
        self.gw.registrar_hecho("productos_saldo", llamada.valor or [], llamada.tool_call_id)
        return llamada.valor or []

    def estado_tarjeta(self, card_id: str) -> Optional[Llamada]:
        llamada = self.gw.llamar("get_card_status", card_id= card_id)
        if llamada.ok:
            self.gw.registrar_hecho(f"estado:{card_id}", llamada.valor, llamada.tool_call_id)
        return llamada

    # --- respuesta y auditoría ------------------------------------------------------------------

    def renderizar(self) -> str:
        """Paso 7: plantillas y frases fijas tal cual; las oraciones libres, reformuladas por el LLM si
        LLM_MODE lo permite y si pasan el grounding check (POL-GEN-02), o tal como las escribió el código
        (POL-REL-04)."""
        libres = [s for s in self.segmentos if s.tipo == "libre"]
        resultado = cliente_llm.reformular([s.texto for s in libres], self.idioma)
        if resultado.llamada:
            self.llm_ids.append(resultado.llamada["llm_call_id"])
            auditoria.registrar_evento(
                self.bd, event_type= "llm_call", conversation_id= self.conv.id, session_id= self.registro.id,
                actor= "orchestrator", auth_level= identidad.nivel_actual(self.bd, self.registro), state= self.estado,
                rule_ids= ["POL-PII-01", "POL-PII-02", "POL-REL-04"], customer_id= self.conv.customer_id,
                session_origin= identidad.origen_sesion(self.registro), campos= resultado.llamada,
            )
        sin_respaldo = 0
        if resultado.textos:
            for segmento, nuevo in zip(libres, resultado.textos):
                if respaldada(segmento.texto, nuevo):
                    segmento.texto = nuevo
                else:
                    sin_respaldo += 1 # Se queda la oración del código (POL-REL-04).
        self.ctx["_grounding"] = {"passed": sin_respaldo == 0, "unsupported_facts": sin_respaldo,
                                  "fallback_template": "POL-REL-04" if (sin_respaldo or resultado.fallo) else None}
        if resultado.fallo or sin_respaldo:
            self.regla("POL-REL-04")
            if resultado.fallo and self.contador("llm_fails") >= LLM_FAIL_MAX:
                self.regla("POL-ESC-07") # G-06: el siguiente turno transfiere.
        return " ".join(s.texto for s in self.segmentos if s.texto)

    def auditar_decision(self, respuesta: str) -> None:
        """Paso 8 (POL-AUD-01): un policy_decision por turno, con reglas, transición y decisión."""
        if not self.reglas:
            self.regla("POL-GEN-01")
        plantillas = sorted({s.regla for s in self.segmentos if s.tipo == "plantilla" and s.regla})
        auditoria.registrar_evento(
            self.bd, event_type= "policy_decision", conversation_id= self.conv.id, session_id= self.registro.id,
            actor= "orchestrator", auth_level= identidad.nivel_actual(self.bd, self.registro), state= self.estado,
            rule_ids= self.reglas, customer_id= self.conv.customer_id, session_origin= identidad.origen_sesion(self.registro),
            campos= {
                "state_before": self.estado_antes, "state_after": self.estado,
                "transition_id": self.transiciones[-1] if self.transiciones else None, "transitions": self.transiciones,
                "decision": self.decision, "intent": self.intencion, "tool_call_ids": self.gw.llamadas_turno,
                # El expediente guarda los ids internos (POL-PII-05); el audit log, sus seudónimos (AL-P3).
                "facts_used": [seudonimizar_ids(h) for h in self.ctx["hechos_verificados"] if h["tool_call_id"] in self.gw.llamadas_turno],
                "grounding_check": self.ctx.pop("_grounding", {"passed": True, "unsupported_facts": 0, "fallback_template": None}),
                "reply": {"text_redacted": seguridad.redactar(respuesta).texto, "language": self.idioma,
                          "templates": plantillas, "llm_call_ids": self.llm_ids},
                "counters": self.ctx["contadores"], "then_handoff": bool(self.ctx.get("luego_transferir")),
                "dispute": bool(self.ctx.get("disputa")),
            },
        )

    def cerrar(self) -> RespuestaTurno:
        respuesta = self.renderizar()
        self.auditar_decision(respuesta)
        ahora = identidad.ahora_utc()
        if self.texto_redactado is not None:
            self.bd.add(MensajeChat(conversacion_id= self.conv.id, turno= self.turno, rol= "cliente",
                                    texto_redactado= self.texto_redactado, creado_en= ahora))
        self.bd.add(MensajeChat(conversacion_id= self.conv.id, turno= self.turno, rol= "asistente",
                                texto_redactado= seguridad.redactar(respuesta).texto, creado_en= ahora))
        self.conv.estado = self.estado
        self.conv.turno = self.turno # conv.idioma solo lo fija el cliente o la detección (POL-GEN-03), nunca un valor por defecto.
        self.conv.case_id = self.case_id
        self.conv.contexto = self.ctx
        self.conv.actualizada_en = ahora
        self.bd.add(self.conv)
        self.bd.commit()

        accion = self.ctx.get("accion") if self.estado == "AWAIT_CONFIRMATION" else None
        pendiente = {"card_last4": accion["last4"], "card_type": accion["tipo"], "expires_at": accion["expira_en"]} if accion else None
        return RespuestaTurno(self.conv.id, respuesta, self.estado, self.idioma, pendiente, self.case_id, self.turno)


# =================================================================================================
# Entradas: iniciar una conversación (turno 0) y procesar un mensaje.
# =================================================================================================

def iniciar_conversacion(bd: Session, registro: SesionIdentidad, idioma: Optional[str] = None,
                         conversacion_id: Optional[str] = None) -> RespuestaTurno:
    """Turno 0 (inicio de sesión). Sin conversacion_id: T-01, o T-51 si el cliente está Suspended o
    Closed. Con conversacion_id de una conversación vencida del mismo cliente: G-02 (POL-AUTH-07)."""
    if registro.rol != "cliente" or not registro.customer_id:
        raise ErrorChat(403, "NOT_A_CUSTOMER_SESSION", "Esta sesión no corresponde a un cliente.")
    identidad.comprobar_vigencia(bd, registro, tocar= True)

    if conversacion_id:
        conv = bd.get(Conversacion, conversacion_id)
        if conv is None or conv.customer_id != registro.customer_id:
            raise ErrorChat(404, "CONVERSATION_NOT_FOUND", "Conversación no encontrada.")
        if conv.estado in ("ENDED", "HANDED_OFF"):
            raise ErrorChat(409, "CONVERSATION_CLOSED", "La conversación ya terminó.")
        anterior = bd.get(SesionIdentidad, conv.sesion_id)
        if anterior is not None and anterior.id != registro.id and anterior.cerrada_en is None:
            try:
                identidad.comprobar_vigencia(bd, anterior, tocar= False)
                raise ErrorChat(409, "SESSION_STILL_ACTIVE", "La conversación sigue ligada a otra sesión vigente.")
            except ErrorSesion:
                pass
        if conv.estado != "SESSION_EXPIRED":
            conv.estado = "SESSION_EXPIRED" # Reautenticar empieza una sesión nueva (POL-AUTH-07).
            _soltar_pendientes(conv)
        conv.sesion_id = registro.id
    else:
        nuevo_id = registro.conversacion_id if bd.get(Conversacion, registro.conversacion_id) is None else "conv_" + auditoria.uuid7()
        conv = Conversacion(
            id= nuevo_id, customer_id= registro.customer_id, sesion_id= registro.id,
            estado= "UNAUTHENTICATED", idioma= None, turno= -1, contexto= _contexto_inicial(),
            creada_en= identidad.ahora_utc(), actualizada_en= identidad.ahora_utc(),
        )
        bd.add(conv)

    registro.conversacion_id = conv.id # Los eventos de esta sesión van a la cadena de la conversación.
    bd.add(registro)
    conv.idioma = idioma or conv.idioma or registro.idioma
    t = Turno(bd, conv, registro)
    with auditoria.turno_auditado(t.trace_id, t.turno):
        _autenticar(t, idioma)
        return t.cerrar()


def _soltar_pendientes(conv: Conversacion) -> None:
    ctx = copy.deepcopy(conv.contexto)
    _vaciar_por_vencimiento(ctx)
    conv.contexto = ctx


def _vaciar_por_vencimiento(ctx: Dict[str, Any]) -> None:
    """G-01: se descartan acción pendiente, token, step-up, candidatos y hechos; queda resume_intent
    con la intención y los slots que escribió el cliente (POL-AUTH-07)."""
    pendiente = ctx.get("accion") or ctx.get("pendiente")
    if pendiente and pendiente.get("intencion"):
        ctx["reanudar"] = {"intent": pendiente["intencion"], "slots": pendiente.get("slots", {})}
    for clave in ("pendiente", "accion", "candidatos", "tipo_candidatos", "disputa", "producto_sel", "oferta_oos", "aclaracion"):
        ctx[clave] = [] if clave == "candidatos" else None
    ctx["hechos"] = {}
    ctx["luego_transferir"] = False
    ctx["reanudar_ofrecido"] = False


def _autenticar(t: Turno, idioma: Optional[str]) -> None:
    """Evento authenticate (c1 en las conversaciones golden), luego T-01/T-51 o G-02/T-51."""
    tool_call_id = t.gw.nuevo_id()
    resultado = {"auth_level": "L1", "language": t.conv.idioma, "customer_status": t.registro.customer_status}
    auditoria.registrar_evento(
        t.bd, event_type= "tool_call", conversation_id= t.conv.id, session_id= t.registro.id, actor= "identity",
        auth_level= "L1", state= t.estado, rule_ids= ["POL-AUTH-01", "POL-AUTH-09"], customer_id= t.conv.customer_id,
        session_origin= identidad.origen_sesion(t.registro),
        campos= {"tool_call_id": tool_call_id, "tool": "authenticate", "attempt": 1, "retry_of": None,
                 "allowed_in_state": True, "args": {}, "status": "ok", "error_code": None, "latency_ms": 0,
                 "result": resultado, "result_digest": auditoria.json_canonico(resultado), "data_as_of": None, "fixture": None},
    )
    t.gw._evidencia(tool_call_id, "authenticate", "ok")
    t.gw.llamadas_turno.append(tool_call_id)
    t.gw.registrar_hecho("customer_status", t.registro.customer_status, tool_call_id)
    t.decision = "authenticate"
    reanudando = t.estado == "SESSION_EXPIRED"

    if t.registro.customer_status in identidad.ESTADOS_REVISION:
        # T-51 / G-02 (POL-AUTH-09): sin clasificación ni lecturas; solo la transferencia.
        t.ctx["reanudar"] = None
        t.transicion("T-51" if not reanudando else "G-02", "HANDOFF", "POL-AUTH-09")
        t.hecho_verificado("customer_status", t.registro.customer_status, tool_call_id)
        t.decir("POL-HND-07", "plantilla", "POL-HND-07")
        _transferir(t, ["POL-AUTH-09"], ["customer status requires human review"], pedido= "no request yet (handoff at sign-in)")
        return

    if reanudando:
        t.transicion("G-02", "IDLE", "POL-AUTH-07")
        t.decir("sesion_iniciada")
        if t.ctx.get("reanudar"):
            t.decir("retomar", regla= "POL-AUTH-07") # Pregunta sin hechos de la sesión anterior.
            t.ctx["reanudar_ofrecido"] = True
    else:
        t.transicion("T-01", "IDLE", "POL-AUTH-01")
        t.regla("POL-GEN-03")
        t.decir("saludo")


def procesar(bd: Session, conversacion_id: str, token: str, mensaje: Optional[str] = None,
             codigo_step_up: Optional[str] = None, idioma: Optional[str] = None,
             dormir: Callable[[float], None] = time.sleep) -> RespuestaTurno:
    conv = bd.get(Conversacion, conversacion_id)
    if conv is None:
        raise ErrorChat(404, "CONVERSATION_NOT_FOUND", "Conversación no encontrada.")
    try:
        sesion_id = identidad.decodificar_token(token, permitir_vencido= True)
    except ErrorSesion as error:
        raise ErrorChat(401, error.codigo, error.mensaje)
    registro = bd.get(SesionIdentidad, sesion_id)
    if registro is None or registro.customer_id != conv.customer_id:
        raise ErrorChat(403, "CONVERSATION_FORBIDDEN", "Esta conversación no es de la sesión.")
    if registro.id != conv.sesion_id:
        raise ErrorChat(409, "SESSION_NOT_ATTACHED", "Inicie la conversación con esta sesión (POST /chat/sesiones).")

    t = Turno(bd, conv, registro, dormir= dormir)
    with auditoria.turno_auditado(t.trace_id, t.turno):
        try:
            _turno(t, mensaje, codigo_step_up, idioma)
        except SesionVencida:
            _sesion_vencida(t)
        except NoPermitidaEnEstado:
            t.segmentos = []
            t.decir("fallo_servicio", regla= "POL-ESC-07")
            _transferir(t, ["POL-ESC-07"], ["Internal defect: a tool was requested in a state that does not allow it."])
        if t.estado in TRANSITORIOS:
            # Un turno nunca termina en un estado transitorio (sección 1); si pasara, es un defecto.
            logger.error("Turno %s de %s terminó en %s; se vuelve a IDLE.", t.turno, conv.id, t.estado)
            t.estado = "IDLE"
        return t.cerrar()


def _turno(t: Turno, mensaje: Optional[str], codigo_step_up: Optional[str], idioma: Optional[str]) -> None:
    if t.estado == "ENDED":
        t.decir("conversacion_terminada")
        return

    # Paso 1 (POL-AUTH-03, POL-GEN-05: la autenticación va primero).
    try:
        identidad.comprobar_vigencia(t.bd, t.registro, tocar= True)
    except ErrorSesion:
        if t.estado != "SESSION_EXPIRED":
            _sesion_vencida(t)
        else:
            t.decir("iniciar_sesion", regla= "POL-AUTH-03")
        return
    if t.estado == "SESSION_EXPIRED":
        t.decir("iniciar_sesion", regla= "POL-AUTH-03")
        return

    if idioma in textos.IDIOMAS: # Solo el cliente cambia su preferencia (POL-GEN-03).
        t.idioma = idioma
        t.conv.idioma = idioma
        t.regla("POL-GEN-03")

    if codigo_step_up is not None:
        _codigo_step_up(t, codigo_step_up)
        return
    if mensaje is None:
        t.decir("sin_verificacion_pendiente")
        return

    # Paso 2: redacción (POL-PII-01, 04; POL-AUTH-08).
    red = seguridad.redactar(mensaje, esperando_codigo= t.estado == "STEP_UP")
    t.texto_redactado = red.texto
    t.ctx["ultimo_mensaje"] = red.texto
    t.regla("POL-PII-01")
    huellas = [{"card_number_hmac": banco.hmac_numero_tarjeta(n), "last4": n[-4:]} for n in red.numeros_tarjeta]
    auditoria.registrar_evento(
        t.bd, event_type= "message_received", conversation_id= t.conv.id, session_id= t.registro.id,
        actor= "customer", auth_level= identidad.nivel_actual(t.bd, t.registro), state= t.estado,
        rule_ids= ["POL-PII-01", "POL-PII-04"], customer_id= t.conv.customer_id,
        session_origin= identidad.origen_sesion(t.registro),
        campos= {"text_redacted": red.texto, "detected_language": seguridad.detectar_idioma(red.texto) or "other",
                 "typed_card_numbers": huellas, "third_party_refs": [seguridad.huella_tercero(c) for c in red.customer_ids
                                                                    if c != t.conv.customer_id],
                 "secrets_redacted": red.secretos},
    )

    if t.estado == "HANDED_OFF":
        _mensaje_tras_transferencia(t, red)
        return

    # Paso 3: idioma (POL-GEN-03, POL-ESC-11, G-07).
    if not _resolver_idioma(t, red.texto):
        return

    # Paso 4: controles de seguridad (POL-ESC-08, POL-ESC-10).
    if seguridad.inyeccion_sospechada(red.texto):
        aciertos = t.contador("injection_hits")
        t.regla("POL-ESC-08", "POL-GEN-01")
        t.evento_seguridad("injection_suspected", None, "transfer" if aciertos >= 2 else "ignored_continue")
        if aciertos >= 2:
            # G-04: segunda inyección en la sesión.
            t.transicion("G-04", "HANDOFF", "POL-ESC-08", "POL-HND-15")
            _transferir(t, ["POL-ESC-08"], ["Second suspected prompt injection in the session; automated handling ended."], mensaje_actual= True)
            return
    if red.secretos:
        t.decir("no_codigo_en_chat", regla= "POL-AUTH-08") # POL-AUTH-08: se redactó y nunca se usa.

    propiedad = [banco.comprobar_numero_tarjeta(t.bd, identidad.sesion_cliente_desde(t.registro), n) for n in red.numeros_tarjeta]
    ajenas = [p for p in propiedad if p.resultado == "ajena"]
    if ajenas:
        # POL-ESC-10 (a): el resultado va solo al contador y al audit log (POL-AUTH-05, INV-10).
        t.contador("unauthorized_hits")
        t.evento_seguridad("unauthorized_attempt", "a_third_party_card", "refused_continue",
                           {"card_number_hmac": ajenas[0].card_number_hmac, "owner_match": False})
    tercero = seguridad.pide_datos_de_tercero(red.texto, red.customer_ids, t.conv.customer_id)
    if tercero:
        t.contador("unauthorized_hits")
        t.evento_seguridad("unauthorized_attempt", "b_third_party_data", "refused_continue",
                           {"third_party_refs": [seguridad.huella_tercero(c) for c in red.customer_ids if c != t.conv.customer_id]})
    if (ajenas or tercero) and t.ctx["contadores"]["unauthorized_hits"] >= 2:
        # G-05: segundo intento no autorizado.
        t.transicion("G-05", "HANDOFF", "POL-ESC-10", "POL-AUTH-05", "POL-AUTH-02")
        t.decir("solo_titular_numero_cliente" if red.customer_ids else "solo_titular", regla= "POL-AUTH-05")
        _transferir(t, ["POL-ESC-10", "POL-AUTH-05"], _preguntas_no_autorizado(t, red), mensaje_actual= True)
        return
    if tercero:
        t.regla("POL-ESC-10", "POL-AUTH-05")
        t.decision = "refuse"
        t.decir("solo_titular_numero_cliente" if red.customer_ids else "solo_titular", regla= "POL-AUTH-05")
        return

    # G-03 en cualquier estado de espera (POL-ESC-09).
    if t.estado not in ("IDLE", "CLARIFY_INTENT") and clasificador.es_pedido_de_humano(red.texto):
        t.transicion("G-03", "HANDOFF", "POL-ESC-09")
        t.decir("transferir_humano", regla= "POL-ESC-09")
        _transferir(t, ["POL-ESC-09"], ["Customer asked for a human agent."], mensaje_actual= True)
        return

    # G-06: fallas repetidas de tools o del LLM (POL-ESC-07).
    if t.ctx["contadores"]["tool_fail_rounds"] >= SESSION_TOOL_FAIL_MAX or t.ctx["contadores"]["llm_fails"] >= LLM_FAIL_MAX:
        t.transicion("G-06", "HANDOFF", "POL-ESC-07", "POL-REL-04")
        t.decir("fallo_servicio", regla= "POL-ESC-07")
        _transferir(t, ["POL-ESC-07"], ["Repeated tool or language-model failures in the session."])
        return

    t.ctx["_numeros_tecleados"] = bool(red.numeros_tarjeta)
    t.ctx["_propiedad"] = [{"resultado": p.resultado, "card_id": p.card_id, "last4": p.last4} for p in propiedad]
    MANEJADORES[t.estado](t, red.texto)
    t.ctx.pop("_numeros_tecleados", None)
    t.ctx.pop("_propiedad", None)


def _preguntas_no_autorizado(t: Turno, red: seguridad.Redaccion) -> List[str]:
    preguntas = []
    if any(e.get("subtype") == "a_third_party_card" for e in t.ctx["evidencia"]["security_events"]):
        preguntas.append("Customer typed a full card number that is not one of their cards (raw number not stored).")
    if any(e.get("subtype") == "b_third_party_data" for e in t.ctx["evidencia"]["security_events"]):
        preguntas.append("Customer asked for another person's data; third-party authorization cannot be checked by the assistant.")
    preguntas.append("Second unauthorized access attempt in the session (POL-ESC-10); decide whether any disclosure is allowed.")
    return preguntas


def _resolver_idioma(t: Turno, texto_redactado: str) -> bool:
    """POL-GEN-03: la preferencia del cliente; si no hay, el idioma del primer mensaje; si no se puede
    decidir, se pregunta una vez en los dos idiomas y después se transfiere (POL-ESC-11, G-07)."""
    if t.conv.idioma:
        return True
    elegido = seguridad.idioma_elegido(texto_redactado) if t.ctx.get("idioma_preguntado") else None
    if elegido:
        # Respuesta a la pregunta de POL-ESC-11: queda como preferencia y se saluda en ese idioma.
        t.idioma = elegido
        t.conv.idioma = elegido
        t.regla("POL-ESC-11", "POL-GEN-03")
        t.decir("saludo")
        return False
    detectado = seguridad.detectar_idioma(texto_redactado)
    if detectado:
        t.idioma = detectado
        t.conv.idioma = detectado
        t.regla("POL-GEN-03")
        return True
    t.regla("POL-ESC-11", "POL-GEN-03")
    if not t.ctx.get("idioma_preguntado"):
        t.ctx["idioma_preguntado"] = True
        t.transiciones.append("G-07")
        t.decision = "clarify"
        t.decir("elegir_idioma", regla= "POL-ESC-11")
        return False
    t.transicion("G-07", "HANDOFF", "POL-ESC-11")
    _transferir(t, ["POL-ESC-11"], ["The customer's language could not be determined (neither Spanish nor Portuguese)."], mensaje_actual= True)
    return False


def _sesion_vencida(t: Turno) -> None:
    """G-01 (POL-AUTH-03, 07): sin datos en la respuesta; queda resume_intent."""
    habia_accion = bool(t.ctx.get("accion"))
    _vaciar_por_vencimiento(t.ctx)
    t.segmentos = []
    t.transicion("G-01", "SESSION_EXPIRED", "POL-AUTH-03", "POL-AUTH-07")
    if habia_accion:
        t.regla("POL-ACT-09")
    t.decir("sesion_vencida_accion" if habia_accion else "sesion_vencida", regla= "POL-AUTH-03")
    t.decir("iniciar_sesion", regla= "POL-AUTH-03")
    t.decision = "authenticate"


def _mensaje_tras_transferencia(t: Turno, red: seguridad.Redaccion) -> None:
    """T-38 (POL-HND-06): el mensaje se agrega al caso, respuesta POL-HND-04, ninguna tool."""
    t.transiciones.append("T-38")
    t.regla("POL-HND-06", "POL-HND-04")
    reglas, prioridad = [], None
    if seguridad.inyeccion_sospechada(red.texto):
        reglas.append("POL-ESC-08")
        if t.contador("injection_hits") >= 2:
            prioridad = "security"
    if seguridad.pide_datos_de_tercero(red.texto, red.customer_ids, t.conv.customer_id) or red.numeros_tarjeta:
        reglas.append("POL-ESC-10")
        if t.contador("unauthorized_hits") >= 2:
            prioridad = "security"
    if re.search(r"\b(?:desbloque\w*|reactiv\w*|reposici\w*|segunda via)\b", seguridad.normalizar(red.texto)):
        reglas.append("POL-ESC-03")
    if t.case_id:
        banco.anexar_mensaje_caso(t.bd, identidad.sesion_cliente_desde(t.registro), t.case_id, red.texto, reglas, prioridad)
        t.decir("POL-HND-04", "plantilla", "POL-HND-04", case_id= t.case_id)
    else:
        cola_respaldo.anexar(t.conv.id, red.texto)
        t.decir("POL-HND-05", "plantilla", "POL-HND-05")
    t.decision = "transfer"


def _codigo_step_up(t: Turno, codigo: str) -> None:
    """Código de la ventana de verificación (nunca del chat, POL-AUTH-08): tool step_up en STEP_UP."""
    if t.estado != "STEP_UP" or not t.ctx.get("accion"):
        t.decir("sin_verificacion_pendiente")
        return
    accion = t.ctx["accion"]

    def paso(bd, sesion_cliente, **argumentos):
        registro = identidad.exigir_sesion_cliente_vigente(bd, sesion_cliente)
        s = identidad.realizar_step_up(bd, registro, argumentos["codigo"], argumentos["card_id"], "block_card")
        return {"auth_level": "L2", "bound_card_id": s.card_id, "expires_at": s.expira_en, "single_use": True, "step_up_id": s.id}

    llamada = t.gw.llamar("step_up", funcion= paso, card_id= accion["card_id"], codigo= codigo)
    if llamada.ok:
        # T-28 (POL-AUTH-04, POL-ACT-02): L2 ligado a la tarjeta; el gateway emite el token.
        t.hecho_verificado("step_up", {"auth_level": "L2", "bound_card_last4": accion["last4"]}, llamada.tool_call_id)
        t.decir("identidad_confirmada", regla= "POL-AUTH-04")
        _pedir_confirmacion(t, "T-28")
        return
    if llamada.error_code == "STEP_UP_LOCKED":
        # T-30 (POL-AUTH-06): bloqueo del step-up; transferencia con prioridad security.
        t.contador("stepup_fails")
        t.evento_seguridad("step_up_lockout", "d_step_up_lockout", "transfer")
        t.ctx["accion"] = None
        t.transicion("T-30", "HANDOFF", "POL-AUTH-06", "POL-ESC-10")
        t.decir("fallo_servicio", regla= "POL-AUTH-06")
        _transferir(t, ["POL-AUTH-06", "POL-ESC-10"], ["Step-up locked after repeated failed codes; the pending block was cancelled."])
        return
    # T-29: pedir el código de nuevo.
    t.contador("stepup_fails")
    t.transicion("T-29", "STEP_UP", "POL-AUTH-06")
    t.decir("codigo_invalido", regla= "POL-AUTH-06")


# =================================================================================================
# Estados de espera y rutas desde IDLE.
# =================================================================================================

def _idle(t: Turno, texto: str) -> None:
    ctx = t.ctx
    # T-50: respuesta a la pregunta de reanudación (POL-AUTH-07).
    if ctx.get("reanudar_ofrecido"):
        ctx["reanudar_ofrecido"] = False
        respuesta = seguridad.respuesta_si_no(texto)
        reanudar, ctx["reanudar"] = ctx.get("reanudar"), None
        if respuesta == "si" and reanudar:
            t.transicion("T-50", "IDLE", "POL-AUTH-07", "POL-GEN-07")
            t.ctx["reanudado"] = True
            _rutear(t, reanudar["intent"], reanudar.get("slots", {}), {"intent_set": [reanudar["intent"]], "signals": {}}, texto)
            return
        if respuesta == "no":
            t.decir("entendido")
            return
    # Oferta de POL-ESC-13 pendiente: un sí transfiere como POL-ESC-09.
    if ctx.get("oferta_oos"):
        oferta, ctx["oferta_oos"] = ctx["oferta_oos"], None
        if seguridad.respuesta_si_no(texto) == "si":
            t.transicion("G-03", "HANDOFF", "POL-ESC-13", "POL-ESC-09")
            ctx["pedido"] = {"last_message_redacted": oferta["mensaje"], "top_intent": "out_of_scope", "conformal_set": ["out_of_scope"]}
            t.decir("transferir_humano", regla= "POL-ESC-13")
            _transferir(t, ["POL-ESC-13"], ["Out-of-scope request; the customer accepted the offer of a human agent. Original message in request."],
                        conservar_pedido= True)
            return
        if seguridad.respuesta_si_no(texto) == "no":
            t.decir("entendido", regla= "POL-ESC-13")
            return
    _clasificar_y_rutear(t, texto)


def _clasificar_y_rutear(t: Turno, texto: str, resultado: Optional[Dict[str, Any]] = None) -> None:
    resultado = resultado or clasificador.clasificar(texto, t.idioma)
    contexto = clasificador.seguimiento_eliptico(resultado, texto, t.ctx.get("ultima_lectura"), seguridad.es_continuacion(texto))
    if contexto:
        # POL-ESC-14: seguimiento elíptico de la intención de lectura anterior.
        resultado = {**resultado, "intent_set": [contexto], "context_override": [contexto]}
        t.regla("POL-ESC-14")
    conjunto = resultado["intent_set"]
    ruta = "act" if len(conjunto) == 1 else ("clarify" if 2 <= len(conjunto) <= CONFORMAL_MAX_SET else "transfer")
    _auditar_clasificacion(t, texto, resultado, ruta)
    t.regla("POL-ESC-06")

    if ruta == "transfer":
        # T-04: conjunto vacío o demasiado grande.
        t.transicion("T-04", "HANDOFF", "POL-ESC-06")
        t.ctx["pedido"] = _pedido(t, resultado)
        t.decir("no_entendi", regla= "POL-ESC-06")
        _transferir(t, ["POL-ESC-06"], ["Request not understood: the classifier set was empty or too large."], conservar_pedido= True)
        return
    if ruta == "clarify":
        # T-03: una pregunta que nombra las opciones; ninguna acción corre (POL-ESC-06).
        t.transicion("T-03", "CLARIFY_INTENT", "POL-ESC-06")
        t.ctx["aclaracion"] = {"candidatos": conjunto, "slots": resultado.get("slots", {}), "signals": resultado.get("signals", {}),
                               "texto": texto}
        t.ctx["contadores"]["clarify_turns"] = 0
        _preguntar_aclaracion(t, conjunto)
        return
    intencion = conjunto[0]
    _rutear(t, intencion, clasificador.slots_de(texto, intencion), resultado, texto)


def _auditar_clasificacion(t: Turno, texto: str, resultado: Dict[str, Any], ruta: str) -> None:
    auditoria.registrar_evento(
        t.bd, event_type= "classification", conversation_id= t.conv.id, session_id= t.registro.id, actor= "orchestrator",
        auth_level= identidad.nivel_actual(t.bd, t.registro), state= t.estado, rule_ids= ["POL-ESC-06"],
        customer_id= t.conv.customer_id, session_origin= identidad.origen_sesion(t.registro),
        campos= {
            "classifier_artifact_sha256": resultado.get("artifact_sha256"), "classifier": resultado.get("classifier"),
            "top_intent": resultado.get("top_intent"), "top_score": resultado.get("top_score"),
            "conformal_set": resultado["intent_set"], "conformal_alpha": resultado.get("conformal_alpha"),
            "conformal_threshold": resultado.get("conformal_threshold"), "max_set": resultado.get("max_set"),
            "scores": dict(list(resultado.get("scores", {}).items())[:5]), "safety_override": resultado.get("safety_override", []),
            "signals": resultado.get("signals", {}), "context_override": resultado.get("context_override", []),
            "fallback_reason": resultado.get("fallback_reason"), "slots": resultado.get("slots", {}), "routing": ruta,
        },
    )


def _preguntar_aclaracion(t: Turno, conjunto: List[str]) -> None:
    a, b = (textos.DESCRIPCION_INTENCION[i][t.idioma] for i in conjunto[:2])
    t.decision = "clarify"
    t.decir("aclarar", regla= "POL-ESC-06", a= a, b= b)


def _aclarar(t: Turno, texto: str) -> None:
    """T-12 a T-14: la respuesta a la pregunta aclaratoria se clasifica de nuevo."""
    aclaracion = t.ctx.get("aclaracion") or {}
    candidatos = aclaracion.get("candidatos", [])
    resultado = clasificador.clasificar(texto, t.idioma)
    conjunto = resultado["intent_set"]
    _auditar_clasificacion(t, texto, resultado, "act" if len(conjunto) == 1 else "clarify")
    t.regla("POL-ESC-06")
    turnos = t.contador("clarify_turns")
    if len(conjunto) == 1:
        t.transicion("T-12", "IDLE", "POL-ESC-06")
        t.ctx["aclaracion"] = None
        slots = {**aclaracion.get("slots", {}), **clasificador.slots_de(texto, conjunto[0])}
        _rutear(t, conjunto[0], slots, {**resultado, "signals": {**aclaracion.get("signals", {}), **resultado.get("signals", {})}},
                aclaracion.get("texto", texto))
        return
    if turnos >= MAX_CLARIFY_TURNS:
        t.transicion("T-14", "HANDOFF", "POL-ESC-06")
        t.decir("no_entendi", regla= "POL-ESC-06")
        _transferir(t, ["POL-ESC-06"], [f"The request stayed ambiguous after {turnos} clarifying questions ({', '.join(candidatos)})."])
        return
    t.transicion("T-13", "CLARIFY_INTENT", "POL-ESC-06")
    _preguntar_aclaracion(t, candidatos)


def _pedido(t: Turno, resultado: Dict[str, Any]) -> Dict[str, Any]:
    return {"last_message_redacted": t.ctx.get("ultimo_mensaje"), "top_intent": resultado.get("top_intent"),
            "conformal_set": resultado.get("intent_set", [])}


def _rutear(t: Turno, intencion: str, slots: Dict[str, str], resultado: Dict[str, Any], texto: str) -> None:
    """Ruta de una intención única desde IDLE (T-05 a T-11, T-39, T-42)."""
    t.intencion = intencion
    t.ctx["pedido"] = _pedido(t, {**resultado, "intent_set": resultado.get("intent_set", [intencion]), "top_intent": resultado.get("top_intent", intencion)})
    t.ctx["contadores"]["clarify_turns"] = 0
    tipo = slots.get("product_kind")
    t.ctx["pendiente"] = {"intencion": intencion, "slots": slots, "signals": resultado.get("signals", {}), "texto": texto}

    if intencion == "conversation_end":
        t.transicion("T-11", "ENDED", "POL-GEN-01")
        t.decision = "none"
        t.decir("cierre")
        return
    if intencion == "out_of_scope":
        _fuera_de_alcance(t, ["POL-GEN-04", "POL-ANS-05", "POL-ESC-13"])
        return
    if intencion == "human_request":
        t.transicion("T-08", "HANDOFF", "POL-ESC-09")
        t.decir("transferir_humano", regla= "POL-ESC-09")
        _transferir(t, ["POL-ESC-09"], ["Customer asked for a human agent."], mensaje_actual= True)
        return
    if tipo not in SIRVE.get(intencion, {None}) or (intencion == "balance_inquiry" and slots.get("balance_item") in ("minimum_payment", "due_date")):
        # T-10 con POL-ANS-14: el producto o el dato pedido no se sirve aquí.
        _fuera_de_alcance(t, ["POL-ANS-14", "POL-GEN-04", "POL-ESC-13"])
        return
    if intencion == "balance_inquiry" and slots.get("balance_item") == "available_credit":
        # POL-ANS-15: nunca se calcula el crédito disponible; plantilla POL-BAL-05 (T-06, T-18 sin tool).
        t.transicion("T-06", "ANSWERING", "POL-ANS-15", "POL-ANS-14")
        t.decir("POL-BAL-05", "plantilla", "POL-BAL-05")
        t.transicion("T-18", "IDLE", "POL-BAL-05")
        t.decision = "abstain"
        return
    if intencion == "card_list":
        t.transicion("T-06", "ANSWERING", "POL-ANS-01")
        _responder(t, "card_list", None)
        return

    _resolver_producto(t, intencion, slots)


def _fuera_de_alcance(t: Turno, reglas: List[str]) -> None:
    """T-10 (POL-ESC-13): nunca una negativa sola: qué puede hacer, y la oferta de un asesor."""
    t.transicion("T-10", "IDLE", *reglas)
    t.decision = "abstain"
    t.decir("fuera_de_alcance", regla= "POL-GEN-04")
    t.decir("capacidades", regla= "POL-ANS-05")
    t.decir("POL-HND-08", "plantilla", "POL-HND-08")
    t.ctx["oferta_oos"] = {"mensaje": t.ctx.get("ultimo_mensaje")}
    t.ctx["pendiente"] = None


# --- identificación del producto (POL-ANS-07, 08, 18) -------------------------------------------

def _familia(intencion: str) -> str:
    return "saldo" if intencion == "balance_inquiry" else "tarjeta"


def _filtrar_tipo(productos: List[Dict[str, Any]], tipo: Optional[str], familia: str) -> List[Dict[str, Any]]:
    if familia == "saldo":
        if tipo in ("card", "credit_card"):
            return [p for p in productos if p["kind"] == "credit_card"]
        if tipo == "savings_account":
            return [p for p in productos if p["kind"] == "savings_account"]
        return productos
    if tipo in TIPOS_TARJETA:
        return [p for p in productos if p["type"] == TIPOS_TARJETA[tipo]]
    return productos


def _id_producto(p: Dict[str, Any]) -> str:
    return p.get("card_id") or p.get("product_id")


def _resolver_producto(t: Turno, intencion: str, slots: Dict[str, str]) -> None:
    familia = _familia(intencion)
    tipo = slots.get("product_kind")
    ultimos4 = slots.get("last4")
    seleccionado = t.ctx.get("producto_sel")
    # Producto ya identificado en el contexto (selected_card_id), si el pedido no nombra otro ni otro tipo.
    reusable = not ultimos4 and seleccionado and _tipo_compatible(seleccionado, tipo)

    if reusable and seleccionado.get("familia") == familia:
        _producto_resuelto(t, intencion, seleccionado, nombrar= False)
        return

    productos = t.productos_saldo() if familia == "saldo" else t.tarjetas()
    if productos is None:
        _falla_lectura(t)
        return
    clave = "productos_saldo" if familia == "saldo" else "tarjetas"
    origen = t.id_hecho(clave)

    if reusable and seleccionado.get("kind_tipo") == "credit_card":
        # D-35: selected_card_id es un id de producto (sm-0.4 sección 3) y el product_id de una tarjeta de crédito es
        # su card_id (gold-0.2), así que la tarjeta elegida para el saldo sirve para movimientos o estado, y al revés.
        # Se toma de la lista recién leída de la otra familia (POL-GEN-07), que trae los campos que esa ruta usa.
        mismo = next((p for p in productos if _id_producto(p) == seleccionado["id"]), None)
        if mismo:
            _producto_resuelto(t, intencion, _seleccion(mismo, familia, tipo, origen), nombrar= False)
            return

    if ultimos4:
        coinciden = [p for p in _filtrar_tipo(productos, tipo, familia) if p["last4"] == ultimos4]
        if len(coinciden) == 1:
            _producto_resuelto(t, intencion, _seleccion(coinciden[0], familia, tipo, origen), nombrar= False)
            return
        if len(coinciden) > 1:
            # T-16 / POL-ANS-08: últimos 4 compartidos; se pide el tipo, no es una falla.
            t.transicion("T-05", "SELECT_CARD", "POL-ANS-08", "POL-ANS-07")
            t.transicion("T-16", "SELECT_CARD", "POL-ANS-08")
            _guardar_candidatos(t, coinciden, familia, origen)
            t.decision = "clarify"
            t.decir("cual_tipo", regla= "POL-ANS-08", ultimos4= ultimos4)
            return
        # T-39 / POL-ANS-18: la tarjeta nombrada no está entre las suyas.
        elegibles = _elegibles(intencion, productos, tipo, familia)
        t.contador("card_misses")
        t.transicion("T-39", "SELECT_CARD", "POL-ANS-18", "POL-AUTH-05", "POL-ESC-10")
        t.hecho_verificado("session_cards" if familia == "tarjeta" else "session_products",
                           [{k: v for k, v in p.items() if k in ("last4", "type", "kind", "status")} for p in elegibles or productos], origen)
        t.hecho_verificado("requested_card_in_session", False, origen)
        _guardar_candidatos(t, elegibles or productos, familia, origen)
        _respuesta_falla_tarjeta(t, elegibles or productos)
        return

    elegibles = _elegibles(intencion, productos, tipo, familia)
    if len(elegibles) == 1:
        _producto_resuelto(t, intencion, _seleccion(elegibles[0], familia, tipo, origen), nombrar= True)
        return
    if not elegibles:
        # T-42: ninguno elegible; se dice y se ofrece transferencia (POL-ANS-07, POL-GEN-04).
        t.transicion("T-42", "IDLE", "POL-ANS-07", "POL-GEN-04")
        t.decision = "abstain"
        clave_frase = "ninguna_elegible_saldo" if familia == "saldo" else (
            "ninguna_elegible_tarjetas_activas" if intencion == "card_block" else "ninguna_elegible_tarjetas")
        t.decir(clave_frase, regla= "POL-ANS-07")
        t.decir("ofrecer_transferencia", regla= "POL-GEN-04")
        return
    # T-05: dos o más elegibles y ninguno nombrado (POL-ANS-07).
    t.transicion("T-05", "SELECT_CARD", "POL-ANS-07", "POL-ANS-17" if familia == "saldo" else "POL-ANS-07")
    _guardar_candidatos(t, elegibles, familia, origen)
    t.decision = "clarify"
    t.libre(_lista_candidatos(t, elegibles, familia, tipo), "POL-ANS-07")
    if familia == "saldo" and tipo in ("card", "credit_card"):
        t.libre("¿De cuál quiere consultar el saldo? Indíqueme los últimos 4 dígitos." if t.idioma == "es"
                else "De qual deles quer consultar o saldo? Informe os últimos 4 dígitos.", "POL-ANS-07")
    else:
        t.libre("¿Cuál quiere consultar?" if t.idioma == "es" else "Qual quer consultar?", "POL-ANS-07")


def _tipo_compatible(seleccionado: Dict[str, Any], tipo: Optional[str]) -> bool:
    """El tipo que nombra el pedido admite el producto seleccionado: ninguno, "tarjeta" para cualquier tarjeta, o el
    mismo tipo. Una cuenta de ahorros elegida por sus últimos 4 no responde por "mi tarjeta de crédito" (D-35)."""
    if tipo is None:
        return True
    if tipo == "card":
        return seleccionado.get("kind_tipo") in TIPOS_TARJETA
    return seleccionado.get("kind_tipo") == tipo


def _elegibles(intencion: str, productos: List[Dict[str, Any]], tipo: Optional[str], familia: str) -> List[Dict[str, Any]]:
    candidatos = _filtrar_tipo(productos, tipo, familia)
    estados = ELEGIBLES_ESTADO.get(intencion)
    return [p for p in candidatos if estados is None or p["status"] in estados]


def _seleccion(producto: Dict[str, Any], familia: str, tipo: Optional[str], origen: Optional[str]) -> Dict[str, Any]:
    return {"id": _id_producto(producto), "last4": producto["last4"], "type": producto.get("type"), "kind": producto.get("kind"),
            "status": producto["status"], "familia": familia, "tipo_slot": tipo, "origen": origen,
            "kind_tipo": "credit_card" if producto.get("type") == "Tarjeta Crédito" or producto.get("kind") == "credit_card"
            else ("debit_card" if producto.get("type") == "Tarjeta Débito" else producto.get("kind"))}


def _guardar_candidatos(t: Turno, productos: List[Dict[str, Any]], familia: str, origen: Optional[str]) -> None:
    t.ctx["candidatos"] = [_seleccion(p, familia, None, origen) for p in productos]
    t.ctx["tipo_candidatos"] = familia


def _nombre_producto(p: Dict[str, Any], idioma: str, con_estado: bool = False) -> str:
    if p.get("kind") == "savings_account":
        base = f"su cuenta de ahorros terminada en {p['last4']}" if idioma == "es" else f"sua conta poupança final {p['last4']}"
        estado = textos.ESTADO_CUENTA.get(p["status"], {}).get(idioma, p["status"])
    else:
        credito = p.get("kind") == "credit_card" or p.get("type") == "Tarjeta Crédito"
        if idioma == "es":
            base = f"la {'de crédito' if credito else 'de débito'} terminada en {p['last4']}"
        else:
            base = f"o {'de crédito' if credito else 'de débito'} final {p['last4']}"
        estado = textos.estado_tarjeta(p["status"], idioma)
    return f"{base} ({estado})" if con_estado else base


def _lista_candidatos(t: Turno, productos: List[Dict[str, Any]], familia: str, tipo: Optional[str]) -> str:
    idioma = t.idioma
    if familia == "saldo" and tipo in ("card", "credit_card"):
        n = textos.numero_palabra(len(productos), idioma)
        finales = textos.lista([f"final {p['last4']} ({textos.estado_tarjeta(p['status'], idioma)})" if idioma == "pt"
                                else f"terminada en {p['last4']} ({textos.estado_tarjeta(p['status'], idioma)})" for p in productos], idioma)
        return f"Usted tiene {n} tarjetas de crédito: {finales}." if idioma == "es" else f"Você tem {n} cartões de crédito: {finales}."
    if familia == "saldo":
        nombres = []
        for p in productos:
            if p["kind"] == "savings_account":
                nombres.append(f"de su cuenta de ahorros terminada en {p['last4']}" if idioma == "es" else f"da sua conta poupança final {p['last4']}")
            else:
                nombres.append(f"de su tarjeta de crédito terminada en {p['last4']}" if idioma == "es" else f"do seu cartão de crédito final {p['last4']}")
        conj = " o " if idioma == "es" else " ou "
        cuerpo = ", ".join(nombres[:-1]) + conj + nombres[-1] if len(nombres) > 1 else nombres[0]
        return f"Puedo consultar el saldo {cuerpo}." if idioma == "es" else f"Posso consultar o saldo {cuerpo}."
    nombres = textos.lista([_nombre_producto(p, idioma, con_estado= True) for p in productos], idioma)
    return f"Tiene varias tarjetas: {nombres}." if idioma == "es" else f"Você tem vários cartões: {nombres}."


def _respuesta_falla_tarjeta(t: Turno, productos: List[Dict[str, Any]]) -> None:
    """POL-ANS-18: idéntica sea un error de tipeo, una tarjeta inexistente o de otro cliente (INV-10)."""
    t.decision = "clarify"
    t.decir("tarjeta_no_encontrada", regla= "POL-ANS-18")
    nombres = textos.lista([_nombre_producto(p, t.idioma) for p in productos], t.idioma)
    t.libre(f"Sus tarjetas son {nombres}." if t.idioma == "es" else f"Os seus cartões são {nombres}.", "POL-ANS-18")
    t.decir("cual_consultar", regla= "POL-ANS-18")
    if t.ctx.get("_numeros_tecleados"):
        t.decir("no_numero_en_chat", regla= "POL-AUTH-08") # Depende solo de que escribió un número completo.


def _seleccionar_tarjeta(t: Turno, texto: str) -> None:
    """SELECT_CARD: T-15, T-16, T-17, T-40, T-41."""
    candidatos = t.ctx.get("candidatos", [])
    pendiente = t.ctx.get("pendiente") or {}
    intencion = pendiente.get("intencion")
    if seguridad.es_cancelacion(texto) and not seguridad.ultimos4_en(texto):
        t.transicion("T-31", "IDLE", "POL-ACT-03")
        t.ctx.update(candidatos= [], pendiente= None)
        t.decir("entendido")
        return
    ultimos = seguridad.ultimos4_en(texto)
    tipo = seguridad.tipo_producto_en(texto)
    elegidos = candidatos
    if ultimos:
        elegidos = [c for c in elegidos if c["last4"] in ultimos]
    if tipo and tipo != "card":
        elegidos = [c for c in elegidos if c.get("kind_tipo") == tipo or c.get("kind") == tipo]
    elif tipo == "card":
        elegidos = [c for c in elegidos if c.get("kind") in (None, "credit_card")] if t.ctx.get("tipo_candidatos") == "saldo" else elegidos

    if (ultimos or tipo) and len(elegidos) == 1:
        t.ctx["contadores"]["card_misses"] = 0
        t.transicion("T-15", "SELECT_CARD", "POL-ANS-07")
        t.ctx["candidatos"] = []
        _producto_resuelto(t, intencion, elegidos[0], nombrar= False)
        return
    if ultimos and len(elegidos) > 1:
        if tipo:
            # T-17: tipo + últimos 4 siguen sin ser únicos.
            t.transicion("T-17", "HANDOFF", "POL-ANS-08", "POL-ESC-05")
            _transferir(t, ["POL-ANS-08", "POL-ESC-05"], ["The product stays ambiguous: two products share the same type and last 4 digits."])
            return
        t.transicion("T-16", "SELECT_CARD", "POL-ANS-08")
        t.decir("cual_tipo", regla= "POL-ANS-08", ultimos4= ultimos[0])
        return
    if ultimos or t.ctx.get("_numeros_tecleados"):
        # Falla de tarjeta: T-40, o T-41 al llegar a CARD_MISS_MAX (POL-ANS-18, POL-ESC-10 c).
        fallas = t.contador("card_misses")
        if fallas >= CARD_MISS_MAX:
            t.evento_seguridad("unauthorized_attempt", "c_second_card_miss", "transfer")
            t.transicion("T-41", "HANDOFF", "POL-ANS-18", "POL-ESC-10")
            _transferir(t, ["POL-ANS-18", "POL-ESC-10"], ["Two consecutive card misses: the customer named cards that are not theirs."])
            return
        t.transicion("T-40", "SELECT_CARD", "POL-ANS-18")
        _respuesta_falla_tarjeta(t, candidatos)
        return
    # Ni últimos 4 ni tipo. Un cierre u otro pedido deja la selección y se rutea desde IDLE en el mismo turno, como
    # T-31 en STEP_UP (D-36); cualquier otro mensaje repite la pregunta, con el límite de aclaraciones (POL-ESC-06).
    resultado = clasificador.clasificar(texto, t.idioma)
    conjunto = resultado["intent_set"]
    if len(conjunto) == 1 and conjunto[0] != intencion and conjunto[0] in CAMBIAN_DE_PEDIDO:
        t.transicion("T-31", "IDLE", "POL-ACT-03")
        t.ctx.update(candidatos= [], tipo_candidatos= None, pendiente= None)
        _clasificar_y_rutear(t, texto, resultado)
        return
    _auditar_clasificacion(t, texto, resultado, "clarify")
    if t.contador("clarify_turns") >= MAX_CLARIFY_TURNS:
        t.transicion("T-14", "HANDOFF", "POL-ESC-06")
        _transferir(t, ["POL-ESC-06"], ["The customer did not identify the product after repeated questions."])
        return
    t.decision = "clarify"
    t.libre(_lista_candidatos(t, candidatos, t.ctx.get("tipo_candidatos") or "tarjeta", None), "POL-ANS-07")
    t.decir("cual_consultar", regla= "POL-ANS-07")


def _producto_resuelto(t: Turno, intencion: str, producto: Dict[str, Any], nombrar: bool) -> None:
    """Ruta de la intención con el producto identificado (T-06 a T-09, T-15)."""
    t.ctx["producto_sel"] = producto
    t.ctx["candidatos"] = []
    if producto.get("familia") == "tarjeta":
        t.ctx["evidencia"]["cards"] = [{"card_id": producto["id"], "last4": producto["last4"]}]
    if intencion == "card_block":
        # T-07: chequeo previo del estado antes del flujo de bloqueo (POL-ACT-01).
        t.transicion("T-07", "ACTION_PRECHECK", "POL-ACT-01", "POL-ANS-07")
        _chequeo_previo(t, producto)
        return
    if intencion == "card_unblock":
        # T-08: no hay tool de desbloqueo (POL-ACT-07); se transfiere (POL-ESC-03).
        t.transicion("T-08", "HANDOFF", "POL-ESC-03", "POL-ACT-07")
        t.decir("no_desbloqueo", regla= "POL-ACT-07")
        hecho = t.gw.hecho_fresco("tarjetas", FACT_MAX_AGE_SEC)
        if hecho:
            t.hecho_verificado("card_status", {"last4": producto["last4"], "type": producto["type"], "status": producto["status"]}, hecho["tool_call_id"])
            t.decir("transferire_desbloqueo", regla= "POL-ESC-03", tipo= textos.tipo_tarjeta(producto["type"], t.idioma),
                    ultimos4= producto["last4"], estado= textos.estado_tarjeta(producto["status"], t.idioma))
        else:
            t.decir("transferire_desbloqueo_sin_tarjeta", regla= "POL-ESC-03")
        reglas = ["POL-ESC-03"] + (["POL-ESC-08"] if t.ctx["contadores"]["injection_hits"] else [])
        preguntas = [f"Customer wants card {producto['last4']} unblocked; the assistant cannot unblock (POL-ACT-07) and has no record of why it was blocked."]
        if t.ctx["contadores"]["injection_hits"]:
            preguntas.append("The request came with a suspected prompt injection; verify the customer's identity before any unblock.")
        _transferir(t, reglas, preguntas)
        return
    if intencion == "block_reason":
        # T-08: se lee y dice el estado, luego T-20 (POL-ESC-02, POL-ANS-11).
        t.ctx["luego_transferir"] = True
        t.transicion("T-08", "ANSWERING", "POL-ESC-02", "POL-ANS-11")
        _responder(t, "card_status", producto)
        if t.estado == "ANSWERING":
            t.transicion("T-20", "HANDOFF", "POL-ESC-02")
            t.decir("sin_causa_bloqueo", regla= "POL-ANS-11")
            _transferir(t, ["POL-ESC-02"], [f"Customer asks why or when card {producto['last4']} was blocked or suspended; there is no status history (POL-ANS-11)."])
        return
    if intencion == "charge_dispute":
        # T-09: búsqueda de la transacción con los datos del cliente (POL-ESC-01, POL-ANS-09).
        t.ctx["disputa"] = {"card": producto}
        t.transicion("T-09", "ANSWERING", "POL-ESC-01", "POL-ANS-09", "POL-ANS-12")
        _buscar_disputa(t, producto)
        return
    # Intenciones de lectura (T-06).
    t.transicion("T-06", "ANSWERING", "POL-ANS-07" if nombrar else "POL-ANS-02")
    _responder(t, intencion, producto)


def _falla_lectura(t: Turno) -> None:
    """POL-ESC-07: una lectura sigue fallando tras los reintentos de POL-REL-01: se dice que el servicio
    no puede completar el pedido, sin afirmar ningún resultado, y se transfiere (G-06 si se llegó a
    SESSION_TOOL_FAIL_MAX rondas fallidas; si no, T-21)."""
    t.decir("fallo_servicio", regla= "POL-ESC-07")
    agotado = t.ctx["contadores"]["tool_fail_rounds"] >= SESSION_TOOL_FAIL_MAX
    t.transicion("G-06" if agotado else "T-21", "HANDOFF", "POL-ESC-07", "POL-REL-01")
    _transferir(t, ["POL-ESC-07"], ["A data tool kept failing after its retries; the request could not be completed (POL-ESC-07)."])


# --- respuestas de lectura (ANSWERING) ----------------------------------------------------------

def _responder(t: Turno, intencion: str, producto: Optional[Dict[str, Any]]) -> None:
    t.estado = "ANSWERING"
    t.decision = "answer"
    texto = (t.ctx.get("pendiente") or {}).get("texto", "")
    slots = (t.ctx.get("pendiente") or {}).get("slots", {})
    if intencion == "card_list":
        tarjetas = t.tarjetas()
        if tarjetas is None:
            return _falla_lectura(t)
        origen = t.id_hecho("tarjetas")
        t.hecho_verificado("session_cards", [{k: c[k] for k in ("last4", "type", "status")} for c in tarjetas], origen)
        if not tarjetas:
            t.decir("ninguna_elegible_tarjetas", regla= "POL-ANS-06")
        else:
            n = textos.numero_palabra(len(tarjetas), t.idioma)
            detalle = textos.lista([_nombre_producto(c, t.idioma, con_estado= True) for c in tarjetas], t.idioma)
            if len(tarjetas) == 1:
                t.libre(f"Tiene una tarjeta: {detalle}." if t.idioma == "es" else f"Você tem um cartão: {detalle}.", "POL-ANS-01")
            else:
                t.libre(f"Tiene {n} tarjetas: {detalle}." if t.idioma == "es" else f"Você tem {n} cartões: {detalle}.", "POL-ANS-01")
        t.regla("POL-ANS-01")
    elif intencion == "card_status":
        llamada = t.estado_tarjeta(producto["id"])
        if not llamada.ok:
            return _falla_lectura(t)
        valor = llamada.valor
        t.hecho_verificado("card_status", valor, llamada.tool_call_id)
        t.libre(_frase_estado(valor, t.idioma), "POL-ANS-02")
        t.regla("POL-ANS-02")
        if seguridad.pregunta_vencimiento(texto):
            # POL-ANS-13, POL-ESC-04: nunca se confirma una fecha de vencimiento.
            codigo = t.ctx.get("codigo_descrito")
            t.decir("no_vencimiento_codigo" if codigo else "no_vencimiento", regla= "POL-ANS-13", codigo= codigo)
            t.decir("ofrecer_transferencia", regla= "POL-ESC-04")
            t.regla("POL-ANS-13", "POL-ESC-04")
    elif intencion == "balance_inquiry":
        _responder_saldo(t, producto)
    elif intencion in ("transaction_list", "transaction_detail"):
        _responder_transacciones(t, intencion, producto, slots)
    if t.estado == "ANSWERING" and not t.ctx.get("luego_transferir"):
        t.ctx["ultima_lectura"] = intencion
        _parte_no_respondida(t, texto, intencion)
        t.transicion("T-18", "IDLE", "POL-GEN-02", "POL-GEN-07")
        t.ctx["pendiente"] = None


def _frase_estado(valor: Dict[str, Any], idioma: str) -> str:
    tipo = textos.tipo_tarjeta(valor["type"], idioma)
    estado = textos.estado_tarjeta(valor["status"], idioma)
    if idioma == "es":
        return f"Su tarjeta {tipo} terminada en {valor['last4']} está {estado}."
    return f"O seu cartão {tipo} final {valor['last4']} está {estado}."


def _parte_no_respondida(t: Turno, texto: str, servida: str) -> None:
    """POL-GEN-06: si el mensaje pidió otra cosa además, se dice en una oración qué no se respondió."""
    if not re.search(r"\b(?:y|e|ademas|tambien|tambem)\b", seguridad.normalizar(texto)):
        return
    otras = clasificador.otras_lecturas(texto, servida)
    if otras:
        t.regla("POL-GEN-06")
        t.decir("parte_no_respondida", regla= "POL-GEN-06", tema= textos.TEMA_INTENCION[otras[0]][t.idioma])


def _responder_saldo(t: Turno, producto: Dict[str, Any]) -> None:
    """POL-ANS-15, 16; POL-GEN-07 (b, c): el saldo se lee en el mismo turno, siempre con as_of."""
    llamada = t.gw.llamar("get_balance", product_id= producto["id"])
    if not llamada.ok:
        return _falla_lectura(t)
    valor = llamada.valor
    t.hecho_verificado("balance", {k: valor.get(k) for k in ("kind", "last4", "status", "currency", "current_balance", "credit_limit", "as_of")},
                       llamada.tool_call_id)
    datos = {"ultimos4": valor["last4"], "saldo": textos.monto(valor["current_balance"], t.pais), "moneda": valor["currency"],
             "as_of": textos.fecha_hora(valor["as_of"], t.idioma)}
    for plantilla in valor["templates"]:
        if plantilla == "POL-BAL-01":
            datos["limite"] = textos.monto(valor["credit_limit"], t.pais)
        t.decir(plantilla, "plantilla", plantilla, **datos)
    t.regla("POL-ANS-15" if valor["kind"] == "credit_card" else "POL-ANS-16", "POL-GEN-07", *valor["templates"])


_DIAS_SEMANA = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _ventana(fecha_slot: Optional[str]) -> Tuple[Optional[date], Optional[date]]:
    """Fechas del slot `date` contra el reloj del banco (docs/intents.md sección 2)."""
    if not fecha_slot:
        return None, None
    hoy = banco.ahora_banco().date()
    if fecha_slot == "today":
        return hoy, hoy
    if fecha_slot == "yesterday":
        return hoy - timedelta(days= 1), hoy - timedelta(days= 1)
    if fecha_slot == "day_before_yesterday":
        return hoy - timedelta(days= 2), hoy - timedelta(days= 2)
    if fecha_slot == "this_week":
        return hoy - timedelta(days= hoy.weekday()), hoy
    if fecha_slot == "last_week":
        inicio = hoy - timedelta(days= hoy.weekday() + 7)
        return inicio, inicio + timedelta(days= 6)
    if fecha_slot == "this_month":
        return hoy.replace(day= 1), hoy
    if fecha_slot == "last_month":
        fin = hoy.replace(day= 1) - timedelta(days= 1)
        return fin.replace(day= 1), fin
    tipo, _, valor = fecha_slot.partition(":")
    try:
        if tipo in ("last_n_days", "n_days_ago"):
            dias = int(valor)
            return (hoy - timedelta(days= dias), hoy) if tipo == "last_n_days" else (hoy - timedelta(days= dias), hoy - timedelta(days= dias))
        if tipo == "month":
            mes = int(valor)
            anio = hoy.year if mes <= hoy.month else hoy.year - 1
            inicio = date(anio, mes, 1)
            fin = (date(anio + (mes == 12), mes % 12 + 1, 1) - timedelta(days= 1))
            return inicio, min(fin, hoy)
        if tipo in ("date", "since"):
            mes, dia = (int(x) for x in valor.split("-"))
            inicio = date(hoy.year if (mes, dia) <= (hoy.month, hoy.day) else hoy.year - 1, mes, dia)
            return (inicio, inicio) if tipo == "date" else (inicio, hoy)
        if tipo == "weekday":
            atras = (hoy.weekday() - _DIAS_SEMANA[valor]) % 7 or 7
            dia_ = hoy - timedelta(days= atras)
            return dia_, dia_
    except (ValueError, KeyError):
        return None, None
    return None, None # few_days_ago y otros: la ventana por defecto (POL-ANS-03).


def _filtros(slots: Dict[str, str]) -> Dict[str, Any]:
    desde, hasta = _ventana(slots.get("date"))
    filtros: Dict[str, Any] = {}
    if desde:
        filtros["desde"], filtros["hasta"] = desde, hasta
    if slots.get("merchant"):
        filtros["comercio"] = slots["merchant"]
    if slots.get("tx_status"):
        filtros["estado"] = {"approved": "Approved", "declined": "Declined", "pending": "Pending", "reversed": "Reversed"}[slots["tx_status"]]
    if slots.get("amount"):
        try:
            valor = Decimal(slots["amount"].split()[0])
            filtros["monto_min"], filtros["monto_max"] = valor - Decimal("0.005"), valor + Decimal("0.005")
        except Exception:
            pass
    return filtros


def _describir(t: Turno, transaccion_id: str, card: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """describe_transaction y la respuesta con plantillas TXS y DEC (sección 6, POL-DEC-93)."""
    llamada = t.gw.llamar("describe_transaction", transaction_id= transaccion_id)
    if not llamada.ok:
        _falla_lectura(t)
        return None
    tx = llamada.valor
    t.hecho_verificado("transaction", {k: tx.get(k) for k in ("transaction_id", "date", "type", "amount", "currency", "merchant", "status", "response_code")},
                       llamada.tool_call_id)
    t.ctx["evidencia"]["transactions"] = sorted(set(t.ctx["evidencia"]["transactions"]) | {tx["transaction_id"]})
    plantilla_txs = next((p for p in tx["templates"] if p.startswith("POL-TXS")), None)
    if plantilla_txs:
        t.segmentos.append(Segmento(textos.oracion_transaccion(tx, plantilla_txs, t.idioma, t.pais, tx["last4"]), "plantilla", plantilla_txs))
    dec = next((p for p in tx["templates"] if p.startswith("POL-DEC")), None)
    if dec in ("POL-DEC-05", "POL-DEC-14", "POL-DEC-51", "POL-DEC-54"):
        codigo = tx["response_code"]
        t.decir("POL-DEC-PREFIX", "plantilla", dec, codigo= codigo, significado= textos.SIGNIFICADO_DEC[codigo][t.idioma])
        t.decir("POL-DEC-DISCLAIMER", "plantilla", "POL-ANS-10")
        t.ctx["codigo_descrito"] = codigo
        t.regla(dec, "POL-DEC-93", "POL-ANS-10")
    elif dec in ("POL-DEC-90", "POL-DEC-91"):
        t.decir(dec, "plantilla", dec)
        t.decir("POL-DEC-DISCLAIMER", "plantilla", "POL-ANS-10")
        t.regla(dec, "POL-ANS-10")
    if "POL-ESC-05" in tx.get("notices", []):
        t.regla("POL-ESC-05") # Dato desconocido o inconsistente: solo lo verificado; se ofrece transferir.
    t.regla("POL-ANS-04", *(p for p in tx["templates"]))
    return tx


def _listar(t: Turno, producto: Dict[str, Any], slots: Dict[str, str]) -> Optional[Llamada]:
    llamada = t.gw.llamar("list_transactions", card_id= producto["id"], **_filtros(slots))
    if not llamada.ok:
        _falla_lectura(t)
        return None
    return llamada


def _responder_transacciones(t: Turno, intencion: str, producto: Dict[str, Any], slots: Dict[str, str]) -> None:
    llamada = _listar(t, producto, slots)
    if llamada is None:
        return
    resultado = llamada.valor
    filas = resultado["transactions"]
    tipo = textos.tipo_tarjeta(producto["type"], t.idioma)
    rango = {"desde": textos.fecha_larga(resultado["from"], t.idioma), "hasta": textos.fecha_larga(resultado["to"], t.idioma)}
    t.regla("POL-ANS-03")
    if resultado["window_capped"]:
        t.decir("ventana_limite", regla= "POL-ANS-03", dias= banco.TX_DIAS_MAX)
    if not filas:
        # POL-ANS-06: se dice que no hay registros, sin inferir nada.
        t.decir("no_transacciones", regla= "POL-ANS-06", tipo= tipo, ultimos4= producto["last4"], **rango)
        t.regla("POL-ANS-06")
        return
    if intencion == "transaction_detail" and len(filas) == 1:
        _describir(t, filas[0]["transaction_id"], producto)
        return
    t.hecho_verificado("transactions", [{k: f[k] for k in ("transaction_id", "date", "amount", "currency", "merchant", "status")} for f in filas],
                       llamada.tool_call_id)
    t.libre(textos.texto("transacciones_encabezado", t.idioma, tipo= tipo, ultimos4= producto["last4"], **rango), "POL-ANS-03")
    for fila in filas:
        t.segmentos.append(Segmento(textos.linea_transaccion(fila, t.idioma, t.pais), "fija", "POL-ANS-03"))
    if resultado["truncated"]:
        t.decir("transacciones_tope", regla= "POL-ANS-03", n= banco.TX_FILAS_MAX)
    if intencion == "transaction_detail":
        # T-19 (POL-ANS-09): varias coinciden; se listan y se pregunta, nunca se elige en silencio.
        t.ctx["candidatos"] = [{"id": f["transaction_id"], "amount": str(f["amount"]), "date": str(f["date"]), "merchant": f["merchant"]} for f in filas]
        t.ctx["tipo_candidatos"] = "transaccion"
        t.transicion("T-19", "SELECT_TRANSACTION", "POL-ANS-09")
        t.decision = "clarify"
        t.decir("cual_transaccion", regla= "POL-ANS-09")


def _buscar_disputa(t: Turno, producto: Dict[str, Any]) -> None:
    """T-09 → T-43 (1 o más candidatas) o T-44 (ninguna) (POL-ESC-01, POL-ANS-09)."""
    slots = (t.ctx.get("pendiente") or {}).get("slots", {})
    llamada = _listar(t, producto, slots)
    if llamada is None:
        return
    filas = llamada.valor["transactions"]
    hecho = t.gw.hecho_fresco("tarjetas", FACT_MAX_AGE_SEC)
    if hecho:
        t.hecho_verificado("card", {"last4": producto["last4"], "type": producto["type"], "status": producto["status"]}, hecho["tool_call_id"])
    if not filas:
        t.transicion("T-44", "HANDOFF", "POL-ESC-01", "POL-ANS-06")
        t.decir("cobro_no_encontrado", regla= "POL-ESC-01", dias= banco.TX_DIAS_DEFECTO)
        _transferir(t, ["POL-ESC-01"], ["Customer disputes a charge on card " + producto["last4"] + "; the transaction was not found in the searched window.",
                                         "The assistant cannot judge whether a charge is valid (POL-ANS-12)."])
        return
    t.ctx["candidatos"] = [{"id": f["transaction_id"], "amount": str(f["amount"]), "date": str(f["date"]), "merchant": f["merchant"]} for f in filas]
    t.ctx["tipo_candidatos"] = "transaccion"
    t.decision = "clarify"
    if len(filas) == 1:
        tx = _describir(t, filas[0]["transaction_id"], producto)
        if tx is None:
            return
        t.ctx["disputa"]["tx"] = tx["transaction_id"]
        t.transicion("T-43", "SELECT_TRANSACTION", "POL-ANS-09", "POL-ESC-01")
        t.decir("es_este_cobro", regla= "POL-ANS-09")
        return
    t.libre(textos.texto("transacciones_encabezado", t.idioma, tipo= textos.tipo_tarjeta(producto["type"], t.idioma), ultimos4= producto["last4"],
                         desde= textos.fecha_larga(llamada.valor["from"], t.idioma), hasta= textos.fecha_larga(llamada.valor["to"], t.idioma)), "POL-ANS-09")
    for fila in filas:
        t.segmentos.append(Segmento(textos.linea_transaccion(fila, t.idioma, t.pais), "fija", "POL-ANS-09"))
    t.transicion("T-43", "SELECT_TRANSACTION", "POL-ANS-09", "POL-ESC-01")
    t.decir("cual_cobro", regla= "POL-ANS-09")


def _elegir_transaccion(t: Turno, texto: str) -> None:
    """SELECT_TRANSACTION: T-22, T-23 (lectura) y T-45 a T-47 (disputa)."""
    candidatos = t.ctx.get("candidatos", [])
    disputa = t.ctx.get("disputa")
    elegida = None
    if disputa and len(candidatos) == 1:
        respuesta = seguridad.respuesta_si_no(texto)
        if respuesta == "si":
            elegida = candidatos[0]
        elif respuesta == "no":
            # T-47: no es esa transacción.
            t.transicion("T-47", "HANDOFF", "POL-ESC-01")
            _transferir(t, ["POL-ESC-01"], ["Customer disputes a charge; the disputed transaction was not identified (the one found was not it)."])
            return
    else:
        norm = seguridad.normalizar(texto)
        ordinales = {"primer": 0, "primera": 0, "segund": 1, "tercer": 2, "cuart": 3, "ultim": -1}
        for palabra, indice in ordinales.items():
            if re.search(rf"\b{palabra}\w*\b", norm) and candidatos:
                elegida = candidatos[indice]
                break
        if elegida is None:
            numeros = re.findall(r"\d+(?:[.,]\d{1,2})?", texto)
            for c in candidatos:
                if any(n.replace(",", ".") in (c["amount"], c["amount"].rstrip("0").rstrip(".")) for n in numeros) or (
                        c.get("merchant") and c["merchant"].lower() in texto.lower()):
                    elegida = c
                    break
        if elegida is None and disputa and seguridad.respuesta_si_no(texto) == "no":
            t.transicion("T-47", "HANDOFF", "POL-ESC-01")
            _transferir(t, ["POL-ESC-01"], ["Customer disputes a charge; none of the listed transactions is the disputed one."])
            return

    if elegida is None:
        if t.contador("clarify_turns") >= MAX_CLARIFY_TURNS:
            t.transicion("T-23", "HANDOFF", "POL-ESC-06")
            _transferir(t, ["POL-ESC-06", "POL-ANS-09"], ["The customer did not pick a transaction after repeated questions."])
            return
        t.decision = "clarify"
        t.decir("cual_cobro" if disputa else "cual_transaccion", regla= "POL-ANS-09")
        return

    if not disputa:
        # T-22: describir la elegida.
        t.transicion("T-22", "ANSWERING", "POL-ANS-09")
        _describir(t, elegida["id"], t.ctx.get("producto_sel") or {})
        if t.estado == "ANSWERING":
            t.transicion("T-18", "IDLE", "POL-GEN-02")
        return

    disputa["tx"] = elegida["id"]
    disputa["confirmada_turno"] = t.turno
    t.ctx["evidencia"]["transactions"] = sorted(set(t.ctx["evidencia"]["transactions"]) | {elegida["id"]})
    tarjeta = disputa["card"]
    hecho = t.gw.hecho_fresco("tarjetas", FACT_MAX_AGE_SEC)
    if tarjeta["status"] == "Active":
        # T-45: se ofrece el bloqueo; nada corre todavía (POL-ESC-01).
        t.transicion("T-45", "OFFER_BLOCK", "POL-ESC-01")
        if hecho:
            t.libre(_frase_estado({"type": tarjeta["type"], "last4": tarjeta["last4"], "status": tarjeta["status"]}, t.idioma), "POL-ESC-01")
        t.decir("ofrecer_bloqueo", regla= "POL-ESC-01")
        t.decision = "clarify"
        return
    # T-46: la tarjeta no está activa; se transfiere sin ofrecer el bloqueo.
    t.transicion("T-46", "HANDOFF", "POL-ESC-01")
    _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= False))


def _preguntas_disputa(t: Turno, ofrecido: bool, aceptado: bool = False) -> List[str]:
    disputa = t.ctx.get("disputa") or {}
    tx = next((h["value"] for h in t.ctx["hechos_verificados"] if h["fact"] in ("transaction", "disputed_transaction")
               and h["value"].get("transaction_id") == disputa.get("tx")), {})
    preguntas = []
    if tx:
        preguntas.append(f"Customer does not recognize transaction {tx.get('transaction_id')} ({tx.get('amount')} {tx.get('currency')}, "
                         f"{tx.get('merchant') or 'no merchant'}, {str(tx.get('date'))[:10]}) and confirmed it at turn {disputa.get('confirmada_turno')}; dispute review needed.")
    preguntas.append("The assistant cannot judge whether a charge is valid (POL-ANS-12).")
    card = disputa.get("card") or {}
    if ofrecido and not aceptado:
        preguntas.append(f"A block of card {card.get('last4')} was offered (POL-ESC-01) and declined by the customer at turn {t.turno}; the card is still {card.get('status')}.")
    return preguntas


def _ofrecer_bloqueo(t: Turno, texto: str) -> None:
    """OFFER_BLOCK: T-48 (sí) o T-49 (no o cualquier otra cosa)."""
    disputa = t.ctx.get("disputa") or {}
    tarjeta = disputa.get("card")
    for h in t.ctx["hechos_verificados"]:
        if h["fact"] == "transaction" and h["value"].get("transaction_id") == disputa.get("tx"):
            h["fact"] = "disputed_transaction"
    if seguridad.respuesta_si_no(texto) == "si" and tarjeta:
        t.ctx["luego_transferir"] = True
        t.transicion("T-48", "ACTION_PRECHECK", "POL-ESC-01", "POL-ACT-01")
        _chequeo_previo(t, tarjeta)
        return
    t.transicion("T-49", "HANDOFF", "POL-ESC-01")
    t.decir("no_bloquee", regla= "POL-ESC-01")
    t.decir("reclamo_asesor", regla= "POL-ANS-12")
    _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= True))


# --- bloqueo: chequeo, step-up, confirmación, ejecución -----------------------------------------

def _chequeo_previo(t: Turno, tarjeta: Dict[str, Any]) -> None:
    """ACTION_PRECHECK: T-24 a T-27 (POL-ACT-01)."""
    t.estado = "ACTION_PRECHECK"
    llamada = t.estado_tarjeta(tarjeta["id"])
    if not llamada.ok:
        return _falla_lectura(t)
    valor = llamada.valor
    t.hecho_verificado("card_status", valor, llamada.tool_call_id)
    pendiente = t.ctx.get("pendiente") or {}
    t.ctx["accion"] = {"accion": "block_card", "card_id": tarjeta["id"], "last4": valor["last4"], "tipo": valor["type"],
                       "intencion": "card_block", "slots": pendiente.get("slots", {}), "signals": pendiente.get("signals", {}),
                       "estado_previo_call": llamada.tool_call_id}
    if valor["status"] == "Blocked":
        # T-24: ya está bloqueada; no se llama a block_card.
        t.ctx["accion"] = None
        t.decir("ya_bloqueada", regla= "POL-ACT-01", tipo= textos.tipo_tarjeta(valor["type"], t.idioma), ultimos4= valor["last4"])
        if t.ctx.get("luego_transferir"):
            t.transicion("T-24", "HANDOFF", "POL-ACT-01")
            _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= True, aceptado= True))
        else:
            t.transicion("T-24", "IDLE", "POL-ACT-01")
        return
    if valor["status"] != "Active":
        # T-25 (POL-ESC-12): Suspended o Closed; se dice el estado y se transfiere.
        t.ctx["accion"] = None
        t.libre(_frase_estado(valor, t.idioma), "POL-ESC-12")
        t.decir("estado_no_permite", regla= "POL-ESC-12")
        t.transicion("T-25", "HANDOFF", "POL-ESC-12")
        _transferir(t, ["POL-ESC-12"], [f"Customer asked to block card {valor['last4']}, whose status is {valor['status']}; an action on it needs a human."])
        return
    t.libre(_frase_estado(valor, t.idioma), "POL-ACT-01")
    if identidad.step_up_valido(t.bd, t.registro.id, tarjeta["id"], "block_card"):
        _pedir_confirmacion(t, "T-27")
        return
    # T-26: se pide el código de un solo uso (POL-AUTH-01, 04; POL-AUTH-08: nunca en el chat).
    t.transicion("T-26", "STEP_UP", "POL-ACT-01", "POL-AUTH-01", "POL-AUTH-04", "POL-AUTH-08")
    t.decision = "act"
    t.decir("pedir_codigo_nuevo" if t.ctx.pop("reanudado", None) else "pedir_codigo", regla= "POL-AUTH-04")


def _pedir_confirmacion(t: Turno, transicion: str) -> None:
    """T-27 / T-28: el gateway emite el token de confirmación y se muestra el aviso (POL-ACT-02)."""
    accion = t.ctx["accion"]
    try:
        token = banco.emitir_token_confirmacion(t.bd, identidad.sesion_cliente_desde(t.registro), accion["card_id"])
    except banco.ErrorHerramienta as error:
        t.ctx["accion"] = None
        t.transicion(transicion, "IDLE", "POL-ACT-02")
        t.decir("fallo_servicio", regla= "POL-ACT-02")
        return
    accion.update(token= token["confirmation_token"], token_id= token["confirmation_token_id"],
                  expira_en= token["expires_at"].isoformat(), turno_aviso= t.turno)
    t.transicion(transicion, "AWAIT_CONFIRMATION", "POL-ACT-02", "POL-AUTH-04")
    t.decision = "clarify"
    tipo = textos.tipo_tarjeta(accion["tipo"], t.idioma)
    t.decir("aviso_bloqueo", regla= "POL-ACT-02", tipo= tipo, ultimos4= accion["last4"])
    t.decir("pregunta_bloqueo", regla= "POL-ACT-02", ultimos4= accion["last4"])


def _paso_step_up_texto(t: Turno, texto: str) -> None:
    """STEP_UP con un mensaje de texto: T-31 (cancelar o cambiar de tema). Un código escrito en el chat
    ya se redactó y no se usa (POL-AUTH-08)."""
    if re.search(r"\[SECRET_\d+\]", texto):
        t.decir("pedir_codigo", regla= "POL-AUTH-08")
        return
    t.ctx["accion"] = None
    if t.ctx.get("luego_transferir"):
        t.transicion("T-31", "HANDOFF", "POL-ACT-03")
        _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= True))
        return
    t.transicion("T-31", "IDLE", "POL-ACT-03")
    if seguridad.es_cancelacion(texto):
        t.decir("bloqueo_cancelado", regla= "POL-ACT-03")
        return
    _clasificar_y_rutear(t, texto) # Un pedido nuevo se rutea desde IDLE en el mismo turno.


def _confirmar(t: Turno, texto: str) -> None:
    """AWAIT_CONFIRMATION: T-32 (sí claro, de un turno posterior, token vigente, misma tarjeta) o T-33."""
    accion = t.ctx.get("accion") or {}
    respuesta = seguridad.respuesta_si_no(texto)
    otros4 = [u for u in seguridad.ultimos4_en(texto) if u != accion.get("last4")]
    vencido = identidad.ahora_utc() >= datetime.fromisoformat(accion["expira_en"]) if accion.get("expira_en") else True
    resultado = ("confirmed" if respuesta == "si" and not otros4 and not vencido and t.turno > accion.get("turno_aviso", t.turno)
                 else "expired" if vencido else "other_card" if otros4 else "declined" if respuesta == "no" else "ambiguous")
    auditoria.registrar_evento(
        t.bd, event_type= "confirmation", conversation_id= t.conv.id, session_id= t.registro.id, actor= "orchestrator",
        auth_level= identidad.nivel_actual(t.bd, t.registro), state= t.estado, rule_ids= ["POL-ACT-02", "POL-ACT-03", "POL-ACT-04"],
        customer_id= t.conv.customer_id, session_origin= identidad.origen_sesion(t.registro),
        campos= {"confirmation_event": "resolved", "confirmation_token_id": accion.get("token_id"), "action": "block_card",
                 "card_ref": auditoria.seudonimo(accion.get("card_id", "")), "last4": accion.get("last4"), "card_type": accion.get("tipo"),
                 "prompt_turn_index": accion.get("turno_aviso"), "expires_at": accion.get("expira_en"), "outcome": resultado,
                 "answer_turn_index": t.turno},
    )
    if resultado != "confirmed":
        # T-33 (POL-ACT-03): se cancela; nada se ejecuta.
        t.ctx["acciones"].append({"action": "block_card", "card_last4": accion.get("last4"), "confirmation_token_id": accion.get("token_id"),
                                  "requested_at": identidad.ahora_utc().isoformat(), "executed": "false", "verified": False,
                                  "verification_tool_call_id": None, "cancelled": resultado})
        t.ctx["accion"] = None
        t.decir("bloqueo_cancelado", regla= "POL-ACT-03")
        if t.ctx.get("luego_transferir"):
            t.transicion("T-33", "HANDOFF", "POL-ACT-03")
            _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= True))
        else:
            t.transicion("T-33", "IDLE", "POL-ACT-03")
            t.decision = "none"
        return
    t.transicion("T-32", "EXECUTING", "POL-ACT-02", "POL-ACT-04")
    _ejecutar_bloqueo(t)


def _ejecutar_bloqueo(t: Turno) -> None:
    """EXECUTING (atómico): lectura previa, block_card una vez por token, lectura de verificación con
    reintentos. Solo un Blocked releído se informa como hecho (POL-ACT-05, 06, 09; T-34, T-35)."""
    accion = t.ctx["accion"]
    t.decision = "act"
    solicitado = identidad.ahora_utc()
    previa = t.estado_tarjeta(accion["card_id"])
    if previa.ok and previa.valor["status"] != "Active":
        t.ctx["accion"] = None
        if previa.valor["status"] == "Blocked":
            t.transicion("T-24", "IDLE", "POL-ACT-01")
            t.decir("ya_bloqueada", regla= "POL-ACT-01", tipo= textos.tipo_tarjeta(previa.valor["type"], t.idioma), ultimos4= previa.valor["last4"])
            return
        t.transicion("T-25", "HANDOFF", "POL-ESC-12")
        t.libre(_frase_estado(previa.valor, t.idioma), "POL-ESC-12")
        _transferir(t, ["POL-ESC-12"], [f"Card {previa.valor['last4']} is {previa.valor['status']}; the block was not run."])
        return
    if previa.ok:
        t.hecho_verificado("card_status_before_action (history)", previa.valor, previa.tool_call_id)

    ejecutado, bloqueo = "false", None
    if previa.ok:
        bloqueo = t.gw.llamar("block_card", card_id= accion["card_id"], token_confirmacion= accion["token"])
        ejecutado = "true" if bloqueo.status == "ok" else ("unknown" if bloqueo.status in ("timeout", "error") else "false")
        t.ctx["ultima_accion_en"] = identidad.ahora_utc().isoformat() # Hechos leídos antes ya no sirven (POL-GEN-07 a).
        if bloqueo.status in ("timeout", "error"):
            # block_card no llegó a escribir su action_result: lo escribe el gateway (POL-ACT-09).
            auditoria.registrar_evento(
                t.bd, event_type= "action_result", conversation_id= t.conv.id, session_id= t.registro.id, actor= "action_gateway",
                auth_level= identidad.nivel_actual(t.bd, t.registro), state= "EXECUTING", rule_ids= ["POL-ACT-06", "POL-ACT-09"],
                customer_id= t.conv.customer_id, session_origin= identidad.origen_sesion(t.registro),
                campos= {"action_id": None, "action": "block_card", "card_ref": auditoria.seudonimo(accion["card_id"]), "last4": accion["last4"],
                         "confirmation_token_id": accion.get("token_id"), "step_up_id": None,
                         "preconditions": {"auth_level": "L2", "pre_status": "Active", "pre_status_tool_call_id": previa.tool_call_id},
                         "tool_call_id": bloqueo.tool_call_id, "requested_at": auditoria.iso_utc(solicitado), "executed": "unknown",
                         "error_code": bloqueo.error_code},
            )

    verificacion = t.estado_tarjeta(accion["card_id"]) if previa.ok else None
    verificado = bool(verificacion and verificacion.ok and verificacion.valor["status"] == "Blocked")
    auditoria.registrar_evento(
        t.bd, event_type= "verification", conversation_id= t.conv.id, session_id= t.registro.id, actor= "action_gateway",
        auth_level= identidad.nivel_actual(t.bd, t.registro), state= "EXECUTING", rule_ids= ["POL-ACT-05"],
        customer_id= t.conv.customer_id, session_origin= identidad.origen_sesion(t.registro),
        campos= {"action_id": (bloqueo.valor or {}).get("request_id") if bloqueo and bloqueo.ok else None,
                 "tool_call_ids": verificacion.intentos if verificacion else [], "expected_status": "Blocked",
                 "observed_status": verificacion.valor["status"] if verificacion and verificacion.ok else None,
                 "verified": verificado, "customer_told": "POL-ACT-11" if verificado else "POL-ACT-10"},
    )
    t.ctx["acciones"].append({
        "action": "block_card", "card_last4": accion["last4"], "confirmation_token_id": accion.get("token_id"),
        "requested_at": solicitado.isoformat(), "executed": ejecutado, "verified": verificado,
        "verification_tool_call_id": verificacion.tool_call_id if verificacion else None,
    })
    t.regla("POL-ACT-05", "POL-ACT-06", "POL-ACT-09")
    senales = accion.get("signals") or {}
    t.ctx["accion"] = None

    if verificado:
        # T-34: POL-ACT-11, y POL-ACT-13 si el pedido traía robo o fraude (POL-ACT-12).
        t.hecho_verificado("card_status_after_action", verificacion.valor, verificacion.tool_call_id)
        t.decir("POL-ACT-11", "plantilla", "POL-ACT-11", tipo= textos.tipo_tarjeta(accion["tipo"], t.idioma), ultimos4= accion["last4"])
        t.regla("POL-ACT-11")
        if senales.get("theft") or senales.get("dispute_or_fraud"):
            t.decir("POL-ACT-13", "plantilla", "POL-ACT-13")
            t.regla("POL-ACT-12", "POL-ACT-13")
        if t.ctx.get("luego_transferir"):
            t.transicion("T-34", "HANDOFF", "POL-ACT-05")
            _transferir(t, ["POL-ESC-01"], _preguntas_disputa(t, ofrecido= True, aceptado= True))
        else:
            t.transicion("T-34", "IDLE", "POL-ACT-05")
        return

    # T-35: sin verificar; POL-ACT-10 y transferencia urgente (POL-HND-15).
    t.transicion("T-35", "HANDOFF", "POL-ACT-05", "POL-ACT-10", "POL-ESC-07", "POL-REL-01", "POL-REL-02", "POL-HND-15")
    lecturas = ", ".join(verificacion.intentos) if verificacion else "none"
    _transferir(t, ["POL-ACT-05", "POL-ESC-07"], [
        f"Was card {accion['last4']} blocked? block_card ({bloqueo.tool_call_id if bloqueo else 'not called'}) ended as "
        f"{bloqueo.status if bloqueo else 'not called'} and the verification reads ({lecturas}) did not return Blocked. "
        "Check the core status and complete the block if it was not applied.",
        "The customer was told to treat the card as NOT blocked (POL-ACT-10).",
    ], plantilla_final= ("POL-ACT-10", accion["last4"]), urgente= True)


# --- transferencia (HANDOFF) --------------------------------------------------------------------

def _prioridad(t: Turno, urgente: bool) -> str:
    """POL-HND-15: urgent > security > normal."""
    if urgente:
        return "urgent"
    contadores = t.ctx["contadores"]
    seguridad_ = (contadores["injection_hits"] or contadores["unauthorized_hits"] >= 2
                  or any(e["type"] in ("step_up_lockout",) or e.get("subtype") == "c_second_card_miss"
                         for e in t.ctx["evidencia"]["security_events"]))
    return "security" if seguridad_ else "normal"


def _transferir(t: Turno, reglas: List[str], preguntas: List[str], pedido: Optional[str] = None,
                conservar_pedido: bool = False, plantilla_final: Optional[Tuple[str, str]] = None, urgente: bool = False,
                mensaje_actual: bool = False) -> None:
    """HANDOFF: expediente completo, open_handoff (reintentable con la misma clave) y T-36 o T-37.

    POL-HND-10 pide el último mensaje relevante: el del pedido en curso cuando la transferencia sigue a
    respuestas en estados de espera (diálogo 5), o el de este turno cuando es este mensaje el que la
    dispara (G-03 a G-07, diálogo 7)."""
    t.estado = "HANDOFF"
    t.decision = "transfer"
    prioridad = _prioridad(t, urgente)
    if prioridad == "security":
        t.regla("POL-HND-15")
    pedido_ctx = t.ctx.get("pedido") or {}
    expediente = {
        "request": pedido if pedido else {
            "last_message_redacted": (t.ctx.get("ultimo_mensaje") if mensaje_actual else None)
            or pedido_ctx.get("last_message_redacted") or t.ctx.get("ultimo_mensaje"),
            "summary": _resumen(t, reglas), "summary_generated_by": "template",
            "top_intent": pedido_ctx.get("top_intent"), "conformal_set": pedido_ctx.get("conformal_set", []),
        },
        "verified_facts": t.ctx["hechos_verificados"],
        "actions_taken": t.ctx["acciones"],
        "evidence": t.ctx["evidencia"],
        "unresolved_questions": preguntas,
        "reason_rule_ids": [r for r in dict.fromkeys(reglas + (["POL-ESC-08"] if t.ctx["contadores"]["injection_hits"] and "POL-ESC-08" not in reglas
                                                                 and prioridad == "security" else []))],
        "priority": prioridad,
        "language": t.idioma,
        "appended_messages": [],
    }
    clave = f"{t.conv.id}:t{t.turno}"
    try:
        llamada = t.gw.llamar("open_handoff", expediente= expediente, idempotency_key= clave)
    except NoPermitidaEnEstado:
        llamada = None
    t.regla("POL-HND-10", "POL-HND-11", "POL-HND-12", "POL-HND-13", "POL-HND-14", "POL-HND-15", "POL-HND-01")
    if llamada is not None and llamada.ok:
        t.case_id = llamada.valor["case_id"]
        t.transicion("T-36", "HANDED_OFF", "POL-HND-03")
        if plantilla_final:
            t.decir(plantilla_final[0], "plantilla", plantilla_final[0], ultimos4= plantilla_final[1], case_id= t.case_id)
        else:
            t.decir("POL-HND-03", "plantilla", "POL-HND-03", case_id= t.case_id)
        return
    # T-37 (POL-HND-02, POL-REL-03): sin caso no se da referencia; cola de respaldo local.
    cola_respaldo.encolar(t.conv.id, clave, expediente)
    t.transicion("T-37", "HANDED_OFF", "POL-HND-02", "POL-HND-05", "POL-REL-03")
    t.ctx["respaldo"] = True
    t.segmentos = [s for s in t.segmentos if s.regla != "POL-ACT-10"]
    t.decir("POL-HND-05", "plantilla", "POL-HND-05")
    auditoria.registrar_evento(
        t.bd, event_type= "handoff", conversation_id= t.conv.id, session_id= t.registro.id, actor= "handoff_service",
        auth_level= identidad.nivel_actual(t.bd, t.registro), state= "HANDOFF", rule_ids= ["POL-REL-03", "POL-HND-02"],
        customer_id= t.conv.customer_id, session_origin= identidad.origen_sesion(t.registro),
        campos= {"handoff_event": "fallback_queued", "case_id": None, "idempotency_key": clave, "priority": prioridad,
                 "reason_rule_ids": expediente["reason_rule_ids"], "case_file_fields_present": {k: True for k in banco.CAMPOS_CONTENIDO}},
    )


def _resumen(t: Turno, reglas: List[str]) -> str:
    pedido = t.ctx.get("pedido") or {}
    intencion = pedido.get("top_intent") or (t.ctx.get("pendiente") or {}).get("intencion")
    return f"Transfer by {', '.join(reglas)}; customer request classified as {intencion or 'not classified'}."


MANEJADORES: Dict[str, Callable[[Turno, str], None]] = {
    "IDLE": _idle,
    "CLARIFY_INTENT": _aclarar,
    "SELECT_CARD": _seleccionar_tarjeta,
    "SELECT_TRANSACTION": _elegir_transaccion,
    "OFFER_BLOCK": _ofrecer_bloqueo,
    "STEP_UP": _paso_step_up_texto,
    "AWAIT_CONFIRMATION": _confirmar,
    "UNAUTHENTICATED": lambda t, texto: t.decir("iniciar_sesion", regla= "POL-AUTH-01"),
}
