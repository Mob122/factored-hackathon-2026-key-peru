"""Redacción de respuestas con un LLM (OpenAI, SDK oficial), configurado solo desde backend/.env.

- LLM_MODE: "mock" (por defecto) nunca llama a la API: la respuesta son las plantillas y frases
  redactadas por el código. "openai" llama a LLM_MODEL en LLM_BASE_URL con OPENAI_API_KEY.
- El backend no arranca si LLM_MODEL no está en LLM_ALLOWED_MODELS, si LLM_MODE no es válido, o
  si LLM_MODE=openai y falta OPENAI_API_KEY.
- El LLM solo reformula oraciones que el código ya escribió con hechos verificados. Las plantillas
  de la política y las frases fijas no se le mandan y no se reescriben (policy_cards.md sección 0).
- Antes de cada llamada se redacta y se escanea el pedido (POL-PII-01, 02; INV-09). Si el escaneo
  encuentra algo, no se llama.
- 429 y errores transitorios: espera exponencial con jitter, 30 s de timeout, como mucho 3
  reintentos; después, respuesta solo con plantillas (POL-REL-04).
- Cada llamada queda en el audit log (evento llm_call): modelo devuelto por la API, hash del
  prompt, tokens y costo a precio de lista.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import hashlib
import json
import logging
import os
import random
import re
import time

from services.agente import seguridad

logger = logging.getLogger(__name__)

MODOS = ("mock", "openai")
TIMEOUT_SEG = 30
MAX_REINTENTOS = 3
ESPERA_BASE_SEG = 1.0
# USD por millón de tokens, precio de lista de OpenAI para gpt-4o-mini supuesto al escribir esto
# (el mismo que ml/src/banking_cs/nlu/llm_baseline.py).
PRECIO_ENTRADA_M = 0.15
PRECIO_ENTRADA_CACHE_M = 0.075
PRECIO_SALIDA_M = 0.60
PLANTILLA_PROMPT = "reformular-v1"
INSTRUCCIONES = (
    "Eres el redactor de un asistente bancario. Recibes oraciones numeradas que ya contienen solo "
    "hechos verificados. Reescribe cada una en {idioma}, en registro {registro}, de forma clara y "
    "breve. No agregues ni quites hechos, cifras, fechas, últimos dígitos, nombres de comercio ni "
    "promesas. Conserva cada número exactamente como aparece. No inventes información. Responde "
    "solo con un arreglo JSON de cadenas, una por oración, en el mismo orden."
)


def _leer_config() -> Dict[str, Any]:
    modo = (os.getenv("LLM_MODE") or "mock").strip().lower()
    modelo = (os.getenv("LLM_MODEL") or "").strip()
    permitidos = [m.strip() for m in (os.getenv("LLM_ALLOWED_MODELS") or "").split(",") if m.strip()]

    if modo not in MODOS:
        raise RuntimeError(f"LLM_MODE debe ser uno de {MODOS}.")
    if not modelo or modelo not in permitidos:
        raise RuntimeError("LLM_MODEL debe estar definido y figurar en LLM_ALLOWED_MODELS (backend/.env).")
    proveedor = (os.getenv("LLM_PROVIDER") or "openai").strip().lower()
    if proveedor != "openai":
        raise RuntimeError("LLM_PROVIDER solo admite openai.")
    if modo == "openai" and not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("LLM_MODE=openai necesita OPENAI_API_KEY en backend/.env.")
    return {"modo": modo, "modelo": modelo, "base_url": os.getenv("LLM_BASE_URL") or None}


CONFIG = _leer_config() # Al importar: si falla, el backend no arranca.


@dataclass
class ResultadoLLM:
    textos: Optional[List[str]] # None: usar las oraciones del código (mock, fallo o escaneo).
    llamada: Optional[Dict[str, Any]] = None # Campos del evento llm_call; None si no hubo llamada.
    fallo: bool = False


@dataclass
class ClienteLLM:
    """Envuelve el cliente de OpenAI. `cliente` se puede reemplazar en pruebas (ninguna prueba llama a la API)."""
    cliente: Any = None
    dormir: Callable[[float], None] = field(default= time.sleep)

    def _cliente(self):
        if self.cliente is None:
            from openai import OpenAI

            # Sin reintentos del SDK: los maneja este módulo (máximo MAX_REINTENTOS).
            self.cliente = OpenAI(api_key= os.getenv("OPENAI_API_KEY"), base_url= CONFIG["base_url"],
                                  timeout= TIMEOUT_SEG, max_retries= 0)
        return self.cliente

    def reformular(self, oraciones: List[str], idioma: str) -> ResultadoLLM:
        if not oraciones or CONFIG["modo"] == "mock":
            return ResultadoLLM(textos= None)

        pedido = json.dumps([seguridad.redactar(o).texto for o in oraciones], ensure_ascii= False)
        escaneo = escanear_pedido(pedido)
        llamada = {
            "llm_call_id": "llm_" + hashlib.sha256(f"{time.time_ns()}{pedido}".encode()).hexdigest()[:12],
            "purpose": "reply_wording", "provider": "openai", "model_id": CONFIG["modelo"],
            "prompt_template": PLANTILLA_PROMPT, "temperature": 0, "max_tokens": 400,
            "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "latency_ms": 0,
            "status": "error", "retries": 0, "cost_usd": 0.0, "request_pii_scan": escaneo,
        }
        if escaneo["blocked"]:
            llamada["status"] = "blocked_pii"
            return ResultadoLLM(textos= None, llamada= llamada, fallo= True)

        mensajes = [
            {"role": "system", "content": INSTRUCCIONES.format(
                idioma= "español" if idioma == "es" else "portugués de Brasil",
                registro= "de usted" if idioma == "es" else "de você")},
            {"role": "user", "content": pedido},
        ]
        llamada["prompt_sha256"] = hashlib.sha256(json.dumps(mensajes, ensure_ascii= False).encode("utf-8")).hexdigest()

        inicio = time.monotonic()
        for intento in range(MAX_REINTENTOS + 1):
            try:
                respuesta = self._cliente().chat.completions.create(
                    model= CONFIG["modelo"], messages= mensajes, temperature= 0, max_tokens= 400,
                )
            except Exception as error:
                transitorio = _es_transitorio(error)
                llamada["retries"] = intento
                llamada["status"] = "timeout" if "Timeout" in type(error).__name__ else "error"
                if transitorio and intento < MAX_REINTENTOS:
                    self.dormir(min(ESPERA_BASE_SEG * 2 ** intento, 8.0) + random.uniform(0, 0.5)) # Exponencial con jitter.
                    continue
                llamada["latency_ms"] = int((time.monotonic() - inicio) * 1000)
                logger.warning("LLM: %s tras %s reintentos; respuesta con plantillas.", type(error).__name__, intento)
                return ResultadoLLM(textos= None, llamada= llamada, fallo= True)

            uso = getattr(respuesta, "usage", None)
            cacheados = getattr(getattr(uso, "prompt_tokens_details", None), "cached_tokens", 0) or 0
            entrada = getattr(uso, "prompt_tokens", 0) or 0
            salida = getattr(uso, "completion_tokens", 0) or 0
            llamada.update({
                "model_id": getattr(respuesta, "model", None) or CONFIG["modelo"], # Versión exacta que devolvió la API.
                "input_tokens": entrada, "cached_input_tokens": cacheados, "output_tokens": salida,
                "latency_ms": int((time.monotonic() - inicio) * 1000), "status": "ok", "retries": intento,
                "cost_usd": round(costo_usd(entrada, cacheados, salida), 6),
            })
            logger.info("LLM %s prompt=%s tokens=%s/%s costo=%.6f USD", llamada["model_id"], llamada["prompt_sha256"][:12],
                        entrada, salida, llamada["cost_usd"])
            textos = _leer_textos(respuesta, len(oraciones))
            return ResultadoLLM(textos= textos, llamada= llamada, fallo= textos is None)

        return ResultadoLLM(textos= None, llamada= llamada, fallo= True) # pragma: no cover


def _es_transitorio(error: Exception) -> bool:
    estado = getattr(error, "status_code", None)
    nombre = type(error).__name__
    return estado == 429 or (isinstance(estado, int) and estado >= 500) or nombre in (
        "RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError", "TimeoutError")


def _leer_textos(respuesta: Any, esperadas: int) -> Optional[List[str]]:
    try:
        contenido = respuesta.choices[0].message.content.strip()
        contenido = re.sub(r"^```(?:json)?\s*|\s*```$", "", contenido)
        textos = json.loads(contenido)
    except (AttributeError, IndexError, TypeError, ValueError):
        return None
    if not isinstance(textos, list) or len(textos) != esperadas or not all(isinstance(t, str) and t.strip() for t in textos):
        return None
    return [t.strip() for t in textos]


def costo_usd(entrada: int, cacheados: int, salida: int) -> float:
    return ((entrada - cacheados) * PRECIO_ENTRADA_M + cacheados * PRECIO_ENTRADA_CACHE_M + salida * PRECIO_SALIDA_M) / 1e6


_CAMPOS_PII_02 = ("credit_score", "estimated_monthly_income", "gender", "marital_status", "education_level",
                  "occupation", "fraud_score", "is_fraud")


def escanear_pedido(pedido: str) -> Dict[str, Any]:
    """INV-09: el pedido no puede llevar valores de POL-PII-01 ni campos de POL-PII-02."""
    hallazgos = 0
    hallazgos += len(re.findall(r"(?<![0-9A-Za-z])\d{13,19}(?![0-9A-Za-z])", pedido))
    hallazgos += len(re.findall(r"\b(?:CLI|PRD|TRX)-[A-Z0-9]{12,20}\b", pedido))
    hallazgos += len(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", pedido))
    hallazgos += sum(pedido.count(campo) for campo in _CAMPOS_PII_02)
    return {"blocked": hallazgos > 0, "hits": hallazgos}


_NUMERO = re.compile(r"\d+")


def respaldada(original: str, reformulada: str) -> bool:
    """Grounding check (POL-GEN-02): cada número de la versión del LLM está en la oración original."""
    numeros_originales = set(_NUMERO.findall(original))
    return all(n in numeros_originales for n in _NUMERO.findall(reformulada))


cliente_llm = ClienteLLM()
