"""Crea o actualiza los usuarios de prueba del IdP simulado (POL-AUTH-10).

- Un usuario "cliente" por cada cliente persona de docs/golden_conversations.md (golden-0.5).
- Un usuario "agente" y un usuario "jurado".
- Todos con la contraseña de SEED_PASSWORD (backend/.env). La contraseña nunca se imprime.

Uso, desde backend/:  python -m scripts.sembrar_usuarios

Es idempotente: si el usuario existe, se le vuelven a fijar el rol, el cliente y la contraseña.
"""

from datetime import datetime, timezone
from typing import Dict, List, Tuple

from sqlmodel import Session, select

from db import crear_db_y_tablas
from db.config import motor
from models.usuarios import Usuario
from security import get_password_encriptado

import os
import sys

DOMINIO = "keyperu.example"
LONGITUD_MINIMA = 12

# Clientes de sesión de las 12 conversaciones golden (docs/golden_conversations.md, tabla Overview),
# con los diálogos en que aparecen. CLI-JAS4V4U7H60H también es el dueño de la tarjeta del diálogo 7.
PERSONAS_GOLDEN: List[Tuple[str, Tuple[int, ...]]] = [
    ("CLI-5B9VSCP2GSML", (1,)),
    ("CLI-JPK27B33SV65", (2,)),
    ("CLI-PETSG0SJC2G2", (3,)),
    ("CLI-FW98UJSYFLWX", (4,)),
    ("CLI-AYAHYQEG16BZ", (5,)),
    ("CLI-AN7KXGR09TB2", (6, 12)),
    ("CLI-GHRMPXT32BKK", (7,)),
    ("CLI-EHVV6YJ6SL5W", (8,)),
    ("CLI-LD6QVNCSTR43", (9,)),
    ("CLI-JAS4V4U7H60H", (10,)),
    ("CLI-SQJOCEDJJNCZ", (11,)),
]


def correo_cliente(customer_id: str) -> str:
    return f"{customer_id.lower()}@clientes.{DOMINIO}"


def usuarios_de_prueba() -> List[Dict[str, object]]:
    usuarios: List[Dict[str, object]] = []
    for customer_id, dialogos in PERSONAS_GOLDEN:
        lista = " y ".join(str(d) for d in dialogos)
        usuarios.append({
            "correo_electronico": correo_cliente(customer_id),
            "nombre": f"Cliente de prueba, diálogo {lista} ({customer_id})",
            "rol": "cliente",
            "customer_id": customer_id,
        })
    usuarios.append({"correo_electronico": f"agente@{DOMINIO}", "nombre": "Agente de prueba", "rol": "agente", "customer_id": None})
    usuarios.append({"correo_electronico": f"jurado@{DOMINIO}", "nombre": "Jurado de prueba", "rol": "jurado", "customer_id": None})
    return usuarios


def sembrar(sesion: Session, password: str) -> Dict[str, int]:
    if len(password) < LONGITUD_MINIMA:
        raise ValueError(f"SEED_PASSWORD debe tener al menos {LONGITUD_MINIMA} caracteres.")

    ahora = datetime.now(timezone.utc)
    hash_password = get_password_encriptado(password)
    resumen = {"creados": 0, "actualizados": 0}

    for datos in usuarios_de_prueba():
        usuario = sesion.exec(select(Usuario).where(Usuario.correo_electronico == datos["correo_electronico"])).first()

        if usuario is None:
            usuario = Usuario(correo_electronico= datos["correo_electronico"], password= hash_password, creado_en= ahora, nombre= "")
            resumen["creados"] += 1
        else:
            resumen["actualizados"] += 1

        usuario.nombre = datos["nombre"]
        usuario.rol = datos["rol"]
        usuario.customer_id = datos["customer_id"]
        usuario.password = hash_password
        usuario.es_activo = True
        usuario.actualizado_en = ahora
        sesion.add(usuario)

    sesion.commit()
    return resumen


def clientes_ausentes_en_gold() -> List[str]:
    """Clientes persona que no están en gold. Si gold no está disponible, lo dice y no falla."""
    from services import banco

    try:
        return [customer_id for customer_id, _ in PERSONAS_GOLDEN if banco.estado_cliente(customer_id) is None]
    except banco.ErrorHerramienta as error:
        print(f"Aviso: no se pudo revisar gold ({error.detalle or error.mensaje}).")
        return []


def main() -> int:
    password = os.getenv("SEED_PASSWORD")

    if not password:
        print("Falta SEED_PASSWORD en backend/.env.")
        return 1

    crear_db_y_tablas()

    with Session(motor) as sesion:
        try:
            resumen = sembrar(sesion, password)
        except ValueError as error:
            print(error)
            return 1

    ausentes = clientes_ausentes_en_gold()
    print(f"Usuarios de prueba: {resumen['creados']} creados, {resumen['actualizados']} actualizados.")
    for datos in usuarios_de_prueba():
        print(f"  {datos['rol']:8} {datos['correo_electronico']}")
    if ausentes:
        print(f"Aviso: estos clientes no están en gold y no podrán iniciar sesión: {ausentes}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
