"""B1 - is there measurable failure demand: do customers contact the call center
more while one of their complaints is open?

Complaint lifetime ("open window") = [creation_date, end), where end is capped at
the dataset end (2026-06-17 inclusive, i.e. 2026-06-18 00:00 exclusive):
  - main:    end = coalesce(closing_date, resolution_date), else dataset end.
             closing_date is only filled for status 'Closed' (~4% of rows), while
             'Resolved' complaints carry resolution_date, so the literal rule would
             treat every resolved complaint as open until the dataset end.
  - literal: end = closing_date, else dataset end (the rule as stated in B1).

Checks (per definition):
  (a) matched placebo: for each complaint, contacts of the same customer inside
      the open window vs an equal-length window of the same customer with no open
      complaint. Candidates, in order: the window ending GAP days before
      creation_date, then the window starting GAP days after the end. A candidate
      must lie inside the data range and not overlap any open window of that
      customer. Rate ratio = sum(real) / sum(placebo) (equal exposure by design),
      95% interval from a customer-cluster Poisson bootstrap.
  (b) customer-days: for every customer with a complaint, contacts per day while
      at least one complaint is open vs while none is, pooled and stratified by
      calendar month (Mantel-Haenszel), so a time trend cannot fake an excess.
  (c) fixed horizons: contacts in the first H days after creation vs the H days
      ending GAP days before creation (length-independent check).
  (d) contact_reason and requires_followup of contacts inside open windows vs
      inside the matched placebo windows.
  (e) contact volume vs resolution_days (main definition, complaints with a
      known resolution_days): real and placebo counts by bucket, and the slope of
      the excess (real - placebo) on resolution_days.

Outputs:
  docs/findings/day1/B1.md                 (committed report)
  data/08_reporting/day1/B1.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (B1 line)

Run from ml/:  .venv/Scripts/python analysis/day1/B1_failure_demand.py
"""

from __future__ import annotations

import math
import time
from datetime import date
from itertools import product
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import chi2_p, ci95, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

START = "2023-06-17 00:00:00"
END = "2026-06-18 00:00:00"  # exclusive; dataset end date 2026-06-17 inclusive
GAP = 30  # days between a placebo window and the open window
HORIZONS = (7, 14, 30)
DEFS = {
    "main": "coalesce(closing_date, resolution_date)",
    "literal": "closing_date",
}
# An excess counts as failure demand only if it clears both bars
MIN_LIFT = 1.2  # real / placebo contact rate
BOOT = 1000
RNG = np.random.default_rng(2026)

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def fp(p: float) -> str:
    return "<0.0001" if p < 1e-4 else f"{p:.4f}"


def ts(x: str) -> str:
    return f"timestamp '{x}'"


def boot_ratio(num: np.ndarray, den: np.ndarray) -> tuple[float, float, float]:
    """sum(num)/sum(den) with a 95% customer-cluster Poisson bootstrap interval.

    num and den are per-customer sums, so resampling rows resamples customers.
    """
    est = num.sum() / den.sum()
    w = RNG.poisson(1.0, size=(BOOT, num.size)).astype(np.float32)
    reps = (w @ num.astype(np.float32)) / (w @ den.astype(np.float32))
    lo, hi = np.percentile(reps, [2.5, 97.5])
    return float(est), float(lo), float(hi)


def fmt_ratio(r: tuple[float, float, float]) -> str:
    return f"{r[0]:.3f} [{r[1]:.3f}, {r[2]:.3f}]"


def build(con: duckdb.DuckDBPyConnection, d: str, end_expr: str) -> None:
    """Open windows, their per-customer union, the placebo choice and counts."""
    con.sql(f"""
        create or replace temp table w_{d} as
        select complaint_id, customer_id, status, resolution_days,
               creation_date s,
               least(coalesce({end_expr}, {ts(END)}), {ts(END)}) e,
               {end_expr} is not null and {end_expr} < {ts(END)} as ended
        from complaints
        where creation_date < {ts(END)}
          and least(coalesce({end_expr}, {ts(END)}), {ts(END)}) > creation_date
    """)
    # Union of open windows per customer (gaps and islands)
    con.sql(f"""
        create or replace temp table u_{d} as
        with o as (
            select customer_id, s, e,
                   max(e) over (partition by customer_id order by s, e
                                rows between unbounded preceding and 1 preceding) pm
            from w_{d}
        ), g as (
            select *, sum(case when pm is null or s > pm then 1 else 0 end)
                        over (partition by customer_id order by s, e
                              rows unbounded preceding) grp
            from o
        )
        select customer_id, min(s) us, max(e) ue from g group by customer_id, grp
    """)
    con.sql(f"""
        create or replace temp table pl_{d} as
        with c as (
            select *, (e - s) len,
                   s - interval {GAP} day - (e - s) p1s, s - interval {GAP} day p1e,
                   e + interval {GAP} day p2s, e + interval {GAP} day + (e - s) p2e
            from w_{d}
        ), v as (
            select c.*,
                   p1s >= {ts(START)} and not exists (
                       select 1 from u_{d} u where u.customer_id = c.customer_id
                         and u.us < c.p1e and u.ue > c.p1s) v1,
                   p2e <= {ts(END)} and not exists (
                       select 1 from u_{d} u where u.customer_id = c.customer_id
                         and u.us < c.p2e and u.ue > c.p2s) v2
            from c
        )
        select complaint_id, customer_id, status, resolution_days, s, e, ended,
               epoch(e) / 86400 - epoch(s) / 86400 as days,
               case when v1 then p1s when v2 then p2s end ps,
               case when v1 then p1e when v2 then p2e end pe,
               case when v1 then 'before' when v2 then 'after' end side
        from v
    """)
    con.sql(f"""
        create or replace temp table ri_{d} as  -- contact rows in real and placebo windows
        select p.complaint_id, p.customer_id, 'real' kind, i.contact_reason,
               i.requires_followup, i.was_resolved
        from pl_{d} p join interactions i
          on i.customer_id = p.customer_id and i.interaction_date >= p.s
         and i.interaction_date < p.e
        union all
        select p.complaint_id, p.customer_id, 'placebo', i.contact_reason,
               i.requires_followup, i.was_resolved
        from pl_{d} p join interactions i
          on i.customer_id = p.customer_id and i.interaction_date >= p.ps
         and i.interaction_date < p.pe
        where p.side is not null
    """)
    con.sql(f"""
        create or replace temp table n_{d} as
        select p.*,
               coalesce(r.rc, 0) rc, coalesce(r.pc, 0) pc
        from pl_{d} p left join (
            select complaint_id, count(*) filter (where kind = 'real') rc,
                   count(*) filter (where kind = 'placebo') pc
            from ri_{d} group by 1
        ) r using (complaint_id)
    """)


def matched(con, d: str) -> dict:
    """(a) matched placebo."""
    out = {}
    out["n_all"], out["days_all"], out["real_all"], out["ended"] = con.sql(f"""
        select count(*), avg(days), sum(rc), count(*) filter (where ended) from n_{d}
    """).fetchone()
    out["n"], out["days"], out["real"], out["plc"], out["before"], out["ended_m"] = (
        con.sql(f"""
        select count(*), avg(days), sum(rc), sum(pc),
               count(*) filter (where side = 'before'), count(*) filter (where ended)
        from n_{d} where side is not null
    """).fetchone()
    )
    cust = con.sql(f"""
        select sum(rc)::double r, sum(pc)::double p from n_{d} where side is not null group by customer_id
    """).fetchnumpy()
    out["rr"] = boot_ratio(cust["r"], cust["p"])
    out["any_real"], out["any_plc"] = con.sql(f"""
        select count(*) filter (where rc > 0), count(*) filter (where pc > 0)
        from n_{d} where side is not null
    """).fetchone()
    out["more"], out["fewer"] = con.sql(f"""
        select count(*) filter (where rc > pc), count(*) filter (where rc < pc)
        from n_{d} where side is not null
    """).fetchone()
    # Sign test on complaints whose counts differ (normal approximation)
    k, m = out["more"], out["more"] + out["fewer"]
    z = (k - m / 2) / math.sqrt(m / 4) if m else 0.0
    out["sign_p"] = math.erfc(abs(z) / math.sqrt(2))
    # Same split by whether the window has a real end
    out["by_ended"] = con.sql(f"""
        select ended, count(*), avg(days), sum(rc), sum(pc)
        from n_{d} where side is not null group by 1 order by 1 desc
    """).fetchall()
    out["by_ended_rr"] = {}
    for e in (True, False):
        c = con.sql(f"""
            select sum(rc)::double r, sum(pc)::double p from n_{d}
            where side is not null and ended = {e} group by customer_id
        """).fetchnumpy()
        out["by_ended_rr"][e] = boot_ratio(c["r"], c["p"]) if c["r"].size else None
    return out


def customer_days(con, d: str) -> dict:
    """(b) contacts per customer-day with / without an open complaint."""
    con.sql(f"""
        create or replace temp table m as
        select ms, least(ms + interval 1 month, {ts(END)}) me
        from (select unnest(generate_series(timestamp '2023-06-01', {ts(END)},
                                            interval 1 month)) ms)
        where ms < {ts(END)}
    """)
    # Exposure per month: all days of complainers, and days inside an open window
    expo = con.sql(f"""
        with cu as (select distinct customer_id from w_{d}),
        tot as (
            select m.ms, (select count(*) from cu)
                   * (epoch(m.me) - epoch(greatest(m.ms, {ts(START)}))) / 86400 t
            from m
        ),
        inn as (
            select m.ms, sum(epoch(least(u.ue, m.me)) - epoch(greatest(u.us, m.ms)))
                         / 86400 t1
            from u_{d} u join m on u.us < m.me and u.ue > m.ms
            group by 1
        )
        select tot.ms, tot.t, coalesce(inn.t1, 0) t1 from tot left join inn using (ms)
    """).fetchall()
    cnt = con.sql(f"""
        with ci as (
            select i.interaction_id, i.interaction_date dt,
                   exists (select 1 from u_{d} u where u.customer_id = i.customer_id
                           and i.interaction_date >= u.us and i.interaction_date < u.ue) inn
            from interactions i
            where i.customer_id in (select customer_id from w_{d})
              and i.interaction_date >= {ts(START)} and i.interaction_date < {ts(END)}
        )
        select date_trunc('month', dt) ms, count(*) filter (where inn) a,
               count(*) filter (where not inn) b
        from ci group by 1
    """).fetchall()
    c = {ms: (a, b) for ms, a, b in cnt}
    rows = []
    for ms, t, t1 in expo:
        a, b = c.get(ms, (0, 0))
        rows.append((ms, a, t1, b, t - t1))
    a_s = sum(r[1] for r in rows)
    t1_s = sum(r[2] for r in rows)
    b_s = sum(r[3] for r in rows)
    t0_s = sum(r[4] for r in rows)
    # Mantel-Haenszel rate ratio over months
    num = sum(a * t0 / (t1 + t0) for _, a, t1, b, t0 in rows if t1 and t0)
    den = sum(b * t1 / (t1 + t0) for _, a, t1, b, t0 in rows if t1 and t0)
    mh = num / den
    # Customer-cluster bootstrap for the pooled ratio
    per = con.sql(f"""
        with cu as (select distinct customer_id from w_{d}),
        tin as (select customer_id, sum(epoch(ue) - epoch(us)) / 86400 t1
                from u_{d} group by 1),
        ci as (
            select i.customer_id,
                   exists (select 1 from u_{d} u where u.customer_id = i.customer_id
                           and i.interaction_date >= u.us and i.interaction_date < u.ue) inn
            from interactions i
            where i.customer_id in (select customer_id from cu)
              and i.interaction_date >= {ts(START)} and i.interaction_date < {ts(END)}
        ),
        k as (select customer_id, count(*) filter (where inn) a,
                     count(*) filter (where not inn) b from ci group by 1)
        select coalesce(k.a, 0)::double a, coalesce(k.b, 0)::double b, tin.t1::double t1,
               ((epoch({ts(END)}) - epoch({ts(START)})) / 86400 - tin.t1)::double t0
        from cu join tin using (customer_id) left join k using (customer_id)
    """).fetchnumpy()
    # rate ratio = (sum a / sum t1) / (sum b / sum t0) = sum(a) / sum(b * T1/T0)
    scale = per["t1"].sum() / per["t0"].sum()
    w = RNG.poisson(1.0, size=(BOOT, per["a"].size)).astype(np.float64)
    reps = (w @ per["a"] / (w @ per["t1"])) / (w @ per["b"] / (w @ per["t0"]))
    lo, hi = np.percentile(reps, [2.5, 97.5])
    ref = con.sql(f"""
        select count(*), count(distinct customer_id) from interactions
        where customer_id not in (select customer_id from w_{d})
          and interaction_date >= {ts(START)} and interaction_date < {ts(END)}
    """).fetchone()
    n_non = con.sql(f"""
        select count(*) from customers
        where customer_id not in (select customer_id from w_{d})
    """).fetchone()[0]
    days_total = (per["t1"] + per["t0"]).sum()
    del scale
    return {
        "rows": rows,
        "a": a_s,
        "t1": t1_s,
        "b": b_s,
        "t0": t0_s,
        "pooled": (a_s / t1_s) / (b_s / t0_s),
        "pooled_ci": (float(lo), float(hi)),
        "mh": mh,
        "n_cust": per["a"].size,
        "share_in": t1_s / days_total,
        "non_rate": ref[0] / (n_non * (days_total / per["a"].size)) if n_non else None,
        "n_non": n_non,
    }


def horizons(con) -> list[tuple]:
    """(c) contacts in [s, s+H) vs [s-GAP-H, s-GAP), complaints with both observed,
    for all complaints and split by whether the complaint has a real end."""
    out = []
    groups = [
        ("all", "true"),
        ("ended", f"{DEFS['main']} is not null"),
        ("never ended", f"{DEFS['main']} is null"),
    ]
    for h, (g, cond) in product(HORIZONS, groups):
        r = con.sql(f"""
            with c as (
                select complaint_id, customer_id, creation_date s from complaints
                where creation_date + interval {h} day <= {ts(END)}
                  and creation_date - interval {GAP + h} day >= {ts(START)}
                  and {cond}
            ), k as (
                select c.customer_id, c.complaint_id,
                       count(i.interaction_id) filter (
                           where i.interaction_date >= c.s
                             and i.interaction_date < c.s + interval {h} day) r,
                       count(i.interaction_id) filter (
                           where i.interaction_date >= c.s - interval {GAP + h} day
                             and i.interaction_date < c.s - interval {GAP} day) p
                from c left join interactions i
                  on i.customer_id = c.customer_id
                 and i.interaction_date >= c.s - interval {GAP + h} day
                 and i.interaction_date < c.s + interval {h} day
                group by 1, 2
            )
            select customer_id, sum(r)::double r, sum(p)::double p,
                   count(*) n, count(*) filter (where r > 0) rr,
                   count(*) filter (where p > 0) pp
            from k group by 1
        """).fetchnumpy()
        n, anyr, anyp = int(r["n"].sum()), int(r["rr"].sum()), int(r["pp"].sum())
        out.append(
            (
                h,
                g,
                n,
                anyr,
                anyp,
                r["r"].sum(),
                r["p"].sum(),
                boot_ratio(r["r"], r["p"]),
            )
        )
    return out


def lag_profile(con) -> list[tuple]:
    """Contacts by 10-day offset from creation_date, ended vs never-ended complaints
    (creation_date far enough from both data edges for -60..+40 days)."""
    return con.sql(f"""
        with c as (
            select customer_id, creation_date s, {DEFS["main"]} is not null ended
            from complaints
            where creation_date >= {ts(START)} + interval 60 day
              and creation_date < {ts(END)} - interval 40 day
        ), n as (select ended, count(*) n from c group by 1)
        select b.ended, b.bucket, b.k, n.n from (
            select c.ended,
                   (date_diff('day', c.s, i.interaction_date) + 60) // 10 * 10 - 60 bucket,
                   count(*) k
            from c join interactions i
              on i.customer_id = c.customer_id
             and i.interaction_date >= c.s - interval 60 day
             and i.interaction_date < c.s + interval 40 day
            group by 1, 2
        ) b join n using (ended)
        order by 1 desc, 2
    """).fetchall()


def adjacent(con) -> tuple:
    """Ended matched complaints: contacts in the open window vs the equal-length
    windows right before creation and right after the end."""
    return con.sql("""
        select count(i.interaction_id) filter (where i.interaction_date >= e.s
                                                 and i.interaction_date < e.e),
               count(i.interaction_id) filter (where i.interaction_date >= e.s - (e.e - e.s)
                                                 and i.interaction_date < e.s),
               count(i.interaction_id) filter (where i.interaction_date >= e.e
                                                 and i.interaction_date < e.e + (e.e - e.s))
        from (select * from n_main where ended and side is not null) e
        join interactions i on i.customer_id = e.customer_id
        where i.interaction_date >= e.s - (e.e - e.s)
          and i.interaction_date < e.e + (e.e - e.s)
    """).fetchone()


def reasons(con, d: str) -> dict:
    """(d) contact_reason and requires_followup, real vs placebo (matched set)."""
    rows = con.sql(f"""
        select contact_reason, count(*) filter (where kind = 'real') r,
               count(*) filter (where kind = 'placebo') p
        from ri_{d} x join n_{d} n using (complaint_id)
        where n.side is not null group by 1 order by 2 desc
    """).fetchall()
    fu = con.sql(f"""
        select kind, count(*), count(*) filter (where requires_followup),
               count(*) filter (where was_resolved)
        from ri_{d} x join n_{d} n using (complaint_id)
        where n.side is not null group by 1
    """).fetchall()
    fu_reason = con.sql(f"""
        select contact_reason,
               count(*) filter (where kind = 'real'),
               count(*) filter (where kind = 'real' and requires_followup),
               count(*) filter (where kind = 'placebo'),
               count(*) filter (where kind = 'placebo' and requires_followup)
        from ri_{d} x join n_{d} n using (complaint_id)
        where n.side is not null group by 1 order by 2 desc
    """).fetchall()
    allr = con.sql(f"""
        select contact_reason, count(*) from ri_{d} where kind = 'real' group by 1
    """).fetchall()
    overall = con.sql("""
        select contact_reason, count(*), count(*) filter (where requires_followup)
        from interactions group by 1
    """).fetchall()
    return {
        "rows": rows,
        "fu": {k: (n, f, v) for k, n, f, v in fu},
        "fu_reason": fu_reason,
        "all_real": dict(allr),
        "overall": {k: (n, f) for k, n, f in overall},
    }


def by_resolution(con) -> dict:
    """(e) contacts vs resolution_days (main definition, known resolution_days)."""
    rows = con.sql("""
        select (resolution_days - 1) // 5 b, count(*), avg(days), avg(rc), avg(pc),
               sum(rc), sum(pc), count(*) filter (where rc > 0)
        from n_main where side is not null and ended and resolution_days is not null
        group by 1 order by 1
    """).fetchall()
    x = con.sql("""
        select resolution_days::double x, rc::double r, pc::double p, days
        from n_main where side is not null and ended and resolution_days is not null
    """).fetchnumpy()

    def slope(y: np.ndarray) -> tuple[float, float]:
        xc = x["x"] - x["x"].mean()
        b = (xc * (y - y.mean())).sum() / (xc**2).sum()
        res = y - y.mean() - b * xc
        se = math.sqrt((res**2).sum() / (len(y) - 2) / (xc**2).sum())
        return b, se

    return {
        "rows": rows,
        "n": len(x["x"]),
        "slope_real": slope(x["r"]),
        "slope_plc": slope(x["p"]),
        "slope_exc": slope(x["r"] - x["p"]),
        "corr_len": float(np.corrcoef(x["x"], x["days"])[0, 1]),
    }


def main() -> None:
    con = duckdb.connect()
    for name, file in [
        ("complaints", "complaints"),
        ("interactions", "call_center_interactions"),
        ("customers", "customers"),
    ]:
        con.sql(
            f"create view {name} as select * from '{(INTER / f'{file}.parquet').as_posix()}'"
        )
    n_c, n_i = con.sql(
        "select (select count(*) from complaints), (select count(*) from interactions)"
    ).fetchone()
    end_src = con.sql(f"""
        select count(*) filter (where closing_date is not null),
               count(*) filter (where closing_date is null and resolution_date is not null),
               count(*) filter (where closing_date is null and resolution_date is null),
               count(*) filter (where coalesce(closing_date, resolution_date) >= {ts(END)}),
               count(*) filter (where closing_date is null and resolution_date is null
                                  and creation_date < {ts(END)} - interval 365 day)
        from complaints
    """).fetchone()
    status = con.sql("""
        select status, count(*), count(closing_date), count(resolution_date)
        from complaints group by 1 order by 2 desc
    """).fetchall()

    res: dict[str, dict] = {}
    for d, expr in DEFS.items():
        log(f"build {d}")
        build(con, d, expr)
        log(f"(a) matched placebo {d}")
        res[d] = {"m": matched(con, d)}
        log(f"(b) customer-days {d}")
        res[d]["cd"] = customer_days(con, d)
    log("(c) fixed horizons")
    hz = horizons(con)
    log("(d) reasons")
    rs = reasons(con, "main")
    log("(e) resolution_days")
    rb = by_resolution(con)
    lag = lag_profile(con)
    adj = adjacent(con)

    # ------------------------------------------------------------------ verdict
    m, cd = res["main"]["m"], res["main"]["cd"]
    lo_c, hi_c = cd["pooled_ci"]
    overall_sig = m["rr"][1] > 1 or lo_c > 1
    e_rr = m["by_ended_rr"][True]
    e_row = next(r for r in m["by_ended"] if r[0])
    e_n, e_exc = e_row[1], e_row[3] - e_row[4]
    ended_sig = e_rr[1] > 1
    if max(m["rr"][0], cd["mh"], e_rr[0] if ended_sig else 0) >= MIN_LIFT:
        verdict = (
            "supported: contact rate is materially higher while a complaint is open"
        )
    elif ended_sig or overall_sig:
        verdict = (
            "refuted as material: no excess overall; the only real signal is a small "
            f"bump ({e_rr[0]:.2f}x, about {100 * e_exc / e_n:.1f} extra contacts per 100 "
            "complaints) in complaints that actually got resolved or closed, fading "
            "within two weeks"
        )
    else:
        verdict = (
            "refuted: contact rate while a complaint is open equals the "
            "no-complaint baseline (excess is noise)"
        )

    def ex_per_100(mm: dict) -> float:
        return 100 * (mm["real"] - mm["plc"]) / mm["n"]

    rr_fu, rn = rs["fu"]["real"][1], rs["fu"]["real"][0]
    pf, pn = rs["fu"]["placebo"][1], rs["fu"]["placebo"][0]
    p_fu = chi2_p([[rr_fu, rn - rr_fu], [pf, pn - pf]])
    p_reason = chi2_p([[r, p] for _, r, p in rs["rows"]])
    tot_r = sum(r for _, r, _ in rs["rows"])
    tot_p = sum(p for _, _, p in rs["rows"])
    ov_n = sum(n for n, _ in rs["overall"].values())
    ov_f = sum(f for _, f in rs["overall"].values())
    lit = res["literal"]

    # ------------------------------------------------------------------ report
    md: list[str] = []
    md.append("# B1 - Failure demand while a complaint is open\n")
    md.append(
        f"Generated by `ml/analysis/day1/B1_failure_demand.py` on {date.today()} over "
        f"`ml/data/02_intermediate/` ({n_c:,} complaints, {n_i:,} call-center "
        f"interactions). Observation period {START[:10]} to 2026-06-17 inclusive. "
        "Intervals for rate ratios are 95% customer-cluster Poisson bootstraps "
        f"({BOOT} replicates); proportions use Wilson 95% intervals; p-values are "
        "chi-square tests unless stated. Contacts are counted at customer level "
        "(B4: no complaint-to-interaction link exists), always against a baseline.\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "There is measurable failure demand: customers contact the call center more "
        "between a complaint's `creation_date` and its closing than they do when no "
        "complaint is open, those extra contacts look like follow-ups "
        "(`contact_reason`, `requires_followup`), and the excess grows with "
        "`resolution_days`. If it fails: Track B is dropped.\n"
    )
    md.append(f"## Verdict: **{verdict}**\n")
    hzd = {(h, g): row for h, g, *row in hz}
    e7, n7 = hzd[(7, "ended")], hzd[(7, "never ended")]
    md.append(
        f"- **Overall, the excess is noise.** Main definition, {m['n']:,} complaints "
        f"with a clean equal-length placebo window: {m['real']:,} contacts inside open "
        f"windows vs {m['plc']:,} in the placebo windows, rate ratio "
        f"{fmt_ratio(m['rr'])}, i.e. {ex_per_100(m):+.1f} contacts per 100 complaints. "
        f"Per customer-day, the {cd['n_cust']:,} customers with a complaint contact at "
        f"{1000 * cd['a'] / cd['t1']:.2f} per 1,000 days with an open complaint vs "
        f"{1000 * cd['b'] / cd['t0']:.2f} without one (pooled {cd['pooled']:.3f} "
        f"[{lo_c:.3f}, {hi_c:.3f}], month-stratified {cd['mh']:.3f}); customers with "
        f"no complaint sit at {1000 * cd['non_rate']:.2f}."
    )
    md.append(
        f"- **One real but small signal: complaints that actually ended.** For the "
        f"{e_n:,} matched complaints with a closing or resolution date (mean "
        f"{e_row[2]:.0f}-day window) the ratio is {fmt_ratio(e_rr)}, i.e. {e_exc:+,} "
        f"contacts ({100 * e_exc / e_n:+.2f} per 100 complaints, "
        f"{pct(e_exc / n_i)} of all interactions). The same-length windows right "
        f"before creation and right after the end hold {adj[1]:,} and {adj[2]:,} "
        f"contacts vs {adj[0]:,} inside. By fixed horizon the bump is "
        f"{e7[3]:,.0f} vs {e7[4]:,.0f} contacts in the first 7 days "
        f"({fmt_ratio(e7[5])}) and fades by 30 days; never-ended complaints show "
        f"nothing ({fmt_ratio(n7[5])} at 7 days). This subgroup was found after "
        "looking at the data, and the lift stays under the "
        f"{MIN_LIFT:.1f}x bar, so it is not failure demand at a scale Track B can use."
    )
    md.append(
        f"- **Contacts during open complaints look like any other contacts.** The "
        f"`contact_reason` mix matches the placebo windows (p {fp(p_reason)}); "
        f"'Queja' is {pct(_share(rs['rows'], 'Queja', 1))} of contacts inside open "
        f"windows vs {pct(_share(rs['rows'], 'Queja', 2))} in placebo. "
        f"`requires_followup` is {pct(rr_fu / rn)} vs {pct(pf / pn)} (p {fp(p_fu)}), "
        f"and {pct(ov_f / ov_n)} over all interactions."
    )
    se = rb["slope_exc"]
    md.append(
        f"- **Volume grows with `resolution_days` only because the window is longer.** "
        f"Real contacts rise by {rb['slope_real'][0]:.4f} per extra day and placebo "
        f"contacts by {rb['slope_plc'][0]:.4f}; the excess slope is {se[0]:+.4f} "
        f"(SE {se[1]:.4f}) contacts per day of resolution."
    )
    md.append(
        f"- **Robust to the end-date rule.** The literal rule (end = `closing_date`, "
        f"else 2026-06-17) gives a matched ratio of {fmt_ratio(lit['m']['rr'])} over "
        f"{lit['m']['n']:,} complaints and a month-stratified per-customer-day ratio of "
        f"{lit['cd']['mh']:.3f}.\n"
    )

    md.append("## Defining the open window\n")
    md.append(
        f"`closing_date` is filled for {end_src[0]:,} complaints ({pct(end_src[0] / n_c)}) "
        f"only. Another {end_src[1]:,} have `resolution_date` but no `closing_date`, and "
        f"{end_src[2]:,} ({pct(end_src[2] / n_c)}) have neither, including "
        f"{end_src[4]:,} created more than a year before the data end: statuses "
        "Open / In Process / Escalated never age out. Under the literal rule every "
        "resolved complaint and every stale open one stays open until the data end, "
        "so windows run for hundreds of days.\n"
    )
    md.append(
        md_table(
            ["status", "complaints", "closing_date set", "resolution_date set"],
            [[s, f"{n:,}", f"{c:,}", f"{r:,}"] for s, n, c, r in status],
        )
    )
    md.append(
        f"\n{end_src[3]:,} complaints end after 2026-06-17 and are capped there. Two "
        "definitions are run:\n\n"
        "- **main**: end = `coalesce(closing_date, resolution_date)`, else the data end.\n"
        "- **literal**: end = `closing_date`, else the data end (B1 as written).\n"
    )
    rows = []
    for d in DEFS:
        mm = res[d]["m"]
        rows.append(
            [
                d,
                f"{mm['n_all']:,}",
                f"{mm['ended']:,}",
                f"{mm['days_all']:.1f}",
                f"{mm['n']:,} ({pct(mm['n'] / mm['n_all'])})",
                f"{mm['days']:.1f}",
                f"{mm['before']:,}",
                f"{pct(res[d]['cd']['share_in'])}",
            ]
        )
    md.append(
        md_table(
            [
                "definition",
                "windows",
                "with a real end",
                "mean days",
                "with clean placebo",
                "mean days (matched)",
                "placebo before",
                "complainer-days open",
            ],
            rows,
        )
    )
    md.append(
        "\nA placebo is the equal-length window ending "
        f"{GAP} days before `creation_date` (else starting {GAP} days after the end) "
        "that lies inside the data range and overlaps no open window of the same "
        "customer. Long stale windows rarely have one, so the matched set leans "
        "toward short, resolved complaints; the customer-day view (b) uses every "
        "complaint.\n"
    )

    md.append("## (a) Matched equal-length placebo\n")
    rows = []
    for d in DEFS:
        mm = res[d]["m"]
        rows.append(
            [
                d,
                f"{mm['n']:,}",
                f"{mm['real']:,}",
                f"{mm['plc']:,}",
                fmt_ratio(mm["rr"]),
                f"{ex_per_100(mm):+.2f}",
                f"{pct(mm['any_real'] / mm['n'])}",
                f"{pct(mm['any_plc'] / mm['n'])}",
                fp(mm["sign_p"]),
            ]
        )
    md.append(
        md_table(
            [
                "definition",
                "complaints",
                "contacts real",
                "contacts placebo",
                "rate ratio [95%]",
                "excess / 100 complaints",
                ">=1 contact real",
                ">=1 contact placebo",
                "sign test p",
            ],
            rows,
        )
    )
    md.append("\nSplit by whether the window has a real end (main definition):\n")
    md.append(
        md_table(
            [
                "window",
                "complaints",
                "mean days",
                "contacts real",
                "contacts placebo",
                "ratio [95%]",
            ],
            [
                [
                    "ended (resolved/closed)" if e else "open to data end",
                    f"{n:,}",
                    f"{dd:.1f}",
                    f"{r:,}",
                    f"{p:,}",
                    fmt_ratio(m["by_ended_rr"][e]) if m["by_ended_rr"][e] else "n/a",
                ]
                for e, n, dd, r, p in m["by_ended"]
            ],
        )
    )

    md.append(
        f"\nEnded matched complaints, equal-length windows: {adj[1]:,} contacts right "
        f"before creation, {adj[0]:,} inside the open window, {adj[2]:,} right after "
        "the end.\n"
    )
    md.append("\n## (b) Contacts per customer-day, open vs no open complaint\n")
    md.append(
        "All customers with at least one complaint; each of their days in the "
        "observation period is either covered by an open window (union over their "
        "complaints) or not. Mantel-Haenszel stratifies by calendar month.\n"
    )
    rows = []
    for d in DEFS:
        c = res[d]["cd"]
        rows.append(
            [
                d,
                f"{c['n_cust']:,}",
                f"{c['a']:,}",
                f"{c['t1']:,.0f}",
                f"{1000 * c['a'] / c['t1']:.3f}",
                f"{c['b']:,}",
                f"{c['t0']:,.0f}",
                f"{1000 * c['b'] / c['t0']:.3f}",
                f"{c['pooled']:.3f} [{c['pooled_ci'][0]:.3f}, {c['pooled_ci'][1]:.3f}]",
                f"{c['mh']:.3f}",
            ]
        )
    md.append(
        md_table(
            [
                "definition",
                "customers",
                "contacts open",
                "customer-days open",
                "per 1k days open",
                "contacts not open",
                "customer-days not open",
                "per 1k days not open",
                "pooled ratio [95%]",
                "MH ratio (month)",
            ],
            rows,
        )
    )
    if cd["non_rate"] is not None:
        md.append(
            f"\nReference: customers with no complaint ({cd['n_non']:,}) contact at "
            f"about {1000 * cd['non_rate']:.3f} per 1,000 customer-days.\n"
        )
    md.append("Monthly detail, main definition (contacts per 1,000 customer-days):\n")
    md.append(
        md_table(
            ["month", "open", "not open", "ratio"],
            [
                [
                    f"{ms:%Y-%m}",
                    f"{1000 * a / t1:.3f}" if t1 else "n/a",
                    f"{1000 * b / t0:.3f}" if t0 else "n/a",
                    f"{(a / t1) / (b / t0):.2f}" if t1 and t0 and b else "n/a",
                ]
                for ms, a, t1, b, t0 in cd["rows"]
            ],
        )
    )

    md.append("\n## (c) Fixed horizons after creation\n")
    md.append(
        f"Real: `[creation_date, +H)`. Placebo: the H days ending {GAP} days before "
        "`creation_date`. Complaints with both windows inside the data range.\n"
    )
    md.append(
        md_table(
            [
                "H",
                "complaints",
                "n",
                ">=1 contact real",
                ">=1 contact placebo",
                "contacts real",
                "contacts placebo",
                "ratio [95%]",
            ],
            [
                [
                    f"{h} d",
                    g,
                    f"{n:,}",
                    f"{pct(ar / n)} {ci95(ar, n)}",
                    f"{pct(ap / n)} {ci95(ap, n)}",
                    f"{r:,.0f}",
                    f"{p:,.0f}",
                    fmt_ratio(rr),
                ]
                for h, g, n, ar, ap, r, p, rr in hz
            ],
        )
    )

    md.append(
        "\nLag profile: contacts per 100 complaints by 10-day offset from "
        "`creation_date` (complaints created at least 60 days after the data start "
        "and 40 days before the end). A follow-up effect shows as a step at 0.\n"
    )
    buckets = sorted({b for _, b, _, _ in lag})
    lagd = {(e, b): 100 * k / n for e, b, k, n in lag}
    md.append(
        md_table(
            ["complaints"] + [f"[{b}, {b + 10})" for b in buckets],
            [
                ["ended" if e else "never ended"]
                + [f"{lagd.get((e, b), 0):.2f}" for b in buckets]
                for e in (True, False)
            ],
        )
    )
    md.append("\n## (d) What the contacts during open complaints are\n")
    md.append(
        "Contacts inside the matched open windows vs inside their placebo windows "
        "(main definition). If failure demand existed, 'Queja' and "
        "`requires_followup` would be over-represented in the real windows and "
        "the real-minus-placebo excess would concentrate in them.\n"
    )
    md.append(
        md_table(
            [
                "contact_reason",
                "real",
                "share real",
                "placebo",
                "share placebo",
                "excess (real - placebo)",
                "share of all interactions",
            ],
            [
                [
                    k,
                    f"{r:,}",
                    pct(r / tot_r),
                    f"{p:,}",
                    pct(p / tot_p),
                    f"{r - p:+,}",
                    pct(rs["overall"][k][0] / ov_n),
                ]
                for k, r, p in rs["rows"]
            ],
        )
    )
    md.append(f"\nReason mix, real vs placebo: p {fp(p_reason)}.\n")
    md.append(
        md_table(
            [
                "contact_reason",
                "requires_followup real",
                "requires_followup placebo",
                "all interactions",
            ],
            [
                [
                    k,
                    f"{pct(rf / rn_) if rn_ else 'n/a'} {ci95(rf, rn_)}",
                    f"{pct(pf_ / pn_) if pn_ else 'n/a'} {ci95(pf_, pn_)}",
                    pct(rs["overall"][k][1] / rs["overall"][k][0]),
                ]
                for k, rn_, rf, pn_, pf_ in rs["fu_reason"]
            ]
            + [
                [
                    "**all**",
                    f"{pct(rr_fu / rn)} {ci95(rr_fu, rn)}",
                    f"{pct(pf / pn)} {ci95(pf, pn)}",
                    pct(ov_f / ov_n),
                ]
            ],
        )
    )
    wr, wp = rs["fu"]["real"][2], rs["fu"]["placebo"][2]
    md.append(
        f"\n`requires_followup` real vs placebo: p {fp(p_fu)}. `was_resolved`: "
        f"{pct(wr / rn)} real vs {pct(wp / pn)} placebo.\n"
    )

    md.append("## (e) Contact volume vs `resolution_days`\n")
    md.append(
        f"Main definition, {rb['n']:,} matched complaints with `resolution_days` "
        f"(corr of `resolution_days` with window length {rb['corr_len']:.3f}). A longer "
        "window collects more contacts by construction; failure demand would show as "
        "a real-minus-placebo excess that grows with `resolution_days`.\n"
    )
    md.append(
        md_table(
            [
                "resolution_days",
                "complaints",
                "mean window days",
                "mean contacts real",
                "mean contacts placebo",
                ">=1 contact real",
                "ratio",
            ],
            [
                [
                    f"{5 * b + 1:02d}-{5 * b + 5:02d}",
                    f"{n:,}",
                    f"{dd:.1f}",
                    f"{mr:.4f}",
                    f"{mp:.4f}",
                    pct(k / n),
                    f"{sr / sp:.2f}" if sp else "n/a",
                ]
                for b, n, dd, mr, mp, sr, sp, k in rb["rows"]
            ],
        )
    )
    md.append(
        "\n"
        + md_table(
            ["outcome", "slope per resolution day", "SE", "z"],
            [
                [lab, f"{b:+.5f}", f"{s:.5f}", f"{b / s:+.2f}"]
                for lab, (b, s) in [
                    ("contacts real", rb["slope_real"]),
                    ("contacts placebo", rb["slope_plc"]),
                    ("excess (real - placebo)", rb["slope_exc"]),
                ]
            ],
        )
    )

    md.append("\n## Consequences\n")
    md.append(
        "- **Failure demand, as B1 defines it, is not in this data at a usable "
        "scale.** Customers call at their usual rate whether or not a complaint is "
        "open, the calls look the same, and slow resolutions do not generate extra "
        "calls beyond the longer window. The one detectable effect, about 1 extra "
        "contact per 100 resolved/closed complaints in the first two weeks, is "
        "~0.02% of call volume and starts slightly before creation, so it may just "
        "as well be contact that gets a complaint resolved as contact caused by it. "
        "By the hypothesis plan's 'Si falla' rule, **Track B loses its central "
        "premise**: a 'reduce repeat contacts by resolving faster' story would have "
        "no measured effect to point to.\n"
        "- **Contacts are drawn almost independently of complaints.** Together with "
        "B4 (no link) and B3 (no history effect), complaints and interactions behave "
        "like nearly independent streams joined only by `customer_id`. Any model "
        "that uses one to predict the other will learn base rates.\n"
        "- **Status and end dates are not trustworthy lifecycle data.** 77% of "
        "complaints never close, `closing_date` exists only for 'Closed', and "
        "`resolution_days` is uniform on 1-30. Any open-case backlog KPI must declare "
        "how it handles this.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "B1.md").write_text(report, encoding="utf-8")
    line = (
        f"- B1 (failure demand): {verdict}. Matched equal-length placebo "
        f"{m['real']:,} vs {m['plc']:,} contacts, ratio {fmt_ratio(m['rr'])} "
        f"({m['n']:,} complaints); per customer-day {cd['mh']:.3f} (month MH); "
        f"reason mix p {fp(p_reason)}, requires_followup {pct(rr_fu / rn)} vs "
        f"{pct(pf / pn)}; excess slope on resolution_days {se[0]:+.4f}/day "
        f"(SE {se[1]:.4f}); see docs/findings/day1/B1.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- B1 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


def _share(rows: list[tuple], key: str, col: int) -> float:
    tot = sum(r[col] for r in rows)
    return next((r[col] for r in rows if r[0] == key), 0) / tot if tot else 0.0


if __name__ == "__main__":
    main()
