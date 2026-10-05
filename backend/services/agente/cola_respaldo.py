"""Cola de respaldo local de expedientes (POL-REL-03, T-37).

Si open_handoff falla tras sus reintentos, el expediente se escribe aquí para reenviarlo después y
al cliente no se le da ninguna referencia (POL-HND-02). Es un archivo JSON Lines fuera de la base de
datos, para que una falla de la base no lo pierda. Ruta: FALLBACK_QUEUE_PATH (por defecto
backend/var/cola_casos.jsonl, ignorado por git). Guarda el expediente tal como se mandó: el texto ya
está redactado y los ids son del cliente de la sesión (POL-PII-05).
"""

from pathlib import Path
from typing import Any, Dict

import json
import os
import threading

from services import identidad

_candado = threading.Lock()


def ruta() -> Path:
    return Path(os.getenv("FALLBACK_QUEUE_PATH") or Path(__file__).resolve().parents[2] / "var" / "cola_casos.jsonl")


def _escribir(registro: Dict[str, Any]) -> None:
    destino = ruta()
    destino.parent.mkdir(parents= True, exist_ok= True)
    with _candado, destino.open("a", encoding= "utf-8") as archivo:
        archivo.write(json.dumps(registro, ensure_ascii= False, default= str) + "\n")


def encolar(conversacion_id: str, idempotency_key: str, expediente: Dict[str, Any]) -> None:
    _escribir({"type": "case_file", "conversation_id": conversacion_id, "idempotency_key": idempotency_key,
               "queued_at": identidad.ahora_utc().isoformat(), "case_file": expediente})


def anexar(conversacion_id: str, mensaje_redactado: str) -> None:
    """Mensaje posterior a una transferencia que quedó en la cola (T-38 sin case_id)."""
    _escribir({"type": "appended_message", "conversation_id": conversacion_id,
               "queued_at": identidad.ahora_utc().isoformat(), "text_redacted": mensaje_redactado})


def leer() -> list:
    destino = ruta()
    if not destino.is_file():
        return []
    return [json.loads(linea) for linea in destino.read_text(encoding= "utf-8").splitlines() if linea.strip()]
