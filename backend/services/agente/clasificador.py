"""Paso 5 del turno: intención con conjunto conformal (docs/contracts/state_machine.md sección 4).

- Modelo: banking_cs.nlu.predict con method="lac" (docs/eval_plan.md 8.4), incluidos sus
  safety_override (card_block y charge_dispute) y signals (POL-ESC-06, POL-ACT-12).
- Si el artefacto no carga (falta, cambió su SHA-256, otra versión de scikit-learn), se usa el
  parser de reglas de banking_cs.nlu.rules, con los mismos overrides. El evento classification
  dice cuál se usó. El backend nunca importa Kedro: solo el paquete banking_cs.nlu.
- POL-ESC-14: un seguimiento elíptico ("E o do cartão de crédito?") no trae intención propia; si el
  modelo da un conjunto vacío o {out_of_scope} y el turno anterior sirvió una intención de lectura,
  el conjunto pasa a ser esa intención. Nunca una acción ni una transferencia.

El texto que llega ya está redactado (POL-PII-01): predict no redacta números de tarjeta.
"""

from pathlib import Path
from typing import Any, Dict, Optional

import logging
import os
import sys

logger = logging.getLogger(__name__)

# Se predice un mensaje a la vez: los hilos de BLAS no aportan nada y OpenBLAS reserva memoria por
# hilo al cargar numpy. Con muchos núcleos y poca memoria libre esa reserva falla y tumba el proceso
# ("OpenBLAS error: Memory allocation still failed"). Debe fijarse antes del primer import de numpy.
for _variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_variable, "1")

RAIZ_REPO = Path(__file__).resolve().parents[2] # MARTIN IS BACK.
DIR_ML_SRC = Path(os.getenv("ML_SRC_DIR") or RAIZ_REPO / "ml" / "src")
if str(DIR_ML_SRC) not in sys.path:
    sys.path.append(str(DIR_ML_SRC))

from banking_cs.nlu import rules # noqa: E402  Solo biblioteca estándar.

INTENCIONES_LECTURA = set(rules.READ_INTENTS)
BLOQUEO, DISPUTA, HUMANO = "card_block", "charge_dispute", "human_request"

_modelo = None
_error_modelo: Optional[str] = None


def _cargar_modelo():
    """Carga el artefacto una vez. Si falla, queda registrado el motivo y se usan las reglas."""
    global _modelo, _error_modelo
    if _modelo is not None or _error_modelo is not None:
        return _modelo
    try:
        from banking_cs.nlu import predict # numpy, scikit-learn, joblib

        _modelo = predict.load(os.getenv("NLU_ARTIFACT_DIR") or None)
    except Exception as error: # ArtifactError, ImportError, versión de scikit-learn distinta...
        _error_modelo = f"{type(error).__name__}: {error}"
        logger.warning("Clasificador: el artefacto NLU no cargó (%s); se usan las reglas de rules.py.", _error_modelo)
    return _modelo


def estado_modelo() -> Dict[str, Any]:
    modelo = _cargar_modelo()
    if modelo is None:
        return {"classifier": "rules-fallback", "error": _error_modelo}
    return {"classifier": modelo.metadata.get("model_type"), "artifact_sha256": modelo.metadata.get("model_sha256")}


def _overrides_reglas(conjunto: list, top: str, texto: str) -> tuple:
    """La misma lógica de predict.apply_overrides, para cuando predict no se puede importar."""
    if HUMANO in conjunto:
        return conjunto, []
    agregadas = []
    for intencion, senal in ((BLOQUEO, rules.block_signal), (DISPUTA, rules.dispute_signal)):
        if intencion in conjunto or not senal(texto):
            continue
        conjunto = [*conjunto, intencion] if conjunto else ([intencion] if top == intencion else [top, intencion])
        agregadas.append(intencion)
    return conjunto, agregadas


def _por_reglas(texto: str) -> Dict[str, Any]:
    intencion, puntaje = rules.classify(texto)
    conjunto, agregadas = _overrides_reglas([intencion], intencion, texto)
    slots = rules.extract_slots(texto, intencion)
    for extra in conjunto[1:]:
        slots.update({k: v for k, v in rules.extract_slots(texto, extra).items() if k not in slots})
    return {
        "intent_set": conjunto,
        "top_intent": intencion,
        "top_score": puntaje,
        "scores": {intencion: puntaje},
        "slots": slots,
        "safety_override": agregadas,
        "signals": {"block_or_theft": rules.block_signal(texto), "theft": rules.theft_signal(texto),
                    "dispute_or_fraud": rules.dispute_signal(texto)},
        "classifier": "rules-fallback",
        "artifact_sha256": None,
        "conformal_alpha": None,
        "conformal_threshold": None,
        "max_set": 2,
        "fallback_reason": _error_modelo,
    }


def clasificar(texto_redactado: str, idioma: Optional[str] = None) -> Dict[str, Any]:
    """Conjunto conformal, intención principal, slots, scores, overrides y señales de un mensaje."""
    modelo = _cargar_modelo()
    if modelo is None:
        return _por_reglas(texto_redactado)

    resultado = modelo.predict(texto_redactado, method= "lac", language= idioma)
    scores = resultado["scores"]
    top = next(iter(scores))
    return {
        **resultado,
        "top_intent": top,
        "top_score": scores[top],
        "classifier": modelo.metadata.get("model_type"),
        "artifact_sha256": modelo.metadata.get("model_sha256"),
        "conformal_alpha": modelo.conformal.get("alpha"),
        "conformal_threshold": modelo.threshold("lac", idioma),
        "max_set": modelo.max_set,
        "fallback_reason": None,
    }


def seguimiento_eliptico(resultado: Dict[str, Any], texto: str, intencion_anterior: Optional[str], es_continuacion: bool) -> Optional[str]:
    """POL-ESC-14: la intención de lectura anterior, si el mensaje es un seguimiento elíptico de ella."""
    sin_intencion = resultado["intent_set"] in ([], ["out_of_scope"])
    if not (sin_intencion and es_continuacion and intencion_anterior in INTENCIONES_LECTURA):
        return None
    slots_producto = {k for k in rules.extract_slots(texto) if k in ("product_kind", "last4")}
    toma = set(rules.INTENT_SLOTS[intencion_anterior])
    return intencion_anterior if slots_producto and slots_producto <= toma else None


def slots_de(texto: str, intencion: str) -> Dict[str, str]:
    """Slots de una intención (los del modelo vienen de las mismas reglas); balance_item solo para saldo."""
    return rules.extract_slots(texto, intencion)


def es_pedido_de_humano(texto_redactado: str) -> bool:
    """G-03 en estados de espera: un pedido de un asesor se atiende en cualquier estado (POL-ESC-09)."""
    return rules.classify(texto_redactado)[0] == HUMANO


def otras_lecturas(texto_redactado: str, servida: str) -> list:
    """POL-GEN-06: otras intenciones de lectura pedidas en el mismo mensaje, que no se sirvieron."""
    puntajes = rules.intent_scores(texto_redactado)
    return [i for i in rules.READ_INTENTS if i != servida and puntajes.get(i, 0) >= 0.5]
