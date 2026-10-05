"""Gold run report: the last gold load compared with docs/contracts/gold_tables.md.

Reads the published gold tables and _load_log.parquet (written by
`kedro run --pipeline gold`) and compares every count the contract states with the
data: rows per table, value breakdowns, ranges and the GQ check results of the last
load. Ends with the known deviations from the contracts.

Outputs:
  docs/findings/gold_run.md       (committed report)
  data/08_reporting/gold_run.md   (copy of the report)

Run from ml/:  .venv/Scripts/python analysis/gold/gold_run_report.py [gold_dir]
gold_dir defaults to data/03_primary/gold.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
GOLD = Path(sys.argv[1]) if len(sys.argv) > 1 else ML / "data/03_primary/gold"
OUTPUTS = [REPO / "docs/findings/gold_run.md", ML / "data/08_reporting/gold_run.md"]
TABLES = ("customers", "cards", "card_transactions", "balance_products")

# Rows per table, gold-0.2 sections 2 to 4b.
CONTRACT_ROWS = {
    "customers": 150_000,
    "cards": 140_040,
    "card_transactions": 1_547_432,
    "balance_products": 220_305,
}

# (section, label, query returning one value, contract value as stated in gold-0.2)
BREAKDOWNS = [
    (
        "2",
        "country = México",
        "SELECT count(*) FROM customers WHERE country = 'México'",
        74_907,
    ),
    (
        "2",
        "country = Colombia",
        "SELECT count(*) FROM customers WHERE country = 'Colombia'",
        45_251,
    ),
    (
        "2",
        "country = Argentina",
        "SELECT count(*) FROM customers WHERE country = 'Argentina'",
        29_842,
    ),
    (
        "2",
        "segment = Basic",
        "SELECT count(*) FROM customers WHERE segment = 'Basic'",
        89_756,
    ),
    (
        "2",
        "segment = Plus",
        "SELECT count(*) FROM customers WHERE segment = 'Plus'",
        37_547,
    ),
    (
        "2",
        "segment = Premium",
        "SELECT count(*) FROM customers WHERE segment = 'Premium'",
        15_207,
    ),
    (
        "2",
        "segment = Student",
        "SELECT count(*) FROM customers WHERE segment = 'Student'",
        7_490,
    ),
    (
        "2",
        "customer_status = Active",
        "SELECT count(*) FROM customers WHERE customer_status = 'Active'",
        127_700,
    ),
    (
        "2",
        "customer_status = Inactive",
        "SELECT count(*) FROM customers WHERE customer_status = 'Inactive'",
        14_914,
    ),
    (
        "2",
        "customer_status = Suspended",
        "SELECT count(*) FROM customers WHERE customer_status = 'Suspended'",
        4_407,
    ),
    (
        "2",
        "customer_status = Closed",
        "SELECT count(*) FROM customers WHERE customer_status = 'Closed'",
        2_979,
    ),
    (
        "2",
        "Suspended or Closed customers holding a card",
        "SELECT count(DISTINCT c.customer_id) FROM customers c JOIN cards k USING (customer_id) "
        "WHERE c.customer_status IN ('Suspended', 'Closed')",
        4_410,
    ),
    (
        "2",
        "Customers without cards (persona S4)",
        "SELECT count(*) FROM customers WHERE customer_id NOT IN (SELECT customer_id FROM cards)",
        58_916,
    ),
    (
        "3",
        "product_type = Tarjeta Crédito",
        "SELECT count(*) FROM cards WHERE product_type = 'Tarjeta Crédito'",
        100_102,
    ),
    (
        "3",
        "product_type = Tarjeta Débito",
        "SELECT count(*) FROM cards WHERE product_type = 'Tarjeta Débito'",
        39_938,
    ),
    (
        "3",
        "status = Active",
        "SELECT count(*) FROM cards WHERE status = 'Active'",
        118_839,
    ),
    (
        "3",
        "status = Blocked",
        "SELECT count(*) FROM cards WHERE status = 'Blocked'",
        7_044,
    ),
    (
        "3",
        "status = Suspended",
        "SELECT count(*) FROM cards WHERE status = 'Suspended'",
        2_860,
    ),
    (
        "3",
        "status = Closed",
        "SELECT count(*) FROM cards WHERE status = 'Closed'",
        11_297,
    ),
    (
        "3",
        "expiration_date null",
        "SELECT count(*) FROM cards WHERE expiration_date IS NULL",
        6_879,
    ),
    (
        "3",
        "opening_date min",
        "SELECT CAST(min(opening_date) AS VARCHAR) FROM cards",
        "2018-06-18",
    ),
    (
        "3",
        "opening_date max",
        "SELECT CAST(max(opening_date) AS VARCHAR) FROM cards",
        "2026-06-17",
    ),
    (
        "4",
        "transaction_type = Purchase",
        "SELECT count(*) FROM card_transactions WHERE transaction_type = 'Purchase'",
        1_083_406,
    ),
    (
        "4",
        "transaction_type = Withdrawal",
        "SELECT count(*) FROM card_transactions WHERE transaction_type = 'Withdrawal'",
        232_392,
    ),
    (
        "4",
        "transaction_type = Payment",
        "SELECT count(*) FROM card_transactions WHERE transaction_type = 'Payment'",
        231_634,
    ),
    (
        "4",
        "status = Approved",
        "SELECT count(*) FROM card_transactions WHERE status = 'Approved'",
        1_423_048,
    ),
    (
        "4",
        "status = Declined",
        "SELECT count(*) FROM card_transactions WHERE status = 'Declined'",
        77_714,
    ),
    (
        "4",
        "status = Pending",
        "SELECT count(*) FROM card_transactions WHERE status = 'Pending'",
        30_885,
    ),
    (
        "4",
        "status = Reversed",
        "SELECT count(*) FROM card_transactions WHERE status = 'Reversed'",
        15_785,
    ),
    (
        "4",
        "response_code null",
        "SELECT count(*) FROM card_transactions WHERE response_code IS NULL",
        77_134,
    ),
    (
        "4",
        "Purchases with null merchant_name",
        "SELECT count(*) FROM card_transactions WHERE transaction_type = 'Purchase' AND merchant_name IS NULL",
        54_172,
    ),
    (
        "4",
        "currency = MXN",
        "SELECT count(*) FROM card_transactions WHERE currency = 'MXN'",
        0,
    ),
    (
        "4",
        "transaction_datetime min",
        "SELECT strftime(min(transaction_datetime), '%Y-%m-%d %H:%M') FROM card_transactions",
        "2023-06-17 06:03",
    ),
    (
        "4",
        "transaction_datetime max",
        "SELECT strftime(max(transaction_datetime), '%Y-%m-%d %H:%M') FROM card_transactions",
        "2026-06-18 05:57",
    ),
    (
        "4",
        "process_date min",
        "SELECT CAST(min(process_date) AS VARCHAR) FROM card_transactions",
        "2023-06-17",
    ),
    (
        "4",
        "process_date max",
        "SELECT CAST(max(process_date) AS VARCHAR) FROM card_transactions",
        "2026-06-17",
    ),
    (
        "5",
        "Card transactions on 2026-06-18 before 06:00 (partition 2026-06-17)",
        "SELECT count(*) FROM card_transactions WHERE transaction_datetime >= TIMESTAMP '2026-06-18'",
        465,
    ),
    (
        "4b",
        "kind = credit_card",
        "SELECT count(*) FROM balance_products WHERE kind = 'credit_card'",
        100_102,
    ),
    (
        "4b",
        "kind = savings_account",
        "SELECT count(*) FROM balance_products WHERE kind = 'savings_account'",
        120_203,
    ),
    *[
        (
            "4b",
            f"{kind}, status = {status}",
            f"SELECT count(*) FROM balance_products WHERE kind = '{kind}' AND status = '{status}'",
            expected,
        )
        for kind, status, expected in [
            ("credit_card", "Active", 85_090),
            ("credit_card", "Blocked", 4_932),
            ("credit_card", "Suspended", 2_027),
            ("credit_card", "Closed", 8_053),
            ("savings_account", "Active", 102_148),
            ("savings_account", "Blocked", 5_923),
            ("savings_account", "Suspended", 2_416),
            ("savings_account", "Closed", 9_716),
        ]
    ],
    (
        "4b",
        "Not Closed (eligible)",
        "SELECT count(*) FROM balance_products WHERE status <> 'Closed'",
        202_536,
    ),
    (
        "4b",
        "Customers holding an eligible product",
        "SELECT count(DISTINCT customer_id) FROM balance_products WHERE status <> 'Closed'",
        111_200,
    ),
    (
        "4b",
        "Credit cards with null credit_limit",
        "SELECT count(*) FROM balance_products WHERE kind = 'credit_card' AND credit_limit IS NULL",
        5_059,
    ),
    (
        "4b",
        "Max current_balance, credit cards",
        "SELECT CAST(max(current_balance) AS VARCHAR) FROM balance_products WHERE kind = 'credit_card'",
        "18392153.91",
    ),
    (
        "4b",
        "Max current_balance, savings accounts",
        "SELECT CAST(max(current_balance) AS VARCHAR) FROM balance_products WHERE kind = 'savings_account'",
        "59614477.73",
    ),
    (
        "4b",
        "currency = MXN",
        "SELECT count(*) FROM balance_products WHERE currency = 'MXN'",
        0,
    ),
]

# "Today" column of gold-0.2 section 5, per (check, level).
CONTRACT_CHECKS = {
    ("GQ-10", "warn"): "8,681 cards",
    ("GQ-11", "warn"): "6 customers",
    ("GQ-19", "warn"): "99.999% agree",
    ("GQ-21", "info"): "18.65% before opening, 29.88% after expiration",
    ("GQ-22", "fail"): "n/a on first load",
    ("GQ-26", "warn"): "5,059 credit cards",
    ("GQ-27", "warn"): "1,203",
    ("GQ-29", "warn"): "16 customers",
}

# Shares of all card transactions; a card without expiration_date counts as "not after".
GQ21_SPLIT = """
SELECT
    avg(CAST(CAST(t.transaction_datetime AS DATE) < k.opening_date AS INTEGER)) AS before_opening,
    avg(coalesce(CAST(CAST(t.transaction_datetime AS DATE) > k.expiration_date AS INTEGER), 0))
        AS after_expiration
FROM card_transactions t JOIN cards k USING (card_id)
"""

DEVIATIONS = """\
## Known deviations

These are places where the implementation differs from, or fills a gap in,
`gold-0.2` and `fresh-0.2`. The contracts are frozen and were not edited.

1. **Source layer is `02_intermediate`, not `03_primary`.** The contract's lineage
   (section 1) has gold reading `03_primary/{customers,products,transactions}`,
   produced by a `data_quality` pipeline that does not exist yet. Gold reads
   `02_intermediate` directly. The C1 dedup rule (later delivery, then later
   `source_file`) is applied while staging, so the result is the same while C1 finds
   0 duplicates. Lineage in gold is unaffected: `source_file` is the raw file in both
   layers.
2. **The load log has 4 rows per load, not 3.** `fresh-0.2` section 6.3 lists
   `customers`, `cards` and `card_transactions` only. `gold-0.2` added
   `balance_products`, and section 4 asks for one row per table, so every load writes
   4 rows. In the fixture, the 2026-06-18 delivery updates card 7921's
   `balance_products` row as well (`0 / 1 / 0 / 0`), because both rows come from the
   same product row and GQ-28 requires them to agree.
3. **`gold_loaded_at` is the batch start time.** The contract says "when that load
   finished". Every row of a batch gets the same value, fixed when the batch starts,
   a few seconds before it finishes; `finished_at` in the load log has the real end.
   The mock bank's `as_of` is therefore slightly early, never late.
4. **Counts of a rejected load.** For a rejected load, every incoming row counts as
   `rows_rejected` and inserted / updated / unchanged are 0. The rows that caused the
   rejection are in `_quarantine/<batch_id>/<table>.parquet` with the IDs of the
   checks they failed. The quarantine location is not in the contract.
5. **Incoming rows are counted after dedup within the delivery** (one per key).
6. **FX-2 is not implemented.** Step 1 of `fresh-0.2` section 3 (skip a file whose
   path and SHA-256 were already published) is a shortcut; the content comparison
   already makes a replay a no-op (FX-3). Input checksums are recorded in the load log.
   FX-6 and FX-7 test the backend overlay and belong to the backend.
7. **GQ-23's "kind matches product_type"** holds by construction (one mapping
   produces `kind`) and is not checked separately. **GQ-21** is one count (rows before
   opening or after expiration); the split is reported above.
8. **Delta files are not ingested by `data_ingestion` yet.** Its parameters read the
   supplied snapshots only. The fixture test ingests `products/updates/**` and
   `customers/updates/**` (assumption A1) with the same query builder.
9. **HMAC convention.** `card_number_hmac` = HMAC-SHA256 with the UTF-8 bytes of
   `CARD_HASH_KEY` as key and the UTF-8 bytes of the 16-digit `product_number` as
   message, lowercase hex. The backend's ownership check must compute it the same way.
"""


def _display(path: Path) -> str:
    """The path from its ``ml/`` folder on, so any checkout of the repo reads the same."""
    parts = path.resolve().parts
    if "ml" not in parts:
        return path.as_posix()
    start = len(parts) - 1 - parts[::-1].index("ml")
    return "/".join(parts[start:])


def _fmt(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else str(value)


def main() -> None:
    con = duckdb.connect()
    for name in TABLES:
        con.execute(
            f"CREATE VIEW {name} AS SELECT * FROM read_parquet('{(GOLD / name).as_posix()}.parquet')"
        )
    con.execute(
        f"CREATE VIEW load_log AS SELECT * FROM read_parquet('{(GOLD / '_load_log').as_posix()}.parquet')"
    )
    batch_id, status, started, finished, n_files, max_date = con.execute(
        "SELECT gold_batch_id, status, min(started_at), max(finished_at), "
        "len(any_value(input_files)), any_value(max_process_date) FROM load_log "
        "GROUP BY gold_batch_id, status ORDER BY max(finished_at) DESC LIMIT 1"
    ).fetchone()
    n_loads = con.execute(
        "SELECT count(DISTINCT gold_batch_id) FROM load_log"
    ).fetchone()[0]

    lines = [
        "# Gold run report",
        "",
        "| Field | Value |",
        "|---|---|",
        "| Contract | `docs/contracts/gold_tables.md` (`gold-0.2`), "
        "`docs/contracts/freshness_policy.md` (`fresh-0.2`) |",
        f"| Last load | `{batch_id}`, status **{status}**, {started} to {finished} |",
        f"| Input files | {n_files:,} (partitions up to {max_date}) |",
        f"| Loads in the log | {n_loads} |",
        f"| Gold directory | `{_display(GOLD)}` |",
        "| Generated by | `ml/analysis/gold/gold_run_report.py` |",
        "",
        "## Rows per table",
        "",
        "| Table | Rows in gold | Contract | Inserted | Updated | Unchanged | Rejected | Match |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in TABLES:
        rows = con.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
        ins, upd, unch, rej = con.execute(
            "SELECT rows_inserted, rows_updated, rows_unchanged, rows_rejected FROM load_log "
            'WHERE gold_batch_id = ? AND "table" = ?',
            [batch_id, name],
        ).fetchone()
        ok = "yes" if rows == CONTRACT_ROWS[name] else "**no**"
        lines.append(
            f"| `{name}` | {rows:,} | {CONTRACT_ROWS[name]:,} | {ins:,} | {upd:,} | {unch:,} | {rej:,} | {ok} |"
        )

    lines += [
        "",
        "## Breakdowns stated in the contract",
        "",
        "| Section | Value | Gold | Contract | Match |",
        "|---|---|---:|---:|---|",
    ]
    mismatches = 0
    for section, label, query, expected in BREAKDOWNS:
        actual = con.execute(query).fetchone()[0]
        ok = actual == expected
        mismatches += not ok
        lines.append(
            f"| {section} | {label} | {_fmt(actual)} | {_fmt(expected)} | {'yes' if ok else '**no**'} |"
        )
    lines += ["", f"{len(BREAKDOWNS) - mismatches} of {len(BREAKDOWNS)} match."]

    checks = con.execute(
        'SELECT "table", c.id, c.level, c.violations FROM load_log, '
        'unnest(checks) AS u(c) WHERE gold_batch_id = ? ORDER BY c.id, c.level, "table"',
        [batch_id],
    ).fetchall()
    failed = sum(v for _, _, level, v in checks if level == "fail")
    before, after = con.execute(GQ21_SPLIT).fetchone()
    lines += [
        "",
        "## Quality checks (last load)",
        "",
        f"Fail-level violations: **{failed}**. Warn- and info-level counts are below;"
        " checks with 0 violations on every table are omitted.",
        "",
        "| Check | Level | Table | Violations | Contract (Today) |",
        "|---|---|---|---:|---|",
    ]
    for table, check_id, level, violations in checks:
        stated = (check_id, level) in CONTRACT_CHECKS and check_id != "GQ-22"
        if violations or stated:
            note = CONTRACT_CHECKS.get((check_id, level), "0")
            lines.append(
                f"| {check_id} | {level} | `{table}` | {violations:,} | {note} |"
            )
    gq19 = next(v for _, check_id, _, v in checks if check_id == "GQ-19")
    gq22 = sum(v for _, check_id, _, v in checks if check_id == "GQ-22")
    n_transactions = con.execute("SELECT count(*) FROM card_transactions").fetchone()[0]
    lines += [
        "",
        f"GQ-19: {gq19:,} of {n_transactions:,} card transactions disagree "
        f"({1 - gq19 / n_transactions:.3%} agree). "
        f"GQ-21 split: {before:.2%} before opening, {after:.2%} after expiration. "
        f"GQ-22: {gq22} rows lost or created over the four tables.",
        "",
        "## Incremental fixture",
        "",
        "`ml/tests/pipelines/gold/test_incremental_update.py` runs the gold pipeline on the "
        "labeled fixture `ml/tests/fixtures/update/` (`fresh-0.2` section 6) and passes "
        "FX-1 (expected state of section 6.3, compared with hand-written CSVs), FX-3 "
        "(reprocessing 2026-06-18 changes nothing), FX-4 (the older snapshot does not undo "
        "the block) and FX-5 (an unknown status rejects the load, leaves gold "
        "byte-identical and quarantines the card and balance-product rows). "
        "`ml/tests/pipelines/gold/test_checks.py` breaks each of the 16 fail-level checks "
        "on one row and asserts it fires, quarantines the row and rejects the load.",
        "",
        DEVIATIONS,
    ]
    report = "\n".join(lines)
    for path in OUTPUTS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")
    print(report)  # noqa: T201 (CLI script)


if __name__ == "__main__":
    main()
