from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

from schemas.usuarios import TipoIdioma

PATRON_CUSTOMER_ID = r"^CLI-[A-Z0-9]{12}$"
PATRON_CARD_ID = r"^PRD-[A-Z0-9]{12}$"


class ClienteEncontrado(BaseModel):
    # Campos mínimos (POL-AUTH-11). Gold no tiene nombres, así que no hay nombre enmascarado.
    customer_id: str
    country: str
    segment: str

class PaginaClientes(BaseModel):
    pagina: int
    tamano: int
    hay_mas: bool
    resultados: List[ClienteEncontrado]
    aviso: str

class CrearSesionPrueba(BaseModel):
    customer_id: str = Field(pattern= PATRON_CUSTOMER_ID)
    idioma: Optional[TipoIdioma] = None

class RespuestaSesionPrueba(BaseModel):
    token: str
    tipo_token: str = "bearer"
    sesion_id: str
    customer_id: str
    customer_status: str
    nivel: str
    idioma: Optional[str]
    expira_inactividad_en: datetime
    expira_absoluta_en: datetime
    aviso: str

class CrearOTPPrueba(BaseModel):
    sesion_id: str = Field(min_length= 1, max_length= 64)

class RespuestaOTPPrueba(BaseModel):
    sesion_id: str
    codigo: str
    expira_en: datetime
    aviso: str

class RespuestaOTPDemo(BaseModel):
    # SMS simulado (POL-AUTH-14): el código de la propia sesión, solo con ENV=development.
    codigo: str
    expira_en: datetime
    canal: str = "sms_simulado"
    aviso: str

class SolicitudStepUp(BaseModel):
    codigo: str = Field(pattern= r"^\d{6}$")
    card_id: str = Field(pattern= PATRON_CARD_ID)
    accion: Literal["block_card"] = "block_card"

class RespuestaStepUp(BaseModel):
    nivel: str
    step_up_id: str
    card_id_vinculada: str
    accion: str
    expira_en: datetime
    uso_unico: bool = True

class LecturaSesion(BaseModel):
    # Sin customer_status: el cliente no ve su estado (INV-14); el orquestador lo recibe en SesionCliente.
    sesion_id: str
    rol: str
    nivel: str
    metodo: str
    customer_id: Optional[str]
    idioma: Optional[str]
    expira_inactividad_en: datetime
    expira_absoluta_en: datetime
