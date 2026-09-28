from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer
import jwt
import os
from pwdlib import PasswordHash

excepcion_credenciales = HTTPException(
    status_code= 401,
    detail= "No se pudo validar las credenciales.",
    headers= {"WWW-Authenticate": "Bearer"}
)

SECRET_KEY = os.getenv("SECRET_KEY", "8888888888888888888888888...")
ALGORITHM = os.getenv("ALGORITHM", "HSXXX")


password_hash = PasswordHash.recommended()
esquema_oauth2 = OAuth2PasswordBearer(tokenUrl= "/autenticacion/iniciar-sesion")

def get_password_encriptado(password: str) -> str:
    return password_hash.hash(password)

def verificar_password(plano_password: str, hasheado_password: str) -> bool:
    return password_hash.verify(plano_password, hasheado_password)

def crear_token_acceso(data: dict, expira_delta: Optional[timedelta] = None) -> str:
    para_encodear = data.copy()

    if expira_delta:
        expirar = datetime.now(timezone.utc) + expira_delta
    else:
        expirar = datetime.now(timezone.utc) + timedelta(minutes= 60)

    para_encodear.update({"exp": expirar}) # exp: Significa "expiration" y se utiliza para indicar la fecha y hora de expiración del token.

    jwt_encodeado = jwt.encode(para_encodear, SECRET_KEY, algorithm= ALGORITHM)    

    return jwt_encodeado
