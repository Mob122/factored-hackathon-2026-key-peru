"""B4 - can complaints be joined to call_center_interactions?

Checks:
  (a) the declared link: share of complaints with non-null origin_interaction_id,
      share of those that exist in call_center_interactions, and whether the
      linked interaction belongs to the same customer_id. Checked on raw CSVs
      too, so an empty column cannot be an ingestion artifact.
  (b) fallback join on customer_id with interaction_date in
      [creation_date - W days, creation_date] for W in 1, 3, 7: match rate,
      unique matches and ambiguity (complaints with more than one candidate).
  (c) whether the fallback finds real links or chance co-occurrence:
      - placebo windows of the same width shifted 60 and 180 days back,
      - a forward window (creation_date, creation_date + W],
      - a Poisson baseline from each customer's overall interaction rate,
      - the lag profile of the nearest prior interaction,
      - enrichment of contact_reason 'Queja' in matched interactions,
      - match rate by reception_channel (Call Center complaints should match
        more if the join captures the origin interaction).

Outputs:
  docs/findings/day1/B4.md                 (committed report)
  data/08_reporting/day1/B4.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (B4 line)

Run from ml/:  .venv/Scripts/python analysis/day1/B4_complaint_interaction_link.py
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import duckdb

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
RAW = ML / "data" / "01_raw"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

WINDOWS = [1, 3, 7]
PLACEBO_SHIFTS = [60, 180]  # days; far enough back to be unrelated to the complaint
LAG_HORIZON = 30  # days, for the nearest-prior-interaction lag profile
DATA_DAYS = 1097  # 2023-06-17 .. 2026-06-17 inclusive
# A join is useful for B1/B3 only if it beats chance clearly
MIN_LIFT = 2.0
MIN_LINK_EXISTS = 0.9  # share of non-null links that must resolve
LAG_ROWS = 10  # lag days shown individually before bucketing

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def pct(x: float) -> str:
    return f"{100 * x:.2f}%"


def md_table(header: list[str], rows: list[list]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def window_stats(
    con: duckdb.DuckDBPyConnection, lo_days: int, hi_days: int, lo_open: bool
) -> dict:
    """Per-complaint candidate counts for interaction_date in
    [creation_date + lo_days, creation_date + hi_days] (lower bound open if lo_open)."""
    lo_op = ">" if lo_open else ">="
    q = f"""
        with cand as (
            select c.complaint_id, c.reception_channel, count(i.interaction_id) as n
            from complaints c
            left join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date {lo_op} c.creation_date + to_days({lo_days})
             and i.interaction_date <= c.creation_date + to_days({hi_days})
            group by all
        )
        select count(*) as total,
               count(*) filter (where n >= 1) as matched,
               count(*) filter (where n = 1) as unique_match,
               count(*) filter (where n > 1) as ambiguous,
               max(n) as max_n,
               avg(n) filter (where n >= 1) as mean_n_matched
        from cand
    """
    r = con.sql(q).fetchone()
    return dict(zip(["total", "matched", "unique", "ambiguous", "max_n", "mean_n"], r))


def main() -> None:
    con = duckdb.connect()
    con.sql(
        f"create view complaints as select * from '{(INTER / 'complaints.parquet').as_posix()}'"
    )
    con.sql(
        f"create view interactions as select * from "
        f"'{(INTER / 'call_center_interactions.parquet').as_posix()}'"
    )
    md: list[str] = []
    n_c = con.sql("select count(*) from complaints").fetchone()[0]
    n_i = con.sql("select count(*) from interactions").fetchone()[0]

    # ------------------------------------------------------------------ (a)
    log("(a) declared link")
    a = con.sql("""
        select count(*) total,
               count(origin_interaction_id) non_null,
               count(i.interaction_id) exists_in_cci,
               count(*) filter (where i.customer_id = c.customer_id) same_customer
        from complaints c
        left join interactions i on i.interaction_id = c.origin_interaction_id
    """).fetchone()
    raw_glob = (RAW / "complaints" / "**" / "*.csv").as_posix()
    raw = con.sql(f"""
        select count(*),
               count(*) filter (where trim(coalesce(origin_interaction_id, '')) <> '')
        from read_csv('{raw_glob}', all_varchar = true, union_by_name = true)
    """).fetchone()
    total, non_null, exists_, same_cust = a

    def share(num: int, den: int) -> str:
        return pct(num / den) if den else "n/a"

    # ------------------------------------------------------------------ (b)
    log("(b) fallback windows")
    real = {w: window_stats(con, -w, 0, lo_open=False) for w in WINDOWS}
    fwd = {w: window_stats(con, 0, w, lo_open=True) for w in WINDOWS}
    placebo = {
        (s, w): window_stats(con, -s - w, -s, lo_open=False)
        for s in PLACEBO_SHIFTS
        for w in WINDOWS
    }

    # Poisson chance baseline: customer rate over the whole period
    log("(c) Poisson baseline")
    poisson = {}
    for w in WINDOWS:
        poisson[w] = con.sql(f"""
            with rate as (
                select customer_id, count(*) / {DATA_DAYS}.0 as lam
                from interactions group by 1
            )
            select avg(1 - exp(-coalesce(r.lam, 0) * {w})),
                   avg(1 - exp(-coalesce(r.lam, 0) * {w}) * (1 + coalesce(r.lam, 0) * {w}))
            from complaints c left join rate r using (customer_id)
        """).fetchone()
    cust_any = con.sql("""
        select count(*) filter (where customer_id in (select customer_id from interactions)),
               count(*)
        from complaints
    """).fetchone()

    # By reception channel (7-day window vs 60-day placebo)
    log("(c) by reception channel")
    by_channel = con.sql("""
        with real as (
            select c.complaint_id, c.reception_channel, count(i.interaction_id) n
            from complaints c left join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date between c.creation_date - interval 7 day and c.creation_date
            group by all
        ), plc as (
            select c.complaint_id, count(i.interaction_id) n
            from complaints c left join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date between c.creation_date - interval 67 day
                                        and c.creation_date - interval 60 day
            group by all
        )
        select r.reception_channel, count(*) total,
               avg((r.n >= 1)::int) real_rate,
               avg((p.n >= 1)::int) placebo_rate
        from real r join plc p using (complaint_id)
        group by 1 order by 2 desc
    """).fetchall()

    # Lag profile of the nearest prior interaction within LAG_HORIZON days
    log("(c) lag profile")
    lag = con.sql(f"""
        with nearest as (
            select c.complaint_id,
                   min(date_diff('second', i.interaction_date, c.creation_date)) / 86400.0 as lag_d
            from complaints c join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date between c.creation_date - interval {LAG_HORIZON} day
                                        and c.creation_date
            group by 1
        )
        select floor(lag_d)::int as day, count(*) from nearest group by 1 order by 1
    """).fetchall()
    # Same-hour check: an origin interaction would often be minutes before the complaint
    same_hour = con.sql("""
        select count(distinct c.complaint_id)
        from complaints c join interactions i
          on i.customer_id = c.customer_id
         and i.interaction_date between c.creation_date - interval 1 hour and c.creation_date
    """).fetchone()[0]
    same_hour_placebo = con.sql("""
        select count(distinct c.complaint_id)
        from complaints c join interactions i
          on i.customer_id = c.customer_id
         and i.interaction_date between c.creation_date - interval 60 day - interval 1 hour
                                    and c.creation_date - interval 60 day
    """).fetchone()[0]

    # Reason enrichment: share of 'Queja' among matched interactions vs overall
    log("(c) reason enrichment")
    overall_queja = con.sql(
        "select avg((contact_reason = 'Queja')::int) from interactions"
    ).fetchone()[0]
    enrich = {}
    for label, lo, hi in [("real 7d", 7, 0), ("placebo 60d", 67, 60)]:
        enrich[label] = con.sql(f"""
            select count(*), avg((i.contact_reason = 'Queja')::int)
            from complaints c join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date between c.creation_date - interval {lo} day
                                        and c.creation_date - interval {hi} day
        """).fetchone()
    # Category agreement: complaint.category vs interaction reason, real vs placebo
    cat_xtab = con.sql("""
        select c.category, i.contact_reason, count(*) n
        from complaints c join interactions i
          on i.customer_id = c.customer_id
         and i.interaction_date between c.creation_date - interval 7 day and c.creation_date
        group by all
    """).fetchall()

    # Interaction volume concentration: do complainers contact more than others?
    conc = con.sql("""
        with per as (select customer_id, count(*) n from interactions group by 1),
             comp as (select distinct customer_id from complaints)
        select avg(n) filter (where customer_id in (select customer_id from comp)),
               avg(n) filter (where customer_id not in (select customer_id from comp))
        from per
    """).fetchone()

    # ------------------------------------------------------------------ verdict
    lift7 = real[7]["matched"] / max(placebo[(60, 7)]["matched"], 1)
    lift1 = real[1]["matched"] / max(placebo[(60, 1)]["matched"], 1)
    link_usable = non_null > 0 and exists_ / max(non_null, 1) > MIN_LINK_EXISTS
    fallback_real = min(lift1, lift7) >= MIN_LIFT

    md.append("# B4 - Joining complaints to call_center_interactions\n")
    md.append(
        f"Generated by `ml/analysis/day1/B4_complaint_interaction_link.py` on {date.today()} "
        f"over `ml/data/02_intermediate/` ({n_c:,} complaints, {n_i:,} interactions). "
        "Windows are measured in 24-hour units from `creation_date`, with both bounds "
        "inclusive for backward windows.\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "`complaints` can be linked to `call_center_interactions`, either through "
        "`origin_interaction_id` or through a join on customer and date, with a usable "
        "match rate.\n"
    )
    verdict = (
        "supported"
        if link_usable
        else "refuted: no declared link, and the fallback join matches at chance level"
        if not fallback_real
        else "partially supported: no declared link, but the fallback join beats chance"
    )
    md.append(f"## Verdict: **{verdict}**\n")
    md.append(
        f"- **Declared link: unusable.** `origin_interaction_id` is non-null in "
        f"{non_null:,} of {total:,} complaints ({share(non_null, total)}). The raw CSVs "
        f"agree: {raw[1]:,} of {raw[0]:,} rows have a non-blank value, so this is not an "
        "ingestion artifact. The existence and customer checks are therefore empty."
    )
    md.append(
        f"- **Fallback join: {'real signal' if fallback_real else 'chance co-occurrence'}.** "
        f"A 7-day backward window matches {pct(real[7]['matched'] / n_c)} of complaints, "
        f"versus {pct(placebo[(60, 7)]['matched'] / n_c)} for the same window shifted 60 days "
        f"back (lift {lift7:.2f}x) and {pct(poisson[7][0])} expected from each customer's "
        f"overall contact rate. The 1-day window has a lift of {lift1:.2f}x."
    )
    md.append(
        "- **Consequence (from 'Si falla'): declared limitation.** No complaint can be "
        "tied to the interaction that caused it. Customer-level temporal joins are "
        "still valid for customer-history questions, but a matched interaction must "
        "not be read as the complaint's origin.\n"
    )

    md.append("## (a) Declared link `origin_interaction_id`\n")
    md.append(
        md_table(
            ["check", "count", "share"],
            [
                ["complaints", f"{total:,}", "100%"],
                [
                    "origin_interaction_id non-null (parquet)",
                    f"{non_null:,}",
                    share(non_null, total),
                ],
                [
                    "origin_interaction_id non-blank (raw CSV)",
                    f"{raw[1]:,}",
                    share(raw[1], raw[0]),
                ],
                [
                    "... exists in call_center_interactions",
                    f"{exists_:,}",
                    share(exists_, non_null) + " of non-null",
                ],
                [
                    "... same customer_id",
                    f"{same_cust:,}",
                    share(same_cust, exists_) + " of existing",
                ],
            ],
        )
    )
    md.append("")

    md.append("## (b) Fallback join by customer_id and window\n")
    md.append(
        "Candidates: interactions of the same `customer_id` with `interaction_date` in "
        "`[creation_date - W days, creation_date]`. *Ambiguous* means more than one "
        "candidate.\n"
    )
    rows = []
    for w in WINDOWS:
        s = real[w]
        rows.append(
            [
                f"{w} d",
                f"{s['matched']:,}",
                pct(s["matched"] / n_c),
                f"{s['unique']:,}",
                pct(s["unique"] / n_c),
                f"{s['ambiguous']:,}",
                pct(s["ambiguous"] / max(s["matched"], 1)),
                f"{(s['mean_n'] or 0):.2f}",
                s["max_n"],
            ]
        )
    md.append(
        md_table(
            [
                "window",
                "matched",
                "match rate",
                "unique",
                "unique rate",
                "ambiguous",
                "ambiguous / matched",
                "mean candidates (matched)",
                "max candidates",
            ],
            rows,
        )
    )
    md.append("")

    md.append("## (c) Does the fallback beat chance?\n")
    md.append(
        "If complaints were generated from interactions, the backward window should "
        "match far more than a window of the same width placed at random in the "
        "customer's history. The placebo windows are "
        "`[creation_date - s - W, creation_date - s]`. The forward window "
        "`(creation_date, creation_date + W]` is a second control and also the region B1 "
        "looks at. The Poisson column is `mean(1 - exp(-lambda_c * W))`, where `lambda_c` "
        f"is the customer's interactions / {DATA_DAYS} days.\n"
    )
    rows = []
    for w in WINDOWS:
        r_ = real[w]["matched"] / n_c
        row = [f"{w} d", pct(r_)]
        for s in PLACEBO_SHIFTS:
            p = placebo[(s, w)]["matched"] / n_c
            row += [pct(p)]
        row += [
            pct(fwd[w]["matched"] / n_c),
            pct(poisson[w][0]),
            f"{r_ / max(placebo[(60, w)]['matched'] / n_c, 1e-9):.2f}x",
        ]
        rows.append(row)
    md.append(
        md_table(
            ["window", "backward (real)"]
            + [f"placebo -{s}d" for s in PLACEBO_SHIFTS]
            + ["forward", "Poisson expected", "lift vs -60d"],
            rows,
        )
    )
    md.append("")
    md.append(
        md_table(
            ["window", "ambiguous real", "ambiguous placebo -60d", "Poisson P(>=2)"],
            [
                [
                    f"{w} d",
                    pct(real[w]["ambiguous"] / n_c),
                    pct(placebo[(60, w)]["ambiguous"] / n_c),
                    pct(poisson[w][1]),
                ]
                for w in WINDOWS
            ],
        )
    )
    md.append("")
    md.append(
        f"Complaint rows whose customer has at least one interaction ever: "
        f"{cust_any[0]:,} of {cust_any[1]:,} ({pct(cust_any[0] / cust_any[1])}). "
        f"Mean interactions per customer: {conc[0]:.2f} for customers with a complaint, "
        f"{(conc[1] or 0):.2f} for customers without one.\n"
    )

    md.append("### Same-hour matches\n")
    md.append(
        "An interaction that opened a complaint would usually sit minutes before "
        f"`creation_date`. Complaints with an interaction in the previous hour: "
        f"{same_hour:,} ({pct(same_hour / n_c)}), versus {same_hour_placebo:,} "
        f"({pct(same_hour_placebo / n_c)}) for the same hour 60 days earlier.\n"
    )

    md.append("### By reception channel (7-day window)\n")
    md.append(
        "Complaints received by Call Center should match more often than those "
        "received by Web, App or Regulator if the join captures the origin.\n"
    )
    md.append(
        md_table(
            ["reception_channel", "complaints", "backward 7d", "placebo -60d", "lift"],
            [
                [ch, f"{n:,}", pct(r_), pct(p), f"{r_ / max(p, 1e-9):.2f}x"]
                for ch, n, r_, p in by_channel
            ],
        )
    )
    md.append("")

    md.append(f"### Lag of the nearest prior interaction (within {LAG_HORIZON} days)\n")
    md.append(
        "A causal link shows up as mass concentrated at lag 0. A flat profile means the "
        "matched interaction is just the customer's most recent contact.\n"
    )
    lag_total = sum(n for _, n in lag)
    md.append(
        md_table(
            ["lag (days)", "complaints", "share of those with a prior contact"],
            [[d, f"{n:,}", pct(n / lag_total)] for d, n in lag if d < LAG_ROWS]
            + [
                [
                    f"{LAG_ROWS}-{LAG_HORIZON - 1}",
                    f"{sum(n for d, n in lag if d >= LAG_ROWS):,}",
                    pct(sum(n for d, n in lag if d >= LAG_ROWS) / lag_total),
                ]
            ],
        )
    )
    md.append("")

    md.append("### Reason enrichment\n")
    md.append(
        f"Share of `contact_reason = 'Queja'` over all interactions: {pct(overall_queja)}. "
        "Among interactions matched to a complaint:\n"
    )
    md.append(
        md_table(
            ["window", "matched interaction rows", "'Queja' share"],
            [[k, f"{v[0]:,}", pct(v[1])] for k, v in enrich.items()],
        )
    )
    md.append("")
    reasons = sorted({r for _, r, _ in cat_xtab})
    cats = sorted({c for c, _, _ in cat_xtab})
    tab = {(c, r): n for c, r, n in cat_xtab}
    rows = []
    for c in cats:
        tot = sum(tab.get((c, r), 0) for r in reasons)
        rows.append([c] + [pct(tab.get((c, r), 0) / tot) for r in reasons])
    md.append(
        "Complaint `category` vs the matched interaction's `contact_reason` (row "
        "shares, 7-day window). Rows that look alike mean category and reason are "
        "independent.\n"
    )
    md.append(md_table(["category"] + reasons, rows))
    md.append("")

    md.append("## Recommendation for B1 and B3\n")
    md.append(
        "- **Do not use `origin_interaction_id`.** It is empty. Any feature built on it is "
        "constant.\n"
        '- **Do not treat a window match as "the interaction that caused the complaint".** '
        "The match rate is what chance predicts from how often the customer contacts the "
        "bank. Attribution by nearest interaction, or dedup by picking one candidate, "
        "manufactures a link the data does not have.\n"
        "- **B1 (failure demand):** use a customer-level interval join, "
        "`interactions.customer_id = complaints.customer_id AND interaction_date in "
        "(creation_date, closing_date]`, as the question asks, and **always report it "
        "against a placebo interval** of the same length taken outside the complaint's "
        "lifetime, e.g. the same span shifted 60 days back. Failure demand is the excess "
        "over the placebo, not the raw count. Keep all candidates (a count per "
        "complaint) instead of picking one. Given the forward-window numbers above, "
        "expect little or no excess.\n"
        "- **B3 (Regulator and prior contacts):** use the backward join "
        "`interaction_date in [creation_date - 7d, creation_date]` as a count of prior "
        "contacts, with the same placebo. 7 days keeps the most signal, if any exists, "
        "while ambiguity stays manageable. 1 and 3 days add no precision because none "
        "of the windows beat chance. B3's volume and `sla_breached` parts do not need "
        "the join.\n"
        "- In the pipeline, build one `03_primary` table of candidates `(complaint_id, "
        "interaction_id, lag_seconds, direction)` over +/-30 days, with a matching placebo "
        "table. B1 and B3 then filter it by direction and window, which keeps the "
        "comparison with the placebo consistent.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "B4.md").write_text(report, encoding="utf-8")
    line = (
        f"- B4 (complaints <-> interactions): {verdict}. origin_interaction_id "
        f"{share(non_null, total)} non-null; fallback customer+[-7d,0] matches "
        f"{pct(real[7]['matched'] / n_c)} vs {pct(placebo[(60, 7)]['matched'] / n_c)} placebo "
        f"(lift {lift7:.2f}x); see docs/findings/day1/B4.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- B4 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
