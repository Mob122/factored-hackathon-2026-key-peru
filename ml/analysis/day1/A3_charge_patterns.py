"""A3 - do preauthorizations, foreign currency and double charges exist?

Scope: transaction_type 'Purchase' on 'Tarjeta Crédito' or 'Tarjeta Débito'
products. Prevalence = flagged card purchases / all card purchases (rows, exact
duplicates included). Track A decision rule: a cause counts if it reaches
>= 1% prevalence.

Causes (SQL in banking_cs.detectors.card_charges, fixtures in
tests/detectors/test_card_charges.py):
  (1) preauthorization: Pending purchase later Reversed or settled (Approved) on
      the same product and merchant; horizon 7 days (1 and 30 days as
      sensitivity). The Pending row is the flagged row.
  (2) foreign currency: purchase currency differs from the customer's local
      currency (Argentina ARS, Colombia COP, México MXN).
  (3) repeat charge: same product, merchant and amount within 10 minutes, split
      into exact pipeline duplicates (identical rows) vs distinct transaction_ids.
  (4) habitual merchant: the customer has >= 3 earlier card purchases at that
      merchant.

Baselines (5 seeds each):
  - shuffled timestamps: transaction_date permuted within each product, for all
    four causes, as requested. (2) does not use time and (4) only counts earlier
    rows per customer and merchant, which is invariant to reordering, so the
    shuffle cannot move them; they also get
  - a shuffled column: currency (2) or merchant_name (4) permuted across all card
    purchases, i.e. what the generator would produce with no link between
    customer and currency / merchant.

Outputs:
  docs/findings/day1/A3.md                 (committed report)
  data/08_reporting/day1/A3.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (A3 line)

Run from ml/:  .venv/Scripts/python analysis/day1/A3_charge_patterns.py
"""

from __future__ import annotations

import math
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import duckdb

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
sys.path.insert(0, str(ML / "src"))

from banking_cs.detectors.card_charges import (  # noqa: E402
    CARD_PRODUCT_TYPES,
    LOCAL_CURRENCY,
    PURCHASE_TYPE,
    TRANSACTION_COLUMNS,
    build_card_purchases_query,
    build_foreign_currency_query,
    build_habitual_merchant_query,
    build_preauthorization_query,
    build_repeat_charge_query,
    build_shuffled_column_query,
)

INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

THRESHOLD = 0.01  # track A decision rule
DAY = 24 * 60
PREAUTH_HORIZON = 7 * DAY  # minutes; primary
PREAUTH_SENSITIVITY = [1 * DAY, 30 * DAY]
REPEAT_WINDOW = 10  # minutes; primary
REPEAT_SENSITIVITY = [60]
MIN_PRIOR = 3
SEEDS = [1, 2, 3, 4, 5]
Z_SIGNAL = 3.0  # z above baseline needed to call a pattern a real excess
SAMPLE_ROWS = 4

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.2f}%"


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def ci95(k: int, n: int) -> str:
    """Wilson 95% interval for a proportion."""
    if n == 0:
        return "n/a"
    p, z = k / n, 1.96
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return f"[{100 * (mid - half):.2f}, {100 * (mid + half):.2f}]"


def compare(k: int, base: list[int], n: int) -> dict:
    """Real count vs baseline counts: mean, range, ratio and a binomial z."""
    mean = statistics.fmean(base)
    p0 = mean / n
    var = max(n * p0 * (1 - p0), statistics.pvariance(base) if len(base) > 1 else 0, 1.0)
    z = (k - mean) / math.sqrt(var)
    # One-sided: a generated pattern shows up as an excess over chance, never a deficit
    return {
        "mean": mean,
        "lo": min(base),
        "hi": max(base),
        "ratio": k / mean if mean else float("inf") if k else 1.0,
        "z": z,
        "signal": k > max(base) and z >= Z_SIGNAL,
    }


def fmt_ratio(r: float) -> str:
    return "inf" if math.isinf(r) else f"{r:.2f}x"


def time_counts(con: duckdb.DuckDBPyConnection, table: str) -> dict[str, int]:
    """Counts for every time-dependent flag on `table` (real or shuffled)."""
    out: dict[str, int] = {}
    for h in [PREAUTH_HORIZON, *PREAUTH_SENSITIVITY]:
        r = con.sql(
            f"""
            select count(*) filter (where is_preauth),
                   count(*) filter (where preauth_reversed),
                   count(*) filter (where preauth_settled),
                   count(*) filter (where preauth_same_amount),
                   count(*) filter (where is_preauth_followup)
            from ({build_preauthorization_query(table, h)})
            """
        ).fetchone()
        for name, v in zip(
            ["preauth", "preauth_reversed", "preauth_settled", "preauth_same_amount",
             "preauth_followup"], r
        ):
            out[f"{name}_{h}"] = v
    for w in [REPEAT_WINDOW, *REPEAT_SENSITIVITY]:
        r = con.sql(
            f"""
            select count(*) filter (where is_exact_duplicate),
                   count(*) filter (where is_repeat_charge)
            from ({build_repeat_charge_query(table, w)})
            """
        ).fetchone()
        out["exact_duplicate"], out[f"repeat_{w}"] = r
    out["habitual"] = con.sql(
        f"select count(*) filter (where is_habitual_merchant) "
        f"from ({build_habitual_merchant_query(table, MIN_PRIOR)})"
    ).fetchone()[0]
    out["foreign"] = con.sql(
        f"select count(*) filter (where is_foreign_currency) "
        f"from ({build_foreign_currency_query(table)})"
    ).fetchone()[0]
    return out


def main() -> None:
    con = duckdb.connect()
    for name in ["transactions", "products", "customers"]:
        con.sql(
            f"create view {name} as select * from "
            f"'{(INTER / f'{name}.parquet').as_posix()}'"
        )
    md: list[str] = []
    md.append("# A3 - Preauthorizations, foreign currency and double charges\n")

    # ------------------------------------------------------------ (a) values
    log("(a) distinct values and scope")
    type_mix = con.sql(
        """
        select p.product_type, t.transaction_type, count(*) n
        from transactions t join products p using (product_id)
        group by all order by 1, 2
        """
    ).fetchall()
    n_tx = con.sql("select count(*) from transactions").fetchone()[0]
    con.sql(
        "create temp table src as "
        + build_card_purchases_query("transactions", "products", "customers")
    )
    n = con.sql("select count(*) from src").fetchone()[0]
    n_purchase = con.sql(
        f"select count(*) from transactions where transaction_type = '{PURCHASE_TYPE}'"
    ).fetchone()[0]
    status = con.sql(
        "select transaction_status, count(*) from src group by 1 order by 2 desc"
    ).fetchall()
    country_cur = con.sql(
        """
        select customer_country, currency, count(*) from src
        group by all order by 1, 2
        """
    ).fetchall()
    merchants = con.sql(
        "select merchant_name, count(*) from src group by 1 order by 2 desc"
    ).fetchall()
    per_product = con.sql(
        """
        select count(distinct product_id), count(distinct customer_id),
               count(*) / count(distinct product_id),
               min(transaction_date), max(transaction_date)
        from src
        """
    ).fetchone()
    log(f"card purchases={n:,} of {n_tx:,} transactions")

    # ------------------------------------------ (b) raw duplicates and nulls
    cols = ", ".join(TRANSACTION_COLUMNS)
    raw = con.sql(
        f"""
        select count(*), count(distinct transaction_id),
               (select count(*) - count(distinct ({cols})) from src),
               count(*) filter (where merchant_name is null),
               count(*) filter (where amount is null),
               count(*) filter (where transaction_date is null),
               count(*) filter (where customer_country is null)
        from src
        """
    ).fetchone()
    cur_vs_product = con.sql(
        """
        select count(*) filter (where s.currency <> p.currency)
        from src s join products p using (product_id)
        """
    ).fetchone()[0]

    md.append(
        f"Generated by `ml/analysis/day1/A3_charge_patterns.py` on "
        f"{date.today().isoformat()} over `ml/data/02_intermediate/`. Scope: "
        f"`transaction_type = '{PURCHASE_TYPE}'` on products with `product_type` in "
        f"{', '.join(f'`{t}`' for t in CARD_PRODUCT_TYPES)}: **{n:,} card purchases** "
        f"({pct(n / n_tx)} of {n_tx:,} transactions; {n_purchase:,} purchases in total, "
        f"so every purchase is on a card). {per_product[0]:,} card products, "
        f"{per_product[1]:,} customers, {per_product[2]:.1f} purchases per product over "
        f"{per_product[3]:%Y-%m-%d} to {per_product[4]:%Y-%m-%d}. Prevalence = flagged "
        f"purchases / {n:,}. Detector SQL: `ml/src/banking_cs/detectors/card_charges.py`; "
        f"fixtures: `ml/tests/detectors/test_card_charges.py`.\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "Card purchases contain benign patterns that customers report as unrecognized "
        "charges: preauthorizations, foreign-currency charges and double charges, plus "
        "purchases at habitual merchants (a reason a charge should be recognized). "
        f"**Decision rule for Track A:** a cause is usable if it reaches >= "
        f"{pct(THRESHOLD)} of card purchases. 'Si falla': the detectors ship with "
        "declared fixtures instead of data-backed prevalence.\n"
    )
    verdict_idx = len(md)

    # ------------------------------------------------------- real detectors
    log("real detectors")
    real = time_counts(con, "src")
    log(f"  {real}")

    # --------------------------------------------------------- baselines
    base_time: list[dict[str, int]] = []
    for s in SEEDS:
        con.sql(
            "create or replace temp table shuf as "
            + build_shuffled_column_query("src", s, "transaction_date", "product_id")
        )
        base_time.append(time_counts(con, "shuf"))
        log(f"  time shuffle seed {s}: {base_time[-1]}")
    base_col: dict[str, list[int]] = {"habitual": [], "foreign": []}
    for s in SEEDS:
        q = build_shuffled_column_query("src", s, "merchant_name", None)
        base_col["habitual"].append(
            con.sql(
                f"select count(*) filter (where is_habitual_merchant) from "
                f"({build_habitual_merchant_query(f'({q})', MIN_PRIOR)})"
            ).fetchone()[0]
        )
        q = build_shuffled_column_query("src", s, "currency", None)
        base_col["foreign"].append(
            con.sql(
                f"select count(*) filter (where is_foreign_currency) from "
                f"({build_foreign_currency_query(f'({q})')})"
            ).fetchone()[0]
        )
    log(f"  column shuffles: {base_col}")

    def bt(key: str) -> list[int]:
        return [b[key] for b in base_time]

    # ------------------------------------------------------------ summary
    causes = [
        ("(1) preauthorization (Pending -> Reversed/Approved, 7 d)",
         f"preauth_{PREAUTH_HORIZON}", "time"),
        ("(2) foreign currency (vs customer's local currency)", "foreign", "column"),
        ("(3a) exact pipeline duplicate", "exact_duplicate", "time"),
        (f"(3b) repeat charge, distinct transaction_id, {REPEAT_WINDOW} min",
         f"repeat_{REPEAT_WINDOW}", "time"),
        (f"(4) habitual merchant (>= {MIN_PRIOR} prior purchases)", "habitual", "column"),
    ]
    summary_rows = []
    results = {}
    for label, key, alt in causes:
        k = real[key]
        ct = compare(k, bt(key), n)
        cc = compare(k, base_col[key], n) if alt == "column" else None
        # The meaningful null for (2) and (4) is the column shuffle
        ref = cc or ct
        results[key] = (k, ct, cc, ref)
        summary_rows.append([
            label, f"{k:,}", f"{pct(k / n)} {ci95(k, n)}",
            f"{pct(ct['mean'] / n)} ({fmt_ratio(ct['ratio'])})",
            f"{pct(cc['mean'] / n)} ({fmt_ratio(cc['ratio'])})" if cc else "-",
            "**yes**" if k / n >= THRESHOLD else "no",
            f"{'yes' if ref['signal'] else 'no'} (z = {ref['z']:+.1f})",
        ])

    md.append("## Summary\n")
    md.append(
        md_table(
            ["cause", "flagged", "prevalence (95% CI)",
             "shuffled timestamps (real/base)", "shuffled column (real/base)",
             f">= {pct(THRESHOLD)}", "above baseline"],
            summary_rows,
        )
        + "\n"
    )
    md.append(
        f"Baselines are the mean of {len(SEEDS)} seeds. 'Shuffled timestamps' permutes "
        "`transaction_date` within each product (every product keeps its own set of "
        "timestamps). 'Shuffled column' permutes `currency` (2) or `merchant_name` (4) "
        "across all card purchases; it is the reference for (2) and (4), because (2) does "
        "not depend on time and (4) only counts earlier rows per customer and merchant, "
        "which no reordering changes. Above baseline = real count above every seed "
        f"and z >= {Z_SIGNAL:.0f} (binomial z at the baseline rate); one-sided, since a "
        "generated pattern shows up as an excess over chance.\n"
    )

    # ------------------------------------------------------ distinct values
    md.append("## (a) Scope and distinct values\n")
    md.append("`product_type` x `transaction_type` over all transactions:\n")
    md.append(
        md_table(["product_type", "transaction_type", "n"],
                 [[a, b, f"{c:,}"] for a, b, c in type_mix]) + "\n"
    )
    md.append(
        "Transaction types follow the product: purchases only occur on cards, and cards "
        "only carry Purchase, Payment and Withdrawal.\n"
    )
    md.append("`transaction_status` in scope:\n")
    md.append(
        md_table(["transaction_status", "n", "share"],
                 [[s, f"{c:,}", pct(c / n)] for s, c in status]) + "\n"
    )
    md.append("Customer country x purchase currency in scope:\n")
    md.append(
        md_table(["customer_country", "currency", "n", "local currency"],
                 [[a, b, f"{c:,}", LOCAL_CURRENCY.get(a, "*unmapped*")]
                  for a, b, c in country_cur]) + "\n"
    )
    md.append(
        "`merchant_name` in scope: "
        + ", ".join(f"{m if m is not None else '*null*'} ({c:,})" for m, c in merchants)
        + ".\n"
    )

    md.append("## (b) Raw duplicates and nulls (before any deduplication)\n")
    md.append(
        md_table(
            ["check", "n", "share"],
            [
                ["card purchase rows", f"{raw[0]:,}", "100%"],
                ["distinct transaction_id", f"{raw[1]:,}", pct(raw[1] / raw[0])],
                ["exact duplicate rows (all raw columns equal)", f"{raw[2]:,}",
                 pct(raw[2] / raw[0])],
                ["merchant_name null", f"{raw[3]:,}", pct(raw[3] / raw[0])],
                ["amount null", f"{raw[4]:,}", pct(raw[4] / raw[0])],
                ["transaction_date null", f"{raw[5]:,}", pct(raw[5] / raw[0])],
                ["customer country null", f"{raw[6]:,}", pct(raw[6] / raw[0])],
                ["currency differs from the card product's currency",
                 f"{cur_vs_product:,}", pct(cur_vs_product / raw[0])],
            ],
        )
        + "\n"
    )
    md.append(
        "Rows with null merchant cannot match (1), (3b) or (4) and are never flagged; "
        "they stay in the denominator.\n"
    )

    # ------------------------------------------------------ (1) preauth
    log("(1) details")
    n_pending = dict(status).get("Pending", 0)
    md.append("## (1) Preauthorization\n")
    md.append(
        f"Flagged row = the Pending purchase. {n_pending:,} card purchases are Pending "
        f"({pct(n_pending / n)}), so {pct(n_pending / n)} is the ceiling for this cause.\n"
    )
    rows = []
    for h in [PREAUTH_HORIZON, *PREAUTH_SENSITIVITY]:
        k = real[f"preauth_{h}"]
        c = compare(k, bt(f"preauth_{h}"), n)
        rows.append([
            f"{h // DAY} d" + (" (primary)" if h == PREAUTH_HORIZON else ""),
            f"{k:,}", pct(k / n), pct(k / n_pending) if n_pending else "n/a",
            f"{c['mean']:,.0f} [{c['lo']:,}, {c['hi']:,}]", fmt_ratio(c["ratio"]),
            f"{c['z']:+.1f}",
        ])
    md.append(
        md_table(
            ["horizon", "flagged", "of card purchases", "of Pending",
             "shuffled mean [min, max]", "real/base", "z"],
            rows,
        )
        + "\n"
    )
    h = PREAUTH_HORIZON
    md.append(
        md_table(
            ["7-day breakdown", "real", "shuffled mean"],
            [
                [lbl, f"{real[f'{key}_{h}']:,}",
                 f"{statistics.fmean(bt(f'{key}_{h}')):,.0f}"]
                for lbl, key in [
                    ("Pending with a later Reversed", "preauth_reversed"),
                    ("Pending with a later Approved (settled)", "preauth_settled"),
                    ("Pending with a match of the same amount", "preauth_same_amount"),
                    ("Reversed/Approved rows that close a Pending", "preauth_followup"),
                ]
            ],
        )
        + "\n"
    )
    samp = con.sql(
        f"""
        select s.transaction_id, s.transaction_date, s.product_id, s.merchant_name,
               s.amount, d.preauth_reversed, d.preauth_settled
        from src s join ({build_preauthorization_query('src', h)}) d using (row_key)
        where d.is_preauth order by s.row_key limit {SAMPLE_ROWS}
        """
    ).fetchall()
    if samp:
        md.append(
            md_table(["transaction_id", "transaction_date", "product_id", "merchant",
                      "amount", "reversed later", "settled later"],
                     [list(r) for r in samp]) + "\n"
        )

    # ------------------------------------------------------ (2) currency
    log("(2) details")
    md.append("## (2) Foreign currency\n")
    by_country = con.sql(
        f"""
        select s.customer_country, d.local_currency, count(*),
               count(*) filter (where d.is_foreign_currency)
        from src s join ({build_foreign_currency_query('src')}) d using (row_key)
        group by all order by 1
        """
    ).fetchall()
    md.append(
        md_table(
            ["customer_country", "local currency", "card purchases", "foreign",
             "share"],
            [[a, b, f"{c:,}", f"{d:,}", pct(d / c)] for a, b, c, d in by_country],
        )
        + "\n"
    )
    mx = next((r for r in by_country if r[0] == "México"), None)
    k_f = real["foreign"]
    no_mx = k_f - (mx[3] if mx else 0)
    n_no_mx = n - (mx[2] if mx else 0)
    ct = compare(k_f, bt("foreign"), n)
    cc = compare(k_f, base_col["foreign"], n)
    md.append(
        f"- MXN never appears, so every Mexican purchase is 'foreign' by construction "
        f"({pct(mx[3] / mx[2]) if mx else 'n/a'}). Excluding México: {no_mx:,} of "
        f"{n_no_mx:,} ({pct(no_mx / n_no_mx) if n_no_mx else 'n/a'}).\n"
        f"- The purchase currency differs from the card product's currency in "
        f"{cur_vs_product:,} rows: a 'foreign' purchase is a USD-denominated card, a "
        f"product attribute, not a per-purchase event (no FX conversion ever happens "
        f"on a charge).\n"
        f"- Baselines: shuffled timestamps {pct(ct['mean'] / n)} (identical by "
        f"construction); currency permuted across purchases {pct(cc['mean'] / n)} "
        f"(real/base {fmt_ratio(cc['ratio'])}, z = {cc['z']:+.1f}). The real rate is "
        f"{'above' if cc['signal'] else 'below'} independence: Argentine and Colombian "
        f"cards are mostly in local currency, and the headline rate is México's "
        f"USD-only cards.\n"
    )

    # ------------------------------------------------------ (3) repeat charges
    log("(3) details")
    md.append("## (3) Same product, merchant and amount within minutes\n")
    rows = []
    for key, lbl in [("exact_duplicate", "(3a) exact duplicate rows")] + [
        (f"repeat_{w}", f"(3b) distinct transaction_id, {w} min"
         + (" (primary)" if w == REPEAT_WINDOW else ""))
        for w in [REPEAT_WINDOW, *REPEAT_SENSITIVITY]
    ]:
        k = real[key]
        c = compare(k, bt(key), n)
        rows.append([lbl, f"{k:,}", f"{pct(k / n)} {ci95(k, n)}",
                     f"{c['mean']:,.1f} [{c['lo']:,}, {c['hi']:,}]",
                     fmt_ratio(c["ratio"]), f"{c['z']:+.1f}"])
    md.append(
        md_table(["pattern", "flagged", "prevalence (95% CI)",
                  "shuffled mean [min, max]", "real/base", "z"], rows) + "\n"
    )
    rep_status = con.sql(
        f"""
        select s.transaction_status, count(*)
        from src s join ({build_repeat_charge_query('src', REPEAT_WINDOW)}) d
          using (row_key)
        where d.is_repeat_charge group by 1 order by 2 desc
        """
    ).fetchall()
    if rep_status:
        md.append(
            "Status of the flagged (second) charge: "
            + ", ".join(f"{s} ({c:,})" for s, c in rep_status) + ".\n"
        )
    samp = con.sql(
        f"""
        with f as (
            select s.* from src s
            join ({build_repeat_charge_query('src', REPEAT_WINDOW)}) d using (row_key)
            where d.is_repeat_charge order by s.row_key limit {SAMPLE_ROWS}
        )
        select a.transaction_id, a.transaction_date, a.transaction_status,
               b.transaction_id, b.transaction_date, b.transaction_status,
               a.merchant_name, a.amount
        from f b join src a
          on a.product_id = b.product_id and a.merchant_name = b.merchant_name
         and a.amount = b.amount and a.transaction_id <> b.transaction_id
         and a.transaction_date between b.transaction_date - to_minutes({REPEAT_WINDOW})
                                    and b.transaction_date
        order by b.row_key
        """
    ).fetchall()
    if samp:
        md.append(
            md_table(["first id", "first date", "first status", "second id",
                      "second date", "second status", "merchant", "amount"],
                     [list(r) for r in samp]) + "\n"
        )
    amounts = con.sql(
        """
        select count(distinct amount), count(*) filter (where amount = round(amount))
        from src
        """
    ).fetchone()
    md.append(
        f"Context: {amounts[0]:,} distinct amounts ({pct(amounts[1] / n)} whole numbers), "
        "so an equal amount at the same merchant and product rarely happens by chance.\n"
    )

    # ------------------------------------------------------ (4) habitual
    log("(4) details")
    md.append("## (4) Habitual merchant\n")
    dist = con.sql(
        f"""
        select least(prior_purchases_at_merchant, 10) k, count(*)
        from ({build_habitual_merchant_query('src', MIN_PRIOR)}) d
        join src s using (row_key) where s.merchant_name is not null
        group by 1 order by 1
        """
    ).fetchall()
    n_merch = n - raw[3]
    grp = con.sql(
        """
        select avg(k), quantile_cont(k, 0.5), max(k), count(*) from (
            select customer_id, merchant_name, count(*) k from src
            where merchant_name is not null group by all)
        """
    ).fetchone()
    per_cust = con.sql(
        """
        select avg(k), quantile_cont(k, 0.5) from (
            select customer_id, count(*) k from src group by 1)
        """
    ).fetchone()
    k_h = real["habitual"]
    ct = compare(k_h, bt("habitual"), n)
    cc = compare(k_h, base_col["habitual"], n)
    md.append(
        f"{k_h:,} card purchases ({pct(k_h / n)}; {pct(k_h / n_merch)} of the "
        f"{n_merch:,} with a merchant) follow >= {MIN_PRIOR} earlier purchases by the "
        f"same customer at the same merchant. Customers make {per_cust[0]:.1f} card "
        f"purchases on average (median {per_cust[1]:.0f}) across {len(merchants) - 1} "
        f"merchants; a customer-merchant pair has {grp[0]:.2f} purchases on average "
        f"(median {grp[1]:.0f}, max {grp[2]}).\n"
    )
    md.append(
        md_table(
            ["prior purchases at merchant", "purchases", "share of purchases with merchant"],
            [[f"{k}{'+' if k == 10 else ''}", f"{c:,}", pct(c / n_merch)] for k, c in dist],
        )
        + "\n"
    )
    md.append(
        f"Baselines: shuffled timestamps {pct(ct['mean'] / n)} (real/base "
        f"{fmt_ratio(ct['ratio'])}; invariant by construction up to timestamp ties); "
        f"merchant permuted across purchases {pct(cc['mean'] / n)} [{pct(cc['lo'] / n)}, "
        f"{pct(cc['hi'] / n)}] (real/base {fmt_ratio(cc['ratio'])}, z = {cc['z']:+.1f}). "
        + (
            "Customers are no more loyal to merchants than random assignment: the "
            "prevalence comes from purchase volume over 24 merchants, not from habit."
            if not cc["signal"]
            else "Customers concentrate their purchases on some merchants more than "
            "random assignment would."
        )
        + "\n"
    )

    # ------------------------------------------------------------ verdict
    reached = [lbl for lbl, key, _ in causes if real[key] / n >= THRESHOLD]
    signal = [lbl for (lbl, key, _) in causes if results[key][3]["signal"]]
    real_and_signal = [lbl for lbl in reached if lbl in signal]
    if real_and_signal and len(real_and_signal) == len(causes):
        verdict = "supported"
    elif real_and_signal:
        verdict = "partially supported"
    else:
        verdict = "refuted as a data-backed pattern"

    bullets = []
    for lbl, key, _ in causes:
        k, ct, cc, ref = results[key]
        bullets.append(
            f"- **{lbl}**: {k:,} ({pct(k / n)}); "
            f"{'reaches' if k / n >= THRESHOLD else 'below'} {pct(THRESHOLD)}; "
            f"{'above' if ref['signal'] else 'not above'} the "
            f"{'column' if cc else 'timestamp'}-shuffle baseline "
            f"({pct(ref['mean'] / n)}, z = {ref['z']:+.1f})."
        )
    md.insert(
        verdict_idx,
        f"## Verdict: **{verdict}**\n\n"
        + "\n".join(bullets)
        + f"\n- **Causes at >= {pct(THRESHOLD)}:** "
        + (", ".join(reached) if reached else "none")
        + ". **Of those, above generator noise:** "
        + (", ".join(real_and_signal) if real_and_signal else "none")
        + ".\n- **Consequence ('Si falla'):** every cause that is below the threshold "
        "or not above its baseline is covered only by the declared fixtures "
        "in `ml/tests/detectors/test_card_charges.py`, not by prevalence in this "
        "dataset. See the per-cause sections for why each number looks the way it "
        "does.\n",
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "A3.md").write_text(report, encoding="utf-8")
    line = (
        f"- A3 (preauth / foreign currency / double charges): {verdict}. "
        f"{n:,} card purchases; "
        + "; ".join(
            f"{lbl.split(' (')[0]} {pct(real[key] / n)} "
            f"(base {pct(results[key][3]['mean'] / n)})"
            for lbl, key, _ in causes
        )
        + f"; >= {pct(THRESHOLD)}: "
        + (", ".join(lbl.split(" ")[0] for lbl in reached) or "none")
        + "; above baseline: "
        + (", ".join(lbl.split(" ")[0] for lbl in signal) or "none")
        + "; see docs/findings/day1/A3.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- A3 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
