from enum import Enum
from pydantic import BaseModel, EmailStr, Field

class TipoRol(str, Enum):
    usuario = "usuario"
    admin = "admin"

class UsuarioBase(BaseModel):
    nombre: str = Field(max_length= 1000)
    correo_electronico: EmailStr
    rol: TipoRol = Field(default= TipoRol.usuario, max_length= 50)
    es_activo: bool = Field(default= True)

class CrearUsuario(UsuarioBase):
    password: str = Field(min_length= 8, max_length= 128)

class LecturaUsuario(UsuarioBase):
    id: int

class IniciarSesionUsuario(BaseModel):
    correo_electronico: EmailStr
    password: str = Field(min_length= 8, max_length= 128)

class Token(BaseModel):
    token: str
    tipo_token: str

class LecturaToken(Token):
    pass