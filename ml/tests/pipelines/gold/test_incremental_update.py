"""FX tests of docs/contracts/freshness_policy.md section 6.

TEST FIXTURE — not supplied data (ml/tests/fixtures/update/README.md).

Each load runs the real 'gold' Kedro pipeline. The raw folder grows like
ml/data/01_raw: data_ingestion's query builder types it into 02_intermediate, then
gold upserts the selected partitions into a gold folder. FX-2 (the checksum shortcut
that skips a replayed file) is not implemented: comparing row content already makes
a replay a no-op (FX-3). FX-6 and FX-7 test the backend overlay.
"""

import hashlib
import shutil
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from kedro.io import DataCatalog, MemoryDataset
from kedro.runner import SequentialRunner
from polars.testing import assert_frame_equal

from banking_cs.datasets import DuckDBQueryDataset, GoldStoreDataset
from banking_cs.pipelines.data_ingestion.nodes import build_ingestion_query
from banking_cs.pipelines.gold.pipeline import create_pipeline
from banking_cs.pipelines.gold.schemas import GOLD_SCHEMAS, TABLES

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "update"
TEST_KEY = "fixture-card-hash-key"

BASE = ("gold-20260618T063000-00000001", "2026-06-18 06:30:00")
DELIVERY = ("gold-20260619T063000-00000002", "2026-06-19 06:30:00")
CARD_7921 = "PRD-I97V8EFELBUP"
DELTA_PRODUCTS = "products/updates/year=2026/month=06/day=18/products_20260618.csv"
DELTA_TRANSACTIONS = "transactions/year=2026/month=06/day=18/transactions_20260618.csv"

# Raw files per table, with the delta layout of freshness policy assumption A1.
GLOBS = {
    "customers": ["customers.csv", "customers/updates/**/*.csv"],
    "products": ["products.csv", "products/updates/**/*.csv"],
    "transactions": ["transactions/**/*.csv"],
}


class Bank:
    """A raw folder, its 02_intermediate and a gold folder."""

    def __init__(self, root: Path) -> None:
        self.raw = root / "01_raw"
        self.intermediate = root / "02_intermediate"
        self.gold = root / "gold"

    def deliver(self, name: str) -> None:
        shutil.copytree(FIXTURE / "raw" / name, self.raw, dirs_exist_ok=True)
        self.ingest()

    def ingest(self) -> None:
        for table, globs in GLOBS.items():
            queries = [
                f"({build_ingestion_query(str(self.raw), glob, table)})"
                for glob in globs
                if any(self.raw.glob(glob))
            ]
            DuckDBQueryDataset(
                filepath=str(self.intermediate / f"{table}.parquet")
            ).save("\nUNION ALL BY NAME\n".join(queries))

    def load(self, batch: tuple[str, str], partitions: list[str] | None = None) -> None:
        batch_id, loaded_at = batch
        params = {
            "partitions": partitions,
            "snapshot_delivery_date": "2026-06-17",
            "batch_id": batch_id,
            "loaded_at": loaded_at,
        }
        catalog = DataCatalog(
            datasets={
                **{
                    f"{table}_intermediate": DuckDBQueryDataset(
                        filepath=str(self.intermediate / f"{table}.parquet")
                    )
                    for table in GLOBS
                },
                "gold_previous": GoldStoreDataset(path=str(self.gold)),
                "gold_store": GoldStoreDataset(path=str(self.gold)),
                "card_hash_key": MemoryDataset(TEST_KEY),
                "params:gold": MemoryDataset(params),
                "params:data_ingestion.raw_root": MemoryDataset(str(self.raw)),
            }
        )
        SequentialRunner().run(create_pipeline(), catalog)

    def table(self, name: str) -> pl.DataFrame:
        return pl.read_parquet(self.gold / f"{name}.parquet")

    def tables(self) -> dict[str, pl.DataFrame]:
        return {name: self.table(name) for name in TABLES}

    def log(self, batch: tuple[str, str]) -> pl.DataFrame:
        log = pl.read_parquet(self.gold / "_load_log.parquet")
        return log.filter(pl.col("gold_batch_id") == batch[0])


def _expected(name: str) -> pl.DataFrame:
    raw = pl.read_csv(FIXTURE / "expected" / f"{name}.csv", infer_schema=False)
    casts = []
    for column, dtype in GOLD_SCHEMAS[name].items():
        if dtype == pl.Date:
            casts.append(pl.col(column).str.to_date("%Y-%m-%d"))
        elif isinstance(dtype, pl.Datetime):
            casts.append(
                pl.col(column).str.to_datetime("%Y-%m-%d %H:%M:%S", time_unit="us")
            )
        else:
            casts.append(pl.col(column).cast(dtype))
    return raw.select(casts)


def _counts(log: pl.DataFrame) -> dict[str, tuple[int, int, int, int]]:
    columns = ["rows_inserted", "rows_updated", "rows_unchanged", "rows_rejected"]
    return {row[0]: tuple(row[1:]) for row in log.select("table", *columns).iter_rows()}


@pytest.fixture
def bank(tmp_path: Path) -> Bank:
    """Base loaded as a backfill, then the 2026-06-18 delivery as a daily load."""
    bank = Bank(tmp_path)
    bank.deliver("base")
    bank.load(BASE)
    bank.deliver("delivery_20260618")
    bank.load(DELIVERY, partitions=["2026-06-18"])
    return bank


def test_base_load_keeps_only_cards_and_balance_products(bank):
    assert _counts(bank.log(BASE)) == {
        "customers": (1, 0, 0, 0),
        "cards": (2, 0, 0, 0),  # the personal loan is left out
        "card_transactions": (3, 0, 0, 0),
        "balance_products": (2, 0, 0, 0),
    }


@pytest.mark.parametrize("name", TABLES)
def test_fx1_gold_state_after_the_delivery(bank, name):
    assert_frame_equal(bank.table(name), _expected(name))


def test_fx1_load_log(bank):
    expected = pl.read_csv(
        FIXTURE / "expected" / "_load_log.csv",
        schema_overrides={"max_process_date": pl.Date},
    )
    log = bank.log(DELIVERY)
    assert_frame_equal(log.select(expected.columns), expected)

    files = log["input_files"][0].to_list()
    assert [(f["path"], f["process_date"]) for f in files] == [
        (DELTA_PRODUCTS, date(2026, 6, 18)),
        (DELTA_TRANSACTIONS, date(2026, 6, 18)),
    ]
    for f in files:
        assert (
            f["sha256"]
            == hashlib.sha256((bank.raw / f["path"]).read_bytes()).hexdigest()
        )
    # Only GQ-21 (info) fires: card 9205 expired on 2026-01-08, before its three
    # 2026-06 transactions (the validity-date limitation, kept on purpose).
    fired = (
        log.select("table", "checks")
        .explode("checks", empty_as_null=True)
        .unnest("checks")
        .filter(pl.col("violations") > 0)
    )
    assert fired.rows() == [("card_transactions", "GQ-21", "info", 3)]


def test_fx3_reprocessing_the_partition_changes_nothing(bank):
    before = bank.tables()
    replay = ("gold-20260619T070000-00000003", "2026-06-19 07:00:00")
    bank.load(replay, partitions=["2026-06-18"])

    assert _counts(bank.log(replay)) == {
        "customers": (0, 0, 0, 0),
        "cards": (0, 0, 1, 0),
        "card_transactions": (0, 0, 1, 0),
        "balance_products": (0, 0, 1, 0),
    }
    for name in TABLES:  # lineage included: unchanged rows keep their batch
        assert_frame_equal(bank.table(name), before[name])
    assert bank.log(replay)["table_checksum"].to_list() == (
        bank.log(DELIVERY)["table_checksum"].to_list()
    )


def test_fx4_reprocessing_the_older_snapshot_keeps_the_block(bank):
    before = bank.tables()
    reload = ("gold-20260619T071000-00000004", "2026-06-19 07:10:00")
    bank.load(reload, partitions=["2026-06-17"])

    cards = bank.table("cards")
    assert cards.filter(pl.col("card_id") == CARD_7921)["status"].item() == "Blocked"
    for name in TABLES:
        assert_frame_equal(bank.table(name), before[name])
    assert _counts(bank.log(reload))["cards"] == (0, 0, 2, 0)


def test_fx5_unknown_status_rejects_the_load_and_quarantines_the_rows(bank):
    before = {name: (bank.gold / f"{name}.parquet").read_bytes() for name in TABLES}
    bad = bank.raw / "products/updates/year=2026/month=06/day=19/products_20260619.csv"
    bad.parent.mkdir(parents=True)
    bad.write_text(
        (bank.raw / DELTA_PRODUCTS)
        .read_text(encoding="utf-8")
        .replace(",Blocked,", ",Frozen,"),
        encoding="utf-8",
    )
    bank.ingest()
    rejected = ("gold-20260620T063000-00000005", "2026-06-20 06:30:00")
    bank.load(rejected, partitions=["2026-06-19"])

    log = bank.log(rejected)
    assert log["status"].unique().to_list() == ["rejected"]
    assert _counts(log)["cards"] == (0, 0, 0, 1)
    assert _counts(log)["balance_products"] == (0, 0, 0, 1)
    assert log["max_process_date"].unique().to_list() == [date(2026, 6, 18)]
    for name in TABLES:
        assert (bank.gold / f"{name}.parquet").read_bytes() == before[name]

    quarantine = bank.gold / "_quarantine" / rejected[0]
    cards = pl.read_parquet(quarantine / "cards.parquet")
    assert cards["card_id"].to_list() == [CARD_7921]
    assert cards["failed_checks"].to_list() == [["GQ-08"]]
    balance = pl.read_parquet(quarantine / "balance_products.parquet")
    assert balance["failed_checks"].to_list() == [["GQ-23"]]
