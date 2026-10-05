"""Entorno de las pruebas del backend.

Las pruebas nunca leen backend/.env ni datos reales: el entorno se fija aquí antes de importar la
aplicación, la base es un SQLite temporal y gold es el fixture de tests/gold_prueba.py.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import os
import sys
import tempfile

import dotenv
import pytest

dotenv.load_dotenv = lambda *args, **kwargs: False # Antes de importar db/ y security/, que llaman a load_dotenv.

RAIZ_BACKEND = Path(__file__).resolve().parents[1]
RAIZ_REPO = RAIZ_BACKEND.parent
DIR_TMP = Path(tempfile.mkdtemp(prefix= "keyperu-pruebas-"))

os.environ.update({
    "ENV": "development",
    "DATABASE_URL": f"sqlite:///{(DIR_TMP / 'pruebas.db').as_posix()}",
    "SECRET_KEY": "clave-de-sesion-solo-para-pruebas-0123456789",
    "ALGORITHM": "HS256",
    "CARD_HASH_KEY": "clave-hmac-solo-para-pruebas",
    "AUDIT_KEY": "clave-auditoria-solo-para-pruebas",
    "SEED_PASSWORD": "contrasena-de-pruebas-larga",
    "GOLD_DIR": str(DIR_TMP / "gold"),
    "RELOJ_SIMULADO": "2026-06-18T10:00:00",
})
sys.path.insert(0, str(RAIZ_BACKEND))

from fastapi.testclient import TestClient # noqa: E402
from sqlmodel import Session, SQLModel # noqa: E402

import models # noqa: E402,F401
from db.config import motor # noqa: E402
from main import app # noqa: E402
from models.usuarios import Usuario # noqa: E402
from security import get_password_encriptado # noqa: E402
from services import banco, identidad # noqa: E402

import gold_prueba # noqa: E402

CLAVE = "contrasena-de-pruebas-larga"
DIR_GOLD = DIR_TMP / "gold"


@pytest.fixture(scope= "session", autouse= True)
def gold_de_prueba() -> Path:
    gold_prueba.escribir_gold(DIR_GOLD, gold_prueba.gold_base(), [gold_prueba.ENTREGAS_BASE], os.environ["CARD_HASH_KEY"])
    return DIR_GOLD


@pytest.fixture(autouse= True)
def base_limpia(gold_de_prueba):
    SQLModel.metadata.drop_all(motor)
    SQLModel.metadata.create_all(motor)
    banco.usar_gold(gold_de_prueba)
    identidad.limitador_busqueda.reiniciar()
    yield
    banco.usar_gold(gold_de_prueba)


@pytest.fixture
def http() -> TestClient:
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def bd() -> Session:
    with Session(motor) as sesion:
        yield sesion


class Reloj:
    """Reemplaza identidad.ahora_utc para simular el paso del tiempo en las sesiones."""

    def __init__(self):
        self.momento = datetime.now(timezone.utc)

    def __call__(self) -> datetime:
        return self.momento

    def avanzar(self, **delta) -> None:
        self.momento += timedelta(**delta)


@pytest.fixture
def reloj(monkeypatch) -> Reloj:
    reloj = Reloj()
    monkeypatch.setattr(identidad, "ahora_utc", reloj)
    return reloj


def crear_usuario(rol: str, correo: str, customer_id: Optional[str] = None) -> int:
    with Session(motor) as sesion:
        usuario = Usuario(nombre= f"Prueba {rol}", correo_electronico= correo, password= get_password_encriptado(CLAVE),
                          rol= rol, customer_id= customer_id, es_activo= True, creado_en= datetime.now(timezone.utc))
        sesion.add(usuario)
        sesion.commit()
        sesion.refresh(usuario)
        return usuario.id


def iniciar_sesion(http: TestClient, correo: str, password: str = CLAVE) -> str:
    respuesta = http.post("/autenticacion/iniciar-sesion", json= {"correo_electronico": correo, "password": password})
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def cabeceras(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def jurado(http) -> Dict[str, str]:
    crear_usuario("jurado", "jurado@pruebas.keyperu.example")
    return cabeceras(iniciar_sesion(http, "jurado@pruebas.keyperu.example"))


def abrir_sesion_cliente(http: TestClient, jurado: Dict[str, str], customer_id: str) -> Tuple[str, str]:
    """Sesión de cliente abierta por el jurado en el IdP de prueba: (token, sesion_id)."""
    respuesta = http.post("/identidad/sesion-prueba", json= {"customer_id": customer_id}, headers= jurado)
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["token"], respuesta.json()["sesion_id"]


def sesion_cliente(bd: Session, token: str) -> identidad.SesionCliente:
    return identidad.verificar_sesion_cliente(bd, token)


def subir_a_l2(http: TestClient, jurado: Dict[str, str], token: str, sesion_id: str, card_id: str) -> dict:
    otp = http.post("/identidad/otp-prueba", json= {"sesion_id": sesion_id}, headers= jurado)
    assert otp.status_code == 201, otp.text
    respuesta = http.post("/autenticacion/step-up", json= {"codigo": otp.json()["codigo"], "card_id": card_id}, headers= cabeceras(token))
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def preparar_bloqueo(http, jurado, bd, customer_id: str, card_id: str):
    """Sesión de cliente en L2 para la tarjeta, con un token de confirmación emitido."""
    token, sesion_id = abrir_sesion_cliente(http, jurado, customer_id)
    subir_a_l2(http, jurado, token, sesion_id, card_id)
    sc = sesion_cliente(bd, token)
    confirmacion = banco.emitir_token_confirmacion(bd, sc, card_id)
    return sc, confirmacion["confirmation_token"], token, sesion_id
