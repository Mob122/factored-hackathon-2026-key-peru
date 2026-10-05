from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel


class TarjetaCliente(BaseModel):
    # `ref` (t1, t2, … por orden de card_id) solo agrupa filas en la pantalla; ninguna tool la acepta (POL-PII-10).
    ref: str
    last4: str
    tipo: str # product_type de gold: "Tarjeta Crédito" o "Tarjeta Débito".
    estado: str # Active, Blocked, Suspended o Closed, con el overlay de block_card aplicado.

class TransaccionCliente(BaseModel):
    fecha: datetime # Reloj del banco, sin zona como en gold.
    tipo: str # Purchase, Withdrawal o Payment.
    monto: Decimal
    moneda: str
    comercio: Optional[str] = None
    estado: str # Approved, Declined, Pending o Reversed. Sin código de respuesta: su significado lo explica el asistente (POL-ANS-04, 10).

class TransaccionesTarjeta(TarjetaCliente):
    truncada: bool # Había más de TX_MAX_ROWS filas: solo van las más recientes (POL-ANS-03).
    transacciones: List[TransaccionCliente]

class TransaccionesCliente(BaseModel):
    desde: date
    hasta: date
    tarjetas: List[TransaccionesTarjeta]

class CasoCliente(BaseModel):
    # Solo la referencia y su contexto: el expediente es del agente (POL-PII-05, POL-PII-07).
    case_id: str
    creado_en: datetime
    prioridad: str
    motivo: Optional[str] = None # Intención del pedido (docs/intents.md); nula si el caso no salió de un pedido.
    tarjetas_last4: List[str]
    mensajes_agregados: int
    conversation_id: str

class ConversacionCliente(BaseModel):
    conversation_id: str
    estado: str
    turnos: int
    idioma: Optional[str] = None
    case_id: Optional[str] = None
    creada_en: datetime
    actualizada_en: datetime
