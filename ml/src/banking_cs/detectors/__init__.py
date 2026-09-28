"""Reusable SQL detectors. Each builder returns a DuckDB SQL string."""

from .card_charges import (
    CARD_PRODUCT_TYPES,
    LOCAL_CURRENCY,
    build_card_purchases_query,
    build_foreign_currency_query,
    build_habitual_merchant_query,
    build_preauthorization_query,
    build_repeat_charge_query,
    build_shuffled_column_query,
)

__all__ = [
    "CARD_PRODUCT_TYPES",
    "LOCAL_CURRENCY",
    "build_card_purchases_query",
    "build_foreign_currency_query",
    "build_habitual_merchant_query",
    "build_preauthorization_query",
    "build_repeat_charge_query",
    "build_shuffled_column_query",
]
