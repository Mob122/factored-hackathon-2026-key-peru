"""The exported artifact (ml/artifacts/nlu) through the runtime loader."""

import json
import shutil
import subprocess
import sys

import pytest

from banking_cs.nlu import predict as predict_module
from banking_cs.nlu.predict import ArtifactError, IntentModel, apply_overrides
from banking_cs.nlu.rules import INTENTS

pytestmark = pytest.mark.skipif(
    not (predict_module.DEFAULT_DIR / "model.joblib").exists(),
    reason="artifact not exported (run python -m banking_cs.nlu.train_eval)",
)


@pytest.fixture(scope="module")
def model():
    return IntentModel()


def test_output_contract(model):
    out = model.predict("¿Cuánto debo en la tarjeta terminada en 4950?")
    assert set(out) == {"intent_set", "slots", "scores", "safety_override", "signals"}
    assert list(out["scores"]) == sorted(
        out["scores"], key=out["scores"].get, reverse=True
    )
    assert set(out["scores"]) == set(INTENTS)
    assert abs(sum(out["scores"].values()) - 1) < 1e-3
    assert out["intent_set"] == ["balance_inquiry"]
    assert out["safety_override"] == []
    assert out["signals"] == {
        "block_or_theft": False,
        "theft": False,
        "dispute_or_fraud": False,
    }
    assert out["slots"] == {
        "product_kind": "card",
        "last4": "4950",
        "balance_item": "balance",
    }


def test_default_conformal_score_is_lac(model):
    assert model.default_method == "lac"
    assert model.conformal["method"] == "split_conformal_lac"
    assert "aps" in model.conformal["alternatives"]


def test_sets_are_deterministic_and_aps_never_empty(model):
    for text in ("Hola", "asdfgh", "Quiero bloquear mi tarjeta de débito."):
        first = model.predict(text)
        assert model.predict(text) == first
        assert model.predict(text, method="aps")["intent_set"]


@pytest.mark.parametrize(
    "text", ["me robaron la tarjeta, congélenla", "travaram meu cartão"]
)
def test_block_override_adds_card_block(model, text):
    out = model.predict(text)
    assert "card_block" in out["intent_set"]
    if "card_block" in out["safety_override"]:
        # Added by the override, so the model's own set did not hold card_block.
        assert "card_block" not in model.predict(text, override=False)["intent_set"]


@pytest.mark.parametrize(
    "text", ["quiero reportar un fraude en mi tarjeta", "não reconheço uma compra"]
)
def test_dispute_override_adds_charge_dispute(model, text):
    out = model.predict(text)
    assert "charge_dispute" in out["intent_set"]
    assert out["intent_set"] != ["card_block"]
    assert out["signals"]["dispute_or_fraud"]
    if "charge_dispute" in out["safety_override"]:
        assert "charge_dispute" not in model.predict(text, override=False)["intent_set"]


def test_theft_signal_is_reported(model):
    assert model.predict("Me robaron la tarjeta")["signals"]["theft"]
    assert not model.predict("Perdí la tarjeta")["signals"]["theft"]


def test_override_rules():
    # A singleton of another intent becomes a clarification.
    assert apply_overrides(["card_status"], "card_status", "travaram meu cartão") == (
        ["card_status", "card_block"],
        ["card_block"],
    )
    # A lone card_block with fraud wording becomes a clarification (C6).
    assert apply_overrides(
        ["card_block"], "card_block", "Quiero reportar un fraude en mi tarjeta"
    ) == (["card_block", "charge_dispute"], ["charge_dispute"])
    # An empty set becomes {top, added}, or {added} when it is the top intent.
    assert apply_overrides([], "out_of_scope", "Perdí la tarjeta") == (
        ["out_of_scope", "card_block"],
        ["card_block"],
    )
    assert apply_overrides([], "card_block", "Perdí la tarjeta") == (
        ["card_block"],
        ["card_block"],
    )
    # A request for a person is transferred right away (POL-ESC-09): no override.
    assert apply_overrides(
        ["human_request"],
        "human_request",
        "Me robaron la tarjeta y no reconozco un cargo, páseme con un asesor",
    ) == (["human_request"], [])
    # No signal, or the intent already in the set: unchanged.
    assert apply_overrides(["balance_inquiry"], "balance_inquiry", "¿Mi saldo?") == (
        ["balance_inquiry"],
        [],
    )
    assert apply_overrides(
        ["charge_dispute"], "charge_dispute", "No reconozco un cargo"
    ) == (["charge_dispute"], [])
    # Only the requested kinds run (used by the evaluation).
    assert apply_overrides(
        ["card_block"], "card_block", "Quiero reportar un fraude", ("card_block",)
    ) == (["card_block"], [])


@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("Quiero bloquear mi tarjeta de débito.", "card_block"),
        ("Por que meu cartão foi bloqueado?", "block_reason"),
        ("Oi, qual é o saldo da minha conta poupança?", "balance_inquiry"),
        ("Gracias, eso es todo.", "conversation_end"),
    ],
)
def test_golden_top_intents(model, text, intent):
    assert next(iter(model.predict(text)["scores"])) == intent


def test_rejects_tampered_model(model, tmp_path):
    for name in ("model.joblib", "conformal.json", "metadata.json"):
        shutil.copy(predict_module.DEFAULT_DIR / name, tmp_path / name)
    meta = json.loads((tmp_path / "metadata.json").read_text())
    meta["model_sha256"] = "0" * 64
    (tmp_path / "metadata.json").write_text(json.dumps(meta))
    with pytest.raises(ArtifactError):
        IntentModel(tmp_path)


def test_loader_imports_without_kedro():
    code = (
        "import sys; sys.modules['kedro'] = None; "
        "from banking_cs.nlu.predict import predict; "
        "print(predict('Hola')['scores'] and 'ok')"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "ok"
