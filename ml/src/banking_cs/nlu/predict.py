"""Runtime loader for the intent classifier and its conformal sets. No Kedro import.

    from banking_cs.nlu.predict import predict
    predict("¿Cuánto debo en la tarjeta terminada en 4950?")
    # {"intent_set": ["balance_inquiry"],
    #  "slots": {"product_kind": "card", "last4": "4950", "balance_item": "balance"},
    #  "scores": {"balance_inquiry": 0.93, ...},
    #  "safety_override": False}

- `intent_set`: the conformal prediction set (docs/policy_cards.md POL-ESC-06): one intent
  -> act; 2 to `max_set` -> clarify; empty or larger -> transfer. Most probable first. The
  default score is LAC (docs/eval_plan.md 8.4, amendment eval-plan-0.3).
- Safety override: when `rules.block_signal` fires and the set lacks card_block, card_block
  is appended, so a singleton of another intent becomes a clarifying question. An empty set
  becomes {top intent, card_block}, or {card_block} when card_block is the top intent (the
  block flow still asks for confirmation, POL-ACT-02). `safety_override` says whether it
  fired, for the audit log.
- `slots`: from the rule extractor (banking_cs.nlu.rules): the slots found in the text that
  the top intent or any intent in the set takes; `balance_item` only when the top intent is
  balance_inquiry.
- `scores`: class probabilities of the deployed model, highest first.

The artifact directory defaults to ml/artifacts/nlu (override with NLU_ARTIFACT_DIR). The
model file's SHA-256 is checked against metadata.json before it is unpickled, and the
scikit-learn version must match the one it was trained with. Input text must already be
redacted (POL-PII-01): this module does not redact card numbers.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import joblib
import numpy as np
import sklearn

from banking_cs.nlu import conformal
from banking_cs.nlu.rules import INTENT_SLOTS, block_signal, extract_slots

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "artifacts" / "nlu"
METHOD_ALIASES = {
    "split_conformal_aps_nonrandomized": "aps",
    "split_conformal_lac": "lac",
    "aps": "aps",
    "lac": "lac",
}
BLOCK = "card_block"


def apply_block_override(
    intent_set: list[str], top: str, text: str
) -> tuple[list[str], bool]:
    """Add card_block to the set when the rules see a block or theft request."""
    if BLOCK in intent_set or not block_signal(text):
        return intent_set, False
    if not intent_set:
        return ([BLOCK] if top == BLOCK else [top, BLOCK]), True
    return [*intent_set, BLOCK], True


class ArtifactError(RuntimeError):
    """The artifact is missing, altered, or incompatible with this environment."""


class IntentModel:
    def __init__(self, artifact_dir: str | Path | None = None):
        root = Path(artifact_dir or os.environ.get("NLU_ARTIFACT_DIR") or DEFAULT_DIR)
        try:
            self.metadata = json.loads(
                (root / "metadata.json").read_text(encoding="utf-8")
            )
            self.conformal = json.loads(
                (root / "conformal.json").read_text(encoding="utf-8")
            )
            model_bytes = (root / "model.joblib").read_bytes()
        except FileNotFoundError as exc:
            raise ArtifactError(
                f"missing NLU artifact in {root}: {exc.filename}"
            ) from exc
        if hashlib.sha256(model_bytes).hexdigest() != self.metadata["model_sha256"]:
            raise ArtifactError(
                "model.joblib does not match the SHA-256 in metadata.json"
            )
        if sklearn.__version__ != self.metadata["sklearn_version"]:
            raise ArtifactError(
                f"scikit-learn {sklearn.__version__} installed, model trained with "
                f"{self.metadata['sklearn_version']}"
            )
        self.model = joblib.load(root / "model.joblib")
        self.classes = list(self.conformal["classes"])
        self.max_set = int(self.conformal["max_set"])
        self.default_method = METHOD_ALIASES[self.conformal["method"]]

    def threshold(self, method: str, language: str | None = None) -> float:
        if method == self.default_method:
            mondrian = self.conformal.get("mondrian_by_language")
            if mondrian and language in mondrian:
                return float(mondrian[language])
            return float(self.conformal["threshold"])
        return float(self.conformal["alternatives"][method]["threshold"])

    def predict(
        self,
        text: str,
        method: str | None = None,
        language: str | None = None,
        override: bool = True,
    ) -> dict:
        """Conformal intent set, slots and scores for one (already redacted) message."""
        method = METHOD_ALIASES[method] if method else self.default_method
        probs = np.asarray(self.model.predict_proba([text])[0], dtype=float)
        idx = conformal.SETS[method](probs[None, :], self.threshold(method, language))[
            0
        ]
        intent_set = [self.classes[i] for i in idx]
        top = self.classes[int(np.argmax(probs))]
        fired = False
        if override:
            intent_set, fired = apply_block_override(intent_set, top, text)
        # Slots found in the text that any candidate intent takes. balance_item defaults
        # to "balance", so it is only filled when balance_inquiry is the top intent.
        allowed = {s for i in {top, *intent_set} for s in INTENT_SLOTS[i]}
        slots = {k: v for k, v in extract_slots(text).items() if k in allowed}
        if top == "balance_inquiry":
            slots["balance_item"] = extract_slots(text, top)["balance_item"]
        order = np.argsort(-probs, kind="stable")
        scores = {self.classes[i]: round(float(probs[i]), 4) for i in order}
        return {
            "intent_set": intent_set,
            "slots": slots,
            "scores": scores,
            "safety_override": fired,
        }


_model: IntentModel | None = None


def load(artifact_dir: str | Path | None = None) -> IntentModel:
    """Load (and cache) the default model."""
    global _model  # noqa: PLW0603
    if _model is None or artifact_dir is not None:
        _model = IntentModel(artifact_dir)
    return _model


def predict(text: str, method: str | None = None, language: str | None = None) -> dict:
    return load().predict(text, method=method, language=language)
