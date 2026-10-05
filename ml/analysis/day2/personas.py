"""Day 2 - demo personas (a), Transaccional transcript content (b, P4) and whether
transcript text predicts contact_reason (c, P5).

(a) Count customers who qualify for each demo scenario and pick 3 examples each:
    S1  2+ Active cards and a Declined card transaction in their last 30 active days
    S2  exactly 1 Active card with a recent Purchase on it
    S3  one Blocked card plus one Active card
    S4  no cards
    S5  a Pending or Reversed card transaction
    For each example: cards (last 4 of product_number, type, status) and the last 10
    card transactions.
(b) P4: distinct call_transcripts.full_text linked to contact_reason = Transaccional,
    grouped by what the customer asks.
(c) P5: distinct texts per reason, texts shared across reasons, and TF-IDF + logistic
    regression with a split grouped by distinct full_text, vs majority class and a
    shuffled-label baseline.

Definitions
  card               product_type in CARD_TYPES
  card transaction   transaction whose product_id joins a card product
  active day         calendar day with at least one card transaction of that customer;
                     "last 30 active days" = that customer's 30 most recent active days
  recent             transaction_date within RECENT_DAYS of the latest transaction in
                     the dataset
All ids are unique in 02_intermediate (checked below), so no dedup is needed here.

Outputs:
  docs/findings/day2/personas.md            (committed report)
  data/08_reporting/day2/personas.md        (copy)

Run from ml/:  .venv/Scripts/python analysis/day2/personas.py
"""

from __future__ import annotations

import re
import sys
import time
from collections import Counter
from pathlib import Path

import duckdb
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, f1_score
from sklearn.model_selection import GroupKFold, KFold

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "day1"))
from A1_unrecognized_charges import fmt, md_table, pct  # noqa: E402

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day2"
OUT_DOCS = REPO / "docs" / "findings" / "day2"
NAME = "personas"

CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")
ACTIVE_DAYS = 30
RECENT_DAYS = 90
N_EXAMPLES = 3
N_LAST_TX = 10
N_TEXTS = 50
FOLDS = 5
SEED = 2026

# P4 groups, checked in this order against the customer's opening turn
ASK_RULES = [
    ("block card", r"bloque"),
    ("declined payment", r"rechaz|declin|no pas[óo]|no me dej"),
    ("charge explanation", r"cargo|cobro|no reconozco|cobraron"),
    ("transfer status", r"transferencia|giro"),
    ("balance", r"saldo"),
]

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def q(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def one_line(text: str, width: int | None = None) -> str:
    s = text.replace("\n\n", " / ").replace("\n", " / ").replace("|", "\\|")
    if width and len(s) > width:
        s = s[: width - 3] + "..."
    return s


def opening(text: str) -> str:
    """First customer turn of a transcript."""
    for line in text.split("\n"):
        if line.startswith("Cliente:"):
            return line.removeprefix("Cliente:").strip()
    return ""


def ask_group(text: str) -> str:
    first = opening(text).lower()
    for name, pat in ASK_RULES:
        if re.search(pat, first):
            return name
    return "other"


def setup(con: duckdb.DuckDBPyConnection) -> None:
    for t in (
        "customers",
        "products",
        "call_center_interactions",
        "call_transcripts",
    ):
        con.execute(
            f"create table {t} as select * from read_parquet('{(INTER / f'{t}.parquet').as_posix()}')"
        )
    con.execute(
        f"create view tx as select * from read_parquet('{(INTER / 'transactions.parquet').as_posix()}')"
    )
    cards_in = ", ".join(f"'{c}'" for c in CARD_TYPES)
    con.execute(
        f"""create table cards as
            select product_id, customer_id, product_type, product_status,
                   right(product_number, 4) as last4
            from products where product_type in ({cards_in})"""
    )
    con.execute(
        """create table ct as
           select t.transaction_id, t.transaction_date, t.product_id, t.customer_id,
                  t.transaction_type, t.amount::double as amount, t.currency,
                  t.merchant_name, t.transaction_status, t.response_code,
                  c.last4, c.product_type, c.product_status
           from tx t join cards c using (product_id)"""
    )
    con.execute(
        """create table cpc as
           select cu.customer_id, cu.customer_status,
                  count(c.product_id) as cards,
                  count(c.product_id) filter (where c.product_status = 'Active') as active,
                  count(c.product_id) filter (where c.product_status = 'Blocked') as blocked
           from customers cu left join cards c using (customer_id)
           group by all"""
    )


def part_a(con: duckdb.DuckDBPyConnection, md: list[str]) -> dict:
    n_cu = q(con, "select count(*) from customers")[0][0]
    ids = q(
        con,
        """select (select count(*) - count(distinct customer_id) from customers),
                  (select count(*) - count(distinct product_id) from products),
                  (select count(*) - count(distinct transaction_id) from tx),
                  (select count(*) from ct where customer_id <> (
                      select customer_id from cards c where c.product_id = ct.product_id))""",
    )[0]
    t_max = q(con, "select max(transaction_date) from tx")[0][0]
    n_ct = q(con, "select count(*) from ct")[0][0]
    statuses = q(
        con,
        "select product_type, product_status, count(*) from cards group by all order by all",
    )
    tx_status = q(
        con,
        "select transaction_status, count(*) from ct group by 1 order by 2 desc",
    )
    tx_type = q(
        con, "select transaction_type, count(*) from ct group by 1 order by 2 desc"
    )
    cu_status = q(
        con,
        "select customer_status, count(*) from customers group by 1 order by 2 desc",
    )
    log(f"(a) {n_cu:,} customers, {n_ct:,} card transactions, last tx {t_max}")

    con.execute(
        f"""create table act_days as
            select customer_id, d from (
                select customer_id, transaction_date::date as d from ct group by all)
            qualify row_number() over (partition by customer_id order by d desc) <= {ACTIVE_DAYS}"""
    )
    recent_from = f"timestamp '{t_max:%Y-%m-%d %H:%M:%S}' - interval {RECENT_DAYS} day"
    scen = {
        "S1": (
            f"2+ Active cards and a Declined card transaction in the last {ACTIVE_DAYS} active days",
            """select customer_id from cpc where active >= 2
                intersect
                select distinct ct.customer_id from ct join act_days a
                  on a.customer_id = ct.customer_id and a.d = ct.transaction_date::date
                where ct.transaction_status = 'Declined'""",
        ),
        "S2": (
            f"exactly 1 Active card with a Purchase on it in the last {RECENT_DAYS} days",
            f"""select customer_id from cpc where active = 1
                intersect
                select distinct customer_id from ct
                where product_status = 'Active' and transaction_type = 'Purchase'
                  and transaction_date >= {recent_from}""",
        ),
        "S3": (
            "exactly 1 Blocked card plus at least 1 Active card",
            "select customer_id from cpc where blocked = 1 and active >= 1",
        ),
        "S4": ("no cards", "select customer_id from cpc where cards = 0"),
        "S5": (
            "a Pending or Reversed card transaction",
            """select distinct customer_id from ct
               where transaction_status in ('Pending', 'Reversed')""",
        ),
    }
    counts = {}
    for key, (_, sql) in scen.items():
        con.execute(f"create table {key} as {sql}")
        counts[key] = q(
            con,
            f"""select count(*),
                       count(*) filter (where cpc.customer_status = 'Active')
                from {key} join cpc using (customer_id)""",
        )[0]
    # context: denominators and variants
    holders = q(con, "select count(*) from cpc where cards > 0")[0][0]
    s1_den = q(con, "select count(*) from cpc where active >= 2")[0][0]
    s1_lt2 = q(
        con,
        """select count(*) from (
             select customer_id from cpc where active = 1
             intersect
             select distinct ct.customer_id from ct join act_days a
               on a.customer_id = ct.customer_id and a.d = ct.transaction_date::date
             where ct.transaction_status = 'Declined')""",
    )[0][0]
    one_active = q(con, "select count(*) from cpc where active = 1")[0][0]
    s1_any_decl = q(
        con,
        """select count(distinct ct.customer_id) from ct join cpc using (customer_id)
           where cpc.active >= 2 and ct.transaction_status = 'Declined'""",
    )[0][0]
    # null baseline for S1: per-transaction decline rate by number of Active cards
    decl_rate = q(
        con,
        """select (cpc.active >= 2) as multi, count(*),
                  avg((ct.transaction_status = 'Declined')::int)
           from ct join cpc using (customer_id) where cpc.active >= 1
           group by 1 order by 1""",
    )
    cover = q(
        con,
        """select avg(covered) from (
             select ct.customer_id, count(*) filter (where a.d is not null) / count(*) as covered
             from ct left join act_days a
               on a.customer_id = ct.customer_id and a.d = ct.transaction_date::date
             group by ct.customer_id)""",
    )[0][0]
    s1_calendar = q(
        con,
        f"""select count(distinct ct.customer_id) from ct join cpc using (customer_id)
            where cpc.active >= 2 and ct.transaction_status = 'Declined'
              and ct.transaction_date >= timestamp '{t_max:%Y-%m-%d %H:%M:%S}' - interval {ACTIVE_DAYS} day""",
    )[0][0]
    s3_loose = q(con, "select count(*) from cpc where blocked >= 1 and active >= 1")[0][
        0
    ]
    s3_exact = q(con, "select count(*) from cpc where blocked = 1 and active = 1")[0][0]
    s5_split = q(
        con,
        """select transaction_status, count(distinct customer_id) from ct
           where transaction_status in ('Pending', 'Reversed') group by 1 order by 1""",
    )
    blocked_tx = q(
        con,
        """select count(*), count(distinct product_id),
                  (select count(*) from cards where product_status = 'Blocked')
           from ct where product_status = 'Blocked'""",
    )[0]
    last4_clash = q(
        con,
        """select count(*) from (select customer_id from cards group by customer_id, last4
                                 having count(*) > 1)""",
    )[0][0]
    s4_other = q(
        con,
        """select count(distinct s.customer_id) from S4 s join products p using (customer_id)""",
    )[0][0]
    recent_tx_per_cust = q(
        con,
        f"""select median(n), avg(n) from (
              select customer_id, count(*) n from ct
              where transaction_date >= {recent_from} group by 1)""",
    )[0]
    log("(a) counts done")

    md.append("## (a) Demo personas\n")
    md.append(
        f"Customers: {n_cu:,}. Card holders: {holders:,} ({pct(holders / n_cu)}). "
        f"Card transactions: {n_ct:,}; latest transaction in the dataset: {t_max:%Y-%m-%d}. "
        f"Duplicate ids in 02_intermediate: customers {ids[0]}, products {ids[1]}, "
        f"transactions {ids[2]}; card transactions whose customer differs from the card "
        f"owner: {ids[3]}.\n"
    )
    md.append("Distinct values used as filters (checked before filtering):\n")
    md.append(
        md_table(
            ["product_type", "product_status", "cards"],
            [[a, b, f"{c:,}"] for a, b, c in statuses],
        )
    )
    md.append(
        "\nCard transactions by status: "
        + ", ".join(f"{a} {b:,}" for a, b in tx_status)
        + ". By type: "
        + ", ".join(f"{a} {b:,}" for a, b in tx_type)
        + ". customer_status: "
        + ", ".join(f"{a} {b:,}" for a, b in cu_status)
        + ".\n"
    )
    md.append("### Counts\n")
    rows = []
    for key, (desc, _) in scen.items():
        n, n_act = counts[key]
        rows.append([key, desc, f"{n:,}", pct(n / n_cu), f"{n_act:,}"])
    md.append(
        md_table(
            [
                "id",
                "scenario",
                "customers",
                "% of customers",
                "of which customer_status = Active",
            ],
            rows,
        )
    )
    md.append(
        f"""
Context for each count:

- S1: {s1_den:,} customers have 2+ Active cards; {counts["S1"][0]:,} of them
  ({pct(counts["S1"][0] / s1_den)}) have a Declined card transaction in their last
  {ACTIVE_DAYS} active days, and {s1_any_decl:,} have one at any time. Customers have few
  card transactions, so the last {ACTIVE_DAYS} active days cover on average
  {pct(float(cover))} of a customer's card transactions: the window is close to "ever".
  With a calendar window instead (a decline in the last {ACTIVE_DAYS} days before
  {t_max:%Y-%m-%d}) S1 has {s1_calendar:,} customers. Among the {one_active:,} customers with
  exactly 1 Active card the active-days condition holds for {s1_lt2:,}
  ({pct(s1_lt2 / one_active)}). Null check: the per-transaction decline rate is
  {pct(decl_rate[0][2])} for 1-Active-card holders ({decl_rate[0][1]:,} transactions) and
  {pct(decl_rate[1][2])} for 2+ ({decl_rate[1][1]:,}), so the higher S1 rate comes from
  more transactions per customer, not from more declines per transaction.
- S2: "recent" means on or after {RECENT_DAYS} days before {t_max:%Y-%m-%d}. Customers with a
  card transaction in that window have a median of {fmt(float(recent_tx_per_cust[0]), 0)}
  card transactions in it (mean {fmt(float(recent_tx_per_cust[1]), 1)}).
- S3: {s3_loose:,} customers have at least 1 Blocked and 1 Active card; {s3_exact:,} have
  exactly one of each. Blocked cards with any transaction: {blocked_tx[1]:,} of
  {blocked_tx[2]:,} ({blocked_tx[0]:,} transactions), so a blocked card has no history
  to show.
- S4: of the {counts["S4"][0]:,} customers without cards, {s4_other:,} hold some other product.
- S5: """
        + ", ".join(f"{a} {b:,} customers" for a, b in s5_split)
        + f""".
- Customers with two cards sharing the same last 4 digits: {last4_clash:,}.
"""
    )

    md.append("### Examples\n")
    md.append(
        f"Three customers per scenario, chosen by a seeded hash of customer_id (seed {SEED}). "
        f"Cards: last 4 of product_number, type, status. Transactions: the last {N_LAST_TX} "
        "card transactions of the customer across all their cards.\n"
    )
    examples = {}
    for key, (desc, _) in scen.items():
        picks = [
            r[0]
            for r in q(
                con,
                f"""select s.customer_id from {key} s join cpc using (customer_id)
                    where cpc.customer_status = 'Active'
                    order by hash(s.customer_id || '{SEED}') limit {N_EXAMPLES}""",
            )
        ]
        examples[key] = picks
        md.append(f"#### {key}: {desc}\n")
        for cid in picks:
            cu = q(
                con,
                f"""select first_name, last_name, country, segment from customers
                    where customer_id = '{cid}'""",
            )[0]
            cards = q(
                con,
                f"""select last4, product_type, product_status from cards
                    where customer_id = '{cid}' order by product_status, last4""",
            )
            txs = q(
                con,
                f"""select transaction_date, last4, transaction_type, amount, currency,
                           merchant_name, transaction_status, response_code
                    from ct where customer_id = '{cid}'
                    order by transaction_date desc limit {N_LAST_TX}""",
            )
            n_tx = q(con, f"select count(*) from ct where customer_id = '{cid}'")[0][0]
            md.append(
                f"**{cid}** ({cu[0]} {cu[1]}, {cu[2]}, {cu[3]}). "
                f"Cards: {len(cards)}; card transactions in the dataset: {n_tx}.\n"
            )
            if cards:
                md.append(
                    md_table(["last 4", "type", "status"], [list(c) for c in cards])
                )
            else:
                md.append("No cards.\n")
            if txs:
                md.append(
                    "\n"
                    + md_table(
                        [
                            "date",
                            "card",
                            "type",
                            "amount",
                            "cur",
                            "merchant",
                            "status",
                            "code",
                        ],
                        [
                            [
                                f"{r[0]:%Y-%m-%d %H:%M}",
                                r[1],
                                r[2],
                                fmt(r[3], 2),
                                r[4],
                                r[5] or "",
                                r[6],
                                r[7] or "",
                            ]
                            for r in txs
                        ],
                    )
                )
            md.append("")
    return {
        "counts": counts,
        "n_cu": n_cu,
        "examples": examples,
        "blocked_tx": blocked_tx,
        "s1_calendar": s1_calendar,
    }


def part_b(con: duckdb.DuckDBPyConnection, md: list[str]) -> dict:
    reasons = q(
        con,
        """select contact_reason, count(*) from call_center_interactions
           group by 1 order by 2 desc""",
    )
    tr = q(
        con,
        """select t.full_text, count(*) as n
           from call_transcripts t join call_center_interactions i using (interaction_id)
           where i.contact_reason = 'Transaccional'
           group by 1 order by n desc, 1""",
    )
    n_rows = sum(r[1] for r in tr)
    n_int = q(
        con,
        "select count(*) from call_center_interactions where contact_reason = 'Transaccional'",
    )[0][0]
    unlinked = q(
        con,
        """select count(*) from call_transcripts t
           anti join call_center_interactions i using (interaction_id)""",
    )[0][0]
    openings_all = q(
        con,
        """select split_part(full_text, chr(10), 1) as opening, count(distinct full_text), count(*)
           from call_transcripts group by 1 order by 3 desc""",
    )
    log(f"(b) {len(tr)} distinct Transaccional texts over {n_rows:,} transcripts")

    groups: dict[str, list[tuple[str, int]]] = {}
    for text, n in tr:
        groups.setdefault(ask_group(text), []).append((text, n))

    md.append("## (b) P4: what Transaccional customers ask\n")
    md.append(
        "contact_reason values: "
        + ", ".join(f"{a} {b:,}" for a, b in reasons)
        + f". Transaccional interactions: {n_int:,}; with a transcript: {n_rows:,} "
        f"({pct(n_rows / n_int)}). Transcripts without a matching interaction: {unlinked}. "
        f"Distinct full_text among them: {len(tr)}.\n"
    )
    md.append(
        "Each text is grouped by the customer's opening turn with keyword rules "
        "(block: `bloque`; declined: `rechaz|declin|no pasó`; charge: `cargo|cobro|no reconozco`; "
        "transfer: `transferencia|giro`; balance: `saldo`). All groups are listed, "
        "including empty ones.\n"
    )
    rows = []
    for name in [g for g, _ in ASK_RULES] + ["other"]:
        items = groups.get(name, [])
        rows.append(
            [
                name,
                len(items),
                f"{sum(n for _, n in items):,}",
                pct(sum(n for _, n in items) / n_rows),
            ]
        )
    md.append(
        md_table(["customer asks", "distinct texts", "transcripts", "share"], rows)
    )
    card_balance = sum(n for text, n in tr if "tarjeta de crédito" in opening(text))
    md.append(
        f"\nWithin balance: credit-card balance {card_balance:,} transcripts "
        f"({pct(card_balance / n_rows)}), savings-account balance {n_rows - card_balance:,}.\n"
    )
    md.append("Two examples per non-empty group (most frequent texts):\n")
    for name in [g for g, _ in ASK_RULES] + ["other"]:
        items = groups.get(name, [])
        if not items:
            continue
        md.append(f"*{name}*\n")
        for text, n in items[:2]:
            md.append(f"- ({n:,}x) {one_line(text)}")
        md.append("")
    md.append(
        "Customer opening turns across **all** transcripts (every contact_reason):\n"
    )
    md.append(
        md_table(
            ["opening line", "distinct texts", "transcripts"],
            [[one_line(a), b, f"{c:,}"] for a, b, c in openings_all],
        )
    )
    md.append(
        f"\nThe {min(N_TEXTS, len(tr))} most frequent distinct Transaccional texts "
        "(turns separated by ` / `):\n"
    )
    md.append(
        md_table(
            ["#", "transcripts", "group", "full_text"],
            [
                [i + 1, f"{n:,}", ask_group(text), one_line(text)]
                for i, (text, n) in enumerate(tr[:N_TEXTS])
            ],
        )
    )
    md.append("")
    return {
        "card_balance": card_balance,
        "groups": {k: (len(v), sum(n for _, n in v)) for k, v in groups.items()},
        "n_distinct": len(tr),
        "n_rows": n_rows,
        "openings": openings_all,
    }


def part_c(con: duckdb.DuckDBPyConnection, md: list[str]) -> dict:
    rows = q(
        con,
        """select t.full_text, i.contact_reason, t.main_topics
           from call_transcripts t join call_center_interactions i using (interaction_id)
           order by t.transcript_id""",
    )
    texts = [r[0] for r in rows]
    y = np.array([r[1] for r in rows])
    n = len(rows)
    reasons = sorted(set(y))
    topic_match = sum(r[1] == r[2] for r in rows)
    intents = q(
        con,
        "select coalesce(detected_intents, 'null'), count(*) from call_transcripts group by 1 order by 2 desc",
    )

    per_reason = q(
        con,
        """select i.contact_reason, count(*), count(distinct t.full_text)
           from call_transcripts t join call_center_interactions i using (interaction_id)
           group by 1 order by 2 desc""",
    )
    n_distinct = len(set(texts))
    by_text: dict[str, Counter] = {}
    for t, r in zip(texts, y):
        by_text.setdefault(t, Counter())[r] += 1
    spread = Counter(len(c) for c in by_text.values())
    # ceiling: best any function of the text alone can do on these rows
    ceiling = sum(c.most_common(1)[0][1] for c in by_text.values()) / n
    majority_label, majority_n = Counter(y).most_common(1)[0]
    # per-text reason distribution vs the overall one (chi-square on text x reason)
    overall = np.array([Counter(y)[r] for r in reasons], dtype=float) / n
    tv = (
        sum(
            0.5
            * np.abs(
                np.array([c[r] for r in reasons]) / sum(c.values()) - overall
            ).sum()
            * sum(c.values())
            for c in by_text.values()
        )
        / n
    )
    rng = np.random.default_rng(SEED)
    y_shuf = rng.permutation(y)
    by_text_s: dict[str, Counter] = {}
    for t, r in zip(texts, y_shuf):
        by_text_s.setdefault(t, Counter())[r] += 1
    tv_shuf = (
        sum(
            0.5
            * np.abs(
                np.array([c[r] for r in reasons]) / sum(c.values()) - overall
            ).sum()
            * sum(c.values())
            for c in by_text_s.values()
        )
        / n
    )
    ceiling_shuf = sum(c.most_common(1)[0][1] for c in by_text_s.values()) / n
    log(f"(c) {n:,} transcripts, {n_distinct} distinct texts; ceiling {ceiling:.4f}")

    text_id = {t: i for i, t in enumerate(sorted(by_text))}
    groups = np.array([text_id[t] for t in texts])

    def run_cv(labels: np.ndarray, splitter, use_groups: bool) -> dict:
        acc, f1, acc_maj, f1_maj = [], [], [], []
        split = splitter.split(texts, labels, groups if use_groups else None)
        for tr_idx, te_idx in split:
            vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
            Xtr = vec.fit_transform([texts[i] for i in tr_idx])
            Xte = vec.transform([texts[i] for i in te_idx])
            clf = LogisticRegression(max_iter=2000)
            clf.fit(Xtr, labels[tr_idx])
            pred = clf.predict(Xte)
            acc.append(accuracy_score(labels[te_idx], pred))
            f1.append(f1_score(labels[te_idx], pred, average="macro"))
            maj = Counter(labels[tr_idx]).most_common(1)[0][0]
            pmaj = np.full(len(te_idx), maj)
            acc_maj.append(accuracy_score(labels[te_idx], pmaj))
            f1_maj.append(f1_score(labels[te_idx], pmaj, average="macro"))
        return {
            "acc": (np.mean(acc), np.std(acc)),
            "f1": (np.mean(f1), np.std(f1)),
            "acc_maj": (np.mean(acc_maj), np.std(acc_maj)),
            "f1_maj": (np.mean(f1_maj), np.std(f1_maj)),
        }

    grouped = run_cv(y, GroupKFold(n_splits=FOLDS), True)
    log("(c) grouped CV done")
    random_split = run_cv(
        y, KFold(n_splits=FOLDS, shuffle=True, random_state=SEED), False
    )
    log("(c) random CV done")
    shuffled = run_cv(y_shuf, GroupKFold(n_splits=FOLDS), True)
    log("(c) shuffled-label CV done")

    md.append("## (c) P5: does full_text predict contact_reason?\n")
    md.append(
        f"Unit: one transcript joined to its interaction ({n:,} rows, {n_distinct} distinct "
        f"full_text). Classes: {', '.join(reasons)}.\n"
    )
    md.append(
        md_table(
            [
                "contact_reason",
                "transcripts",
                "distinct full_text",
                "% of all distinct texts",
            ],
            [[a, f"{b:,}", c, pct(c / n_distinct)] for a, b, c in per_reason],
        )
    )
    md.append(
        "\nNumber of different contact_reason values each distinct text appears with:\n"
    )
    md.append(
        md_table(
            ["reasons per text", "distinct texts"],
            [[k, spread[k]] for k in sorted(spread)],
        )
    )
    md.append(
        f"""
Separability of the label by text alone, on all rows (no model):

- Majority class: {majority_label}, {pct(majority_n / n)} of transcripts.
- Ceiling for any text-only classifier (each distinct text predicts its own most common
  reason, fitted and scored on the same rows): {pct(ceiling)}; same with shuffled labels:
  {pct(ceiling_shuf)}.
- Average total-variation distance between a text's reason distribution and the overall
  one: {fmt(tv, 4)}; with shuffled labels: {fmt(tv_shuf, 4)}.

TF-IDF (word 1-2 grams) + logistic regression, {FOLDS}-fold CV, mean (sd):
"""
    )

    def cell(d: tuple[float, float]) -> str:
        return f"{d[0]:.4f} ({d[1]:.4f})"

    md.append(
        md_table(
            [
                "split",
                "model accuracy",
                "model macro-F1",
                "majority accuracy",
                "majority macro-F1",
            ],
            [
                [
                    "grouped by distinct full_text",
                    cell(grouped["acc"]),
                    cell(grouped["f1"]),
                    cell(grouped["acc_maj"]),
                    cell(grouped["f1_maj"]),
                ],
                [
                    "random rows (text leaks across folds)",
                    cell(random_split["acc"]),
                    cell(random_split["f1"]),
                    cell(random_split["acc_maj"]),
                    cell(random_split["f1_maj"]),
                ],
                [
                    "grouped, shuffled labels (null)",
                    cell(shuffled["acc"]),
                    cell(shuffled["f1"]),
                    cell(shuffled["acc_maj"]),
                    cell(shuffled["f1_maj"]),
                ],
            ],
        )
    )
    md.append(
        f"\nSide note: call_transcripts.main_topics equals contact_reason in "
        f"{topic_match:,} of {n:,} rows ({pct(topic_match / n)}); it is a copy of the label, "
        "not a feature. detected_intents values: "
        + ", ".join(f"{a} {b:,}" for a, b in intents)
        + ".\n"
    )
    return {
        "grouped": grouped,
        "random": random_split,
        "shuffled": shuffled,
        "ceiling": ceiling,
        "majority": (majority_label, majority_n / n),
        "spread": spread,
        "n_distinct": n_distinct,
        "topic_match": topic_match / n,
        "intents": intents,
    }


def main() -> None:
    con = duckdb.connect()
    setup(con)
    log("setup done")
    body: list[str] = []
    a = part_a(con, body)
    b = part_b(con, body)
    c = part_c(con, body)

    counts, n_cu = a["counts"], a["n_cu"]
    gacc = c["grouped"]["acc"][0]
    maj_acc = c["grouped"]["acc_maj"][0]
    balance_share = b["groups"].get("balance", (0, 0))[1] / b["n_rows"]
    card_asks = sum(
        b["groups"].get(g, (0, 0))[1]
        for g in ("block card", "declined payment", "charge explanation")
    )
    s_min = min(counts[k][0] for k in counts)

    head = [
        "# Day 2: demo personas, Transaccional transcripts (P4) and text vs contact_reason (P5)\n",
        "Script: `ml/analysis/day2/personas.py` (rerunnable). Source: `ml/data/02_intermediate/` "
        "(all rows, no dedup; ids checked unique below).\n",
        "## Verdicts\n",
        f"- **(a) Personas: supported.** Every scenario has real customers; the smallest has "
        f"{s_min:,}. S1 {counts['S1'][0]:,}, S2 {counts['S2'][0]:,}, S3 {counts['S3'][0]:,}, "
        f"S4 {counts['S4'][0]:,}, S5 {counts['S5'][0]:,} (of {n_cu:,} customers). "
        f"Blocked cards have {a['blocked_tx'][0]:,} transactions, so S3 shows a blocked card "
        f"with no history. S1's \"last {ACTIVE_DAYS} active days\" spans most of a customer's "
        f"history; with a decline in the last {ACTIVE_DAYS} calendar days S1 still has "
        f"{a['s1_calendar']:,} customers.",
        f"- **(b) P4: refuted.** All {b['n_distinct']} distinct Transaccional texts are "
        f"balance inquiries ({pct(balance_share)} of transcripts): savings-account balance "
        "or credit-card balance, followed by generic filler turns. No transcript asks about a "
        f"charge, a declined payment, a transfer or blocking a card ({card_asks} transcripts). "
        "Every transcript in the table, for any reason, opens with one of the same "
        f"{len(b['openings'])} lines, and amounts are unfilled placeholders (`{{monto}}`).",
        f"- **(c) P5: refuted.** Text does not predict contact_reason. Each reason sees "
        f"almost all {c['n_distinct']} texts; grouped-split accuracy {gacc:.4f} vs majority "
        f"{maj_acc:.4f}, the same as with shuffled labels "
        f"({c['shuffled']['acc'][0]:.4f}). Even with no split the ceiling is "
        f"{pct(c['ceiling'])}. The label is independent of the text, as in generator noise.",
        "",
        "## What this means for the scope (docs/proposal.md v3)\n",
        "- Keep the card workflow and its tool contracts (`list_cards`, `get_card_status`, "
        "`list_transactions`, `describe_transaction`, `block_card`, `open_handoff`). The data "
        "has customers for every demo scene: multi-card disambiguation with a decline (S1), a "
        "simple single-card inquiry (S2), a blocked + active pair (S3), the out-of-scope "
        "no-card customer that goes to handoff (S4), and pending/reversed items to describe "
        "(S5). Use the example ids below as fixtures for mock-bank tests and scenarios.",
        "- S3 confirms section 4 and 11: a blocked card has no transactions, so "
        '"why was I blocked?" can only go to a human.',
        '- Section 6 ("native transcript label if P5 shows it helps"): drop it. Transcripts '
        "carry two balance-inquiry openings and a label that is independent of the text, so "
        "they give neither utterances nor intent labels. The classifier is trained only on "
        "team-generated utterances, declared as such, as section 6 already allows.",
        "- Section 3 cites Transaccional at 35% of interactions as the evidence for the track. "
        "That number stays, but nothing in the transcripts says what those contacts were "
        "about, so the claim that they are card or transaction inquiries is our framing, "
        "not something the data shows. State it that way in the write-up.",
        "- Balance inquiry is the only request the transcripts contain, and "
        f"{pct(b['card_balance'] / b['n_rows'])} of Transaccional transcripts ask for the "
        "credit-card balance and available limit. It is cheap to add as a read-only intent "
        "(`get_card_status` already returns the card; add current_balance and credit_limit "
        "from products) and gives the demo one request grounded in the dataset's own "
        "conversations.",
        "- Do not use `main_topics` or `detected_intents` from call_transcripts as labels or "
        f"features: main_topics copies contact_reason in {pct(c['topic_match'])} of rows and "
        "detected_intents only takes the values "
        + ", ".join(f"`{v}`" for v, _ in c["intents"])
        + ".",
        "",
    ]
    report = "\n".join(head + body)
    for out in (OUT_DOCS, OUT_DATA):
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{NAME}.md").write_text(report, encoding="utf-8")
    log(f"wrote {OUT_DOCS / (NAME + '.md')}")


if __name__ == "__main__":
    main()
