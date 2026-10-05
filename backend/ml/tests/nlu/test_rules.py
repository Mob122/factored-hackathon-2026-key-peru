"""Rule parser against the labeling guide (docs/intents.md sections 4 and 5) and the
classifier inputs of the golden conversations (docs/golden_conversations.md)."""

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from banking_cs.nlu.rules import (
    BALANCE_ITEMS,
    INTENT_SLOTS,
    INTENTS,
    PRODUCT_KINDS,
    block_signal,
    dispute_signal,
    extract_slots,
    parse,
)

INTENTS_MD = Path(__file__).resolve().parents[3] / "docs" / "intents.md"
VARIANTS = ("es-MX", "es-CO", "es-AR", "pt-BR")


def _annotation_slots(note: str) -> dict[str, str]:
    slots = {}
    for value in re.findall(r"`(\w+)`", note):
        if value in BALANCE_ITEMS:
            slots["balance_item"] = value
        elif value in PRODUCT_KINDS:
            slots["product_kind"] = value
    return slots


def _guide_examples() -> list[tuple[str, str, str, dict]]:
    """(variant, text, intent, annotated slots) for every section 4 cell."""
    text = INTENTS_MD.read_text(encoding="utf-8")
    section = text.split("## 4. Examples", 1)[1].split("## 5. Hard negatives", 1)[0]
    examples = []
    for block in re.split(r"^### ", section, flags=re.M)[1:]:
        intent = re.match(r"`(\w+)`", block).group(1)
        rows = [line for line in block.splitlines() if line.startswith("| ")]
        for row in rows[1:]:  # header row, the separator starts with "|---"
            cells = [c.strip() for c in row.strip("|").split("|")]
            for variant, cell in zip(VARIANTS, cells):
                note = re.search(r"\((`.+?`)\)\s*$", cell)
                utterance = cell[: note.start()].strip() if note else cell
                slots = _annotation_slots(note.group(1)) if note else {}
                examples.append((variant, utterance, intent, slots))
    return examples


def _hard_negatives() -> list[tuple[str, str, str, dict]]:
    """(id, text, intent, annotated slots) for every section 5 row."""
    text = INTENTS_MD.read_text(encoding="utf-8")
    section = text.split("## 5. Hard negatives", 1)[1].split("## 6.", 1)[0]
    rows = []
    for line in section.splitlines():
        m = re.match(r"\| (HN-\d+) \| [\w-]+ \| (.+?) \| (.+?) \|", line)
        if m:
            label = m.group(3)
            intent = re.match(r"`(\w+)`", label).group(1)
            rows.append(
                (
                    m.group(1),
                    m.group(2),
                    intent,
                    _annotation_slots(label[len(intent) + 2 :]),
                )
            )
    return rows


GUIDE = _guide_examples()
HARD_NEGATIVES = _hard_negatives()

GOLDEN_YAML = (
    Path(__file__).resolve().parents[2] / "nlu_corpus" / "dev" / "golden_turns.yaml"
)


def _golden_turns():
    """Classifier inputs of the golden conversations; context-dependent turns are strict xfails."""
    turns = yaml.safe_load(GOLDEN_YAML.read_text(encoding="utf-8"))["turns"]
    params = []
    for t in turns:
        marks = (
            [pytest.mark.xfail(reason=t["context_dependent"], strict=True)]
            if t.get("context_dependent")
            else []
        )
        params.append(
            pytest.param(t["text"], t["intent"], t.get("slots") or {}, marks=marks)
        )
    return params


GOLDEN = _golden_turns()


def test_doc_tables_parsed():
    assert len(GUIDE) == 12 * 3 * 4
    assert {intent for _, _, intent, _ in GUIDE} == set(INTENTS)
    assert len(HARD_NEGATIVES) == 36


@pytest.mark.parametrize(("variant", "text", "intent", "slots"), GUIDE)
def test_guide_examples(variant, text, intent, slots):
    result = parse(text)
    assert result["intent"] == intent, (variant, text, result)
    assert slots.items() <= result["slots"].items(), (text, result)


@pytest.mark.parametrize(("hn_id", "text", "intent", "slots"), HARD_NEGATIVES)
def test_hard_negatives(hn_id, text, intent, slots):
    result = parse(text)
    assert result["intent"] == intent, (hn_id, text, result)
    assert slots.items() <= result["slots"].items(), (hn_id, result)


@pytest.mark.parametrize(("text", "intent", "slots"), GOLDEN)
def test_golden_turns(text, intent, slots):
    result = parse(text)
    assert result["intent"] == intent, (text, result)
    assert slots.items() <= result["slots"].items(), (text, result)


def test_output_contract():
    result = parse("¿Cuál es el saldo de mi tarjeta de crédito terminada en 4950?")
    assert set(result) == {"intent", "slots", "score"}
    assert result["slots"] == {
        "product_kind": "credit_card",
        "last4": "4950",
        "balance_item": "balance",
    }
    assert 0 < result["score"] <= 1


def test_slots_restricted_to_intent():
    for param in GOLDEN:
        result = parse(param.values[0])
        assert set(result["slots"]) <= set(INTENT_SLOTS[result["intent"]])


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Tengo un cargo de 245.300 pesos", "245300 PESO"),
        ("me cobraron 1,234.56 dólares", "1234.56 USD"),
        ("un consumo de 1.234,56 pesos colombianos", "1234.56 COP"),
        ("uma compra de R$ 150,90", "150.9 BRL"),
        ("me sacaron 20 lucas", "20000 PESO"),
        ("un cobro de mil pesos", "1000 PESO"),
        ("No reconozco un cargo de 392", "392"),
        ("un pago de US$ 75", "75 USD"),
        ("um débito de 89 reais", "89 BRL"),
        ("un cargo de 15 mil pesos", "15000 PESO"),
    ],
)
def test_amount_formats(text, expected):
    assert extract_slots(text)["amount"] == expected


@pytest.mark.parametrize(
    "text",
    [
        "¿Qué significa el código 51?",
        "movimientos de los últimos 15 días",
        "compras desde el 1 de junio",
        "la tarjeta terminada en 4950",
    ],
)
def test_no_spurious_amount(text):
    assert "amount" not in extract_slots(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("lo que compré ayer", "yesterday"),
        ("los cargos de la semana pasada", "last_week"),
        ("qué gasté en mayo", "month:05"),
        ("cargos desde el 1 de junio", "since:06-01"),
        ("as compras do mês passado", "last_month"),
        ("los últimos 15 días", "last_n_days:15"),
        ("los últimos quince días", "last_n_days:15"),
        ("hace unos días", "few_days_ago"),
        ("la compra del viernes", "weekday:fri"),
        ("la compra que hice el viernes", "weekday:fri"),
        ("compras de este mes", "this_month"),
        ("o que gastei ontem", "yesterday"),
        ("el 3 de mayo", "date:05-03"),
    ],
)
def test_dates(text, expected):
    assert extract_slots(text).get("date") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mi tarjeta terminación 6873", "6873"),
        ("o cartão final 8407", "8407"),
        ("la tarjeta <CARD_0044>", "0044"),
        ("la terminada en 2771", "2771"),
        ("la que termina en 0245", "0245"),
        ("mi tarjeta 4950", "4950"),
        ("cuyos últimos cuatro dígitos son 1234", None),
        ("los últimos 4 dígitos 1234", "1234"),
    ],
)
def test_last4(text, expected):
    assert extract_slots(text).get("last4") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("la compra rechazada", "declined"),
        ("a compra não passou", "declined"),
        ("um pagamento estornado", "reversed"),
        ("un cargo pendiente", "pending"),
        ("una compra aprobada", "approved"),
    ],
)
def test_tx_status(text, expected):
    assert extract_slots(text)["tx_status"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("el saldo de la caja de ahorro", "savings_account"),
        ("o saldo da conta poupança", "savings_account"),
        ("la tarjeta crédito", "credit_card"),
        ("el plástico", "card"),
        ("mi cuenta corriente", "current_account"),
        ("la de débito", "debit_card"),
        ("lo que debo del préstamo", "other_product"),
    ],
)
def test_product_kind(text, expected):
    assert extract_slots(text)["product_kind"] == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "¿Qué es este cargo en Restaurante El Buen Sabor?",
            "Restaurante El Buen Sabor",
        ),
        ("una compra en Estación de Servicio", "Estación de Servicio"),
        ("a compra no Uber foi recusada", "Uber"),
        ("Hay una compra en Empresa Telefónica que yo no hice.", "Empresa Telefónica"),
        ("un cargo de Cable TV", "Cable TV"),
        ("un consumo en el súper", None),
    ],
)
def test_merchant(text, expected):
    assert extract_slots(text).get("merchant") == expected


def test_package_imports_without_kedro():
    code = (
        "import sys; sys.modules['kedro'] = None; "
        "import banking_cs.nlu.rules, banking_cs.nlu; print('ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr


@pytest.mark.parametrize(
    "text",
    [
        "me robaron la tarjeta, congélenla",
        "travaram meu cartão",
        "Quero travar o cartão",
        "Perdí la tarjeta",
        "Sumiu meu cartão",
        "Quiero reportar mi tarjeta como robada.",
        "Quiero apagar mi tarjeta un rato.",
        "Bloquee todas mis tarjetas, por favor.",
    ],
)
def test_block_signal_fires(text):
    assert block_signal(text)


@pytest.mark.parametrize(
    "text",
    [
        "¿Por qué me bloquearon la tarjeta?",
        "Quiero desbloquear mi tarjeta.",
        "Quero destravar o cartão",
        "Me bloquearon el usuario de la app por intentos fallidos.",
        "¿Cuál es mi saldo?",
        "No reconozco un cargo",
        "Apaga la luz",
        "Hola",
        "Não quero falar com robô, me passa para alguém.",
    ],
)
def test_block_signal_quiet(text):
    assert not block_signal(text)


def test_block_signal_does_not_change_the_rules_baseline():
    # "travar" is only in the safety signal; the frozen baseline does not know it.
    assert parse("Quero travar o cartão")["intent"] != "card_block"
    assert block_signal("Quero travar o cartão")


@pytest.mark.parametrize(
    "text",
    [
        "quiero reportar un fraude en mi tarjeta",
        "não reconheço uma compra",
        "Hay un cobro que no hice",
        "Quero contestar uma cobrança",
        "Caí num golpe, tem fraude no cartão",
        "Me estafaron con la tarjeta",
    ],
)
def test_dispute_signal_fires(text):
    assert dispute_signal(text)


@pytest.mark.parametrize(
    "text",
    [
        "¿Cuál es mi saldo?",
        "Quiero bloquear mi tarjeta",
        "Me robaron la tarjeta",
        "¿Por qué me rechazaron la compra?",
        "Quiero desbloquear mi tarjeta",
    ],
)
def test_dispute_signal_quiet(text):
    assert not dispute_signal(text)
