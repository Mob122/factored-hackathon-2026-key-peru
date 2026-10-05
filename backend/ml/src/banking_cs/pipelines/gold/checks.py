"""Quality checks of docs/contracts/gold_tables.md section 5 (GQ-01 to GQ-29).

Each check marks the rows that violate it. A fail-level violation rejects the load
and its rows go to quarantine; warn- and info-level checks are only counted in the
load log. GQ-26 has one fail part (savings account with a limit) and one warn part
(credit card without a limit), reported as two entries with the same ID.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import polars as pl

from .nodes import delivery_date, latest_per_key, product_order
from .schemas import (
    BALANCE_KINDS,
    CARD_TYPES,
    COUNTRIES,
    CURRENCIES,
    CUSTOMER_STATUSES,
    GOLD_SCHEMAS,
    KEYS,
    LINEAGE,
    PRODUCT_STATUSES,
    REQUIRED,
    RESPONSE_CODES,
    SEGMENTS,
    TABLES,
    TRANSACTION_STATUSES,
    TRANSACTION_TYPES,
)


@dataclass(frozen=True)
class Check:
    id: str
    table: str
    level: str  # "fail", "warn" or "info"
    violation: pl.Expr  # true on a violating row; null counts as no violation
    count_distinct: str | None = None  # count distinct values instead of rows

    @property
    def column(self) -> str:
        return f"{self.id}:{self.level}"


def _not_in(column: str, allowed: tuple[str, ...]) -> pl.Expr:
    """A present value outside ``allowed`` (nulls are GQ-02's business)."""
    return pl.col(column).is_not_null() & ~pl.col(column).is_in(list(allowed))


def build_checks(batch: dict[str, Any]) -> list[Check]:
    """All row-level checks. GQ-22 is table-level and computed in ``run_checks``."""
    input_paths = batch["input_files"]["path"].to_list()
    newest: date | None = batch["max_process_date"]
    # GQ-10: the close of the newest partition, max(process_date) + 1 day at 06:00.
    closed_at = (
        datetime.combine(newest + timedelta(days=1), time(6)) if newest else None
    )
    is_credit_card = pl.col("kind") == "credit_card"

    checks = []
    for table in TABLES:
        key = KEYS[table]
        checks += [
            Check(
                "GQ-01",
                table,
                "fail",
                pl.col(key).is_null() | pl.col(key).is_duplicated(),
            ),
            Check(
                "GQ-02",
                table,
                "fail",
                pl.any_horizontal([pl.col(c).is_null() for c in REQUIRED[table]]),
            ),
            Check(
                "GQ-03",
                table,
                "fail",
                pl.any_horizontal([pl.col(c).is_null() for c in LINEAGE])
                | (
                    (pl.col("gold_batch_id") == batch["batch_id"])
                    & ~pl.col("source_file").is_in(input_paths)
                ),
            ),
        ]
    checks += [
        # customers
        Check(
            "GQ-04",
            "customers",
            "warn",
            _not_in("country", COUNTRIES)
            | _not_in("segment", SEGMENTS)
            | _not_in("customer_status", CUSTOMER_STATUSES),
        ),
        # cards
        Check("GQ-05", "cards", "fail", pl.col("_customer_exists").is_null()),
        Check(
            "GQ-06",
            "cards",
            "fail",
            ~pl.col("last4").str.contains(r"^[0-9]{4}$")
            | pl.col("_number_is_16_digits").not_(),
        ),
        Check(
            "GQ-07",
            "cards",
            "fail",
            pl.col("card_number_hmac").is_not_null()
            & pl.col("card_number_hmac").is_duplicated(),
        ),
        Check(
            "GQ-08",
            "cards",
            "fail",
            _not_in("product_type", CARD_TYPES) | _not_in("status", PRODUCT_STATUSES),
        ),
        Check(
            "GQ-09", "cards", "warn", pl.col("expiration_date") < pl.col("opening_date")
        ),
        Check("GQ-10", "cards", "warn", pl.col("last_updated") > pl.lit(closed_at)),
        Check(
            "GQ-11",
            "cards",
            "warn",
            pl.len().over("customer_id", "last4") > 1,
            count_distinct="customer_id",
        ),
        # card_transactions
        Check(
            "GQ-12",
            "card_transactions",
            "fail",
            pl.col("_card_customer_id").is_null()
            | (pl.col("customer_id") != pl.col("_card_customer_id")),
        ),
        Check(
            "GQ-13",
            "card_transactions",
            "fail",
            pl.col("currency") != pl.col("_product_currency"),
        ),
        Check("GQ-14", "card_transactions", "fail", pl.col("amount") <= 0),
        Check(
            "GQ-15",
            "card_transactions",
            "warn",
            _not_in("transaction_type", TRANSACTION_TYPES)
            | _not_in("status", TRANSACTION_STATUSES),
        ),
        Check(
            "GQ-16",
            "card_transactions",
            "warn",
            _not_in("response_code", RESPONSE_CODES),
        ),
        Check(
            "GQ-17",
            "card_transactions",
            "warn",
            pl.when(pl.col("status") == "Approved")
            .then(_not_in("response_code", ("00",)))
            .otherwise(pl.col("response_code") == "00"),
        ),
        Check(
            "GQ-18",
            "card_transactions",
            "warn",
            (pl.col("transaction_type") != "Purchase")
            & pl.col("merchant_name").is_not_null(),
        ),
        Check(
            "GQ-19",
            "card_transactions",
            "warn",
            pl.col("process_date")
            != (pl.col("transaction_datetime") - pl.duration(hours=6)).dt.date(),
        ),
        Check(
            "GQ-20",
            "card_transactions",
            "warn",
            (pl.col("_card_status") != "Active")
            & (pl.col("process_date") >= pl.col("_card_delivery")),
        ),
        Check(
            "GQ-21",
            "card_transactions",
            "info",
            (pl.col("transaction_datetime").dt.date() < pl.col("_card_opening"))
            | (pl.col("transaction_datetime").dt.date() > pl.col("_card_expiration")),
        ),
        # balance_products. GQ-23's "kind matches product_type" holds by construction:
        # stage_products is the only producer of kind.
        Check(
            "GQ-23",
            "balance_products",
            "fail",
            _not_in("kind", tuple(BALANCE_KINDS.values()))
            | _not_in("status", PRODUCT_STATUSES)
            | _not_in("currency", CURRENCIES),
        ),
        Check(
            "GQ-24", "balance_products", "fail", pl.col("_customer_exists").is_null()
        ),
        Check(
            "GQ-25",
            "balance_products",
            "fail",
            pl.col("current_balance").is_null() | (pl.col("current_balance") < 0),
        ),
        Check(
            "GQ-26",
            "balance_products",
            "fail",
            (pl.col("kind") == "savings_account")
            & pl.col("credit_limit").is_not_null(),
        ),
        Check(
            "GQ-26",
            "balance_products",
            "warn",
            is_credit_card & pl.col("credit_limit").is_null(),
        ),
        Check(
            "GQ-27",
            "balance_products",
            "warn",
            is_credit_card & (pl.col("current_balance") > pl.col("credit_limit")),
        ),
        Check(
            "GQ-28",
            "balance_products",
            "fail",
            is_credit_card
            & (
                pl.col("_card_exists").is_null()
                | (pl.col("last4") != pl.col("_card_last4"))
                | (pl.col("status") != pl.col("_card_status"))
            ),
        ),
        Check(
            "GQ-29",
            "balance_products",
            "warn",
            (pl.col("status") != "Closed")
            & (pl.len().over("customer_id", "last4", pl.col("status") != "Closed") > 1),
            count_distinct="customer_id",
        ),
    ]
    return checks


def _with_lookups(
    tables: dict[str, pl.DataFrame],
    products_intermediate: pl.LazyFrame,
    snapshot_delivery_date: date,
) -> dict[str, pl.DataFrame]:
    """Add the cross-table columns the checks read (all prefixed with ``_``)."""
    known_customers = (
        tables["customers"]
        .select(pl.col("customer_id").unique())
        .with_columns(_customer_exists=pl.lit(True))
    )
    cards = tables["cards"]
    if "_number_is_16_digits" not in cards.columns:
        cards = cards.with_columns(_number_is_16_digits=pl.lit(None, dtype=pl.Boolean))
    one_card = cards.unique("card_id", keep="first", maintain_order=True)
    # GQ-13 is checked against the card product's currency in the source products.
    product_currency = (
        latest_per_key(
            products_intermediate.filter(pl.col("product_type").is_in(CARD_TYPES)),
            "product_id",
            product_order(snapshot_delivery_date),
        )
        .select("product_id", pl.col("currency").alias("_product_currency"))
        .collect()
    )
    card_lookup = one_card.select(
        "card_id",
        pl.col("customer_id").alias("_card_customer_id"),
        pl.col("status").alias("_card_status"),
        delivery_date(snapshot_delivery_date).alias("_card_delivery"),
        pl.col("opening_date").alias("_card_opening"),
        pl.col("expiration_date").alias("_card_expiration"),
    )
    return {
        "customers": tables["customers"],
        "cards": cards.join(known_customers, on="customer_id", how="left"),
        "card_transactions": tables["card_transactions"]
        .join(card_lookup, on="card_id", how="left")
        .join(product_currency, left_on="card_id", right_on="product_id", how="left"),
        "balance_products": tables["balance_products"]
        .join(known_customers, on="customer_id", how="left")
        .join(
            one_card.select(
                pl.col("card_id").alias("product_id"),
                pl.col("last4").alias("_card_last4"),
                pl.col("status").alias("_card_status"),
                pl.lit(True).alias("_card_exists"),
            ),
            on="product_id",
            how="left",
        ),
    }


def run_checks(
    gold_candidate: dict[str, Any],
    products_intermediate: pl.LazyFrame,
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Run every check on the staged tables.

    Returns ``summary`` (one row per table, check and level, with the violation
    count) and ``quarantine`` (per table, the rows with at least one fail-level
    violation and the IDs of the checks they failed).
    """
    tables = gold_candidate["tables"]
    annotated = _with_lookups(
        tables, products_intermediate, batch["snapshot_delivery_date"]
    )
    checks = build_checks(batch)
    summary, quarantine = [], {}
    for name in TABLES:
        table_checks = [c for c in checks if c.table == name]
        marked = annotated[name].with_columns(
            [c.violation.fill_null(False).alias(c.column) for c in table_checks]
        )
        for check in table_checks:
            hits = marked.filter(pl.col(check.column))
            n = (
                hits[check.count_distinct].n_unique()
                if check.count_distinct
                else hits.height
            )
            summary.append(
                {"table": name, "id": check.id, "level": check.level, "violations": n}
            )

        # GQ-22: no row lost or created outside the delivered delta.
        counts = gold_candidate["counts"][name]
        expected_rows = counts["previous_rows"] + counts["inserted"]
        summary.append(
            {
                "table": name,
                "id": "GQ-22",
                "level": "fail",
                "violations": abs(tables[name].height - expected_rows),
            }
        )

        fail_checks = [c for c in table_checks if c.level == "fail"]
        rejected = marked.filter(
            pl.any_horizontal([pl.col(c.column) for c in fail_checks])
        )
        if rejected.height:
            quarantine[name] = rejected.select(
                *GOLD_SCHEMAS[name],
                pl.concat_list(
                    [pl.when(pl.col(c.column)).then(pl.lit(c.id)) for c in fail_checks]
                )
                .list.drop_nulls()
                .alias("failed_checks"),
            )
    summary_df = pl.DataFrame(
        summary,
        schema={
            "table": pl.String,
            "id": pl.String,
            "level": pl.String,
            "violations": pl.Int64,
        },
    ).sort("table", "id", "level", maintain_order=True)
    return {"summary": summary_df, "quarantine": quarantine}
