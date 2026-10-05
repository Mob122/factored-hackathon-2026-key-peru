from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import HTTPException
from fastapi.security import OAuth2PasswordBearer
from dotenv import load_dotenv
import jwt
import os
from pwdlib import PasswordHash

load_dotenv(dotenv_path= '.env') # Carga backend/.env si existe; no pisa variables ya definidas en el entorno.

excepcion_credenciales = HTTPException(
    status_code= 401,
    detail= "No se pudo validar las credenciales.",
    headers= {"WWW-Authenticate": "Bearer"}
)

ALGORITMOS_PERMITIDOS = {"HS256", "HS384", "HS512"} # Solo HMAC; nunca "none".

def _leer_secreto(nombre: str) -> str:
    """Lee un secreto obligatorio. Sin valor por defecto: si falta, el backend no arranca (POL-AUTH-10)."""
    valor = os.getenv(nombre)

    if not valor:
        raise RuntimeError(f"Falta la variable de entorno {nombre}. Defínala en backend/.env (vea backend/.env.example).")

    return valor

SECRET_KEY = _leer_secreto("SECRET_KEY") # Firma los JWT de sesión.
CARD_HASH_KEY = _leer_secreto("CARD_HASH_KEY") # Clave del HMAC de números de tarjeta, la misma que usa gold (docs/findings/gold_run.md).
AUDIT_KEY = _leer_secreto("AUDIT_KEY") # Clave de los seudónimos del audit log (docs/contracts/audit_log.md, AL-P3).
ALGORITHM = os.getenv("ALGORITHM", "HS256")

if ALGORITHM not in ALGORITMOS_PERMITIDOS:
    raise RuntimeError(f"ALGORITHM debe ser uno de {sorted(ALGORITMOS_PERMITIDOS)}.")

# Parámetros de sesión (docs/policy_cards.md, sección 11). Valores del prototipo, no de un banco.
SESION_INACTIVIDAD_MIN = 15 # SESSION_IDLE_MIN (POL-AUTH-03)
SESION_MAX_MIN = 60 # SESSION_MAX_MIN (POL-AUTH-03)
STEP_UP_TTL_MIN = 5 # STEPUP_TTL_MIN (POL-AUTH-04)
STEP_UP_MAX_FALLOS = 3 # STEPUP_MAX_FAILS (POL-AUTH-06)
OTP_PRUEBA_TTL_MIN = 5 # TEST_OTP_TTL_MIN (POL-AUTH-11)
BUSQUEDA_MAX_RESULTADOS = 20 # TEST_SEARCH_PAGE_MAX (POL-AUTH-11)
BUSQUEDA_MAX_POR_MINUTO = 10 # TEST_SEARCH_PER_MIN (POL-AUTH-11)


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
        expirar = datetime.now(timezone.utc) + timedelta(minutes= SESION_MAX_MIN)

    para_encodear.update({"exp": expirar}) # exp: Significa "expiration" y se utiliza para indicar la fecha y hora de expiración del token.

    jwt_encodeado = jwt.encode(para_encodear, SECRET_KEY, algorithm= ALGORITHM)

    return jwt_encodeado
