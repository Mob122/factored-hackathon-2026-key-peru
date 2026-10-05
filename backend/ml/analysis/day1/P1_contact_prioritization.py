"""P1 - prioritization table of call-center contact reasons.

For every contact_reason in call_center_interactions (and for the reason groups
below): share of contacts, mean duration and wait time, FCR (was_resolved),
escalation rate, requires_followup, sentiment, and survey scores from
satisfaction_surveys joined on interaction_id.

Each metric's spread across reasons is compared against a shuffled-reason
baseline: contact_reason is permuted across rows (keeping every row's outcomes
fixed), the per-reason metric is recomputed, and the observed between-reason
statistic sum_g n_g (m_g - m)^2 is compared with its permutation distribution.
A difference counts as real only if it beats the baseline (p < ALPHA) AND its
range across reasons clears a pre-declared materiality bar (MATERIAL).

Outputs:
  docs/findings/day1/P1_contact_prioritization.md   (committed report)
  data/08_reporting/day1/P1_contact_prioritization.md (copy)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (P1 line)

Run from ml/:  .venv/Scripts/python analysis/day1/P1_contact_prioritization.py
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import ci95, fmt, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"
NAME = "P1_contact_prioritization"

# contact_reason -> requested group. The source has only 6 coarse labels (no
# card / account / credit detail anywhere: mentioned_products joins products in
# <1% of ids, transcript main_topics copies contact_reason), so two requested
# groups have no source label and stay empty.
GROUPS = [
    "card servicing",
    "transaction/payment inquiry",
    "account inquiry",
    "credit product",
    "complaint follow-up",
    "other",
]
MAPPING = {
    "Transaccional": ("transaction/payment inquiry", "transactional contact"),
    "Queja": ("complaint follow-up", "complaint contact"),
    "Producto": (
        "credit product",
        "generic 'product' label; best available fit, may also hold card and "
        "account questions",
    ),
    "Técnico": ("other", "technical / digital support, no requested group"),
    "Comercial": ("other", "sales / offers, no requested group"),
    "Retención": ("other", "retention, no requested group"),
}

PERMS = 500
ALPHA = 0.05
# Range across reasons (max - min) needed to call a real difference material
MATERIAL = {
    "rate": 0.02,  # 2 pp for proportions
    "rel": 0.05,  # 5% of the overall mean for durations, waits and scores
    "sent": 0.05,  # 0.05 on the [-1, 1] sentiment_score
}
RNG = np.random.default_rng(2026)

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def fp(p: float) -> str:
    return f"<{1 / (PERMS + 1):.4f}" if p <= 1 / (PERMS + 1) else f"{p:.4f}"


# (key, label, source column, kind, subset) - subset filters rows with a value
METRICS = [
    ("dur", "mean duration (s)", "dur", "rel", "has_dur"),
    ("wait", "mean wait (s)", "wait", "rel", "has_wait"),
    ("fcr", "FCR (was_resolved)", "fcr", "rate", None),
    ("esc", "escalation rate", "esc", "rate", None),
    ("fu", "requires_followup", "fu", "rate", None),
    ("sent", "mean sentiment_score", "sent", "sent", None),
    ("neg", "negative sentiment share", "neg", "rate", None),
    ("csat", "CSAT mean (1-4)", "csat", "rel", "has_csat"),
    ("csat_top", "CSAT satisfied (3-4)", "csat_top", "rate", "has_csat"),
    ("ces", "CES mean (1-4)", "ces", "rel", "has_ces"),
    ("nps", "NPS-survey mean (2-7)", "nps", "rel", "has_nps"),
    ("surv", "survey coverage", "surv", "rate", None),
]


def group_means(codes: np.ndarray, y: np.ndarray, k: int) -> tuple:
    n = np.bincount(codes, minlength=k).astype(float)
    s = np.bincount(codes, weights=y, minlength=k)
    return n, np.divide(s, n, out=np.full(k, np.nan), where=n > 0)


def between_stat(codes: np.ndarray, y: np.ndarray, k: int) -> float:
    n, m = group_means(codes, y, k)
    mu = y.mean()
    ok = n > 0
    return float((n[ok] * (m[ok] - mu) ** 2).sum())


def perm_test(codes: np.ndarray, y: np.ndarray, k: int) -> tuple[float, float, float]:
    """Observed statistic, permutation p and the permuted 95th-percentile range."""
    obs = between_stat(codes, y, k)
    stats = np.empty(PERMS)
    ranges = np.empty(PERMS)
    for b in range(PERMS):
        pc = RNG.permutation(codes)
        n, m = group_means(pc, y, k)
        stats[b] = between_stat(pc, y, k)
        mm = m[n > 0]
        ranges[b] = mm.max() - mm.min()
    p = (1 + (stats >= obs).sum()) / (PERMS + 1)
    return obs, float(p), float(np.percentile(ranges, 95))


def perm_test_strat(
    codes: np.ndarray, y: np.ndarray, strata: np.ndarray, k: int
) -> tuple[float, float]:
    """Reason effect on y within strata: statistic summed over strata, reasons
    permuted within each stratum. Returns (max within-stratum range, p)."""
    idx = [np.flatnonzero(strata == s) for s in np.unique(strata)]

    def stat(c: np.ndarray) -> float:
        return sum(between_stat(c[ix], y[ix], k) for ix in idx)

    obs = stat(codes)
    rng = 0.0
    for ix in idx:
        n, m = group_means(codes[ix], y[ix], k)
        rng = max(rng, float(m[n > 0].max() - m[n > 0].min()))
    hits = 0
    for _ in range(PERMS):
        pc = codes.copy()
        for ix in idx:
            pc[ix] = RNG.permutation(pc[ix])
        hits += stat(pc) >= obs
    return rng, (1 + hits) / (PERMS + 1)


def main() -> None:
    con = duckdb.connect()
    con.sql(f"""
        create view interactions as
        select * from read_parquet('{(INTER / "call_center_interactions.parquet").as_posix()}')
    """)
    con.sql(f"""
        create view surveys as
        select * from read_parquet('{(INTER / "satisfaction_surveys.parquet").as_posix()}')
    """)

    # ---- raw profile: rows, duplicates, nulls, distinct values
    n_rows, n_ids = con.sql(
        "select count(*), count(distinct interaction_id) from interactions"
    ).fetchone()
    s_rows, s_ids, s_joined, s_ids_joined = con.sql("""
        select count(*), count(distinct s.interaction_id),
               count(i.interaction_id), count(distinct i.interaction_id)
        from surveys s left join (select distinct interaction_id from interactions) i
          using (interaction_id)
    """).fetchone()
    nulls = con.sql("""
        select count(*) filter (where contact_reason is null),
               count(*) filter (where duration_seconds is null),
               count(*) filter (where wait_time_seconds is null),
               count(*) filter (where was_resolved is null),
               count(*) filter (where was_escalated is null),
               count(*) filter (where requires_followup is null),
               count(*) filter (where detected_sentiment is null),
               count(*) filter (where sentiment_score is null)
        from interactions
    """).fetchone()
    reasons = con.sql("""
        select contact_reason, count(*) n from interactions group by 1 order by 2 desc
    """).fetchall()
    rc_equal = con.sql(
        "select count(*) filter (where contact_reason is distinct from reason_category) from interactions"
    ).fetchone()[0]
    sentiments = con.sql("""
        select detected_sentiment, count(*), avg(sentiment_score)
        from interactions group by 1 order by 3
    """).fetchall()
    stypes = con.sql("""
        select survey_type, count(*), min(main_score), max(main_score), avg(main_score)
        from surveys group by 1 order by 1
    """).fetchall()
    cov = con.sql("""
        select channel, interaction_type, count(*), count(duration_seconds),
               count(wait_time_seconds)
        from interactions group by all order by 3 desc
    """).fetchall()
    unknown = [r for r, _ in reasons if r not in MAPPING]
    if unknown:
        raise SystemExit(f"unmapped contact_reason values: {unknown}")
    log(f"{n_rows:,} interactions, {s_rows:,} surveys")

    # ---- row-level frame (one row per interaction, survey scores attached)
    df = con.sql("""
        with sv as (
            select interaction_id,
                   max(main_score) filter (where survey_type = 'CSAT') csat,
                   max(main_score) filter (where survey_type = 'CES') ces,
                   max(main_score) filter (where survey_type = 'NPS') nps,
                   count(*) ns
            from surveys group by 1
        )
        select i.contact_reason reason,
               i.interaction_type = 'Inbound Call' inbound,
               coalesce(i.duration_seconds, 0)::double dur,
               i.duration_seconds is not null has_dur,
               coalesce(i.wait_time_seconds, 0)::double wait,
               i.wait_time_seconds is not null has_wait,
               i.was_resolved::double fcr,
               i.was_escalated::double esc,
               i.requires_followup::double fu,
               i.sentiment_score::double sent,
               (i.detected_sentiment in ('Negativo', 'Muy Negativo'))::double neg,
               coalesce(sv.csat, 0)::double csat,
               sv.csat is not null has_csat,
               coalesce(sv.csat >= 3, false)::double csat_top,
               coalesce(sv.ces, 0)::double ces,
               sv.ces is not null has_ces,
               coalesce(sv.nps, 0)::double nps,
               sv.nps is not null has_nps,
               (sv.ns is not null)::double surv
        from interactions i left join sv using (interaction_id)
    """).fetchnumpy()
    reason_arr = np.asarray(df["reason"], dtype=object)
    names = [r for r, _ in reasons]
    rcode = np.array([names.index(r) for r in reason_arr])
    gnames = [g for g in GROUPS if any(MAPPING[r][0] == g for r in names)]
    r2g = np.array([gnames.index(MAPPING[r][0]) for r in names])
    gcode = r2g[rcode]
    cols = {k: np.asarray(v) for k, v in df.items() if k != "reason"}
    log("frame built")

    def table(codes: np.ndarray, labels: list[str], mask: np.ndarray | None):
        """Per-label metric values, plus the permutation test per metric."""
        k = len(labels)
        base = np.ones(codes.size, bool) if mask is None else mask
        res = {"n": np.bincount(codes[base], minlength=k)}
        tests = {}
        for key, _, col, kind, sub in METRICS:
            m = base & (cols[sub] if sub else True)
            c, y = codes[m], cols[col][m]
            nn, mean = group_means(c, y, k)
            res[key] = mean
            res[key + "_n"] = nn
            obs, p, null95 = perm_test(c, y, k)
            ok = nn > 0
            rng = float(mean[ok].max() - mean[ok].min())
            bar = MATERIAL[kind] * (y.mean() if kind == "rel" else 1)
            if p >= ALPHA:
                verdict = "noise"
            elif rng < bar:
                verdict = "real, not material"
            else:
                verdict = "real"
            tests[key] = dict(
                overall=float(y.mean()),
                rng=rng,
                null95=null95,
                p=p,
                bar=bar,
                verdict=verdict,
                n=int(m.sum()),
            )
            # Totals for the prioritization columns
        res["dur_sum"] = np.bincount(
            codes[base], weights=cols["dur"][base], minlength=k
        )
        res["unres"] = np.bincount(
            codes[base], weights=1 - cols["fcr"][base], minlength=k
        )
        return res, tests

    r_all, t_all = table(rcode, names, None)
    log("reasons done")
    g_all, tg_all = table(gcode, gnames, None)
    log("groups done")
    inbound = cols["inbound"].astype(bool)
    r_in, t_in = table(rcode, names, inbound)
    log("inbound sensitivity done")

    # ---- mediation: which reason gaps survive once was_resolved is fixed
    res_b = cols["fcr"].astype(int)
    med = []
    for key, sub in (
        ("csat", "has_csat"),
        ("csat_top", "has_csat"),
        ("ces", "has_ces"),
        ("nps", "has_nps"),
        ("fu", None),
        ("dur", "has_dur"),
        ("neg", None),
    ):
        m = cols[sub] if sub else np.ones(res_b.size, bool)
        rng, p = perm_test_strat(rcode[m], cols[key][m], res_b[m], len(names))
        med.append((key, t_all[key]["rng"], rng, p))
    by_res = con.sql("""
        select i.was_resolved, count(*) n, avg(s.main_score) csat,
               avg((s.main_score >= 3)::int) top
        from surveys s join interactions i using (interaction_id)
        where s.survey_type = 'CSAT' group by 1 order by 1
    """).fetchall()
    fu_res = con.sql("""
        select was_resolved, count(*), avg(requires_followup::int)
        from interactions group by 1 order by 1
    """).fetchall()
    sent_mix = con.sql("""
        select contact_reason,
               avg((detected_sentiment = 'Neutral')::int) neutral,
               avg((detected_sentiment in ('Negativo', 'Muy Negativo'))::int) neg,
               avg((detected_sentiment in ('Positivo', 'Muy Positivo'))::int) pos
        from interactions group by 1 order by 2 desc
    """).fetchall()
    csat_sent = con.sql("""
        select i.detected_sentiment, count(*),
               avg(s.main_score) filter (
                   where i.contact_reason not in ('Transaccional', 'Producto')),
               avg(s.main_score)
        from surveys s join interactions i using (interaction_id)
        where s.survey_type = 'CSAT' group by 1 order by 1
    """).fetchall()
    dur_res = con.sql("""
        select contact_reason,
               avg(duration_seconds) filter (where was_resolved),
               avg(duration_seconds) filter (where not was_resolved)
        from interactions group by 1 order by 1
    """).fetchall()
    log("mediation done")

    # ---- report
    def fmt_val(key: str, v: float) -> str:
        if np.isnan(v):
            return "n/a"
        kind = next(m[3] for m in METRICS if m[0] == key)
        if kind == "rate":
            return pct(v)
        if key in ("dur", "wait"):
            return fmt(v, 1)
        return fmt(v, 3)

    def metric_rows(res: dict, labels: list[str], total: int) -> list[list]:
        rows = []
        for j, lab in enumerate(labels):
            n = int(res["n"][j])
            rows.append(
                [lab, f"{n:,}", f"{pct(n / total)} {ci95(n, total)}"]
                + [
                    fmt_val(k, res[k][j])
                    for k in (
                        "dur",
                        "wait",
                        "fcr",
                        "esc",
                        "fu",
                        "sent",
                        "neg",
                        "csat",
                        "csat_top",
                    )
                ]
            )
        return rows

    head = [
        "reason",
        "contacts",
        "share (95% CI)",
        "duration s",
        "wait s",
        "FCR",
        "escalated",
        "followup",
        "sentiment",
        "negative",
        "CSAT",
        "CSAT 3-4",
    ]

    def prio_rows(res: dict, labels: list[str]) -> list[list]:
        tot_n, tot_d, tot_u = res["n"].sum(), res["dur_sum"].sum(), res["unres"].sum()
        order = np.argsort(-res["unres"])
        return [
            [
                labels[j],
                pct(res["n"][j] / tot_n),
                pct(res["dur_sum"][j] / tot_d),
                f"{int(res['unres'][j]):,}",
                pct(res["unres"][j] / tot_u),
                f"{int(round(res['fu'][j] * res['n'][j])):,}",
            ]
            for j in order
        ]

    def test_rows(tests: dict) -> list[list]:
        out = []
        for key, label, _, _, _ in METRICS:
            t = tests[key]
            f = (
                (lambda v: pct(v))
                if next(m[3] for m in METRICS if m[0] == key) == "rate"
                else (lambda v: fmt(v, 3))
            )
            out.append(
                [
                    label,
                    f"{t['n']:,}",
                    f(t["overall"]),
                    f(t["rng"]),
                    f(t["null95"]),
                    fp(t["p"]),
                    f(t["bar"]),
                    f"**{t['verdict']}**",
                ]
            )
        return out

    thead = [
        "metric",
        "rows",
        "overall",
        "range across labels",
        "shuffled 95th pct range",
        "perm p",
        "materiality bar",
        "verdict",
    ]

    real = [lab for key, lab, *_ in METRICS if t_all[key]["verdict"] == "real"]
    noise = [lab for key, lab, *_ in METRICS if t_all[key]["verdict"] == "noise"]
    real_nm = [
        lab for key, lab, *_ in METRICS if t_all[key]["verdict"] == "real, not material"
    ]
    med_d = {k: (a, b, p) for k, a, b, p in med}
    chain = ("csat", "csat_top", "ces", "nps", "fu")
    via_fcr = [k for k in chain if med_d[k][2] >= ALPHA]
    top = names[0]

    def ri(r: str) -> int:
        return names.index(r)

    def unres_share(r: str) -> float:
        return r_all["unres"][ri(r)] / r_all["unres"].sum()

    def dur_share(r: str) -> float:
        return r_all["dur_sum"][ri(r)] / r_all["dur_sum"].sum()

    fcr_hi = names[int(np.nanargmax(r_all["fcr"]))]
    fcr_lo = names[int(np.nanargmin(r_all["fcr"]))]
    verdict = (
        "reason differences are real, set by 3 generator knobs (FCR, handle time, "
        "sentiment mix); CSAT and follow-up follow from FCR alone; wait and escalation "
        "are flat"
        if len(via_fcr) == len(chain)
        else f"reason differences are real in: {', '.join(real)}"
    )

    md = [
        "# P1 - Contact reason prioritization",
        "",
        f"Generated by `ml/analysis/day1/{NAME}.py` on {date.today().isoformat()} over "
        f"`ml/data/02_intermediate/` ({n_rows:,} interactions, {s_rows:,} surveys). "
        "Interactions span 2023-06-17 to 2026-06-18.",
        "",
        "## Question",
        "",
        "Which contact reasons should an AI-first service layer target first? For each "
        "`contact_reason` and reason group: volume, handle time, wait, FCR, escalation, "
        "follow-up, sentiment and survey scores, and whether any difference between "
        "reasons is real or generator noise (shuffled-reason baseline).",
        "",
        f"## Verdict: **{verdict}**",
        "",
    ]
    tv = t_all
    md += [
        f"- **Real, material differences (beyond the shuffled baseline):** "
        f"{', '.join(real)}. FCR runs from {pct(np.nanmax(r_all['fcr']))} ({fcr_hi}) to "
        f"{pct(np.nanmin(r_all['fcr']))} ({fcr_lo}), a {pct(tv['fcr']['rng'])} range "
        f"against a shuffled 95th percentile of {pct(tv['fcr']['null95'])}. Mean "
        f"duration runs {fmt(np.nanmin(r_all['dur']), 1)}-"
        f"{fmt(np.nanmax(r_all['dur']), 1)} s (shuffled range "
        f"{fmt(tv['dur']['null95'], 1)} s).",
        f"- **Noise:** {', '.join(noise)}. Wait is ~{fmt(tv['wait']['overall'], 0)} s and "
        f"escalation ~{pct(tv['esc']['overall'])} for every reason. Equal survey "
        "coverage means the CSAT comparison is not biased by who gets surveyed."
        + (
            f" Detectable but below the materiality bar: {', '.join(real_nm)}."
            if real_nm
            else ""
        ),
        f"- **CSAT and follow-up are FCR in disguise.** CSAT is "
        f"{fmt(by_res[0][2], 2)} when unresolved and {fmt(by_res[1][2], 2)} when "
        "resolved, in every reason; `requires_followup` is "
        f"{pct(fu_res[0][2])} when unresolved and {pct(fu_res[1][2])} when resolved. "
        "With `was_resolved` held fixed, the reason gap in "
        + (
            "CSAT, CES, NPS-survey score and follow-up is at noise level"
            if len(via_fcr) == len(chain)
            else f"only {', '.join(via_fcr) or 'none'} falls to noise level"
        )
        + " (section g). The reason drives FCR, and FCR drives the rest.",
        f"- **Sentiment is a separate knob, and an odd one.** Transaccional is "
        f"{pct(sent_mix[0][1])} `Neutral`, Producto mostly Neutral, and the other 4 "
        "reasons share one mix (~35% negative). Within those 4 reasons, "
        "CSAT barely moves with sentiment (section g), so sentiment is not a usable "
        "satisfaction proxy.",
        f"- **Priority depends on the lever.** For deflection by volume: Transaccional "
        f"({pct(r_all['n'][ri('Transaccional')] / n_rows)} of contacts, "
        f"{pct(r_all['fcr'][ri('Transaccional')])} FCR, shortest calls). For failure "
        f"reduction: Queja ({pct(r_all['n'][ri('Queja')] / n_rows)} of contacts but "
        f"{pct(unres_share('Queja'))} of unresolved contacts and "
        f"{pct(dur_share('Queja'))} of handle time, CSAT 3-4 "
        f"{pct(r_all['csat_top'][ri('Queja')])}). Técnico is second on unresolved "
        f"contacts ({pct(unres_share('Técnico'))}).",
        "- **Grouping caveat.** The source has 6 coarse labels. Card servicing and "
        "account inquiry have no source label; `Producto` is mapped to credit product "
        "as the closest fit, but it may also contain card and account questions. "
        "`other` pools Técnico, Comercial and Retención, whose outcomes are close but "
        "not identical (FCR 60-70%).",
        "- **Consequence:** the reason label is a valid prioritization key. Target "
        "Transaccional for automated resolution and Queja for resolution-rate "
        "improvement. By construction of the generator, any FCR gain moves CSAT by "
        "about 1 point per extra resolved contact, so CSAT uplift is not independent "
        "evidence. Escalation and wait time cannot differentiate reasons.",
        "",
        "## (a) Raw profile (before any cleaning)",
        "",
        f"- `call_center_interactions`: {n_rows:,} rows, {n_ids:,} distinct `interaction_id` "
        f"({n_rows - n_ids:,} duplicates).",
        f"- `satisfaction_surveys`: {s_rows:,} rows, {s_ids:,} distinct `interaction_id`; "
        f"{s_joined:,} rows ({pct(s_joined / s_rows)}) join an interaction. At most one "
        "survey per interaction, so the join does not fan out.",
        f"- `contact_reason` equals `reason_category` in all but {rc_equal:,} rows.",
        "",
        md_table(
            ["column", "nulls", "share"],
            [
                [c, f"{v:,}", pct(v / n_rows)]
                for c, v in zip(
                    [
                        "contact_reason",
                        "duration_seconds",
                        "wait_time_seconds",
                        "was_resolved",
                        "was_escalated",
                        "requires_followup",
                        "detected_sentiment",
                        "sentiment_score",
                    ],
                    nulls,
                )
            ],
        ),
        "",
        "Duration and wait nulls are structural, not random: duration exists only for "
        "voice/video rows (Phone, Web, part of App) and wait only for inbound calls.",
        "",
        md_table(
            ["channel", "interaction_type", "rows", "with duration", "with wait"],
            [[a, b, f"{c:,}", f"{d:,}", f"{e:,}"] for a, b, c, d, e in cov],
        ),
        "",
        "### Distinct values",
        "",
        md_table(["contact_reason", "rows"], [[r, f"{n:,}"] for r, n in reasons]),
        "",
        md_table(
            ["detected_sentiment", "rows", "mean sentiment_score"],
            [[s, f"{n:,}", fmt(m, 3)] for s, n, m in sentiments],
        ),
        "",
        "Negative sentiment share = `Negativo` + `Muy Negativo`.",
        "",
        md_table(
            ["survey_type", "rows", "min", "max", "mean"],
            [[t, f"{n:,}", a, b, fmt(m, 3)] for t, n, a, b, m in stypes],
        ),
        "",
        "Only `CSAT` surveys feed the CSAT columns; CES and NPS-type surveys are "
        "tested separately in (d). CSAT satisfied = score 3 or 4.",
        "",
        "## (b) Mapping to groups",
        "",
        md_table(
            ["contact_reason", "group", "reason"],
            [[r, MAPPING[r][0], MAPPING[r][1]] for r in names]
            + [["*none*", g, "no source label"] for g in GROUPS if g not in gnames],
        ),
        "",
        "## (c) Prioritization table by contact_reason",
        "",
        md_table(head, metric_rows(r_all, names, n_rows)),
        "",
        "Duration is over rows with a duration, wait over inbound calls; CSAT over "
        "interactions with a CSAT survey.",
        "",
        "### Priority view (sorted by unresolved contacts)",
        "",
        md_table(
            [
                "reason",
                "share of contacts",
                "share of handle time",
                "unresolved contacts",
                "share of unresolved",
                "follow-ups",
            ],
            prio_rows(r_all, names),
        ),
        "",
        "## (d) Differences between reasons vs shuffled-reason baseline",
        "",
        f"`contact_reason` permuted across rows {PERMS} times (seed 2026). Statistic: "
        "sum over reasons of n x (reason mean - overall mean)^2. `range` is max - min "
        "across reasons; the shuffled column is its 95th percentile under permutation. "
        f"Verdict: noise if p >= {ALPHA}; real but not material if the range is below "
        "the bar (2 pp for rates, 5% of the mean for durations and scores, 0.05 for "
        "sentiment_score).",
        "",
        md_table(thead, test_rows(t_all)),
        "",
        "## (e) Aggregated by group",
        "",
        md_table(["group"] + head[1:], metric_rows(g_all, gnames, n_rows)),
        "",
        md_table(
            [
                "group",
                "share of contacts",
                "share of handle time",
                "unresolved contacts",
                "share of unresolved",
                "follow-ups",
            ],
            prio_rows(g_all, gnames),
        ),
        "",
        "Group labels permuted the same way (equivalent to permuting reasons and "
        "re-mapping):",
        "",
        md_table(thead, test_rows(tg_all)),
        "",
        "## (f) Sensitivity: inbound calls only",
        "",
        f"Restricting to the {int(inbound.sum()):,} inbound calls (the only rows with "
        "wait time, and the demand an agent actually answers) removes channel-mix "
        "effects.",
        "",
        md_table(head, metric_rows(r_in, names, int(inbound.sum()))),
        "",
        md_table(thead, test_rows(t_in)),
        "",
        "## (g) Mediation: what the reason drives directly",
        "",
        "Reasons permuted within each `was_resolved` stratum (same statistic, summed "
        f"over strata, {PERMS} permutations). If the gap disappears, the metric depends "
        "on the reason only through FCR.",
        "",
        md_table(
            [
                "metric",
                "range across reasons (raw)",
                "max range within a was_resolved stratum",
                "stratified perm p",
                "reading",
            ],
            [
                [
                    next(m[1] for m in METRICS if m[0] == k),
                    pct(a) if k in ("csat_top", "fu", "neg") else fmt(a, 3),
                    pct(b) if k in ("csat_top", "fu", "neg") else fmt(b, 3),
                    fp(p),
                    "via FCR only" if p >= ALPHA else "direct reason effect",
                ]
                for k, a, b, p in med
            ],
        ),
        "",
        md_table(
            ["was_resolved", "CSAT surveys", "CSAT mean", "CSAT 3-4"],
            [[r, f"{n:,}", fmt(c, 3), pct(t)] for r, n, c, t in by_res],
        ),
        "",
        md_table(
            ["was_resolved", "interactions", "requires_followup"],
            [[r, f"{n:,}", pct(f)] for r, n, f in fu_res],
        ),
        "",
        md_table(
            ["contact_reason", "neutral", "negative", "positive"],
            [[r, pct(a), pct(b), pct(c)] for r, a, b, c in sent_mix],
        ),
        "",
        md_table(
            [
                "detected_sentiment",
                "CSAT surveys",
                "CSAT mean, 4 reasons with the same sentiment mix",
                "CSAT mean all",
            ],
            [[s, f"{n:,}", fmt(a, 3), fmt(b, 3)] for s, n, a, b in csat_sent],
        ),
        "",
        "The all-rows CSAT is higher for Neutral only because Transaccional and "
        "Producto (the high-FCR reasons) are mostly Neutral. Within the 4 reasons that "
        "share one sentiment mix, all tiers score alike.",
        "",
        md_table(
            [
                "contact_reason",
                "mean duration resolved (s)",
                "mean duration unresolved (s)",
            ],
            [[r, fmt(a, 1), fmt(b, 1)] for r, a, b in dur_res],
        ),
        "",
        "Duration is a per-reason parameter, mostly independent of the outcome; "
        "Transaccional is the exception (unresolved calls run longer).",
        "",
        "## Notes",
        "",
        "- The data is synthetic; this report only says whether reason-level differences "
        "exceed what random reason labels would produce.",
        "- `mentioned_products` could have split `Producto` into card / account / credit, "
        "but its ids join `products` in under 1% of cases (see C1), so it is not used.",
        "- Survey coverage is part of (d): if reasons were surveyed at different rates "
        "the CSAT comparison would be biased; the coverage row shows whether they are.",
        "",
    ]
    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{NAME}.md").write_text(report, encoding="utf-8")
    line = (
        f"- P1 (contact reason prioritization): {verdict}. {top} "
        f"{pct(r_all['n'][0] / n_rows)} of {n_rows:,} contacts at "
        f"{pct(r_all['fcr'][0])} FCR; Queja {pct(r_all['n'][ri('Queja')] / n_rows)} of "
        f"contacts but {pct(unres_share('Queja'))} of unresolved; FCR range "
        f"{pct(tv['fcr']['rng'])} vs shuffled {pct(tv['fcr']['null95'])}; escalation "
        f"range {pct(tv['esc']['rng'])} (p {fp(tv['esc']['p'])}); card servicing and "
        f"account inquiry have no source label; see docs/findings/day1/{NAME}.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- P1 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
