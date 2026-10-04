"""Intent and slot understanding (docs/intents.md). Plain Python, no Kedro import."""

from banking_cs.nlu.rules import INTENT_SLOTS, INTENTS, SLOTS, extract_slots, parse

__all__ = ["INTENTS", "INTENT_SLOTS", "SLOTS", "extract_slots", "parse"]
