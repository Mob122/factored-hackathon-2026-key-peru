"""Nodes for the 'gold' pipeline.

Implements docs/contracts/gold_tables.md (gold-0.2) with the incremental load of
docs/contracts/freshness_policy.md (fresh-0.2) section 3. A backfill and a daily load
run the same nodes; ``gold.partitions`` selects which delivered files are processed.

Gold reads ``02_intermediate``, which keeps every delivered row with its
``source_file``. The C1 dedup rule (later delivery, then later ``source_file``) is
applied while staging.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import date, datetime
from pathlib import Path
from typing import Any

import polars as pl

from .schemas import (
    BALANCE_KINDS,
    CARD_TYPES,
    GOLD_SCHEMAS,
    KEYS,
    LINEAGE,
    TABLES,
    TS,
)

logger = logging.getLogger(__name__)

_PATH_DATE = r"(year=\d{4}/month=\d{2}/day=\d{2})"

LOAD_LOG_SCHEMA: dict[str, pl.DataType] = {
    "gold_batch_id": pl.String,
    "table": pl.String,
    "started_at": TS,
    "finished_at": TS,
    "input_files": pl.List(
        pl.Struct({"path": pl.String, "sha256": pl.String, "process_date": pl.Date})
    ),
    "rows_inserted": pl.Int64,
    "rows_updated": pl.Int64,
    "rows_unchanged": pl.Int64,
    "rows_rejected": pl.Int64,
    "checks": pl.List(
        pl.Struct({"id": pl.String, "level": pl.String, "violations": pl.Int64})
    ),
    "status": pl.String,
    "table_checksum": pl.String,
    "max_process_date": pl.Date,
}


# --- Helpers ----------------------------------------------------------------


def delivery_date(snapshot_delivery_date: date) -> pl.Expr:
    """Delivery date of each row's ``source_file``.

    Partitioned and delta files carry it in the path (``year=YYYY/month=MM/day=DD``).
    The one-file snapshots ``customers.csv`` and ``products.csv`` are registered with
    ``snapshot_delivery_date`` (freshness policy section 1).
    """
    return (
        pl.col("source_file")
        .str.extract(_PATH_DATE, 1)
        .str.to_date("year=%Y/month=%m/day=%d")
        .fill_null(pl.lit(snapshot_delivery_date))
    )


def latest_per_key(
    rows: pl.LazyFrame, key: str, order: list[pl.Expr | str]
) -> pl.LazyFrame:
    """Keep one row per ``key``: the greatest by ``order`` (nulls lose)."""
    return rows.sort(
        order, descending=True, nulls_last=True, maintain_order=True
    ).unique(subset=key, keep="first", maintain_order=True)


def product_order(snapshot_delivery_date: date) -> list[pl.Expr | str]:
    """Later delivery wins, then the later ``source_file``; ``last_updated`` only
    breaks ties within one delivery (fresh-0.2 section 3, step 4)."""
    return [delivery_date(snapshot_delivery_date), "source_file", "last_updated"]


def _delivery_order(table: str, snapshot_delivery_date: date) -> pl.Expr:
    """Which delivery a stored or incoming row comes from, for the upsert."""
    if table == "card_transactions":
        return pl.col("process_date")
    return delivery_date(snapshot_delivery_date)


def _as_date(value: Any) -> date:
    return value if isinstance(value, date) else date.fromisoformat(str(value))


def _as_dates(value: Any) -> list[date] | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split(",")
    return [_as_date(v) for v in value]


def _this_load(rows: pl.LazyFrame, batch: dict[str, Any]) -> pl.LazyFrame:
    paths = batch["input_files"]["path"].to_list()
    return rows.filter(pl.col("source_file").is_in(paths))


def _hmac_hex(numbers: pl.Series, key: str) -> pl.Series:
    """HMAC-SHA256 of each card number (UTF-8) under ``key`` (UTF-8), lowercase hex."""
    secret = key.encode()
    return pl.Series(
        [
            None
            if n is None
            else hmac.new(secret, n.encode(), hashlib.sha256).hexdigest()
            for n in numbers
        ],
        dtype=pl.String,
    )


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        logger.warning("Input file not found for checksum: %s", path)
        return None
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def table_checksum(table: pl.DataFrame, name: str) -> str:
    """SHA-256 of the table content sorted by key, lineage columns excluded."""
    columns = [c for c in GOLD_SCHEMAS[name] if c not in LINEAGE]
    content = table.select(columns).sort(KEYS[name], nulls_last=True)
    digest = hashlib.sha256(",".join(columns).encode())
    for chunk in content.iter_slices(200_000):
        digest.update(chunk.write_csv(include_header=False).encode())
    return digest.hexdigest()


def _empty(name: str) -> pl.DataFrame:
    return pl.DataFrame(schema=GOLD_SCHEMAS[name])


# --- Nodes ------------------------------------------------------------------


def plan_load(
    customers_intermediate: pl.LazyFrame,
    products_intermediate: pl.LazyFrame,
    transactions_intermediate: pl.LazyFrame,
    gold_previous: dict[str, pl.DataFrame],
    params: dict[str, Any],
) -> dict[str, Any]:
    """Pick the input files of this load and open a batch.

    ``params["partitions"]`` lists delivery dates to process; ``None`` processes every
    delivered file (backfill). ``batch_id`` and ``loaded_at`` may be fixed for
    reproducible tests; otherwise a new ID and the current time are used.
    """
    snapshot = _as_date(params["snapshot_delivery_date"])
    partitions = _as_dates(params.get("partitions"))
    files = (
        pl.concat(
            [
                lf.select("source_file").unique()
                for lf in (
                    customers_intermediate,
                    products_intermediate,
                    transactions_intermediate,
                )
            ]
        )
        .with_columns(process_date=delivery_date(snapshot))
        .rename({"source_file": "path"})
    )
    if partitions is not None:
        files = files.filter(pl.col("process_date").is_in(partitions))
    files = files.unique().sort("path").collect()

    started_at = datetime.now().replace(microsecond=0)
    loaded_at = params.get("loaded_at")
    loaded_at = datetime.fromisoformat(str(loaded_at)) if loaded_at else started_at
    batch_id = (
        params.get("batch_id")
        or f"gold-{loaded_at:%Y%m%dT%H%M%S}-{secrets.token_hex(4)}"
    )

    previous_max = None
    log = gold_previous.get("_load_log")
    if log is not None:
        previous_max = log.filter(pl.col("status") == "published")[
            "max_process_date"
        ].max()
    newest = [d for d in (previous_max, files["process_date"].max()) if d is not None]
    logger.info(
        "Gold batch %s: %d input files, partitions=%s",
        batch_id,
        files.height,
        "all" if partitions is None else [str(p) for p in partitions],
    )
    return {
        "batch_id": batch_id,
        "started_at": started_at,
        "loaded_at": loaded_at,
        "snapshot_delivery_date": snapshot,
        "input_files": files,
        "previous_max_process_date": previous_max,
        "max_process_date": max(newest) if newest else None,
    }


def stage_customers(
    customers_intermediate: pl.LazyFrame, batch: dict[str, Any]
) -> pl.DataFrame:
    """Gold ``customers`` rows of this load (gold-0.2 section 2)."""
    rows = latest_per_key(
        _this_load(customers_intermediate, batch),
        "customer_id",
        [delivery_date(batch["snapshot_delivery_date"]), "source_file"],
    )
    return rows.select(
        "customer_id", "country", "segment", "customer_status", "source_file"
    ).collect()


def stage_products(
    products_intermediate: pl.LazyFrame, card_hash_key: str, batch: dict[str, Any]
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Gold ``cards`` and ``balance_products`` rows of this load (sections 3 and 4b).

    Both come from the same winning product row, so a credit card's two rows always
    agree (GQ-28). ``_number_is_16_digits`` is a transient column for GQ-06; it is
    never published.
    """
    if not card_hash_key:
        raise ValueError(
            "card_hash_key is empty: set card_hash_key.key in conf/local/credentials.yml"
        )
    rows = latest_per_key(
        _this_load(products_intermediate, batch),
        "product_id",
        product_order(batch["snapshot_delivery_date"]),
    ).collect()
    last4 = pl.col("product_number").str.slice(-4).alias("last4")

    card_rows = rows.filter(pl.col("product_type").is_in(CARD_TYPES))
    cards = card_rows.select(
        pl.col("product_id").alias("card_id"),
        "customer_id",
        last4,
        _hmac_hex(card_rows["product_number"], card_hash_key).alias("card_number_hmac"),
        "product_type",
        pl.col("product_status").alias("status"),
        "opening_date",
        "expiration_date",
        "last_updated",
        "source_file",
        pl.col("product_number")
        .str.contains(r"^[0-9]{16}$")
        .alias("_number_is_16_digits"),
    )
    balance_products = rows.filter(
        pl.col("product_type").is_in(list(BALANCE_KINDS))
    ).select(
        "product_id",
        "customer_id",
        pl.col("product_type").replace_strict(BALANCE_KINDS).alias("kind"),
        last4,
        pl.col("product_status").alias("status"),
        "currency",
        "current_balance",
        "credit_limit",
        "source_file",
    )
    return cards, balance_products


def stage_card_transactions(
    transactions_intermediate: pl.LazyFrame,
    products_intermediate: pl.LazyFrame,
    batch: dict[str, Any],
) -> pl.DataFrame:
    """Gold ``card_transactions`` rows of this load (section 4).

    A transaction is a card transaction when its product is a card in any delivered
    products file (product types never change). Excluded source columns never leave
    this function.
    """
    card_products = (
        products_intermediate.filter(pl.col("product_type").is_in(CARD_TYPES))
        .select("product_id")
        .unique()
    )
    rows = _this_load(transactions_intermediate, batch).join(
        card_products, on="product_id", how="semi"
    )
    return (
        latest_per_key(rows, "transaction_id", ["process_date", "source_file"])
        .select(
            "transaction_id",
            pl.col("product_id").alias("card_id"),
            "customer_id",
            pl.col("transaction_date").alias("transaction_datetime"),
            "process_date",
            "transaction_type",
            "amount",
            "currency",
            "merchant_name",
            pl.col("transaction_status").alias("status"),
            "response_code",
            "source_file",
        )
        .collect()
    )


def _upsert(
    previous: pl.DataFrame | None,
    incoming: pl.DataFrame,
    name: str,
    batch: dict[str, Any],
) -> tuple[pl.DataFrame, dict[str, int]]:
    """Upsert ``incoming`` into ``previous`` by key (fresh-0.2 section 3, step 4).

    - New key: inserted with this batch's lineage.
    - The stored row comes from a later delivery: the stored row stays.
    - Same content (all non-lineage columns): the stored row stays with its lineage,
      which makes a replay a no-op.
    - Otherwise: updated, with this batch's lineage.

    Rows are never deleted. Counts are over the incoming rows (one per key).
    """
    schema = GOLD_SCHEMAS[name]
    key = KEYS[name]
    compared = [c for c in schema if c not in LINEAGE and c != key]
    order = _delivery_order(name, batch["snapshot_delivery_date"])

    previous = (
        _empty(name) if previous is None else previous.select(list(schema)).cast(schema)
    )
    incoming = incoming.with_columns(
        gold_batch_id=pl.lit(batch["batch_id"], dtype=pl.String),
        gold_loaded_at=pl.lit(batch["loaded_at"], dtype=TS),
    ).cast(schema)

    stored = previous.select(
        key,
        pl.lit(True).alias("_stored"),
        order.alias("_stored_order"),
        pl.col("source_file").alias("_stored_source"),
        *[pl.col(c).alias(f"_stored_{c}") for c in compared],
    )
    stored_is_later = (pl.col("_stored_order") > pl.col("_incoming_order")) | (
        (pl.col("_stored_order") == pl.col("_incoming_order"))
        & (pl.col("_stored_source") > pl.col("source_file"))
    )
    same_content = pl.all_horizontal(
        [pl.col(c).eq_missing(pl.col(f"_stored_{c}")) for c in compared]
    )
    joined = (
        incoming.with_columns(_incoming_order=order)
        .join(stored, on=key, how="left")
        .with_columns(
            _outcome=pl.when(pl.col("_stored").is_null())
            .then(pl.lit("inserted"))
            .when(stored_is_later.fill_null(False) | same_content)
            .then(pl.lit("unchanged"))
            .otherwise(pl.lit("updated"))
        )
    )
    written = joined.filter(pl.col("_outcome") != "unchanged").select(incoming.columns)
    table = pl.concat(
        [previous.join(written.select(key), on=key, how="anti"), written],
        how="diagonal_relaxed",
    )
    outcomes = dict(joined["_outcome"].value_counts().iter_rows())
    counts = {
        "incoming": incoming.height,
        "inserted": outcomes.get("inserted", 0),
        "updated": outcomes.get("updated", 0),
        "unchanged": outcomes.get("unchanged", 0),
        "previous_rows": previous.height,
    }
    return table, counts


def upsert_tables(  # noqa: PLR0913 (one argument per Kedro input)
    gold_previous: dict[str, pl.DataFrame],
    staged_customers: pl.DataFrame,
    staged_cards: pl.DataFrame,
    staged_card_transactions: pl.DataFrame,
    staged_balance_products: pl.DataFrame,
    batch: dict[str, Any],
) -> dict[str, Any]:
    """Build the staged version of the four gold tables and the per-table counts."""
    staged = {
        "customers": staged_customers,
        "cards": staged_cards,
        "card_transactions": staged_card_transactions,
        "balance_products": staged_balance_products,
    }
    tables, counts = {}, {}
    for name in TABLES:
        tables[name], counts[name] = _upsert(
            gold_previous.get(name), staged[name], name, batch
        )
    return {"tables": tables, "counts": counts}


def publish_gold(
    gold_candidate: dict[str, Any],
    gold_check_results: dict[str, Any],
    gold_previous: dict[str, pl.DataFrame],
    batch: dict[str, Any],
    raw_root: str,
) -> dict[str, Any]:
    """Publish the staged tables, or reject the load if any fail-level check fired.

    A rejected load leaves the previous gold untouched: only its load-log rows and its
    quarantine are written. All its incoming rows count as rejected.
    """
    summary = gold_check_results["summary"]
    failed = summary.filter((pl.col("level") == "fail") & (pl.col("violations") > 0))
    published = failed.height == 0
    status = "published" if published else "rejected"

    if published:
        tables = {
            name: gold_candidate["tables"][name]
            .select(list(GOLD_SCHEMAS[name]))
            .sort(KEYS[name], nulls_last=True)
            for name in TABLES
        }
        live = tables
        max_process_date = batch["max_process_date"]
    else:
        tables = None
        live = {name: gold_previous.get(name) for name in TABLES}
        max_process_date = batch["previous_max_process_date"]
        logger.warning(
            "Gold batch %s rejected by %s",
            batch["batch_id"],
            sorted(set(failed["id"].to_list())),
        )

    input_files = [
        {
            "path": row["path"],
            "sha256": _sha256(Path(raw_root) / row["path"]),
            "process_date": row["process_date"],
        }
        for row in batch["input_files"].iter_rows(named=True)
    ]
    finished_at = datetime.now().replace(microsecond=0)
    rows = []
    for name in TABLES:
        counts = gold_candidate["counts"][name]
        rows.append(
            {
                "gold_batch_id": batch["batch_id"],
                "table": name,
                "started_at": batch["started_at"],
                "finished_at": finished_at,
                "input_files": input_files,
                "rows_inserted": counts["inserted"] if published else 0,
                "rows_updated": counts["updated"] if published else 0,
                "rows_unchanged": counts["unchanged"] if published else 0,
                "rows_rejected": 0 if published else counts["incoming"],
                "checks": summary.filter(pl.col("table") == name)
                .select("id", "level", "violations")
                .to_dicts(),
                "status": status,
                "table_checksum": None
                if live[name] is None
                else table_checksum(live[name], name),
                "max_process_date": max_process_date,
            }
        )
    load_log = pl.DataFrame(rows, schema=LOAD_LOG_SCHEMA)
    for row in load_log.iter_rows(named=True):
        logger.info(
            "Gold %s %s: %d inserted, %d updated, %d unchanged, %d rejected",
            row["table"],
            status,
            row["rows_inserted"],
            row["rows_updated"],
            row["rows_unchanged"],
            row["rows_rejected"],
        )
    return {
        "batch_id": batch["batch_id"],
        "tables": tables,
        "quarantine": gold_check_results["quarantine"],
        "load_log": load_log,
    }
