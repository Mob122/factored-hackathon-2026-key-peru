"""The exported artifact (ml/artifacts/nlu) through the runtime loader."""

import json
import shutil
import subprocess
import sys

import pytest

from banking_cs.nlu import predict as predict_module
from banking_cs.nlu.predict import ArtifactError, IntentModel
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
    assert set(out) == {"intent_set", "slots", "scores"}
    assert list(out["scores"]) == sorted(
        out["scores"], key=out["scores"].get, reverse=True
    )
    assert set(out["scores"]) == set(INTENTS)
    assert abs(sum(out["scores"].values()) - 1) < 1e-3
    assert out["intent_set"][0] == "balance_inquiry"
    assert out["slots"] == {
        "product_kind": "card",
        "last4": "4950",
        "balance_item": "balance",
    }


def test_aps_sets_are_never_empty_and_deterministic(model):
    for text in ("Hola", "asdfgh", "Quiero bloquear mi tarjeta de débito."):
        first = model.predict(text)
        assert first["intent_set"]
        assert model.predict(text) == first


def test_lac_alternative_gives_smaller_sets(model):
    text = "¿Cuánto debo en la tarjeta terminada en 4950?"
    assert len(model.predict(text, method="lac")["intent_set"]) <= len(
        model.predict(text)["intent_set"]
    )


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
        "print(predict('Hola')['intent_set'][0])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "out_of_scope"
