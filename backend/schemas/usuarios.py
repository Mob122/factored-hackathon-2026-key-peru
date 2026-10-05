from enum import Enum
from typing import Optional
from pydantic import BaseModel, EmailStr, Field

class TipoRol(str, Enum):
    cliente = "cliente" # Sesión de cliente ligada a un customer_id (POL-AUTH-05).
    agente = "agente" # Asesor humano; reservado para la bandeja de casos.
    jurado = "jurado" # Evaluador: usa el IdP de prueba (POL-AUTH-11).

class TipoIdioma(str, Enum):
    es = "es"
    pt = "pt"

class UsuarioBase(BaseModel):
    nombre: str = Field(max_length= 1000)
    correo_electronico: EmailStr
    es_activo: bool = Field(default= True)

class CrearUsuario(UsuarioBase):
    # Sin rol ni customer_id: el registro abierto solo crea clientes sin datos (POL-AUTH-10).
    password: str = Field(min_length= 8, max_length= 128)

class LecturaUsuario(UsuarioBase):
    id: int
    rol: TipoRol
    customer_id: Optional[str] = None

class IniciarSesionUsuario(BaseModel):
    correo_electronico: EmailStr
    password: str = Field(min_length= 8, max_length= 128)
    idioma: Optional[TipoIdioma] = None # Preferencia elegida al iniciar sesión (POL-GEN-03).

class Token(BaseModel):
    token: str
    tipo_token: str

class LecturaToken(Token):
    pass
