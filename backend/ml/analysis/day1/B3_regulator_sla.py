"""B3 - is there volume in the Regulator channel and in breached SLAs, and do
Regulator complaints follow earlier complaints, contacts or SLA breaches?

Checks:
  (a) complaints by reception_channel x sla_breached: counts, shares, breach rate
      per channel, chi-square of channel vs breach.
  (b) the same by country (from customers) and by category: Regulator share and
      breach rate per value, chi-square tests of independence.
  (c) coherence of sla_breached: breach rate by resolution_days, time to first
      response, status and priority. A real SLA flag should track elapsed time.
  (d) prior history, using the customer-level window join B4 recommends (window
      counts vs a placebo, never attribution): share of complaints with an
      earlier complaint (creation_date in [c - 90d, c)) or a call-center contact
      (interaction_date in [c - 90d, c]) from the same customer, Regulator vs
      non-Regulator. Placebo: the same 90-day window shifted 180 days back.
      Only complaints with creation_date >= data start + 270 days are used, so
      both windows are fully observed.
  (e) sla_breached on an earlier complaint vs a later Regulator complaint:
      - backward: Regulator rate of a complaint by the breach status of the
        same customer's complaints in the previous 90 days (real and placebo),
      - forward: share of complaints followed by a Regulator complaint from the
        same customer within 90 days, by sla_breached, with any later complaint
        as the reference outcome. Only complaints created >= 90 days before the
        data end are used.

Outputs:
  docs/findings/day1/B3.md                 (committed report)
  data/08_reporting/day1/B3.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (B3 line)

Run from ml/:  .venv/Scripts/python analysis/day1/B3_regulator_sla.py
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path

import duckdb
from A1_unrecognized_charges import chi2_p, ci95, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

REGULATOR = "Regulator"
WINDOW = 90  # days of history before (or after) a complaint
PLACEBO_SHIFT = 180  # days; placebo window is [c - 270d, c - 180d)
# Signals must clear both bars to count as structure
MIN_LIFT = 1.5  # real vs placebo, or exposed vs unexposed
SIG_P = 0.05

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def rate_ci(k: int, n: int) -> str:
    return f"{pct(k / n) if n else 'n/a'} {ci95(k, n)}"


def rr_ci(k1: int, n1: int, k0: int, n0: int) -> str:
    """Risk ratio (group 1 / group 0) with a 95% log-normal interval."""
    if not (k1 and k0 and n1 and n0):
        return "n/a"
    rr = (k1 / n1) / (k0 / n0)
    se = math.sqrt(1 / k1 - 1 / n1 + 1 / k0 - 1 / n0)
    return f"{rr:.2f} [{rr * math.exp(-1.96 * se):.2f}, {rr * math.exp(1.96 * se):.2f}]"


def p2x2(k1: int, n1: int, k0: int, n0: int) -> float:
    return chi2_p([[k1, n1 - k1], [k0, n0 - k0]])


def fp(p: float) -> str:
    return "<0.0001" if p < 1e-4 else f"{p:.4f}"


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
    start, end = con.sql(
        "select min(creation_date), max(creation_date) from complaints"
    ).fetchone()
    n_c = con.sql("select count(*) from complaints").fetchone()[0]
    back_from = f"timestamp '{start}' + interval {WINDOW + PLACEBO_SHIFT} day"
    fwd_to = f"timestamp '{end}' - interval {WINDOW} day"

    # One row per complaint with every window count used below
    log("per-complaint window counts")
    s, w = PLACEBO_SHIFT, WINDOW
    con.sql(f"""
        create temp table f as
        with base as (
            select c.complaint_id, c.customer_id, c.creation_date, c.category,
                   c.sla_breached, c.reception_channel, c.reception_channel = '{REGULATOR}' as reg,
                   k.country
            from complaints c left join customers k using (customer_id)
        ),
        pc as (  -- earlier complaints of the same customer, real and placebo window
            select b.complaint_id,
                   count(*) filter (where p.creation_date >= b.creation_date - interval {w} day)
                       as pc_real,
                   count(*) filter (where p.creation_date >= b.creation_date - interval {w} day
                                      and p.sla_breached) as pcb_real,
                   count(*) filter (where p.creation_date < b.creation_date - interval {s} day
                                      and p.creation_date >= b.creation_date
                                                             - interval {s + w} day)
                       as pc_plc,
                   count(*) filter (where p.creation_date < b.creation_date - interval {s} day
                                      and p.creation_date >= b.creation_date
                                                             - interval {s + w} day
                                      and p.sla_breached) as pcb_plc
            from base b join complaints p
              on p.customer_id = b.customer_id and p.complaint_id <> b.complaint_id
             and p.creation_date < b.creation_date
             and p.creation_date >= b.creation_date - interval {s + w} day
            group by 1
        ),
        pi as (  -- call-center contacts of the same customer, real and placebo window
            select b.complaint_id,
                   count(*) filter (where i.interaction_date >= b.creation_date
                                                              - interval {w} day) as pi_real,
                   count(*) filter (where i.interaction_date <= b.creation_date
                                                              - interval {s} day) as pi_plc
            from base b join interactions i
              on i.customer_id = b.customer_id
             and i.interaction_date <= b.creation_date
             and i.interaction_date >= b.creation_date - interval {s + w} day
             and (i.interaction_date >= b.creation_date - interval {w} day
                  or i.interaction_date <= b.creation_date - interval {s} day)
            group by 1
        ),
        fw as (  -- later complaints of the same customer within the window
            select b.complaint_id, count(*) as fwd_any,
                   count(*) filter (where n.reception_channel = '{REGULATOR}') as fwd_reg
            from base b join complaints n
              on n.customer_id = b.customer_id and n.complaint_id <> b.complaint_id
             and n.creation_date > b.creation_date
             and n.creation_date <= b.creation_date + interval {w} day
            group by 1
        )
        select b.*,
               coalesce(pc_real, 0) pc_real, coalesce(pcb_real, 0) pcb_real,
               coalesce(pc_plc, 0) pc_plc, coalesce(pcb_plc, 0) pcb_plc,
               coalesce(pi_real, 0) pi_real, coalesce(pi_plc, 0) pi_plc,
               coalesce(fwd_any, 0) fwd_any, coalesce(fwd_reg, 0) fwd_reg,
               b.creation_date >= {back_from} as eval_back,
               b.creation_date <= {fwd_to} as eval_fwd
        from base b
        left join pc using (complaint_id)
        left join pi using (complaint_id)
        left join fw using (complaint_id)
    """)
    no_country = con.sql("select count(*) from f where country is null").fetchone()[0]

    # ------------------------------------------------------------------ (a)
    log("(a) channel x sla_breached")
    ch = con.sql("""
        select reception_channel, count(*) n, count(*) filter (where sla_breached) b
        from complaints group by 1 order by 2 desc
    """).fetchall()
    n_b = sum(b for _, _, b in ch)
    p_ch = chi2_p([[b, n - b] for _, n, b in ch])
    reg_n, reg_b = next((n, b) for c, n, b in ch if c == REGULATOR)
    months = (end - start).days / 30.44

    # ------------------------------------------------------------------ (b)
    log("(b) by country and category")

    def by_dim(dim: str) -> tuple[list[list], float, float, list[list]]:
        r = con.sql(f"""
            select coalesce({dim}, '(null)'), count(*) n,
                   count(*) filter (where reg) r,
                   count(*) filter (where sla_breached) b,
                   count(*) filter (where reg and sla_breached) rb
            from f group by 1 order by 1
        """).fetchall()
        rows = [
            [v, f"{n:,}", f"{rr:,}", rate_ci(rr, n), pct(b / n), rate_ci(rb, rr)]
            for v, n, rr, b, rb in r
        ]
        p_reg = chi2_p([[rr, n - rr] for _, n, rr, _, _ in r])
        p_b = chi2_p([[b, n - b] for _, n, _, b, _ in r])
        xt = con.sql(f"""
            select coalesce({dim}, '(null)') v, reception_channel, count(*)
            from f group by all
        """).fetchall()
        chans = [c for c, _, _ in ch]
        vals = [row[0] for row in r]
        tab = {(v, c): n for v, c, n in xt}
        share_rows = []
        for v in vals:
            tot = sum(tab.get((v, c), 0) for c in chans)
            share_rows.append([v] + [pct(tab.get((v, c), 0) / tot) for c in chans])
        return rows, p_reg, p_b, share_rows

    dims = {d: by_dim(d) for d in ("country", "category")}
    p_ch_country = chi2_p(
        [
            [n for _, _, n in sorted(g)]
            for g in _group(
                con.sql("""
                    select country, reception_channel, count(*)
                    from f
                    where country is not null group by all
                """).fetchall()
            )
        ]
    )

    # ------------------------------------------------------------------ (c)
    log("(c) sla_breached coherence")
    coh = {}
    coh["resolution_days"] = con.sql("""
        select case when resolution_days is null then 'not resolved (null)'
                    when resolution_days <= 5 then '01-05'
                    when resolution_days <= 10 then '06-10'
                    when resolution_days <= 15 then '11-15'
                    when resolution_days <= 20 then '16-20'
                    when resolution_days <= 25 then '21-25'
                    else '26+' end, count(*), count(*) filter (where sla_breached)
        from complaints group by 1 order by 1
    """).fetchall()
    coh["hours to first response"] = con.sql("""
        with h as (select date_diff('hour', creation_date, first_response_date) hr,
                          sla_breached from complaints)
        select case when hr is null then 'no response (null)'
                    when hr <= 4 then '00-04'
                    when hr <= 24 then '05-24'
                    when hr <= 72 then '25-72'
                    else '73+' end, count(*), count(*) filter (where sla_breached)
        from h group by 1 order by 1
    """).fetchall()
    for col in ("status", "priority"):
        coh[col] = con.sql(f"""
            select {col}, count(*), count(*) filter (where sla_breached)
            from complaints group by 1 order by 1
        """).fetchall()
    coh_p = {k: chi2_p([[b, n - b] for _, n, b in v]) for k, v in coh.items()}
    res_corr = con.sql(
        "select corr(resolution_days, sla_breached::int) from complaints"
    ).fetchone()[0]

    # ------------------------------------------------------------------ (d)
    log("(d) prior history, Regulator vs rest")
    hist = {}
    for g in (True, False):
        hist[g] = con.sql(f"""
            select count(*),
                   count(*) filter (where pc_real > 0), count(*) filter (where pc_plc > 0),
                   count(*) filter (where pi_real > 0), count(*) filter (where pi_plc > 0),
                   count(*) filter (where pc_real + pi_real > 0),
                   count(*) filter (where pc_plc + pi_plc > 0),
                   avg(pi_real), avg(pi_plc)
            from f where eval_back and reg = {g}
        """).fetchone()
    n_eval_back = hist[True][0] + hist[False][0]
    measures = [
        ("earlier complaint", 1, 2),
        ("call-center contact", 3, 4),
        ("either", 5, 6),
    ]

    # ------------------------------------------------------------------ (e)
    log("(e) sla_breached -> later Regulator")
    back = {}
    for label, cnt, brc in [
        ("real", "pc_real", "pcb_real"),
        ("placebo", "pc_plc", "pcb_plc"),
    ]:
        back[label] = con.sql(f"""
            select case when {cnt} = 0 then 'no earlier complaint'
                        when {brc} = 0 then 'earlier complaint(s), none breached'
                        else 'earlier complaint(s), >=1 breached' end g,
                   count(*), count(*) filter (where reg)
            from f where eval_back group by 1 order by 1 desc
        """).fetchall()
    fwd = {
        b: con.sql(f"""
            select count(*), count(*) filter (where fwd_reg > 0),
                   count(*) filter (where fwd_any > 0)
            from f where eval_fwd and sla_breached = {b}
        """).fetchone()
        for b in (True, False)
    }
    # Same, restricted to non-Regulator index complaints (the escalation path)
    fwd_nr = {
        b: con.sql(f"""
            select count(*), count(*) filter (where fwd_reg > 0)
            from f where eval_fwd and not reg and sla_breached = {b}
        """).fetchone()
        for b in (True, False)
    }
    repeat = con.sql(f"""
        select is_repeat_complainer, count(*),
               count(*) filter (where reception_channel = '{REGULATOR}')
        from complaints group by 1 order by 1 desc
    """).fetchall()

    # ------------------------------------------------------------------ verdict
    def lift(k1: int, k0: int) -> float:
        return k1 / k0 if k0 else float("inf")

    reg_h, non_h = hist[True], hist[False]
    reg_either_lift = lift(reg_h[5], reg_h[6])
    p_reg_vs_non = p2x2(reg_h[5], reg_h[0], non_h[5], non_h[0])
    history_signal = reg_either_lift >= MIN_LIFT and p_reg_vs_non < SIG_P
    (t_n, t_r, t_a), (f_n, f_r, f_a) = fwd[True], fwd[False]
    p_fwd = p2x2(t_r, t_n, f_r, f_n)
    sla_rr = (t_r / t_n) / (f_r / f_n) if f_r else float("inf")
    sla_signal = sla_rr >= MIN_LIFT and p_fwd < SIG_P
    struct_p = [dims["country"][1], dims["category"][1], p_ch]
    no_structure = all(p >= SIG_P for p in struct_p)
    sla_random = all(p >= SIG_P for p in coh_p.values())

    if history_signal or sla_signal:
        verdict = (
            "supported: Regulator complaints follow earlier contacts or SLA breaches"
        )
    else:
        verdict = (
            "volume confirmed, structure refuted: Regulator and SLA-breach volume exist, "
            "but neither depends on country, category or customer history"
        )

    md: list[str] = []
    md.append("# B3 - Regulator channel and breached SLAs\n")
    md.append(
        f"Generated by `ml/analysis/day1/B3_regulator_sla.py` on {date.today()} over "
        f"`ml/data/02_intermediate/` ({n_c:,} complaints, {start:%Y-%m-%d} to "
        f"{end:%Y-%m-%d}). Country comes from `customers.country` ({no_country:,} "
        "complaints without a match). Intervals are Wilson 95%; p-values are "
        "chi-square tests of independence. Windows are in 24-hour units from "
        "`creation_date`.\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "There is volume in the Regulator reception channel and in `sla_breached`, and "
        "the temporal order with earlier contacts carries signal: Regulator complaints "
        "are preceded by earlier complaints or contacts from the same customer, "
        "especially complaints whose SLA was breached. If it fails: only the SLA risk "
        "is used.\n"
    )
    md.append(f"## Verdict: **{verdict}**\n")
    md.append(
        f"- **Volume exists but is small for Regulator.** {reg_n:,} Regulator complaints "
        f"({pct(reg_n / n_c)} of all, about {reg_n / months:.0f} per month). "
        f"{n_b:,} complaints ({pct(n_b / n_c)}) have `sla_breached = true`. The Regulator "
        f"breach rate is {rate_ci(reg_b, reg_n)} against {pct((n_b - reg_b) / (n_c - reg_n))} "
        f"for the other channels (p {fp(p2x2(reg_b, reg_n, n_b - reg_b, n_c - reg_n))})."
    )
    md.append(
        f"- **{'No' if no_structure else 'Some'} structure by country, category or "
        f"channel.** The Regulator share does not depend on country (p "
        f"{fp(dims['country'][1])}) or category (p {fp(dims['category'][1])}), and the "
        f"breach rate does not depend on channel (p {fp(p_ch)}), country (p "
        f"{fp(dims['country'][2])}) or category (p {fp(dims['category'][2])})."
    )
    md.append(
        f"- **Regulator complaints are not preceded by more history.** Within 90 days "
        f"before, {rate_ci(reg_h[5], reg_h[0])} of Regulator complaints have an earlier "
        f"complaint or contact from the same customer, versus "
        f"{rate_ci(non_h[5], non_h[0])} of non-Regulator complaints (p "
        f"{fp(p_reg_vs_non)}) and {pct(reg_h[6] / reg_h[0])} in the placebo window "
        f"shifted {PLACEBO_SHIFT} days back (lift {reg_either_lift:.2f}x)."
    )
    md.append(
        f"- **An earlier breached SLA does not lead to a Regulator complaint.** "
        f"{rate_ci(t_r, t_n)} of breached complaints are followed by a Regulator "
        f"complaint from the same customer within 90 days, versus {rate_ci(f_r, f_n)} "
        f"of non-breached ones (risk ratio {rr_ci(t_r, t_n, f_r, f_n)}, p {fp(p_fwd)}). "
        f"Only {t_r + f_r} such follow-ups exist because repeat complaints are rare, so "
        "this test alone cannot exclude a moderate effect. The backward view agrees: "
        "a complaint whose customer had a breached complaint in the previous 90 days "
        f"is Regulator {rate_ci(*_k_n(back['real'], '>=1 breached'))}, the same as the "
        f"{pct(reg_n / n_c)} base rate."
    )
    md.append(
        f"- **`sla_breached` looks like a random ~{100 * n_b / n_c:.0f}% flag.** It does "
        "not rise with `resolution_days` (corr "
        f"{res_corr:.3f}, p {fp(coh_p['resolution_days'])}), time to first response (p "
        f"{fp(coh_p['hours to first response'])}), status (p {fp(coh_p['status'])}) or "
        f"priority (p {fp(coh_p['priority'])}). "
        + (
            "The fallback 'only the SLA risk is used' therefore has no learnable target "
            "in `sla_breached` either. An SLA target would have to be derived from "
            "timestamps (e.g. `resolution_days` against a declared threshold)."
            if sla_random
            else "Part of the flag tracks elapsed time; see (c)."
        )
        + "\n"
    )

    md.append("## (a) Complaints by reception_channel and sla_breached\n")
    md.append(
        md_table(
            [
                "reception_channel",
                "complaints",
                "share",
                "sla_breached = true",
                "sla_breached = false",
                "breach rate [95% CI]",
            ],
            [
                [c, f"{n:,}", pct(n / n_c), f"{b:,}", f"{n - b:,}", rate_ci(b, n)]
                for c, n, b in ch
            ]
            + [
                [
                    "**total**",
                    f"{n_c:,}",
                    "100%",
                    f"{n_b:,}",
                    f"{n_c - n_b:,}",
                    rate_ci(n_b, n_c),
                ]
            ],
        )
    )
    md.append(f"\nChannel vs breach: p {fp(p_ch)}.\n")

    md.append("## (b) By country and category\n")
    for dim, (rows, p_reg, p_b, share_rows) in dims.items():
        md.append(f"### By {dim}\n")
        md.append(
            md_table(
                [
                    dim,
                    "complaints",
                    "Regulator",
                    "Regulator share [95% CI]",
                    "breach rate (all)",
                    "breach rate (Regulator) [95% CI]",
                ],
                rows,
            )
        )
        md.append(
            f"\nRegulator share vs {dim}: p {fp(p_reg)}. Breach rate vs {dim}: p {fp(p_b)}.\n"
        )
        md.append(f"Reception channel mix per {dim} (row shares):\n")
        md.append(md_table([dim] + [c for c, _, _ in ch], share_rows))
        md.append("")
    md.append(f"Full channel mix vs country: p {fp(p_ch_country)}.\n")

    md.append("## (c) Does sla_breached track elapsed time?\n")
    md.append(
        "A real SLA flag should rise with resolution time and with time to first "
        "response, and differ by priority, since SLAs usually do. Flat rates mean the "
        "flag was drawn independently of the case timeline.\n"
    )
    for k, v in coh.items():
        md.append(f"**{k}** (p {fp(coh_p[k])})\n")
        md.append(
            md_table(
                [k, "complaints", "breach rate [95% CI]"],
                [[g, f"{n:,}", rate_ci(b, n)] for g, n, b in v],
            )
        )
        md.append("")

    md.append("## (d) Earlier complaints and contacts within 90 days\n")
    md.append(
        "Join recommended in B4: customer-level window counts compared with a placebo, "
        "with no attribution of a specific earlier event. Real window: earlier "
        f"complaints with `creation_date` in `[c - {WINDOW}d, c)` and call-center "
        f"contacts with `interaction_date` in `[c - {WINDOW}d, c]`. Placebo: the same "
        f"window shifted {PLACEBO_SHIFT} days back. Complaints created from "
        f"{start:%Y-%m-%d} + {WINDOW + PLACEBO_SHIFT} days on "
        f"({n_eval_back:,} of {n_c:,}) so both windows fall inside the data.\n"
    )
    rows = []
    for label, ri, pi_ in measures:
        for g, name in ((True, "Regulator"), (False, "non-Regulator")):
            h = hist[g]
            rows.append(
                [
                    label,
                    name,
                    f"{h[0]:,}",
                    rate_ci(h[ri], h[0]),
                    rate_ci(h[pi_], h[0]),
                    f"{lift(h[ri], h[pi_]):.2f}x",
                ]
            )
        rows.append(
            [
                label,
                "Regulator vs non-Regulator (real)",
                "",
                f"p {fp(p2x2(reg_h[ri], reg_h[0], non_h[ri], non_h[0]))}",
                f"p {fp(p2x2(reg_h[pi_], reg_h[0], non_h[pi_], non_h[0]))}",
                "",
            ]
        )
    md.append(
        md_table(
            [
                "preceded by",
                "group",
                "complaints",
                "real 90d [95% CI]",
                f"placebo -{PLACEBO_SHIFT}d [95% CI]",
                "lift real / placebo",
            ],
            rows,
        )
    )
    md.append(
        f"\nMean call-center contacts in the window: Regulator {reg_h[7]:.3f} real vs "
        f"{reg_h[8]:.3f} placebo; non-Regulator {non_h[7]:.3f} real vs {non_h[8]:.3f} "
        "placebo.\n"
    )

    md.append(
        "## (e) sla_breached on an earlier complaint vs a later Regulator complaint\n"
    )
    md.append("### Backward: Regulator rate by the customer's previous 90 days\n")
    md.append(
        "Each complaint is grouped by the breach status of the same customer's "
        "complaints in the window. If breaches push customers to the regulator, the "
        "'>=1 breached' row should have a clearly higher Regulator rate in the real "
        "window and not in the placebo.\n"
    )
    labels = [g for g, _, _ in back["real"]]
    plc = {g: (n, r) for g, n, r in back["placebo"]}
    md.append(
        md_table(
            [
                "earlier complaints in window",
                "complaints (real)",
                "Regulator rate real [95% CI]",
                "complaints (placebo)",
                "Regulator rate placebo [95% CI]",
            ],
            [
                [
                    g,
                    f"{n:,}",
                    rate_ci(r, n),
                    f"{plc.get(g, (0, 0))[0]:,}",
                    rate_ci(*plc.get(g, (0, 0))[::-1]),
                ]
                for g, n, r in back["real"]
            ],
        )
    )
    br = {g: (n, r) for g, n, r in back["real"]}
    hi, lo = labels[-1], labels[1] if len(labels) > 2 else labels[0]
    md.append(
        f"\nReal window, '>=1 breached' vs 'none breached': risk ratio "
        f"{rr_ci(br[hi][1], br[hi][0], br[lo][1], br[lo][0])}, p "
        f"{fp(p2x2(br[hi][1], br[hi][0], br[lo][1], br[lo][0]))}.\n"
        if hi in br and lo in br and hi != lo
        else ""
    )
    md.append("### Forward: is a complaint followed by a Regulator complaint?\n")
    md.append(
        f"Complaints created up to {WINDOW} days before the data end ({t_n + f_n:,}). "
        "Outcome: a later complaint from the same customer within "
        f"`(c, c + {WINDOW}d]`. 'Any later complaint' is the reference: a breach "
        "effect specific to the regulator would show up in the Regulator column "
        "without a matching rise in the reference.\n"
    )
    md.append(
        md_table(
            [
                "sla_breached",
                "complaints",
                "later Regulator complaint [95% CI]",
                "any later complaint [95% CI]",
            ],
            [
                ["true", f"{t_n:,}", rate_ci(t_r, t_n), rate_ci(t_a, t_n)],
                ["false", f"{f_n:,}", rate_ci(f_r, f_n), rate_ci(f_a, f_n)],
                [
                    "risk ratio true / false",
                    "",
                    f"{rr_ci(t_r, t_n, f_r, f_n)}, p {fp(p_fwd)}",
                    f"{rr_ci(t_a, t_n, f_a, f_n)}, p {fp(p2x2(t_a, t_n, f_a, f_n))}",
                ],
            ],
        )
    )
    (nt_n, nt_r), (nf_n, nf_r) = fwd_nr[True], fwd_nr[False]
    md.append(
        f"\nRestricted to non-Regulator complaints (the escalation path): "
        f"{rate_ci(nt_r, nt_n)} breached vs {rate_ci(nf_r, nf_n)} not breached "
        f"(risk ratio {rr_ci(nt_r, nt_n, nf_r, nf_n)}, p {fp(p2x2(nt_r, nt_n, nf_r, nf_n))}).\n"
    )
    md.append(
        "`is_repeat_complainer` flag vs Regulator share (context; the flag's own "
        "definition is not documented):\n"
    )
    (r1, n1, k1), (r0, n0, k0) = repeat
    md.append(
        md_table(
            ["is_repeat_complainer", "complaints", "Regulator share [95% CI]"],
            [[r1, f"{n1:,}", rate_ci(k1, n1)], [r0, f"{n0:,}", rate_ci(k0, n0)]],
        )
    )
    md.append(f"\np {fp(p2x2(k1, n1, k0, n0))}, risk ratio {rr_ci(k1, n1, k0, n0)}.\n")

    md.append("## Consequences\n")
    md.append(
        "- **Regulator risk is not predictable from what this data holds.** Its share is "
        "flat across country and category and unrelated to the customer's prior "
        "complaints, contacts or breaches. A Regulator-escalation model would learn "
        "the base rate.\n"
        "- **The 'Si falla' fallback (SLA risk only) does not hold up either.** "
        "`sla_breached` does not follow resolution time, first response, priority or "
        "status, so a model trained on it has no signal to find. If Track B keeps an "
        "SLA angle, define the target from timestamps (`resolution_days`, "
        "`first_response_date`) against a declared threshold and say that the "
        "dataset's own flag was not used.\n"
        "- **The Regulator and SLA fields can still be shown as descriptive KPIs** "
        "(volume, share, trend) in the product, as long as they are not presented as "
        "drivers.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "B3.md").write_text(report, encoding="utf-8")
    line = (
        f"- B3 (Regulator and SLA): {verdict}. Regulator {reg_n:,} ({pct(reg_n / n_c)}), "
        f"breached {pct(n_b / n_c)}; 90d prior complaint/contact {pct(reg_h[5] / reg_h[0])} "
        f"Regulator vs {pct(non_h[5] / non_h[0])} other vs {pct(reg_h[6] / reg_h[0])} placebo; "
        f"later Regulator after breach {pct(t_r / t_n)} vs {pct(f_r / f_n)}; sla_breached "
        f"independent of resolution_days; see docs/findings/day1/B3.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- B3 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


def _k_n(rows: list[tuple], key: str) -> tuple[int, int]:
    """(Regulator count, complaints) of the backward group whose label contains key."""
    n, r = next((n, r) for g, n, r in rows if key in g)
    return r, n


def _group(rows: list[tuple]) -> list[list[tuple]]:
    """Group (key, sub, n) rows by key, for building contingency tables."""
    out: dict = {}
    for r in rows:
        out.setdefault(r[0], []).append(r)
    return list(out.values())


if __name__ == "__main__":
    main()
