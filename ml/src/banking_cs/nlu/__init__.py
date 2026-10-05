"""Intent and slot understanding (docs/intents.md). Plain Python, no Kedro import.

- banking_cs.nlu.rules: rule parser and slot extractor (standard library only).
- banking_cs.nlu.predict: `predict(text)` with the exported classifier and its conformal
  threshold (numpy, scikit-learn, joblib).
"""

from banking_cs.nlu.rules import INTENT_SLOTS, INTENTS, SLOTS, extract_slots, parse

__all__ = ["INTENTS", "INTENT_SLOTS", "SLOTS", "extract_slots", "parse"]
