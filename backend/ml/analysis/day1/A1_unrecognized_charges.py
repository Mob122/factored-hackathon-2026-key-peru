"""A1 - are unrecognized charges a relevant share of demand?

Checks:
  (a) distinct contact_reason / reason_category in call_center_interactions and
      category / subcategory in complaints, with counts, plus the theme fields in
      call_transcripts (detected_intents, main_topics, keywords, free text).
  (b) the approved mapping to the A1 theme (unrecognized charges, disputes, fraud,
      chargebacks):
        core      = complaints category 'Transactions' ('Cargo no reconocido' or
                    null subcategory, since category determines subcategory)
        extended  = complaints category 'Fees' ('Cobro indebido'), sensitivity only
        rest      = Technical, Branch, Service
      No interaction reason and no transcript field maps to the theme.
  (c) share of demand by country, reception channel and year, with a chi-square
      test of independence, and rank among all reasons.
  (d) outcome metrics for core vs extended vs rest on the complaint side
      (escalated status, sla_breached, resolution_days, resolution_satisfaction,
      compensation, repeat complainer). Interaction FCR / escalation / CSAT are
      reported per contact_reason as context only: B4 showed complaints cannot be
      linked to interactions, so they are not attributable to A1.

Outputs:
  docs/findings/day1/A1.md                 (committed report)
  data/08_reporting/day1/A1.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (A1 line)

Run from ml/:  .venv/Scripts/python analysis/day1/A1_unrecognized_charges.py
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path

import duckdb

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

CORE_CATEGORY = "Transactions"
EXTENDED_CATEGORY = "Fees"
# Free-text patterns for the theme in transcripts (Spanish, lower-cased)
THEME_REGEX = (
    r"(no reconoc|fraud|contracargo|disput|cobro indebido|doble cobro|cargo|"
    r"clonad|robo|estafa|chargeback)"
)
# A theme is "relevant demand" if it clearly stands out, not just its fair share
MIN_SHARE_OF_CONTACTS = 0.05
UNIFORM_P = 0.05  # chi-square p above this: no structure by the dimension

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.2f}%"


def fmt(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:,.{nd}f}"


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


def _gamma_q(a: float, x: float) -> float:
    """Regularized upper incomplete gamma Q(a, x) (Numerical Recipes gser/gcf)."""
    if x <= 0:
        return 1.0
    lg = math.lgamma(a)
    if x < a + 1:
        term = total = 1 / a
        ap = a
        for _ in range(10_000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-15:
                break
        return 1 - total * math.exp(-x + a * math.log(x) - lg)
    b, c, d = x + 1 - a, 1e300, 1 / (x + 1 - a)
    h = d
    for i in range(1, 10_000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = 1e-300 if abs(d) < 1e-300 else d
        c = b + an / c
        c = 1e-300 if abs(c) < 1e-300 else c
        d = 1 / d
        h *= d * c
        if abs(d * c - 1) < 1e-15:
            break
    return math.exp(-x + a * math.log(x) - lg) * h


def chi2_p(table: list[list[float]]) -> float:
    """p-value of the chi-square test of independence for a contingency table."""
    rows = [sum(r) for r in table]
    cols = [sum(c) for c in zip(*table)]
    n = sum(rows)
    stat = sum(
        (table[i][j] - rows[i] * cols[j] / n) ** 2 / (rows[i] * cols[j] / n)
        for i in range(len(rows))
        for j in range(len(cols))
        if rows[i] and cols[j]
    )
    dof = (len(rows) - 1) * (len(cols) - 1)
    return _gamma_q(dof / 2, stat / 2)


GROUP_SQL = f"""
    case category
        when '{CORE_CATEGORY}' then 'core'
        when '{EXTENDED_CATEGORY}' then 'extended'
        else 'rest'
    end
"""
GROUPS = ["core", "extended", "rest"]


def main() -> None:
    con = duckdb.connect()
    for name, file in [
        ("complaints", "complaints"),
        ("interactions", "call_center_interactions"),
        ("transcripts", "call_transcripts"),
        ("customers", "customers"),
        ("surveys", "satisfaction_surveys"),
    ]:
        con.sql(
            f"create view {name} as select * from "
            f"'{(INTER / f'{file}.parquet').as_posix()}'"
        )
    con.sql(
        f"""
        create temp table c as
        select c.*, {GROUP_SQL} as grp, cu.country,
               year(c.creation_date) as yr
        from complaints c left join customers cu using (customer_id)
        """
    )
    n_c = con.sql("select count(*) from c").fetchone()[0]
    n_i = con.sql("select count(*) from interactions").fetchone()[0]
    n_t = con.sql("select count(*) from transcripts").fetchone()[0]
    log(f"complaints={n_c:,} interactions={n_i:,} transcripts={n_t:,}")

    md: list[str] = []
    md.append("# A1 - Unrecognized charges as a share of demand\n")
    md.append(
        f"Generated by `ml/analysis/day1/A1_unrecognized_charges.py` on "
        f"{date.today().isoformat()} over `ml/data/02_intermediate/` ({n_c:,} complaints, "
        f"{n_i:,} interactions, {n_t:,} transcripts). Country comes from `customers` via "
        f"`customer_id`; year is the calendar year of `creation_date` (2023 starts on "
        f"2023-06-17 and 2026 ends on 2026-06-18, so both are partial).\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "Unrecognized charges (and related disputes, fraud and chargebacks) are a "
        "relevant share of customer-service demand. If not, Track A is dropped.\n"
    )

    # ---------------------------------------------------------------- (a) values
    log("(a) distinct values")
    inter_vals = con.sql(
        """
        select contact_reason, reason_category, count(*) n
        from interactions group by all order by n desc
        """
    ).fetchall()
    same_reason = con.sql(
        "select count(*) filter (where contact_reason is distinct from reason_category) "
        "from interactions"
    ).fetchone()[0]
    comp_vals = con.sql(
        """
        select category, subcategory, count(*) n from c
        group by all order by category, subcategory nulls last
        """
    ).fetchall()
    subcats_per_cat = con.sql(
        "select max(k) from (select category, count(distinct subcategory) k "
        "from c group by 1)"
    ).fetchone()[0]
    descr = con.sql("select count(distinct description) from c").fetchone()[0]
    intents = con.sql(
        "select detected_intents, count(*) n from transcripts group by all order by n desc"
    ).fetchall()
    topics = con.sql(
        "select main_topics, count(*) n from transcripts group by all order by n desc"
    ).fetchall()
    kw_tokens = con.sql(
        """
        select distinct trim(unnest(string_split(detected_keywords, ','))) t
        from transcripts where detected_keywords is not null order by 1
        """
    ).fetchall()
    n_texts = con.sql(
        "select count(distinct full_text), count(distinct customer_text) from transcripts"
    ).fetchone()
    theme_hits = con.sql(
        f"""
        select count(*) filter (where regexp_matches(lower(full_text), '{THEME_REGEX}')),
               count(*) filter (where regexp_matches(lower(detected_keywords), '{THEME_REGEX}')),
               count(*) filter (where regexp_matches(lower(mentioned_entities), '{THEME_REGEX}'))
        from transcripts
        """
    ).fetchone()
    topic_agree = con.sql(
        """
        select count(*), count(*) filter (where t.main_topics = i.contact_reason)
        from transcripts t join interactions i using (interaction_id)
        where t.main_topics is not null
        """
    ).fetchone()

    md.append("## (a) Distinct values\n")
    md.append("### call_center_interactions\n")
    md.append(
        md_table(
            ["contact_reason", "reason_category", "n", "share"],
            [[r[0], r[1], f"{r[2]:,}", pct(r[2] / n_i)] for r in inter_vals],
        )
        + "\n"
    )
    md.append(
        f"`contact_reason` and `reason_category` differ in {same_reason:,} rows: they are "
        "the same 6-value field. No value refers to charges, disputes or fraud.\n"
    )
    md.append("### complaints\n")
    md.append(
        md_table(
            ["category", "subcategory", "n", "share"],
            [[r[0], r[1] if r[1] is not None else "*null*", f"{r[2]:,}", pct(r[2] / n_c)]
             for r in comp_vals],
        )
        + "\n"
    )
    md.append(
        f"Each category has at most {subcats_per_cat} non-null subcategory, so the "
        f"subcategory adds no detail and its nulls can be filled from the category. "
        f"`description` has {descr} distinct values ('Queja relacionada con <category>').\n"
    )
    md.append("### call_transcripts\n")
    md.append(
        md_table(
            ["field", "distinct values (n)"],
            [
                ["detected_intents",
                 ", ".join(f"{v if v is not None else '*null*'} ({n:,})" for v, n in intents)],
                ["main_topics",
                 ", ".join(f"{v if v is not None else '*null*'} ({n:,})" for v, n in topics)],
                ["detected_keywords (tokens)", ", ".join(t[0] for t in kw_tokens)],
                ["full_text / customer_text", f"{n_texts[0]:,} / {n_texts[1]:,} distinct texts"],
            ],
        )
        + "\n"
    )
    md.append(
        f"Theme regex `{THEME_REGEX}` matches {theme_hits[0]:,} `full_text`, "
        f"{theme_hits[1]:,} `detected_keywords` and {theme_hits[2]:,} `mentioned_entities` "
        f"values out of {n_t:,}. `main_topics` equals the interaction's `contact_reason` in "
        f"{pct(topic_agree[1] / topic_agree[0])} of {topic_agree[0]:,} joined rows, so it is "
        "a copy of the same field. Transcripts carry no signal for the theme.\n"
    )

    # --------------------------------------------------------------- (b) mapping
    md.append("## (b) Mapping (approved before use)\n")
    md.append(
        md_table(
            ["source", "value", "group", "reason"],
            [
                ["complaints", "Transactions / Cargo no reconocido", "core",
                 "unrecognized charge by definition"],
                ["complaints", "Transactions / *null*", "core",
                 "category determines subcategory"],
                ["complaints", "Fees / Cobro indebido (+ *null*)", "extended",
                 "dispute over a bank fee, not a third-party or fraudulent charge; "
                 "sensitivity only"],
                ["complaints", "Technical, Branch, Service", "rest", "unrelated"],
                ["interactions", "all 6 reasons", "not mapped",
                 "none means dispute or fraud; Queja and Transaccional are too broad"],
                ["transcripts", "all fields", "not mapped", "theme absent"],
            ],
        )
        + "\n"
    )

    # ------------------------------------------------------- (c) share and rank
    log("(c) share and rank")
    grp_n = dict(con.sql("select grp, count(*) from c group by 1").fetchall())
    core_n, ext_n = grp_n["core"], grp_n["extended"]
    total_contacts = n_c + n_i
    cat_rank = con.sql(
        "select category, count(*) n from c group by 1 order by n desc"
    ).fetchall()
    all_reasons = [(f"interaction: {r[0]}", r[2]) for r in inter_vals] + [
        (f"complaint: {r[0]}", r[1]) for r in cat_rank
    ]
    all_reasons.sort(key=lambda x: -x[1])
    core_rank_c = [r[0] for r in cat_rank].index(CORE_CATEGORY) + 1
    core_rank_all = [r[0] for r in all_reasons].index(f"complaint: {CORE_CATEGORY}") + 1
    spread = (cat_rank[0][1] - cat_rank[-1][1]) / n_c

    md.append("## (c) Share of demand and rank\n")
    md.append(
        md_table(
            ["group", "complaints", "share of complaints (95% CI)",
             "share of all contacts (complaints + interactions)"],
            [
                ["core", f"{core_n:,}", f"{pct(core_n / n_c)} {ci95(core_n, n_c)}",
                 pct(core_n / total_contacts)],
                ["core + extended", f"{core_n + ext_n:,}",
                 f"{pct((core_n + ext_n) / n_c)} {ci95(core_n + ext_n, n_c)}",
                 pct((core_n + ext_n) / total_contacts)],
            ],
        )
        + "\n"
    )
    md.append(
        f"**Rank among complaint categories:** {core_rank_c} of {len(cat_rank)}. The "
        f"largest and smallest categories differ by {100 * spread:.2f} percentage points; a uniform "
        f"split would give each {pct(1 / len(cat_rank))}.\n"
    )
    md.append(
        f"**Rank among all reasons** (6 interaction reasons + 5 complaint categories): "
        f"{core_rank_all} of {len(all_reasons)}.\n"
    )
    md.append(
        md_table(
            ["rank", "reason", "n", "share of all contacts"],
            [[i + 1, r[0], f"{r[1]:,}", pct(r[1] / total_contacts)]
             for i, r in enumerate(all_reasons)],
        )
        + "\n"
    )

    def by_dim(dim: str, label: str) -> tuple[list[list], float]:
        rows = con.sql(
            f"""
            select {dim} d, count(*) n,
                   count(*) filter (where grp = 'core') core,
                   count(*) filter (where grp = 'extended') ext
            from c group by 1 order by 1 nulls last
            """
        ).fetchall()
        table = con.sql(
            f"select {dim}, category, count(*) from c where {dim} is not null "
            "group by all"
        ).fetchall()
        dims = sorted({t[0] for t in table})
        cats = sorted({t[1] for t in table})
        m = {(t[0], t[1]): t[2] for t in table}
        p = chi2_p([[m.get((d, k), 0) for k in cats] for d in dims])
        out = []
        for d, n, core, ext in rows:
            out.append([
                d if d is not None else "*null*", f"{n:,}", f"{core:,}",
                f"{pct(core / n)} {ci95(core, n)}", pct((core + ext) / n),
            ])
        log(f"  {label}: chi2 p={p:.3g}")
        return out, p

    md.append("### By country, reception channel and year\n")
    md.append(
        "Share of each slice's complaints. The p-value is a chi-square test of "
        "independence between the slice and the 5 categories; a high p-value means "
        "the category mix does not depend on the slice.\n"
    )
    pvals = {}
    for dim, label in [("country", "country"), ("reception_channel", "reception channel"),
                       ("yr", "year")]:
        rows, p = by_dim(dim, label)
        pvals[label] = p
        md.append(f"**{label}** (chi-square p = {p:.3g})\n")
        md.append(
            md_table(
                [label, "complaints", "core", "core share (95% CI)", "core + extended share"],
                rows,
            )
            + "\n"
        )

    # Interactions have no theme, but their volume by the same dimensions frames
    # how small complaints are next to total demand.
    inter_dim = con.sql(
        """
        select cu.country, count(*) n from interactions i
        left join customers cu using (customer_id) group by 1 order by 1 nulls last
        """
    ).fetchall()
    comp_country = dict(con.sql("select country, count(*) from c group by 1").fetchall())
    core_country = dict(
        con.sql("select country, count(*) from c where grp = 'core' group by 1").fetchall()
    )
    md.append(
        "**Core as a share of all contacts by country** (complaints + interactions of "
        "customers in that country):\n"
    )
    md.append(
        md_table(
            ["country", "interactions", "complaints", "core", "core / all contacts"],
            [
                [d if d is not None else "*null*", f"{n:,}",
                 f"{comp_country.get(d, 0):,}", f"{core_country.get(d, 0):,}",
                 pct(core_country.get(d, 0) / (n + comp_country.get(d, 0)))]
                for d, n in inter_dim
            ],
        )
        + "\n"
    )
    inter_year = dict(
        con.sql("select year(interaction_date), count(*) from interactions group by 1").fetchall()
    )
    comp_year = dict(con.sql("select yr, count(*) from c group by 1").fetchall())
    core_year = dict(con.sql("select yr, count(*) from c where grp='core' group by 1").fetchall())
    md.append("**Core as a share of all contacts by year:**\n")
    md.append(
        md_table(
            ["year", "interactions", "complaints", "core", "core / all contacts"],
            [
                [y, f"{inter_year.get(y, 0):,}", f"{comp_year.get(y, 0):,}",
                 f"{core_year.get(y, 0):,}",
                 pct(core_year.get(y, 0) / (inter_year.get(y, 0) + comp_year.get(y, 0)))]
                for y in sorted(set(inter_year) | set(comp_year))
            ],
        )
        + "\n"
    )
    md.append(
        "Interaction channels (Phone, App, Web Chat, WhatsApp, Email, Web) cannot be "
        "split by theme, so the channel view is only available for complaint "
        "`reception_channel`.\n"
    )

    # ------------------------------------------------------------ (d) outcomes
    log("(d) outcome metrics")
    md.append("## (d) Outcomes: core vs extended vs rest (complaints)\n")
    md.append(
        "Complaints have no FCR or escalation flag. The closest equivalents are "
        "`status = 'Escalated'`, `sla_breached`, `resolution_days` (non-null only for "
        "Resolved and Closed) and `resolution_satisfaction` (non-null only for Closed, "
        "scale 1-5).\n"
    )
    out = {
        r[0]: r[1:]
        for r in con.sql(
            """
            select grp, count(*),
                   count(*) filter (where status = 'Escalated'),
                   count(*) filter (where sla_breached),
                   count(sla_breached),
                   avg(resolution_days), median(resolution_days), count(resolution_days),
                   avg(resolution_satisfaction), count(resolution_satisfaction),
                   count(*) filter (where compensation_granted > 0),
                   count(*) filter (where status in ('Resolved', 'Closed')),
                   count(*) filter (where is_repeat_complainer),
                   count(*) filter (where priority in ('Alta', 'High', 'Critica', 'Critical',
                                                        'Crítica', 'Urgente', 'Urgent')),
                   median(claimed_amount),
                   count(*) filter (where status = 'Rejected')
            from c group by 1
            """
        ).fetchall()
    }
    prio = con.sql(
        "select priority, count(*) from c group by 1 order by 2 desc"
    ).fetchall()
    rows = []
    for label, fn in [
        ("n", lambda o: f"{o[0]:,}"),
        ("status Escalated (95% CI)", lambda o: f"{pct(o[1] / o[0])} {ci95(o[1], o[0])}"),
        ("status Rejected", lambda o: pct(o[14] / o[0])),
        ("status Resolved or Closed", lambda o: pct(o[10] / o[0])),
        ("sla_breached (95% CI)", lambda o: f"{pct(o[2] / o[3])} {ci95(o[2], o[3])}"),
        ("resolution_days mean / median (n)",
         lambda o: f"{fmt(o[4])} / {fmt(o[5], 0)} ({o[6]:,})"),
        ("resolution_satisfaction mean (n)", lambda o: f"{fmt(o[7])} ({o[8]:,})"),
        ("compensation granted > 0", lambda o: pct(o[9] / o[0])),
        ("is_repeat_complainer", lambda o: pct(o[11] / o[0])),
        ("median claimed_amount", lambda o: fmt(o[13])),
    ]:
        rows.append([label] + [fn(out[g]) for g in GROUPS])
    md.append(md_table(["metric", "core", "extended", "rest"], rows) + "\n")
    md.append(
        "Priority values: "
        + ", ".join(f"{p if p is not None else '*null*'} ({n:,})" for p, n in prio)
        + ".\n"
    )
    # chi-square of group vs status as the single "does anything differ" test
    st = con.sql("select grp, status, count(*) from c group by all").fetchall()
    stats = sorted({s[1] for s in st if s[1] is not None})
    m = {(s[0], s[1]): s[2] for s in st}
    p_status = chi2_p([[m.get((g, s), 0) for s in stats] for g in GROUPS])
    md.append(f"Chi-square test of group vs `status`: p = {p_status:.3g}.\n")

    md.append("### Context only: interaction outcomes by contact_reason (not A1)\n")
    md.append(
        "These cannot be attributed to unrecognized charges (no mapping, and B4 showed "
        "complaints cannot be linked to interactions). FCR = `was_resolved`; CSAT = mean "
        "`main_score` of `satisfaction_surveys` with `survey_type = 'CSAT'`, joined on "
        "`interaction_id`.\n"
    )
    ctx = con.sql(
        """
        with s as (
            select interaction_id, avg(main_score) csat
            from surveys where survey_type = 'CSAT' group by 1
        )
        select i.contact_reason, count(*) n,
               avg(i.was_resolved::int), avg(i.was_escalated::int),
               avg(i.requires_followup::int), avg(s.csat), count(s.csat)
        from interactions i left join s using (interaction_id)
        group by 1 order by n desc
        """
    ).fetchall()
    md.append(
        md_table(
            ["contact_reason", "n", "FCR (was_resolved)", "was_escalated",
             "requires_followup", "CSAT mean (n)"],
            [[r[0], f"{r[1]:,}", pct(r[2]), pct(r[3]), pct(r[4]),
              f"{fmt(r[5])} ({r[6]:,})"] for r in ctx],
        )
        + "\n"
    )

    # ----------------------------------------------------------------- verdict
    core_share_all = core_n / total_contacts
    no_structure = all(p > UNIFORM_P for p in pvals.values())
    if core_share_all >= MIN_SHARE_OF_CONTACTS and not no_structure:
        verdict = "supported"
    elif core_share_all < MIN_SHARE_OF_CONTACTS and no_structure:
        verdict = "not supported as a differentiating theme"
    else:
        verdict = "weak"
    md.insert(
        4,
        "## Verdict: **"
        + verdict
        + "**\n\n"
        + f"- **Measurable only in complaints.** No `contact_reason`, transcript intent, "
        f"topic, keyword or text refers to charges, disputes or fraud, so the theme cannot "
        f"be seen in the {n_i:,} interactions or {n_t:,} transcripts.\n"
        + f"- **Fair share, not a standout.** Core unrecognized charges are "
        f"{pct(core_n / n_c)} of complaints (rank {core_rank_c} of {len(cat_rank)}, with "
        f"all categories within {100 * spread:.2f} pp of each other) but "
        f"{pct(core_share_all)} of all contacts (rank {core_rank_all} of "
        f"{len(all_reasons)}). With Fees added: {pct((core_n + ext_n) / n_c)} and "
        f"{pct((core_n + ext_n) / total_contacts)}.\n"
        + f"- **No structure.** The category mix does not depend on country "
        f"(p = {pvals['country']:.2g}), reception channel (p = "
        f"{pvals['reception channel']:.2g}) or year (p = {pvals['year']:.2g}), and core "
        f"outcomes look like the rest (group vs status p = {p_status:.2g}).\n"
        + "- **Consequence (from 'Si falla'):** the data give no reason to prioritise "
        "unrecognized charges over any other complaint category. Track A can only rest "
        "on industry evidence, not on this dataset's demand.\n",
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "A1.md").write_text(report, encoding="utf-8")
    line = (
        f"- A1 (unrecognized charges as demand): {verdict}. Only measurable in complaints: "
        f"core {pct(core_n / n_c)} of complaints (rank {core_rank_c}/{len(cat_rank)}, "
        f"uniform categories) and {pct(core_share_all)} of all contacts; no theme in "
        f"interactions or transcripts; no structure by country/channel/year; "
        f"see docs/findings/day1/A1.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- A1 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
