"""Build a small demo gold for running the agent locally (docs/decisions_log.md D-38).

Takes from the full gold (ml/data/03_primary/gold) every customer named in
docs/golden_conversations.md, plus a random sample of other customers stratified by
country and segment, with all their cards, card_transactions and balance_products.
The four tables keep the gold-0.2 schema (docs/contracts/gold_tables.md).
_load_log.parquet is copied unchanged: the backend uses it to find the gold folder and
the delivery date of each source file (freshness_policy.md section 4).

Output, both gitignored: ml/data/demo_gold/ and ml/data/demo_gold.zip. The zip is flat,
so it unzips straight into any GOLD_DIR. Prints the size and row counts of the full and
the demo gold.

Usage (ml venv, any working directory):
    python ml/scripts/make_demo_gold.py [--sample 200] [--seed 20261004]
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
import zipfile
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
FULL_GOLD = ROOT / "ml" / "data" / "03_primary" / "gold"
DEMO_GOLD = ROOT / "ml" / "data" / "demo_gold"
DEMO_ZIP = ROOT / "ml" / "data" / "demo_gold.zip"
GOLDEN_DOC = ROOT / "docs" / "golden_conversations.md"

TABLES = {
    "customers": "customer_id",
    "cards": "card_id",
    "card_transactions": "transaction_id",
    "balance_products": "product_id",
}
LOAD_LOG = "_load_log.parquet"
CUSTOMER_ID = re.compile(r"\bCLI-[A-Z0-9]{12}\b")


def say(line: str) -> None:
    print(line)  # noqa: T201


def golden_customers(doc: Path) -> list[str]:
    return sorted(set(CUSTOMER_ID.findall(doc.read_text(encoding="utf-8"))))


def allocate(
    strata: dict[tuple[str, str], int], total: int
) -> dict[tuple[str, str], int]:
    """Proportional allocation with largest remainders, so the sizes add up to ``total``."""
    population = sum(strata.values())
    exact = {key: total * size / population for key, size in strata.items()}
    sizes = {key: int(value) for key, value in exact.items()}
    missing = total - sum(sizes.values())
    for key in sorted(exact, key=lambda k: (-(exact[k] - sizes[k]), k))[:missing]:
        sizes[key] += 1
    return sizes


def sample_customers(
    con: duckdb.DuckDBPyConnection, exclude: set[str], total: int, seed: int
) -> list[str]:
    rows = con.execute(
        f"SELECT country, segment, customer_id FROM read_parquet('{FULL_GOLD / 'customers.parquet'}')"
    ).fetchall()
    strata: dict[tuple[str, str], list[str]] = {}
    for country, segment, customer_id in rows:
        if customer_id not in exclude:
            strata.setdefault((country, segment), []).append(customer_id)

    sizes = allocate({key: len(ids) for key, ids in strata.items()}, total)
    rng = random.Random(seed)
    sample: list[str] = []
    for key in sorted(strata):
        sample += rng.sample(sorted(strata[key]), sizes[key])
    return sample


def table_stats(
    con: duckdb.DuckDBPyConnection, folder: Path
) -> dict[str, tuple[int, int]]:
    """Rows and bytes of each table file."""
    stats = {}
    for table in TABLES:
        path = folder / f"{table}.parquet"
        rows = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
        stats[table] = (rows, path.stat().st_size)
    return stats


def schema(con: duckdb.DuckDBPyConnection, path: Path) -> list[tuple[str, str]]:
    return [
        (row[0], row[1])
        for row in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{path}')"
        ).fetchall()
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--sample",
        type=int,
        default=200,
        help="random customers besides the golden ones",
    )
    parser.add_argument("--seed", type=int, default=20261004)
    args = parser.parse_args(argv)

    if not (FULL_GOLD / LOAD_LOG).is_file():
        say(
            f"No full gold in {FULL_GOLD}. Run the gold pipeline first (kedro run --pipeline gold)."
        )
        return 1

    con = duckdb.connect()
    golden = golden_customers(GOLDEN_DOC)
    found = {
        row[0]
        for row in con.execute(
            f"SELECT customer_id FROM read_parquet('{FULL_GOLD / 'customers.parquet'}') WHERE customer_id IN "
            f"({', '.join('?' for _ in golden)})",
            golden,
        ).fetchall()
    }
    if missing := sorted(set(golden) - found):
        say(f"Golden customers missing from the full gold: {missing}")
        return 1

    selected = golden + sample_customers(con, set(golden), args.sample, args.seed)
    con.execute("CREATE TEMP TABLE selected (customer_id VARCHAR PRIMARY KEY)")
    con.executemany(
        "INSERT INTO selected VALUES (?)", [(customer_id,) for customer_id in selected]
    )

    if DEMO_GOLD.exists():
        shutil.rmtree(DEMO_GOLD)
    DEMO_GOLD.mkdir(parents=True)

    for table, key in TABLES.items():
        source, target = FULL_GOLD / f"{table}.parquet", DEMO_GOLD / f"{table}.parquet"
        con.execute(
            f"COPY (SELECT * FROM read_parquet('{source}') "
            f"WHERE customer_id IN (SELECT customer_id FROM selected) ORDER BY {key}) "
            f"TO '{target}' (FORMAT parquet, COMPRESSION zstd)"
        )
        if schema(con, source) != schema(con, target):
            say(f"Schema changed while copying {table}.")
            return 1
    shutil.copy2(FULL_GOLD / LOAD_LOG, DEMO_GOLD / LOAD_LOG)

    # Every transaction's card is in the demo cards (gold_tables.md: card_id is a foreign key to cards).
    orphans = con.execute(
        f"SELECT count(*) FROM read_parquet('{DEMO_GOLD / 'card_transactions.parquet'}') t "
        f"ANTI JOIN read_parquet('{DEMO_GOLD / 'cards.parquet'}') c USING (card_id)"
    ).fetchone()[0]
    if orphans:
        say(f"{orphans} demo transactions have no card in the demo cards.")
        return 1

    if DEMO_ZIP.exists():
        DEMO_ZIP.unlink()
    with zipfile.ZipFile(DEMO_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(DEMO_GOLD.iterdir()):
            archive.write(path, arcname=path.name)

    full, demo = table_stats(con, FULL_GOLD), table_stats(con, DEMO_GOLD)
    say(
        f"Demo gold: {len(golden)} golden customers + {args.sample} sampled by country and segment (seed {args.seed})."
    )
    say(
        f"{'table':<20}{'full rows':>12}{'full MB':>10}{'demo rows':>12}{'demo MB':>10}"
    )
    for table in TABLES:
        say(
            f"{table:<20}{full[table][0]:>12,}{full[table][1] / 1e6:>10.2f}{demo[table][0]:>12,}{demo[table][1] / 1e6:>10.2f}"
        )
    total_full = (
        sum(size for _, size in full.values()) + (FULL_GOLD / LOAD_LOG).stat().st_size
    )
    total_demo = (
        sum(size for _, size in demo.values()) + (DEMO_GOLD / LOAD_LOG).stat().st_size
    )
    say(
        f"{'total (with ' + LOAD_LOG + ')':<32}{total_full / 1e6:>10.2f}{'':>12}{total_demo / 1e6:>10.2f}"
    )
    say(
        f"{DEMO_ZIP.relative_to(ROOT).as_posix()}: {DEMO_ZIP.stat().st_size / 1e6:.2f} MB"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
