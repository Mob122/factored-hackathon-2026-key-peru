"""Tablas del IdP de prueba (identidad simulada). Fechas en UTC con zona (SQLModel las devuelve en UTC)."""

from datetime import datetime
from sqlmodel import SQLModel, Field
from typing import Optional


class SesionIdentidad(SQLModel, table= True):
    """Registro de sesión del lado del servidor: es la fuente de verdad, el JWT solo lo nombra (POL-AUTH-12)."""
    __tablename__ = "sesiones_identidad"

    id: str = Field(primary_key= True, max_length= 64)
    usuario_id: Optional[int] = Field(default= None, foreign_key= "usuarios.id", index= True) # Nulo en sesiones abiertas por un jurado.
    rol: str = Field(max_length= 20)
    customer_id: Optional[str] = Field(default= None, max_length= 16, index= True) # Cliente al que queda ligada la sesión (POL-AUTH-05).
    customer_status: Optional[str] = Field(default= None, max_length= 20) # Leído de gold al iniciar sesión (POL-AUTH-09).
    idioma: Optional[str] = Field(default= None, max_length= 2) # "es" o "pt", preferencia del cliente (POL-GEN-03).
    metodo: str = Field(max_length= 20) # "contrasena" o "idp_prueba".
    emitida_por_usuario_id: Optional[int] = Field(default= None, foreign_key= "usuarios.id") # Jurado que abrió la sesión (POL-AUTH-11).
    conversacion_id: str = Field(max_length= 64)
    creada_en: datetime
    ultima_actividad_en: datetime
    expira_absoluta_en: datetime
    cerrada_en: Optional[datetime] = Field(default= None)
    motivo_cierre: Optional[str] = Field(default= None, max_length= 20) # "cierre", "inactividad" o "maximo".
    step_up_fallos: int = Field(default= 0)
    step_up_bloqueado: bool = Field(default= False) # POL-AUTH-06


class CodigoOTPPrueba(SQLModel, table= True):
    """Código de un solo uso emitido por el IdP de prueba. Solo se guarda su HMAC, nunca el código."""
    __tablename__ = "codigos_otp_prueba"

    id: Optional[int] = Field(default= None, primary_key= True)
    sesion_id: str = Field(foreign_key= "sesiones_identidad.id", index= True)
    codigo_hash: str = Field(max_length= 64)
    emitido_por_usuario_id: int = Field(foreign_key= "usuarios.id")
    creado_en: datetime
    expira_en: datetime
    usado_en: Optional[datetime] = Field(default= None)
    anulado_en: Optional[datetime] = Field(default= None) # Reemplazado por un código nuevo o por el bloqueo del step-up.


class StepUp(SQLModel, table= True):
    """Nivel L2: ligado a una tarjeta y una acción, de un solo uso (POL-AUTH-04)."""
    __tablename__ = "step_ups"

    id: str = Field(primary_key= True, max_length= 40)
    sesion_id: str = Field(foreign_key= "sesiones_identidad.id", index= True)
    card_id: str = Field(max_length= 16)
    accion: str = Field(max_length= 20)
    creado_en: datetime
    expira_en: datetime
    usado_en: Optional[datetime] = Field(default= None)
