"""Portal del cliente: lecturas de sus propios datos en la web, fuera del chat (POL-PII-10).

- Tarjetas y transacciones salen de las mismas tools que usa el asistente (list_cards POL-ANS-01,
  list_transactions POL-ANS-03), con sus mismos controles: sesión de cliente vigente, solo el cliente
  de la sesión, estado del cliente (POL-AUTH-09), ventana de días y tope de filas. De una transacción
  van solo los campos de POL-ANS-03: el código de respuesta no dice la causa (POL-ANS-10) y lo explica
  el asistente con sus plantillas.
- Nunca devuelve ids internos (card_id, product_id, transaction_id). Una tarjeta se nombra con `ref`
  (t1, t2, … por orden de card_id), que solo agrupa filas en la pantalla y ninguna tool acepta.
- De los casos devuelve la referencia y su contexto, nunca el expediente (hechos verificados,
  evidencia, preguntas abiertas), que es del agente (POL-PII-05, POL-PII-07).
- Los saldos no están aquí: solo los dice el asistente, leídos en el turno y con su as_of (POL-GEN-07).
- No son turnos del chat, así que no escriben en el audit log.
"""

from datetime import timedelta
from typing import Any, Dict, List

from sqlmodel import Session, select

from models.banco import Caso
from models.chat import Conversacion
from services import banco
from services.identidad import SesionCliente

CONVERSACIONES_MAX = 50


def _tarjetas_con_ref(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    return [
        {"ref": f"t{n}", "card_id": tarjeta["card_id"], "last4": tarjeta["last4"], "tipo": tarjeta["type"],
         "estado": tarjeta["status"]}
        for n, tarjeta in enumerate(banco.list_cards(sesion, sesion_cliente), start= 1)
    ]


def tarjetas(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    return [{k: v for k, v in tarjeta.items() if k != "card_id"} for tarjeta in _tarjetas_con_ref(sesion, sesion_cliente)]


def transacciones(sesion: Session, sesion_cliente: SesionCliente, dias: int) -> Dict[str, Any]:
    """Las transacciones de los últimos `dias` días de cada tarjeta del cliente (1 a TX_DIAS_MAX)."""
    hoy = banco.ahora_banco().date()
    desde = hoy - timedelta(days= dias)
    por_tarjeta = []

    for tarjeta in _tarjetas_con_ref(sesion, sesion_cliente):
        lista = banco.list_transactions(sesion, sesion_cliente, tarjeta.pop("card_id"), desde= desde, hasta= hoy)
        por_tarjeta.append({
            **tarjeta,
            "truncada": lista["truncated"],
            "transacciones": [
                {"fecha": tx["date"], "tipo": tx["type"], "monto": tx["amount"], "moneda": tx["currency"],
                 "comercio": tx["merchant"], "estado": tx["status"]}
                for tx in lista["transactions"]
            ],
        })

    return {"desde": desde, "hasta": hoy, "tarjetas": por_tarjeta}


def casos(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    filas = sesion.exec(
        select(Caso).where(Caso.customer_id == sesion_cliente.customer_id).order_by(Caso.created_at.desc())
    ).all()

    def last4s(caso: Caso) -> List[str]:
        tarjetas_caso = caso.evidence.get("cards", []) if isinstance(caso.evidence, dict) else []
        return sorted({t["last4"] for t in tarjetas_caso if isinstance(t, dict) and t.get("last4")})

    return [
        {
            "case_id": caso.case_id,
            "creado_en": caso.created_at,
            "prioridad": caso.priority,
            "motivo": caso.request.get("top_intent") if isinstance(caso.request, dict) else None,
            "tarjetas_last4": last4s(caso),
            "mensajes_agregados": len(caso.appended_messages),
            "conversation_id": caso.conversation_ref,
        }
        for caso in filas
    ]


def conversaciones(sesion: Session, sesion_cliente: SesionCliente) -> List[Dict[str, Any]]:
    filas = sesion.exec(
        select(Conversacion).where(Conversacion.customer_id == sesion_cliente.customer_id)
        .order_by(Conversacion.actualizada_en.desc()).limit(CONVERSACIONES_MAX)
    ).all()

    return [
        {"conversation_id": c.id, "estado": c.estado, "turnos": c.turno, "idioma": c.idioma, "case_id": c.case_id,
         "creada_en": c.creada_en, "actualizada_en": c.actualizada_en}
        for c in filas
    ]
