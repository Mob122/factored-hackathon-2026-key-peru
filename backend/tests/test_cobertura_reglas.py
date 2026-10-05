"""Las reglas T1 que hace cumplir esta capa del backend (IdP de prueba, banco simulado, gateway de
acciones dentro de block_card, almacén de casos y audit log) tienen al menos una prueba que las cita,
y siguen siendo T1 en docs/policy_cards.md. Las reglas T1 del orquestador, la capa de redacción y el
grounding check se prueban cuando esas piezas existan (docs/decisions_log.md, D-24)."""

import re

from conftest import RAIZ_BACKEND, RAIZ_REPO

REGLAS_T1_BACKEND = [
    "POL-GEN-01", "POL-GEN-07",
    "POL-AUTH-01", "POL-AUTH-02", "POL-AUTH-03", "POL-AUTH-04", "POL-AUTH-05", "POL-AUTH-06", "POL-AUTH-07",
    "POL-AUTH-09", "POL-AUTH-10", "POL-AUTH-11", "POL-AUTH-12",
    "POL-ANS-01", "POL-ANS-02", "POL-ANS-03", "POL-ANS-04", "POL-ANS-06", "POL-ANS-12", "POL-ANS-13",
    "POL-ANS-15", "POL-ANS-16", "POL-ANS-17", "POL-ANS-18",
    "POL-ACT-01", "POL-ACT-02", "POL-ACT-04", "POL-ACT-06", "POL-ACT-07", "POL-ACT-08", "POL-ACT-09",
    "POL-ESC-10", "POL-ESC-12",
    "POL-HND-10", "POL-HND-11", "POL-HND-12", "POL-HND-13", "POL-HND-14", "POL-HND-15",
    "POL-REL-02",
    "POL-PII-02", "POL-PII-03", "POL-PII-05", "POL-PII-07",
]


def _niveles_en_la_politica() -> dict:
    niveles = {}
    for linea in (RAIZ_REPO / "docs" / "policy_cards.md").read_text(encoding= "utf-8").splitlines():
        coincidencia = re.match(r"^\| (POL-[A-Z]+-\d{2}) \|", linea)
        if coincidencia:
            niveles[coincidencia.group(1)] = linea.rstrip().rstrip("|").rsplit("|", 1)[1].strip()
    return niveles


def test_cada_regla_t1_de_esta_capa_tiene_una_prueba():
    """Cada regla de REGLAS_T1_BACKEND aparece citada en alguna prueba de backend/tests."""
    citas = "\n".join(
        ruta.read_text(encoding= "utf-8") for ruta in (RAIZ_BACKEND / "tests").glob("test_*.py") if ruta.name != "test_cobertura_reglas.py"
    )

    assert [regla for regla in REGLAS_T1_BACKEND if regla not in citas] == []


def test_las_reglas_de_esta_capa_son_t1_en_la_politica():
    """La columna Tier de docs/policy_cards.md marca T1 cada regla que esta capa dice hacer cumplir."""
    niveles = _niveles_en_la_politica()

    assert {regla: niveles.get(regla) for regla in REGLAS_T1_BACKEND if niveles.get(regla) != "T1"} == {}
