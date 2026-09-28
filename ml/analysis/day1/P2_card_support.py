"""P2 - does the data support a card-servicing workflow?

Card servicing here means: a customer contacts the bank about one of their
cards (block / unblock, declined charge, "which charge is this?"). The agent
needs (1) card products with a status to act on, (2) a way to tell a customer's
cards apart, (3) transaction status and response codes to explain a decline,
(4) merchant names the customer would recognize, and (5) a small enough
candidate set of recent transactions to pin down the one being discussed.

Sections:
  (a) products by product_type x product_status (share Blocked, Suspended)
  (b) cards per customer (share with 2+ cards)
  (c) card transactions: transaction_status x response_code, and whether codes
      differ by status (chi-square over the non-approved statuses)
  (d) merchant_name cardinality and per-customer repeat rate, against a
      shuffled-merchant baseline
  (e) card transactions per customer in a random 30-day window
  (f) natural ambiguity: for SAMPLE random card customers, how often two card
      transactions in the same calendar week share a merchant or a similar
      amount (same currency, within AMOUNT_TOL relative difference)

Card transaction = transaction whose product_id joins a product of type
'Tarjeta Crédito' or 'Tarjeta Débito'.

Outputs:
  docs/findings/day1/P2_card_support.md   (committed report)
  data/08_reporting/day1/P2_card_support.md (copy)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (P2 line)

Run from ml/:  .venv/Scripts/python analysis/day1/P2_card_support.py
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import chi2_p, fmt, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"
NAME = "P2_card_support"

CARD_TYPES = ("Tarjeta Crédito", "Tarjeta Débito")
SAMPLE = 200  # customers for the ambiguity check
AMOUNT_TOL = 0.05  # "similar amount": |a - b| / max(a, b) <= 5%, same currency
AMOUNT_TOL_TIGHT = 0.01
WINDOW_DAYS = 30
SEED = 2026
PERMS = 20  # shuffled-merchant baselines

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def q(con: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return con.execute(sql).fetchall()


def quantiles(con: duckdb.DuckDBPyConnection, table: str, col: str) -> list:
    r = q(
        con,
        f"""select min({col}), quantile_cont({col}, 0.10), quantile_cont({col}, 0.25),
                   median({col}), avg({col}), quantile_cont({col}, 0.75),
                   quantile_cont({col}, 0.90), max({col})
            from {table}""",
    )[0]
    return [fmt(float(v), 1) for v in r]


QHEAD = ["min", "p10", "p25", "median", "mean", "p75", "p90", "max"]


def main() -> None:
    con = duckdb.connect()
    con.execute(f"select setseed({SEED / 10000})")
    con.execute(
        f"create table p as select * from read_parquet('{(INTER / 'products.parquet').as_posix()}')"
    )
    con.execute(
        f"create table cu as select * from read_parquet('{(INTER / 'customers.parquet').as_posix()}')"
    )
    con.execute(
        f"create view t as select * from read_parquet('{(INTER / 'transactions.parquet').as_posix()}')"
    )
    cards_in = ", ".join(f"'{c}'" for c in CARD_TYPES)
    con.execute(
        f"""create table ct as
            select t.transaction_id, t.transaction_date, t.product_id, t.customer_id,
                   t.transaction_type, t.amount::double as amount, t.currency,
                   t.merchant_name, t.transaction_status, t.response_code,
                   p.product_type, p.customer_id as p_customer_id,
                   p.opening_date, p.expiration_date
            from t join p using (product_id)
            where p.product_type in ({cards_in})"""
    )
    n_tx = q(con, "select count(*) from t")[0][0]
    n_ct = q(con, "select count(*) from ct")[0][0]
    t_min, t_max = q(con, "select min(transaction_date), max(transaction_date) from t")[
        0
    ]
    log(f"{n_tx:,} transactions, {n_ct:,} card transactions")
    md: list[str] = []

    # ---------------------------------------------------------------- (a)
    rows = q(
        con,
        """select product_type, count(*),
                  sum((product_status = 'Active')::int),
                  sum((product_status = 'Blocked')::int),
                  sum((product_status = 'Suspended')::int),
                  sum((product_status = 'Closed')::int),
                  count(distinct product_status)
           from p group by all order by 2 desc""",
    )
    n_p = sum(r[1] for r in rows)
    tab_a = [
        [
            r[0],
            f"{r[1]:,}",
            pct(r[2] / r[1]),
            pct(r[3] / r[1]),
            pct(r[4] / r[1]),
            pct(r[5] / r[1]),
        ]
        for r in rows
    ]
    tot = [sum(r[i] for r in rows) for i in range(1, 6)]
    tab_a.append(["**all**", f"{tot[0]:,}"] + [pct(x / tot[0]) for x in tot[1:]])
    card_rows = [r for r in rows if r[0] in CARD_TYPES]
    n_cards = sum(r[1] for r in card_rows)
    n_card_blk = sum(r[3] for r in card_rows)
    n_card_sus = sum(r[4] for r in card_rows)
    # status spread across types: max - min Blocked share
    blk_shares = [r[3] / r[1] for r in rows]
    sus_shares = [r[4] / r[1] for r in rows]
    status_chi_p = chi2_p([[r[2], r[3], r[4], r[5]] for r in rows])

    # activity of cards by status
    act = q(
        con,
        f"""select p.product_status, count(*) as cards,
                   count(p.last_transaction_date) as with_last_tx,
                   count(distinct x.product_id) as with_tx,
                   coalesce(sum(x.n), 0) as tx
            from p left join (select product_id, count(*) n from ct group by 1) x
              using (product_id)
            where p.product_type in ({cards_in})
            group by 1 order by 2 desc""",
    )
    tab_act = [
        [r[0], f"{r[1]:,}", pct(r[2] / r[1]), pct(r[3] / r[1]), f"{r[4]:,}"]
        for r in act
    ]
    tx_nonactive = sum(r[4] for r in act if r[0] != "Active")
    lu = q(
        con,
        f"""select product_status, min(last_updated), max(last_updated)
            from p where product_type in ({cards_in}) group by 1 order by 1""",
    )
    exp = q(
        con,
        f"""select sum((expiration_date is null)::int),
                   sum((expiration_date < date '{t_max:%Y-%m-%d}')::int), count(*)
            from p where product_type in ({cards_in}) and product_status = 'Active'""",
    )[0]
    validity = q(
        con,
        """select sum((transaction_date::date < opening_date)::int),
                  sum((transaction_date::date > expiration_date)::int),
                  count(*) from ct""",
    )[0]
    owner_mismatch = q(con, "select sum((customer_id <> p_customer_id)::int) from ct")[
        0
    ][0]
    log("(a) done")

    # ---------------------------------------------------------------- (b)
    con.execute(
        f"""create table cpc as
            select cu.customer_id,
                   count(p.product_id) as cards,
                   count(p.product_id) filter (where p.product_status = 'Active') as active_cards,
                   count(p.product_id) filter (where p.product_type = 'Tarjeta Crédito') as credit,
                   count(p.product_id) filter (where p.product_type = 'Tarjeta Débito') as debit
            from cu left join p on p.customer_id = cu.customer_id
                 and p.product_type in ({cards_in})
            group by 1"""
    )
    n_cu = q(con, "select count(*) from cpc")[0][0]
    n_holders = q(con, "select count(*) from cpc where cards > 0")[0][0]
    dist_b = q(
        con,
        """select least(cards, 5) k, count(*), sum((active_cards >= 2)::int)
           from cpc group by 1 order by 1""",
    )
    tab_b = [
        [
            ("5+" if r[0] == 5 else str(r[0])),
            f"{r[1]:,}",
            pct(r[1] / n_cu),
            pct(r[1] / n_holders) if r[0] > 0 else "-",
        ]
        for r in dist_b
    ]
    two_plus = q(
        con,
        """select sum((cards >= 2)::int), sum((active_cards >= 2)::int),
                  sum((credit >= 1 and debit >= 1)::int), sum((credit >= 2)::int),
                  sum((debit >= 2)::int), max(cards)
           from cpc""",
    )[0]
    # same-type cards: can the customer tell them apart? product_number last 4
    same_last4 = q(
        con,
        f"""select count(*) from (
              select customer_id, right(product_number, 4) l4, count(*) n
              from p where product_type in ({cards_in}) group by 1, 2 having n > 1)""",
    )[0][0]
    pn_len = q(
        con,
        f"""select product_type, length(product_number) l, count(*)
            from p where product_type in ({cards_in}) group by all order by 1, 2""",
    )
    log("(b) done")

    # ---------------------------------------------------------------- (c)
    st = q(
        con,
        """select transaction_status, count(*), count(response_code),
                  count(distinct response_code)
           from ct group by 1 order by 2 desc""",
    )
    codes = [
        r[0]
        for r in q(
            con, "select distinct coalesce(response_code, 'null') from ct order by 1"
        )
    ]
    xt = {
        (r[0], r[1]): r[2]
        for r in q(
            con,
            """select transaction_status, coalesce(response_code, 'null'), count(*)
               from ct group by all""",
        )
    }
    statuses = [r[0] for r in st]
    tab_c = []
    for s in statuses:
        n_s = sum(xt.get((s, c), 0) for c in codes)
        tab_c.append(
            [s, f"{n_s:,}", pct(n_s / n_ct)]
            + [pct(xt.get((s, c), 0) / n_s) for c in codes]
        )
    non_ok = [s for s in statuses if s != "Approved"]
    decline_codes = [c for c in codes if c not in ("00", "null")]
    chi_codes_p = chi2_p([[xt.get((s, c), 0) for c in decline_codes] for s in non_ok])
    approved_non00 = sum(xt.get(("Approved", c), 0) for c in decline_codes)
    non_ok_00 = sum(xt.get((s, "00"), 0) for s in non_ok)
    # code by transaction_type and card type among declines
    by_type = q(
        con,
        """select transaction_type, product_type, count(*),
                  avg((transaction_status <> 'Approved')::int)
           from ct group by all order by 1, 2""",
    )
    tab_c_type = [[r[0], r[1], f"{r[2]:,}", pct(r[3])] for r in by_type]
    codes_by_type = q(
        con,
        """select transaction_type, response_code, count(*) from ct
           where transaction_status = 'Declined' and response_code is not null
           group by all""",
    )
    types = sorted({r[0] for r in codes_by_type})
    m = {(r[0], r[1]): r[2] for r in codes_by_type}
    chi_type_p = chi2_p([[m.get((t_, c), 0) for c in decline_codes] for t_ in types])
    # decline code vs balance: does '51' (insufficient funds) track amount?
    amt_code = q(
        con,
        """select response_code, avg(amount) from ct
           where transaction_status = 'Declined' and response_code is not null
             and currency = 'USD' group by 1 order by 1""",
    )
    fraud_code = q(
        con,
        """select ct.response_code, avg(t.is_fraud::int), avg(t.fraud_score::double)
            from t join ct using (transaction_id)
            where ct.transaction_status = 'Declined' and ct.response_code is not null
            group by 1 order by 1""",
    )
    exp_code = q(
        con,
        """select response_code,
                  avg((transaction_date::date > expiration_date)::int)
           from ct where transaction_status = 'Declined' and response_code is not null
           group by 1 order by 1""",
    )
    exp_approved = q(
        con,
        """select avg((transaction_date::date > expiration_date)::int)
           from ct where transaction_status = 'Approved'""",
    )[0][0]
    log("(c) done")

    # ---------------------------------------------------------------- (d)
    n_merch = q(
        con, "select count(distinct merchant_name), count(merchant_name) from ct"
    )[0]
    merch_by_type = q(
        con,
        """select transaction_type, count(*), count(merchant_name) from ct
           group by 1 order by 1""",
    )
    cat_per_merch = q(
        con,
        """select max(k) from (select merchant_name, count(distinct merchant_category) k
           from t where merchant_name is not null group by 1)""",
    )[0][0]
    all_merch = q(con, "select count(distinct merchant_name) from t")[0][0]
    con.execute(
        """create table mt as
           select customer_id, merchant_name, transaction_date
           from ct where merchant_name is not null"""
    )

    def repeat_stats(src: str) -> tuple[float, float, float]:
        # repeat rate = share of merchant transactions at a merchant the customer
        # already used; per-customer mean distinct merchants; share of customers
        # whose top merchant covers >= 25% of their merchant transactions
        r = q(
            con,
            f"""with c as (
                  select customer_id, count(*) n, count(distinct merchant_name) d
                  from {src} group by 1)
                select 1 - sum(d) / sum(n), avg(d), avg(n) from c""",
        )[0]
        return float(r[0]), float(r[1]), float(r[2])

    rep_obs = repeat_stats("mt")
    per_cust = quantiles(
        con,
        "(select customer_id, count(*) n, count(distinct merchant_name) d from mt group by 1)",
        "d",
    )
    top_share = q(
        con,
        """with c as (select customer_id, merchant_name, count(*) k from mt group by 1, 2),
                s as (select customer_id, max(k) / sum(k) sh, sum(k) n from c group by 1)
           select avg(sh), avg(sh) filter (where n >= 10) from s""",
    )[0]
    base = []
    for i in range(PERMS):
        con.execute(f"select setseed({(SEED + i) / 100000})")
        con.execute(
            """create or replace table mt_shuf as
               with a as (select customer_id, row_number() over (order by random()) r from mt),
                    b as (select merchant_name, row_number() over (order by random()) r from mt)
               select a.customer_id, b.merchant_name from a join b using (r)"""
        )
        base.append(repeat_stats("mt_shuf")[0])
    base_mean, base_hi = float(np.mean(base)), float(np.max(base))
    base_top = q(
        con,
        """with c as (select customer_id, merchant_name, count(*) k from mt_shuf group by 1, 2),
                s as (select customer_id, max(k) / sum(k) sh, sum(k) n from c group by 1)
           select avg(sh), avg(sh) filter (where n >= 10) from s""",
    )[0]
    merch_share = q(
        con,
        """select merchant_name, count(*) / sum(count(*)) over () from mt
           group by 1 order by 2 desc""",
    )
    log("(d) done")

    # ---------------------------------------------------------------- (e)
    # one random 30-day window per customer with >= 1 card transaction; the
    # window end is uniform over [first day + 30, last day] of the data
    span_days = (t_max.date() - t_min.date()).days
    con.execute(f"select setseed({SEED / 10000})")
    con.execute(
        f"""create table anchors as
            select customer_id,
                   timestamp '{t_min:%Y-%m-%d} 00:00:00'
                     + to_days({WINDOW_DAYS} + floor(random() * {span_days - WINDOW_DAYS})::int) as a_end
            from (select distinct customer_id from ct)"""
    )
    con.execute(
        f"""create table win as
            select a.customer_id,
                   count(c.transaction_id) as card_tx,
                   count(c.transaction_id) filter (where c.transaction_type = 'Purchase') as purchases,
                   count(distinct c.merchant_name) as merchants
            from anchors a left join ct c
              on c.customer_id = a.customer_id
             and c.transaction_date >= a.a_end - to_days({WINDOW_DAYS})
             and c.transaction_date < a.a_end
            group by 1"""
    )
    con.execute(
        f"""create table win_all as
            select a.customer_id, count(t.transaction_id) as all_tx
            from anchors a left join t
              on t.customer_id = a.customer_id
             and t.transaction_date >= a.a_end - to_days({WINDOW_DAYS})
             and t.transaction_date < a.a_end
            group by 1"""
    )
    n_card_cust = q(con, "select count(*) from win")[0][0]
    q_card = quantiles(con, "win", "card_tx")
    q_purch = quantiles(con, "win", "purchases")
    q_merch = quantiles(con, "win", "merchants")
    q_all = quantiles(con, "win_all", "all_tx")
    zero_win = q(
        con, "select avg((card_tx = 0)::int), avg((card_tx >= 10)::int) from win"
    )[0]
    # active-period view: windows ending in a month where the customer transacted
    life = quantiles(
        con,
        """(select customer_id, count(*) * 30.0 /
                   greatest(date_diff('day', min(transaction_date), max(transaction_date)), 30) r
            from ct group by 1)""",
        "r",
    )
    txc = quantiles(con, "(select customer_id, count(*) n from ct group by 1)", "n")
    log("(e) done")

    # ---------------------------------------------------------------- (f)
    con.execute(f"select setseed({SEED / 10000})")
    con.execute(
        f"""create table samp as
            select customer_id from (select distinct customer_id from ct)
            order by hash(customer_id || '{SEED}') limit {SAMPLE}"""
    )
    con.execute(
        """create table st as
           select c.*, date_trunc('week', transaction_date) wk from ct c
           join samp using (customer_id)"""
    )
    n_st = q(con, "select count(*) from st")[0][0]
    con.execute(
        f"""create table pairs as
            select a.transaction_id id, a.customer_id, a.wk,
                   (a.merchant_name is not null and a.merchant_name = b.merchant_name) same_m,
                   (a.currency = b.currency and abs(a.amount - b.amount)
                      / greatest(a.amount, b.amount) <= {AMOUNT_TOL}) sim_a,
                   (a.currency = b.currency and abs(a.amount - b.amount)
                      / greatest(a.amount, b.amount) <= {AMOUNT_TOL_TIGHT}) sim_a1,
                   (a.transaction_type = b.transaction_type) same_type
            from st a join st b
              on a.customer_id = b.customer_id and a.wk = b.wk
             and a.transaction_id <> b.transaction_id"""
    )
    tx_flags = q(
        con,
        """with f as (
              select id, bool_or(same_m) m, bool_or(sim_a) a, bool_or(sim_a1) a1,
                     bool_or(same_m and sim_a) ma, bool_or(same_m or sim_a) any_
              from pairs group by 1)
            select count(*), sum(m::int), sum(a::int), sum(a1::int), sum(ma::int),
                   sum(any_::int) from f""",
    )[0]
    has_sib = tx_flags[0]
    wk = q(
        con,
        """with w as (select customer_id, wk, count(*) n from st group by 1, 2),
                pw as (select customer_id, wk, bool_or(same_m) m, bool_or(sim_a) a,
                              bool_or(same_m or sim_a) any_ from pairs group by 1, 2)
           select count(*), sum((n >= 2)::int),
                  sum(coalesce(pw.m, false)::int), sum(coalesce(pw.a, false)::int),
                  sum(coalesce(pw.any_, false)::int), avg(n), median(n), max(n)
           from w left join pw using (customer_id, wk)""",
    )[0]
    cust_hit = q(
        con,
        """select (select count(distinct customer_id) from pairs where same_m or sim_a),
                  (select count(distinct customer_id) from st)""",
    )[0]
    # merchant-level ambiguity: same merchant AND same currency, different amount,
    # so the amount alone disambiguates
    merch_amount_split = q(
        con,
        """select avg((not sim_a)::int) from pairs where same_m""",
    )[0][0]
    # expected similar-amount rate for two random same-currency card amounts
    sim_null = q(
        con,
        f"""with s0 as (select amount, currency from ct using sample 3000 rows (reservoir, {SEED})),
                 s as (select *, row_number() over () i from s0),
                 x as (select a.amount a, b.amount b from s a join s b
                       on a.currency = b.currency and a.i < b.i)
            select avg((abs(a - b) / greatest(a, b) <= {AMOUNT_TOL})::int) from x""",
    )[0][0]
    log("(f) done")

    # ---------------------------------------------------------------- report
    card_blk = n_card_blk / n_cards
    card_sus = n_card_sus / n_cards
    same_m_rate = tx_flags[1] / n_st
    sim_a_rate = tx_flags[2] / n_st
    any_rate = tx_flags[5] / n_st
    wk_multi_share = wk[4] / wk[1] if wk[1] else 0.0
    verdict = (
        "partially supported: cards, their status and per-card transactions exist, but "
        "decline codes are random, blocked/suspended cards have no history, and card "
        "activity is too sparse for transaction lookup to be hard"
    )

    md += [
        "# P2 - Card support workflow feasibility",
        "",
        f"Generated by `ml/analysis/day1/{NAME}.py` over `ml/data/02_intermediate/` "
        f"({n_p:,} products, {n_ct:,} card transactions out of {n_tx:,}). Transactions "
        f"span {t_min:%Y-%m-%d} to {t_max:%Y-%m-%d}.",
        "",
        "## Question",
        "",
        "Can an AI agent run a card-servicing flow on this data: identify the card, read "
        "its status (block / unblock), explain a declined or pending charge, and find the "
        "transaction the customer is talking about among their recent ones?",
        "",
        f"## Verdict: **{verdict}**",
        "",
        f"- **Card entity: yes.** {n_cards:,} cards "
        f"({pct(n_cards / n_p)} of products); {pct(card_blk)} Blocked and "
        f"{pct(card_sus)} Suspended. Status shares are the same for every product type "
        f"(chi-square p {fmt(status_chi_p, 3)}), so status is a generic product field, "
        "not a card-specific process.",
        f"- **Blocked / Suspended / Closed cards never transact.** All {n_ct:,} card "
        f"transactions sit on Active cards ({tx_nonactive:,} on the others), and only "
        "Active cards have `last_transaction_date`. There is no event history of when or why "
        'a card was blocked, so "why was my card blocked?" or "my charge was declined '
        'because the card is blocked" cannot be grounded; only the current status can be '
        "read.",
        f"- **Several cards per customer: common.** {pct(two_plus[0] / n_holders)} of "
        f"card holders have 2+ cards ({pct(two_plus[1] / n_holders)} have 2+ Active). "
        "The agent must ask which card; `product_number` last 4 digits identify it "
        f"(collisions within a customer: {same_last4:,}).",
        f"- **Decline reasons: present but uninformative.** Non-approved transactions carry "
        f"{len(decline_codes)} codes ({', '.join(decline_codes)}) in equal shares, and the "
        f"mix is the same for Declined, Pending and Reversed (chi-square p "
        f"{fmt(chi_codes_p, 3)}) and for every transaction type (p {fmt(chi_type_p, 3)}). "
        "Code 51 (insufficient funds) does not track amount, code 54 (expired card) does not "
        "track expiration_date, and 05/14 do not track fraud. The agent can translate a code "
        "into words but should not build explanations on it.",
        f"- **Merchants: {n_merch[0]} names, no habits.** Only Purchases carry a merchant. "
        f"Per-customer repeat rate {pct(rep_obs[0])} vs {pct(base_mean)} with merchants "
        "shuffled across customers, and top-merchant share matches the shuffle too: merchants "
        'are drawn at random per transaction. "My usual gym charge" style references have '
        'nothing behind them; merchant names are generic ("Super Ahorro", "Taxi Seguro").',
        f"- **Candidate set: tiny, because card activity is sparse.** In a random "
        f"{WINDOW_DAYS}-day window a card customer has a median of {q_card[3]} card "
        f"transactions (mean {q_card[4]}, p90 {q_card[6]}, max {q_card[7]}); "
        f"{pct(zero_win[0])} have none. Over their whole history the median card customer "
        f"has {txc[3]} card transactions in 3 years. A real card holder makes dozens per "
        "month, so this is far easier than production.",
        f"- **Natural ambiguity: very low, for the same reason.** Over {SAMPLE} random card "
        f"customers ({n_st:,} card transactions), {pct(same_m_rate)} of transactions share a "
        f"merchant with another card transaction in the same week, {pct(sim_a_rate)} have "
        f"a same-week amount within {pct(AMOUNT_TOL)}, {pct(any_rate)} either (none both). "
        f"Among weeks with 2+ card transactions, {pct(wk_multi_share)} contain such a pair. "
        "Any one of date, merchant or amount usually pins the transaction down, so a "
        "disambiguation step will rarely trigger on real data; to demo it, inject "
        "look-alike transactions into a test customer.",
        "- **Consequence:** build the card flow as: pick card (last 4) -> show status "
        "-> list recent transactions -> confirm the one meant -> explain status/code with a "
        "fixed template. Do not promise root-cause explanations (why blocked, why declined): "
        "the data does not carry them. Validity dates are also unreliable "
        f"({pct(validity[0] / validity[2])} of card transactions predate the card's "
        f"opening_date, {pct(validity[1] / validity[2])} postdate its expiration_date).",
        "",
        "## (a) Products by type and status",
        "",
        md_table(
            ["product_type", "products", "Active", "Blocked", "Suspended", "Closed"],
            tab_a,
        ),
        "",
        f"Blocked share ranges {pct(min(blk_shares))}-{pct(max(blk_shares))} and Suspended "
        f"{pct(min(sus_shares))}-{pct(max(sus_shares))} across types; type x status "
        f"chi-square p {fmt(status_chi_p, 3)}.",
        "",
        "Card activity by status:",
        "",
        md_table(
            [
                "product_status",
                "cards",
                "has last_transaction_date",
                "has card transactions",
                "card transactions",
            ],
            tab_act,
        ),
        "",
        "`last_updated` range by status (a status-change timestamp would be the only way to "
        "date a block):",
        "",
        md_table(
            ["product_status", "min last_updated", "max last_updated"],
            [[r[0], f"{r[1]:%Y-%m-%d}", f"{r[2]:%Y-%m-%d}"] for r in lu],
        ),
        "",
        f"Active cards without expiration_date: {exp[0]:,}; Active cards whose "
        f"expiration_date is before the end of the data: {exp[1]:,} of {exp[2]:,} "
        f"({pct(exp[1] / exp[2])}). Card transactions whose customer_id differs from the "
        f"card owner: {owner_mismatch:,}.",
        "",
        "## (b) Cards per customer",
        "",
        f"{n_cu:,} customers, {n_holders:,} ({pct(n_holders / n_cu)}) hold at least one card.",
        "",
        md_table(
            ["cards", "customers", "share of all customers", "share of card holders"],
            tab_b,
        ),
        "",
        md_table(
            ["measure", "customers", "share of card holders"],
            [
                ["2+ cards", f"{two_plus[0]:,}", pct(two_plus[0] / n_holders)],
                ["2+ Active cards", f"{two_plus[1]:,}", pct(two_plus[1] / n_holders)],
                ["credit and debit", f"{two_plus[2]:,}", pct(two_plus[2] / n_holders)],
                ["2+ credit cards", f"{two_plus[3]:,}", pct(two_plus[3] / n_holders)],
                ["2+ debit cards", f"{two_plus[4]:,}", pct(two_plus[4] / n_holders)],
            ],
        ),
        "",
        f"Max cards for one customer: {two_plus[5]}. `product_number` length by type: "
        + ", ".join(f"{r[0]} {r[1]} digits ({r[2]:,})" for r in pn_len)
        + f". Customers with two cards sharing the same last 4 digits: {same_last4:,}.",
        "",
        "## (c) Card transaction status and response codes",
        "",
        "Row shares of response_code within each status (`null` = missing code):",
        "",
        md_table(["transaction_status", "rows", "share"] + codes, tab_c),
        "",
        f"- Distinct non-null codes: {len([c for c in codes if c != 'null'])} "
        f"({', '.join(c for c in codes if c != 'null')}).",
        f"- Approved is always `00` (or null); approved with a decline code: {approved_non00:,}. "
        f"Non-approved with `00`: {non_ok_00:,}. So the code only restates the status.",
        f"- Among Declined / Pending / Reversed the {len(decline_codes)} codes are uniform "
        f"and the mix does not depend on status (chi-square p {fmt(chi_codes_p, 3)}).",
        "",
        "Non-approved share by transaction type and card type:",
        "",
        md_table(
            ["transaction_type", "product_type", "rows", "not Approved"], tab_c_type
        ),
        "",
        "Do the codes carry their standard meaning (Declined rows)?",
        "",
        md_table(
            [
                "code",
                "standard meaning",
                "mean USD amount",
                "is_fraud",
                "mean fraud_score",
                "past expiration_date",
            ],
            [
                [
                    a[0],
                    {
                        "05": "do not honor",
                        "14": "invalid card number",
                        "51": "insufficient funds",
                        "54": "expired card",
                    }.get(a[0], "?"),
                    fmt(float(a[1])),
                    pct(float(f[1])),
                    fmt(float(f[2])),
                    pct(float(e[1])),
                ]
                for a, f, e in zip(amt_code, fraud_code, exp_code)
            ],
        ),
        "",
        f"Approved card transactions past expiration_date: {pct(float(exp_approved))}. "
        "No code stands out on amount, fraud or expiry, so codes are assigned at random.",
        "",
        "## (d) Merchants",
        "",
        f"- {n_merch[0]} distinct merchant_name values on card transactions "
        f"({all_merch} in all transactions); each maps to at most {cat_per_merch} "
        "merchant_category (plus nulls).",
        "- merchant_name is filled only for Purchases: "
        + ", ".join(f"{r[0]} {pct(r[2] / r[1])}" for r in merch_by_type)
        + ".",
        f"- Largest merchant share {pct(merch_share[0][1])} ({merch_share[0][0]}), smallest "
        f"{pct(merch_share[-1][1])} ({merch_share[-1][0]}).",
        "",
        md_table(
            ["measure", "observed", f"shuffled merchants (mean of {PERMS})"],
            [
                [
                    "repeat rate (share of merchant tx at a merchant already used)",
                    pct(rep_obs[0]),
                    f"{pct(base_mean)} (max {pct(base_hi)})",
                ],
                ["mean distinct merchants per customer", fmt(rep_obs[1]), "-"],
                ["mean merchant tx per customer", fmt(rep_obs[2]), "-"],
                [
                    "mean top-merchant share",
                    pct(float(top_share[0])),
                    pct(float(base_top[0])),
                ],
                [
                    "mean top-merchant share, customers with 10+ tx",
                    pct(float(top_share[1])),
                    pct(float(base_top[1])),
                ],
            ],
        ),
        "",
        "Distinct merchants per customer (all history):",
        "",
        md_table(QHEAD, [per_cust]),
        "",
        "## (e) Transactions per customer in a 30-day window",
        "",
        f"{n_card_cust:,} customers with at least one card transaction. One window per "
        f"customer, end date uniform over the data span. Card transactions per customer "
        f"over their whole history: median {txc[3]} (p90 {txc[6]}).",
        "",
        md_table(
            ["count in window"] + QHEAD,
            [
                ["card transactions"] + q_card,
                ["card purchases"] + q_purch,
                ["distinct merchants"] + q_merch,
                ["all transactions (any product)"] + q_all,
            ],
        ),
        "",
        f"{pct(zero_win[0])} of windows have no card transaction; {pct(zero_win[1])} have 10+. "
        f"Card transactions per 30 days of each customer's own active span (first to last "
        f"card transaction): median {life[3]}, p90 {life[6]}.",
        "",
        "## (f) Natural ambiguity within a week",
        "",
        f"{SAMPLE} customers drawn at random (seeded hash) from those with card transactions; "
        f"{n_st:,} card transactions, {wk[0]:,} customer-weeks (calendar weeks, Monday start). "
        f"Similar amount = same currency and relative difference <= {pct(AMOUNT_TOL)}.",
        "",
        md_table(
            [
                "transaction has a same-week card transaction with ...",
                "transactions",
                "share",
            ],
            [
                ["any other card transaction", f"{has_sib:,}", pct(has_sib / n_st)],
                ["the same merchant", f"{tx_flags[1]:,}", pct(tx_flags[1] / n_st)],
                [
                    f"amount within {pct(AMOUNT_TOL)}",
                    f"{tx_flags[2]:,}",
                    pct(tx_flags[2] / n_st),
                ],
                [
                    f"amount within {pct(AMOUNT_TOL_TIGHT)}",
                    f"{tx_flags[3]:,}",
                    pct(tx_flags[3] / n_st),
                ],
                [
                    "same merchant and similar amount",
                    f"{tx_flags[4]:,}",
                    pct(tx_flags[4] / n_st),
                ],
                [
                    "same merchant or similar amount",
                    f"{tx_flags[5]:,}",
                    pct(tx_flags[5] / n_st),
                ],
            ],
        ),
        "",
        md_table(
            ["customer-weeks", "count", "share"],
            [
                ["all", f"{wk[0]:,}", "100.00%"],
                ["with 2+ card transactions", f"{wk[1]:,}", pct(wk[1] / wk[0])],
                ["with a same-merchant pair", f"{wk[2]:,}", pct(wk[2] / wk[0])],
                ["with a similar-amount pair", f"{wk[3]:,}", pct(wk[3] / wk[0])],
                ["with either", f"{wk[4]:,}", pct(wk[4] / wk[0])],
            ],
        ),
        "",
        f"Card transactions per active customer-week: mean {fmt(float(wk[5]))}, median "
        f"{fmt(float(wk[6]), 0)}, max {wk[7]}. {cust_hit[0]} of {cust_hit[1]} sampled "
        f"customers have at least one ambiguous pair somewhere in their history. "
        f"Same-merchant pairs that the amount separates (> {pct(AMOUNT_TOL)} apart): "
        f"{pct(float(merch_amount_split))}. Two random same-currency card amounts fall within "
        f"{pct(AMOUNT_TOL)} of each other {pct(float(sim_null))} of the time, so similar "
        "amounts arise at chance level; ambiguity is low because customers make few card "
        "transactions per week, not because amounts are distinctive.",
        "",
        "## Method notes",
        "",
        "- Card transaction = transaction joined on product_id to a 'Tarjeta Crédito' or "
        "'Tarjeta Débito' product; every transaction product_id joins products.",
        "- Window counts use one random window per customer instead of the calendar month so "
        "month edges do not matter. DuckDB random() is seeded but runs in parallel, so window and shuffle figures can move by ~0.1 pp between runs.",
        "- Shuffled merchant baseline: merchant names permuted across all card merchant "
        "transactions, customer counts kept fixed.",
        "- Codes: ISO 8583 meanings are listed only to test whether the data honors them.",
        "",
    ]
    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{NAME}.md").write_text(report, encoding="utf-8")
    line = (
        f"- P2 (card support workflow): {verdict}. {n_cards:,} cards, {pct(card_blk)} "
        f"Blocked / {pct(card_sus)} Suspended, none of them with transactions; "
        f"{pct(two_plus[0] / n_holders)} of holders have 2+ cards; {len(decline_codes)} "
        f"decline codes uniform across statuses (p {fmt(chi_codes_p, 3)}); "
        f"{n_merch[0]} merchants; median {q_card[3]} card tx per 30 days; "
        f"{pct(any_rate)} of tx have a same-week same-merchant or similar-amount twin; "
        f"see docs/findings/day1/{NAME}.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- P2 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
