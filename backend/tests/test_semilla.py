"""Script de semilla de usuarios de prueba (POL-AUTH-10)."""

import re

import pytest
from sqlmodel import select

from conftest import CLAVE, RAIZ_REPO
from models.usuarios import Usuario
from scripts import sembrar_usuarios
from security import verificar_password


def test_personas_coinciden_con_las_conversaciones_golden():
    """POL-AUTH-10: hay un usuario cliente por cada cliente de sesión de docs/golden_conversations.md."""
    texto = (RAIZ_REPO / "docs" / "golden_conversations.md").read_text(encoding= "utf-8")
    resumen = texto.split("## Overview", 1)[1].split("\n## ", 1)[0]
    en_golden = {re.search(r"CLI-[A-Z0-9]{12}", linea).group(0) for linea in resumen.splitlines() if re.match(r"^\| \d+ \|", linea)}

    assert {customer_id for customer_id, _ in sembrar_usuarios.PERSONAS_GOLDEN} == en_golden
    assert len(en_golden) == 11


def test_semilla_crea_clientes_agente_y_jurado(bd):
    """POL-AUTH-10: 11 clientes persona ligados a su customer_id, un agente y un jurado, todos con
    SEED_PASSWORD. Volver a correrla actualiza sin duplicar."""
    assert sembrar_usuarios.sembrar(bd, CLAVE) == {"creados": 13, "actualizados": 0}
    assert sembrar_usuarios.sembrar(bd, CLAVE) == {"creados": 0, "actualizados": 13}

    usuarios = bd.exec(select(Usuario)).all()
    roles = sorted(u.rol for u in usuarios)
    assert roles == sorted(["agente", "jurado"] + ["cliente"] * 11)
    assert all(u.customer_id for u in usuarios if u.rol == "cliente")
    assert all(u.customer_id is None for u in usuarios if u.rol != "cliente")
    assert all(verificar_password(CLAVE, u.password) for u in usuarios)


def test_semilla_rechaza_una_contrasena_corta(bd):
    """POL-AUTH-10: SEED_PASSWORD debe tener al menos 12 caracteres."""
    with pytest.raises(ValueError):
        sembrar_usuarios.sembrar(bd, "corta")
