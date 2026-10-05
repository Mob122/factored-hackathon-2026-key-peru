"""Tool gateway del orquestador.

- Tools permitidas por estado (docs/contracts/state_machine.md sección 2). Una llamada no permitida
  devuelve TOOL_NOT_ALLOWED_IN_STATE, escribe un evento security y nunca llega a la tool.
- Cada tool sigue haciendo sus propios controles de sesión (POL-AUTH-03, 05) y block_card los de
  POL-ACT-01, 02 y 06.
- Lecturas: hasta READ_RETRIES reintentos con espera; cada reintento es otra llamada con su id
  ("c7-r1") y su evento (POL-REL-01). block_card nunca se reintenta (POL-ACT-06); open_handoff se
  reintenta con la misma clave de idempotencia (POL-REL-02).
- Cada llamada escribe un evento tool_call con argumentos seudonimizados y el resultado reducido a
  los campos de POL-PII-03, más el digest del resultado completo (AL-P3, AL-P6).
- Los resultados quedan como hechos con su hora de lectura, para POL-GEN-07.

Las tools del banco corren en el mismo proceso, así que no hay un corte por tiempo: un TimeoutError
o un error de servicio que levante la tool (o una falla inyectada en una prueba) se registra como
timeout o error. Un cliente del core bancario real tendría su propio límite de TOOL_TIMEOUT_SEC.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

import hashlib
import json
import time

from sqlmodel import Session

from services import auditoria, banco, identidad
from services.identidad import ErrorSesion

READ_RETRIES = 2 # POL-REL-01
ESPERAS_SEG = (0.5, 1.0)
LECTURAS = {"list_cards", "get_card_status", "list_transactions", "describe_transaction", "list_balance_products", "get_balance"}

PERMITIDAS: Dict[str, set] = { # state_machine.md sección 2
    "UNAUTHENTICATED": {"authenticate"},
    "IDLE": {"list_cards", "list_balance_products"},
    "CLARIFY_INTENT": set(),
    "SELECT_CARD": {"list_cards", "list_balance_products"},
    "ANSWERING": {"list_cards", "list_balance_products", "get_card_status", "list_transactions", "describe_transaction", "get_balance"},
    "SELECT_TRANSACTION": {"list_transactions", "describe_transaction"},
    "OFFER_BLOCK": set(),
    "ACTION_PRECHECK": {"get_card_status"},
    "STEP_UP": {"step_up"},
    "AWAIT_CONFIRMATION": set(),
    "EXECUTING": {"get_card_status", "block_card"},
    "HANDOFF": {"open_handoff"},
    "SESSION_EXPIRED": {"authenticate"},
    "HANDED_OFF": set(),
    "ENDED": set(),
}

# Campos que pueden quedar en claro en el audit log (AL-P4); los ids van como seudónimos (AL-P3).
_CAMPOS_CLAROS = {"last4", "type", "status", "kind", "currency", "current_balance", "credit_limit", "as_of", "date",
                  "amount", "merchant", "response_code", "templates", "notices", "accepted", "from", "to",
                  "window_capped", "truncated", "auth_level", "expires_at", "single_use", "language", "customer_status"}
_IDS = {"card_id": "card_ref", "product_id": "card_ref", "transaction_id": "transaction_ref", "request_id": "action_ref",
        "case_id": "case_id", "step_up_id": "step_up_id", "bound_card_id": "card_ref"}


class SesionVencida(Exception):
    """Una tool devolvió SESSION_EXPIRED: el turno pasa por G-01."""


class NoPermitidaEnEstado(Exception):
    """Defecto interno: el orquestador pidió una tool que el estado no permite."""


@dataclass
class Llamada:
    tool_call_id: str
    tool: str
    status: str # ok, empty, error, timeout, refused, session_expired
    valor: Any = None
    error_code: Optional[str] = None
    intentos: List[str] = field(default_factory= list)

    @property
    def ok(self) -> bool:
        return self.status in ("ok", "empty")


def _serializable(valor: Any) -> Any:
    return json.loads(json.dumps(valor, default= str))


def resumen_auditable(valor: Any) -> Any:
    """Resultado reducido a los campos permitidos, con ids seudonimizados (AL-P3, AL-P4, AL-P6)."""
    if isinstance(valor, list):
        return [resumen_auditable(v) for v in valor]
    if isinstance(valor, dict):
        limpio = {}
        for clave, contenido in valor.items():
            if clave in _IDS and isinstance(contenido, str):
                ref = _IDS[clave]
                limpio[ref] = contenido if ref in ("case_id", "step_up_id") else auditoria.seudonimo(contenido)
            elif clave == "transactions":
                limpio[clave] = resumen_auditable(contenido)
            elif clave in _CAMPOS_CLAROS:
                limpio[clave] = _serializable(contenido)
        return limpio
    return None


class Gateway:
    def __init__(self, bd: Session, conversacion, registro, contexto: Dict[str, Any], estado: Callable[[], str],
                 dormir: Callable[[float], None] = time.sleep):
        self.bd = bd
        self.conversacion = conversacion
        self.registro = registro
        self.ctx = contexto
        self.estado = estado
        self.dormir = dormir
        self.llamadas_turno: List[str] = []

    # --- ids y hechos ---------------------------------------------------------------------------

    def nuevo_id(self) -> str:
        self.ctx["tool_seq"] = self.ctx.get("tool_seq", 0) + 1
        return f"c{self.ctx['tool_seq']}"

    def registrar_hecho(self, clave: str, valor: Any, tool_call_id: str) -> None:
        self.ctx.setdefault("hechos", {})[clave] = {
            "valor": _serializable(valor), "tool_call_id": tool_call_id, "leido_en": identidad.ahora_utc().isoformat(),
        }

    def hecho_fresco(self, clave: str, max_seg: int) -> Optional[Dict[str, Any]]:
        """POL-GEN-07 (a): un hecho sirve si se leyó hace menos de max_seg y ninguna acción con efecto corrió después."""
        hecho = self.ctx.get("hechos", {}).get(clave)
        if not hecho:
            return None
        leido = datetime.fromisoformat(hecho["leido_en"])
        ultima_accion = self.ctx.get("ultima_accion_en")
        if ultima_accion and datetime.fromisoformat(ultima_accion) >= leido:
            return None
        return hecho if (identidad.ahora_utc() - leido).total_seconds() <= max_seg else None

    # --- llamadas -------------------------------------------------------------------------------

    def _auditar(self, tool_call_id: str, tool: str, intento: int, reintento_de: Optional[str], argumentos: Dict[str, Any],
                 status: str, error_code: Optional[str], latencia_ms: int, resultado: Any, permitida: bool = True) -> None:
        completo = json.dumps(resultado, default= str, sort_keys= True) if resultado is not None else ""
        auditoria.registrar_evento(
            self.bd, event_type= "tool_call", conversation_id= self.conversacion.id, session_id= self.registro.id,
            actor= "tool_gateway", auth_level= identidad.nivel_actual(self.bd, self.registro), state= self.estado(),
            rule_ids= [], customer_id= self.registro.customer_id, session_origin= identidad.origen_sesion(self.registro),
            campos= {
                "tool_call_id": tool_call_id, "tool": tool, "attempt": intento, "retry_of": reintento_de,
                "allowed_in_state": permitida, "args": resumen_auditable(argumentos) or {}, "status": status,
                "error_code": error_code, "latency_ms": latencia_ms, "result": resumen_auditable(resultado),
                "result_digest": hashlib.sha256(completo.encode("utf-8")).hexdigest(),
                "data_as_of": _serializable(resultado.get("as_of")) if isinstance(resultado, dict) and resultado.get("as_of") else None,
                "fixture": None,
            },
        )

    def _evidencia(self, tool_call_id: str, tool: str, status: str) -> None:
        self.ctx.setdefault("evidencia", {}).setdefault("tool_calls", []).append({
            "tool_call_id": tool_call_id, "tool": tool, "called_at": identidad.ahora_utc().strftime("%H:%M:%S"),
            "status": status, "result_ref": f"audit://{self.conversacion.id}/{tool_call_id}",
        })

    def llamar(self, tool: str, funcion: Optional[Callable[..., Any]] = None, **argumentos) -> Llamada:
        estado = self.estado()
        base_id = self.nuevo_id()
        if tool not in PERMITIDAS.get(estado, set()):
            self._auditar(base_id, tool, 1, None, argumentos, "not_allowed_in_state", "TOOL_NOT_ALLOWED_IN_STATE", 0, None, permitida= False)
            auditoria.registrar_evento(
                self.bd, event_type= "security", conversation_id= self.conversacion.id, session_id= self.registro.id,
                actor= "tool_gateway", auth_level= identidad.nivel_actual(self.bd, self.registro), state= estado,
                rule_ids= ["POL-GEN-01"], customer_id= self.registro.customer_id,
                session_origin= identidad.origen_sesion(self.registro),
                campos= {"security_event": "tool_not_allowed_in_state", "subtype": tool, "occurrence": 1,
                         "detector": "gateway-state-table-sm-0.4", "evidence": {}, "effect": "refused_continue"},
            )
            raise NoPermitidaEnEstado(f"{tool} no está permitida en {estado}")

        funcion = funcion or banco.HERRAMIENTAS[tool]
        intentos = READ_RETRIES + 1 if tool in LECTURAS else (3 if tool == "open_handoff" else 1)
        llamada = Llamada(tool_call_id= base_id, tool= tool, status= "error")

        for intento in range(intentos):
            tool_call_id = base_id if intento == 0 else f"{base_id}-r{intento}"
            if intento:
                self.dormir(ESPERAS_SEG[min(intento - 1, len(ESPERAS_SEG) - 1)])
            inicio = time.monotonic()
            valor, status, codigo = None, "ok", None
            try:
                valor = funcion(self.bd, identidad.sesion_cliente_desde(self.registro), **argumentos)
                if valor in ([], None) or (isinstance(valor, dict) and valor.get("transactions") == []):
                    status = "empty"
            except banco.ErrorHerramienta as error:
                status = "session_expired" if error.codigo in ("SESSION_EXPIRED", "SESSION_INVALID") else "refused"
                codigo = error.codigo
            except ErrorSesion as error:
                status, codigo = ("session_expired" if error.codigo == "SESSION_EXPIRED" else "refused"), error.codigo
            except TimeoutError:
                status, codigo = "timeout", "TIMEOUT"
            except Exception as error: # Falla del servicio: se registra y, si es una lectura, se reintenta.
                status, codigo = "error", type(error).__name__.upper()
            latencia = int((time.monotonic() - inicio) * 1000)

            self._auditar(tool_call_id, tool, intento + 1, base_id if intento else None, argumentos, status, codigo, latencia, valor)
            self._evidencia(tool_call_id, tool, status)
            self.llamadas_turno.append(tool_call_id)
            llamada = Llamada(tool_call_id= tool_call_id, tool= tool, status= status, valor= valor, error_code= codigo,
                              intentos= [*llamada.intentos, tool_call_id])

            if status == "session_expired":
                raise SesionVencida()
            if status in ("ok", "empty", "refused"):
                break
            if tool == "block_card": # POL-ACT-06: nunca se reintenta a ciegas.
                break

        if not llamada.ok and llamada.status != "refused":
            self.ctx.setdefault("contadores", {})["tool_fail_rounds"] = self.ctx.get("contadores", {}).get("tool_fail_rounds", 0) + 1
        return llamada
