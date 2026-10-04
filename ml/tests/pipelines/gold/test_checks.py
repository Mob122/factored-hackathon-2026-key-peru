"""Tests for the gold quality checks (docs/contracts/gold_tables.md section 5).

A small valid gold state passes every check. Each fail-level check is then broken on
one row: the check must fire, the row must land in quarantine and the load must be
rejected. Warn-level checks are counted and the load is still published.
"""

from datetime import date, datetime
from decimal import Decimal

import polars as pl
import pytest

from banking_cs.pipelines.gold.checks import run_checks
from banking_cs.pipelines.gold.nodes import publish_gold
from banking_cs.pipelines.gold.schemas import GOLD_SCHEMAS, KEYS, TABLES

BATCH_ID = "gold-20260619T063000-00000002"
LOADED_AT = datetime(2026, 6, 19, 6, 30)
TXN_FILE = "transactions/year=2026/month=06/day=10/transactions_20260610.csv"
BATCH = {
    "batch_id": BATCH_ID,
    "started_at": LOADED_AT,
    "loaded_at": LOADED_AT,
    "snapshot_delivery_date": date(2026, 6, 17),
    "input_files": pl.DataFrame(
        {
            "path": ["customers.csv", "products.csv", TXN_FILE],
            "process_date": [date(2026, 6, 17), date(2026, 6, 17), date(2026, 6, 10)],
        }
    ),
    "previous_max_process_date": None,
    "max_process_date": date(2026, 6, 17),
}

C1 = "CLI-AAAAAAAAAAAA"
K1 = "PRD-CREDIT000001"  # credit card, also a balance product
K2 = "PRD-DEBIT0000001"  # debit card
S1 = "PRD-SAVINGS00001"  # savings account
T1 = "TRX-AAAAAAAAAAAAAAAAAAA1"  # purchase on K1
T2 = "TRX-AAAAAAAAAAAAAAAAAAA2"  # withdrawal on K2

PRODUCTS = pl.LazyFrame(
    {
        "product_id": [K1, K2, S1],
        "product_type": ["Tarjeta Crédito", "Tarjeta Débito", "Cuenta Ahorro"],
        "currency": ["COP", "COP", "COP"],
        "source_file": ["products.csv"] * 3,
        "last_updated": [datetime(2023, 1, 1)] * 3,
    }
)


def _table(name: str, rows: list[dict]) -> pl.DataFrame:
    lineage = {"gold_batch_id": BATCH_ID, "gold_loaded_at": LOADED_AT}
    return pl.DataFrame([{**row, **lineage} for row in rows], schema=GOLD_SCHEMAS[name])


def _card(card_id, last4, hmac, product_type):
    return {
        "card_id": card_id,
        "customer_id": C1,
        "last4": last4,
        "card_number_hmac": hmac,
        "product_type": product_type,
        "status": "Active",
        "opening_date": date(2022, 1, 1),
        "expiration_date": date(2028, 1, 1),
        "last_updated": datetime(2023, 1, 1),
        "source_file": "products.csv",
    }


def _transaction(transaction_id, card_id, **values):
    return {
        "transaction_id": transaction_id,
        "card_id": card_id,
        "customer_id": C1,
        "transaction_datetime": datetime(2026, 6, 10, 12, 0),
        "process_date": date(2026, 6, 10),
        "currency": "COP",
        "status": "Approved",
        "source_file": TXN_FILE,
        **values,
    }


def _balance(product_id, kind, last4, balance, limit):
    return {
        "product_id": product_id,
        "customer_id": C1,
        "kind": kind,
        "last4": last4,
        "status": "Active",
        "currency": "COP",
        "current_balance": Decimal(balance),
        "credit_limit": None if limit is None else Decimal(limit),
        "source_file": "products.csv",
    }


def _valid_tables() -> dict[str, pl.DataFrame]:
    return {
        "customers": _table(
            "customers",
            [
                {
                    "customer_id": C1,
                    "country": "Colombia",
                    "segment": "Basic",
                    "customer_status": "Active",
                    "source_file": "customers.csv",
                }
            ],
        ),
        "cards": _table(
            "cards",
            [
                _card(K1, "1111", "a" * 64, "Tarjeta Crédito"),
                _card(K2, "2222", "b" * 64, "Tarjeta Débito"),
            ],
        ),
        "card_transactions": _table(
            "card_transactions",
            [
                _transaction(
                    T1,
                    K1,
                    transaction_type="Purchase",
                    amount=Decimal("100.00"),
                    merchant_name="Tienda Don José",
                    response_code="00",
                ),
                _transaction(
                    T2,
                    K2,
                    transaction_type="Withdrawal",
                    amount=Decimal("50.00"),
                    merchant_name=None,
                    response_code=None,
                ),
            ],
        ),
        "balance_products": _table(
            "balance_products",
            [
                _balance(K1, "credit_card", "1111", "500.00", "1000.00"),
                _balance(S1, "savings_account", "3333", "50.00", None),
            ],
        ),
    }


def _candidate(tables: dict[str, pl.DataFrame]) -> dict:
    counts = {
        name: {
            "incoming": tables[name].height,
            "inserted": tables[name].height,
            "updated": 0,
            "unchanged": 0,
            "previous_rows": 0,
        }
        for name in TABLES
    }
    return {"tables": tables, "counts": counts}


def _set(tables: dict, name: str, key_value: str, **values) -> dict:
    """Change columns of the row of ``name`` whose key is ``key_value``."""
    df = tables[name]
    hit = pl.col(KEYS[name]) == key_value
    changes = [
        pl.when(hit)
        .then(pl.lit(value, dtype=df.schema.get(column, pl.Boolean)))
        .otherwise(pl.col(column) if column in df.columns else None)
        .alias(column)
        for column, value in values.items()
    ]
    return {**tables, name: df.with_columns(changes)}


def _violations(summary: pl.DataFrame, check_id: str, level: str, table: str) -> int:
    return summary.filter(
        (pl.col("id") == check_id)
        & (pl.col("level") == level)
        & (pl.col("table") == table)
    )["violations"].sum()


def test_valid_state_passes_every_check():
    results = run_checks(_candidate(_valid_tables()), PRODUCTS, BATCH)
    summary = results["summary"]
    assert summary["violations"].sum() == 0
    assert results["quarantine"] == {}
    assert set(summary["id"]) == {f"GQ-{i:02d}" for i in range(1, 30)}


FAIL_CASES = [
    pytest.param(
        "GQ-01",
        "customers",
        C1,
        lambda t: {**t, "customers": pl.concat([t["customers"], t["customers"]])},
        id="GQ-01 duplicate key",
    ),
    pytest.param(
        "GQ-02",
        "cards",
        K1,
        lambda t: _set(t, "cards", K1, opening_date=None),
        id="GQ-02 required null",
    ),
    pytest.param(
        "GQ-03",
        "card_transactions",
        T1,
        lambda t: _set(t, "card_transactions", T1, source_file="transactions/x.csv"),
        id="GQ-03 source_file not an input",
    ),
    pytest.param(
        "GQ-05",
        "cards",
        K2,
        lambda t: _set(t, "cards", K2, customer_id="CLI-UNKNOWN00000"),
        id="GQ-05 orphan card",
    ),
    pytest.param(
        "GQ-06",
        "cards",
        K1,
        lambda t: _set(t, "cards", K1, last4="12a4"),
        id="GQ-06 bad last4",
    ),
    pytest.param(
        "GQ-06",
        "cards",
        K2,
        lambda t: _set(t, "cards", K2, _number_is_16_digits=False),
        id="GQ-06 source number not 16 digits",
    ),
    pytest.param(
        "GQ-07",
        "cards",
        K2,
        lambda t: _set(t, "cards", K2, card_number_hmac="a" * 64),
        id="GQ-07 duplicate hmac",
    ),
    pytest.param(
        "GQ-08",
        "cards",
        K2,
        lambda t: _set(t, "cards", K2, status="Frozen"),
        id="GQ-08 unknown status",
    ),
    pytest.param(
        "GQ-12",
        "card_transactions",
        T1,
        lambda t: _set(t, "card_transactions", T1, card_id="PRD-UNKNOWN00000"),
        id="GQ-12 unknown card",
    ),
    pytest.param(
        "GQ-12",
        "card_transactions",
        T1,
        lambda t: _set(t, "card_transactions", T1, customer_id="CLI-OTHER0000000"),
        id="GQ-12 customer mismatch",
    ),
    pytest.param(
        "GQ-13",
        "card_transactions",
        T1,
        lambda t: _set(t, "card_transactions", T1, currency="USD"),
        id="GQ-13 currency mismatch",
    ),
    pytest.param(
        "GQ-14",
        "card_transactions",
        T1,
        lambda t: _set(t, "card_transactions", T1, amount=Decimal("0.00")),
        id="GQ-14 amount not positive",
    ),
    pytest.param(
        "GQ-23",
        "balance_products",
        S1,
        lambda t: _set(t, "balance_products", S1, currency="MXN"),
        id="GQ-23 currency not allowed",
    ),
    pytest.param(
        "GQ-24",
        "balance_products",
        S1,
        lambda t: _set(t, "balance_products", S1, customer_id="CLI-UNKNOWN00000"),
        id="GQ-24 orphan product",
    ),
    pytest.param(
        "GQ-25",
        "balance_products",
        S1,
        lambda t: _set(t, "balance_products", S1, current_balance=Decimal("-1.00")),
        id="GQ-25 negative balance",
    ),
    pytest.param(
        "GQ-26",
        "balance_products",
        S1,
        lambda t: _set(t, "balance_products", S1, credit_limit=Decimal("10.00")),
        id="GQ-26 savings account with a limit",
    ),
    pytest.param(
        "GQ-28",
        "balance_products",
        K1,
        lambda t: _set(t, "balance_products", K1, status="Blocked"),
        id="GQ-28 disagrees with cards",
    ),
]


@pytest.mark.parametrize(("check_id", "table", "key", "mutate"), FAIL_CASES)
def test_fail_check_quarantines_the_row_and_rejects_the_load(
    check_id, table, key, mutate, tmp_path
):
    candidate = _candidate(mutate(_valid_tables()))
    results = run_checks(candidate, PRODUCTS, BATCH)

    assert _violations(results["summary"], check_id, "fail", table) > 0
    quarantined = results["quarantine"][table].filter(pl.col(KEYS[table]) == key)
    assert any(check_id in ids for ids in quarantined["failed_checks"].to_list())

    out = publish_gold(candidate, results, {}, BATCH, str(tmp_path))
    assert out["tables"] is None
    assert out["load_log"]["status"].unique().to_list() == ["rejected"]


def test_gq22_rejects_lost_rows_without_quarantining_any():
    candidate = _candidate(_valid_tables())
    candidate["counts"]["customers"]["previous_rows"] = 3
    results = run_checks(candidate, PRODUCTS, BATCH)
    assert _violations(results["summary"], "GQ-22", "fail", "customers") == 3
    assert results["quarantine"] == {}


def test_warn_checks_are_counted_and_the_load_is_published(tmp_path):
    tables = _set(
        _valid_tables(), "balance_products", K1, current_balance=Decimal("2000.00")
    )
    tables = _set(tables, "card_transactions", T2, merchant_name="Tienda Don José")
    tables = _set(tables, "cards", K2, last4="1111")  # two cards share last4
    candidate = _candidate(tables)
    results = run_checks(candidate, PRODUCTS, BATCH)
    summary = results["summary"]

    assert _violations(summary, "GQ-27", "warn", "balance_products") == 1
    assert _violations(summary, "GQ-18", "warn", "card_transactions") == 1
    assert _violations(summary, "GQ-11", "warn", "cards") == 1  # one customer
    assert results["quarantine"] == {}

    out = publish_gold(candidate, results, {}, BATCH, str(tmp_path))
    assert out["tables"] is not None
    log = out["load_log"]
    assert log["status"].unique().to_list() == ["published"]
    balance_checks = log.filter(pl.col("table") == "balance_products")["checks"][0]
    assert {"id": "GQ-27", "level": "warn", "violations": 1} in balance_checks.to_list()
