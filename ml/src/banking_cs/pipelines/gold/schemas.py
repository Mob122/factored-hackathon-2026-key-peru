"""Gold table columns, keys and allowed values.

Transcribed from docs/contracts/gold_tables.md (gold-0.2). Column order matches the
contract. Every column not listed here is unavailable to the backend by construction.
"""

import polars as pl

CONTRACT_VERSION = "gold-0.2"

MONEY = pl.Decimal(15, 2)
TS = pl.Datetime("us")

LINEAGE: dict[str, pl.DataType] = {
    "source_file": pl.String,
    "gold_batch_id": pl.String,
    "gold_loaded_at": TS,
}

GOLD_SCHEMAS: dict[str, dict[str, pl.DataType]] = {
    "customers": {
        "customer_id": pl.String,
        "country": pl.String,
        "segment": pl.String,
        "customer_status": pl.String,
        **LINEAGE,
    },
    "cards": {
        "card_id": pl.String,
        "customer_id": pl.String,
        "last4": pl.String,
        "card_number_hmac": pl.String,
        "product_type": pl.String,
        "status": pl.String,
        "opening_date": pl.Date,
        "expiration_date": pl.Date,
        "last_updated": TS,
        **LINEAGE,
    },
    "card_transactions": {
        "transaction_id": pl.String,
        "card_id": pl.String,
        "customer_id": pl.String,
        "transaction_datetime": TS,
        "process_date": pl.Date,
        "transaction_type": pl.String,
        "amount": MONEY,
        "currency": pl.String,
        "merchant_name": pl.String,
        "status": pl.String,
        "response_code": pl.String,
        **LINEAGE,
    },
    "balance_products": {
        "product_id": pl.String,
        "customer_id": pl.String,
        "kind": pl.String,
        "last4": pl.String,
        "status": pl.String,
        "currency": pl.String,
        "current_balance": MONEY,
        "credit_limit": MONEY,
        **LINEAGE,
    },
}

TABLES = tuple(GOLD_SCHEMAS)

KEYS = {
    "customers": "customer_id",
    "cards": "card_id",
    "card_transactions": "transaction_id",
    "balance_products": "product_id",
}

# Columns that may be null; every other non-lineage column is required (GQ-02).
OPTIONAL = {
    "customers": set(),
    "cards": {"expiration_date"},
    "card_transactions": {"merchant_name", "response_code"},
    "balance_products": {"credit_limit"},
}

REQUIRED = {
    table: [c for c in schema if c not in LINEAGE and c not in OPTIONAL[table]]
    for table, schema in GOLD_SCHEMAS.items()
}

# Source product types, as observed (Spanish labels kept).
CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")
BALANCE_KINDS = {"Tarjeta Crédito": "credit_card", "Cuenta Ahorro": "savings_account"}

COUNTRIES = ("México", "Colombia", "Argentina")
SEGMENTS = ("Basic", "Plus", "Premium", "Student")
CUSTOMER_STATUSES = ("Active", "Inactive", "Suspended", "Closed")
PRODUCT_STATUSES = ("Active", "Blocked", "Suspended", "Closed")
TRANSACTION_TYPES = ("Purchase", "Withdrawal", "Payment")
TRANSACTION_STATUSES = ("Approved", "Declined", "Pending", "Reversed")
RESPONSE_CODES = ("00", "05", "14", "51", "54")
CURRENCIES = ("USD", "COP", "ARS")
