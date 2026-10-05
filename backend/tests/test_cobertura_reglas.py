"""Cada regla T1 de docs/policy_cards.md tiene al menos una prueba que la verifica.

Una regla cuenta como probada solo si su id aparece en el docstring de una función de prueba (test_*)
de backend/tests o ml/tests: ahí cada prueba declara las reglas que comprueba. Un id en un comentario
o en el código no cuenta. La lista de reglas T1 se lee de la columna Tier de la política, así que una
regla T1 nueva sin prueba hace fallar esta prueba (docs/decisions_log.md, D-24 y D-33).
"""

import ast
import re

from conftest import RAIZ_BACKEND, RAIZ_REPO

_REGLA = re.compile(r"POL-[A-Z]+-\d{2}")


def niveles_en_la_politica() -> dict:
    niveles = {}
    for linea in (RAIZ_REPO / "docs" / "policy_cards.md").read_text(encoding= "utf-8").splitlines():
        coincidencia = re.match(r"^\| (POL-[A-Z]+-\d{2}) \|", linea)
        if coincidencia:
            niveles[coincidencia.group(1)] = linea.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
    return niveles


def reglas_probadas() -> dict:
    """Regla -> pruebas cuyo docstring la cita."""
    citas: dict = {}
    archivos = list((RAIZ_BACKEND / "tests").glob("test_*.py")) + list((RAIZ_REPO / "ml" / "tests").rglob("test_*.py"))
    for ruta in archivos:
        arbol = ast.parse(ruta.read_text(encoding= "utf-8"))
        for nodo in ast.walk(arbol):
            if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)) and nodo.name.startswith("test_"):
                for regla in set(_REGLA.findall(ast.get_docstring(nodo) or "")):
                    citas.setdefault(regla, []).append(f"{ruta.name}::{nodo.name}")
    return citas


def test_cada_regla_t1_de_la_politica_tiene_una_prueba():
    """Todas las reglas T1 de la política (hoy 80 de 112) están citadas en el docstring de al menos una prueba."""
    niveles = niveles_en_la_politica()
    t1 = sorted(r for r, nivel in niveles.items() if nivel == "T1")
    citas = reglas_probadas()

    assert len(t1) >= 80
    assert [regla for regla in t1 if regla not in citas] == []


def test_las_pruebas_solo_citan_reglas_que_existen():
    """Ningún docstring de prueba cita un id de regla que no está en la política."""
    niveles = niveles_en_la_politica()

    assert sorted(set(reglas_probadas()) - set(niveles)) == []
