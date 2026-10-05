"""A2 - are disputed-charge complaints closed as a valid (legitimate) charge?

Scope: the dispute-related complaint categories from A1
    core      = category 'Transactions' ('Cargo no reconocido')
    extended  = category 'Fees' ('Cobro indebido'), sensitivity only
with 'rest' (Technical, Branch, Service) as the comparison group.

Checks:
  (a) distribution of status.
  (b) compensation_granted zero vs non-zero. The column has no literal zeros:
      null means no compensation, and it is only non-null for Resolved / Closed.
  (c) distribution of resolution_days (non-null only for Resolved / Closed).
  (d) keyword rules over the resolution text -> outcome (charge valid / refunded /
      fraud confirmed / other), counts, and whether the outcome agrees with the
      compensation field and depends on the complaint category.
  (e) 20 random examples per outcome (fixed seed) to check the rules by hand.
  (f) estimated share of disputes closed as a legitimate charge.

Outputs:
  docs/findings/day1/A2.md                 (committed report)
  data/08_reporting/day1/A2.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (A2 line)

Run from ml/:  .venv/Scripts/python analysis/day1/A2_dispute_outcomes.py
"""

from __future__ import annotations

import random
import re
import statistics
import time
from datetime import date
from pathlib import Path

import duckdb
from A1_unrecognized_charges import chi2_p, ci95, fmt, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

CORE_CATEGORY = "Transactions"
EXTENDED_CATEGORY = "Fees"
GROUPS = ["core", "extended", "rest"]
STATUSES = ["Open", "In Process", "Escalated", "Resolved", "Closed", "Rejected"]
DECIDED = ("Resolved", "Closed", "Rejected")  # a final decision was taken
SEED = 42
N_EXAMPLES = 20

# Keyword rules over the lower-cased resolution text, first match wins. Each rule
# is (rule name, outcome, pattern). 'valid_explicit' is wording that states the
# charge was correct; 'valid_explained' is the weaker industry convention that an
# explanation with no adjustment or payment means the charge stood.
RULES: list[tuple[str, str, str]] = [
    (
        "fraud",
        "fraud confirmed",
        r"fraud|suplant|clonad|no autorizad|robo|estafa|phishing|contracargo",
    ),
    (
        "refund",
        "refunded",
        r"reembols|devoluci|devolvi|revers|abono|compensaci|ajuste|correcci|anul",
    ),
    (
        "valid_explicit",
        "charge valid",
        r"cargo (es )?v[aá]lido|procedente|leg[ií]tim|reconoci[oó] el cargo|"
        r"se ratific|se mantiene el cargo|no corresponde",
    ),
    ("valid_explained", "charge valid", r"explicaci"),
]
OUTCOMES = ["charge valid", "refunded", "fraud confirmed", "other"]
NO_TEXT = "no text"

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def classify(text: str | None) -> tuple[str, str]:
    """(outcome, rule) for a resolution text."""
    if text is None:
        return NO_TEXT, "-"
    low = text.lower()
    for rule, outcome, pattern in RULES:
        if re.search(pattern, low):
            return outcome, rule
    return "other", "none"


def quantiles(xs: list[int]) -> list[str]:
    """n, mean, sd, min, p10, p25, median, p75, p90, max."""
    if not xs:
        return ["0"] + ["n/a"] * 9
    xs = sorted(xs)
    q = statistics.quantiles(xs, n=20, method="inclusive")  # 5% steps
    return [
        f"{len(xs):,}",
        fmt(statistics.fmean(xs)),
        fmt(statistics.pstdev(xs)),
        str(xs[0]),
        fmt(q[1], 1),
        fmt(q[4], 1),
        fmt(statistics.median(xs), 1),
        fmt(q[14], 1),
        fmt(q[17], 1),
        str(xs[-1]),
    ]


QHEAD = ["n", "mean", "sd", "min", "p10", "p25", "median", "p75", "p90", "max"]


def share(k: int, n: int) -> str:
    return f"{pct(k / n) if n else 'n/a'} {ci95(k, n)}"


def main() -> None:
    con = duckdb.connect()
    con.sql(
        f"create view complaints as select * from "
        f"'{(INTER / 'complaints.parquet').as_posix()}'"
    )
    rows = con.sql(
        f"""
        select complaint_id, category,
               case category when '{CORE_CATEGORY}' then 'core'
                             when '{EXTENDED_CATEGORY}' then 'extended'
                             else 'rest' end as grp,
               status, resolution, resolution_days,
               coalesce(compensation_granted, 0)::double as comp,
               compensation_granted is not null and compensation_granted = 0 as comp_zero,
               claimed_amount::double as claimed, currency, resolution_satisfaction
        from complaints
        """
    ).fetchall()
    cols = [
        "id",
        "category",
        "grp",
        "status",
        "resolution",
        "days",
        "comp",
        "comp_zero",
        "claimed",
        "currency",
        "sat",
    ]
    recs = [dict(zip(cols, r)) for r in rows]
    for r in recs:
        r["outcome"], r["rule"] = classify(r["resolution"])
    n_all = len(recs)
    by_grp = {g: [r for r in recs if r["grp"] == g] for g in GROUPS}
    literal_zero = sum(r["comp_zero"] for r in recs)
    log(f"complaints={n_all:,} " + " ".join(f"{g}={len(by_grp[g]):,}" for g in GROUPS))

    md: list[str] = []
    md.append("# A2 - Disputed charges closed as a valid charge\n")
    md.append(
        f"Generated by `ml/analysis/day1/A2_dispute_outcomes.py` on "
        f"{date.today().isoformat()} over `ml/data/02_intermediate/complaints.parquet` "
        f"({n_all:,} complaints). Groups come from A1: **core** = Transactions / "
        f"Cargo no reconocido ({len(by_grp['core']):,}), **extended** = Fees / Cobro "
        f"indebido ({len(by_grp['extended']):,}, sensitivity only), **rest** = "
        f"Technical, Branch, Service ({len(by_grp['rest']):,}). 'Decided' means "
        f"status Resolved, Closed or Rejected.\n"
    )
    md.append("## Hypothesis\n")
    md.append(
        "Some unrecognized-charge complaints are closed as a valid charge, visible in "
        "the `resolution` text and in `compensation_granted`. If not, Track A can only "
        "rest on industry evidence.\n"
    )
    verdict_at = len(md)
    md.append("")  # verdict placeholder

    # (a) status ------------------------------------------------------------
    md.append("## (a) Status\n")
    table = []
    out = []
    for s in STATUSES:
        cnt = [sum(r["status"] == s for r in by_grp[g]) for g in GROUPS]
        table.append(cnt)
        out.append(
            [s] + [f"{c:,} ({pct(c / len(by_grp[g]))})" for c, g in zip(cnt, GROUPS)]
        )
    md.append(md_table(["status"] + GROUPS, out))
    p_status = chi2_p(table)
    md.append(
        f"\nChi-square of group vs status: p = {p_status:.3g}. Only Resolved and "
        f"Closed rows carry `resolution`, `resolution_days` and "
        f"`compensation_granted`; Rejected rows carry none of them, so the reason for "
        f"a rejection is not recorded.\n"
    )

    # (b) compensation -------------------------------------------------------
    md.append("## (b) compensation_granted: zero vs non-zero\n")
    md.append(
        f"The column has {literal_zero} literal zeros: null means no compensation. "
        f"Non-null values only appear on Resolved / Closed rows.\n"
    )
    out = []
    for g in GROUPS:
        rs = by_grp[g]
        rc = [r for r in rs if r["status"] in ("Resolved", "Closed")]
        paid = [r for r in rc if r["comp"] > 0]
        ratios = [r["comp"] / r["claimed"] for r in paid if r["claimed"]]
        out.append(
            [
                g,
                f"{len(rc):,}",
                f"{len(rc) - len(paid):,}",
                f"{len(paid):,}",
                share(len(paid), len(rc)),
                f"{sum(r['comp'] > 0 for r in rs) / len(rs):.2%}",
                fmt(statistics.median([r["comp"] for r in paid])) if paid else "n/a",
                fmt(max(r["comp"] for r in paid)) if paid else "n/a",
                f"{statistics.median(ratios):.1%}" if ratios else "n/a",
            ]
        )
    md.append(
        md_table(
            [
                "group",
                "resolved/closed",
                "zero",
                "non-zero",
                "non-zero share of resolved/closed (95% CI)",
                "non-zero share of all",
                "median paid",
                "max paid",
                "median paid / claimed",
            ],
            out,
        )
    )
    comp_table = [
        [
            sum(
                r["comp"] > 0
                for r in by_grp[g]
                if r["status"] in ("Resolved", "Closed")
            ),
            sum(
                r["comp"] == 0
                for r in by_grp[g]
                if r["status"] in ("Resolved", "Closed")
            ),
        ]
        for g in GROUPS
    ]
    p_comp = chi2_p(comp_table)
    md.append(
        f"\nChi-square of group vs compensation (resolved/closed only): "
        f"p = {p_comp:.3g}. Compensation is a small goodwill amount (max "
        f"{fmt(max(r['comp'] for r in recs))}), not a refund of the claimed amount.\n"
    )
    out = []
    for s in ("Resolved", "Closed"):
        for g in GROUPS[:2]:
            rc = [r for r in by_grp[g] if r["status"] == s]
            k = sum(r["comp"] > 0 for r in rc)
            out.append([s, g, f"{len(rc):,}", share(k, len(rc))])
    md.append(md_table(["status", "group", "n", "non-zero share (95% CI)"], out))
    md.append("")

    # (c) resolution_days -----------------------------------------------------
    md.append("## (c) resolution_days\n")
    out = [
        [g] + quantiles([r["days"] for r in by_grp[g] if r["days"] is not None])
        for g in GROUPS
    ]
    md.append(md_table(["group"] + QHEAD, out))
    md.append("")
    out = []
    for g in GROUPS[:2]:
        for s in ("Resolved", "Closed"):
            xs = [
                r["days"]
                for r in by_grp[g]
                if r["status"] == s and r["days"] is not None
            ]
            out.append([g, s] + quantiles(xs))
    md.append(md_table(["group", "status"] + QHEAD, out))
    bins = [(0, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 30), (31, 10**6)]
    out = []
    for lo, hi in bins:
        label = f"{lo}-{hi}" if hi < 10**6 else f">{lo - 1}"
        row = [label]
        for g in GROUPS:
            xs = [r["days"] for r in by_grp[g] if r["days"] is not None]
            row.append(pct(sum(lo <= x <= hi for x in xs) / len(xs)))
        out.append(row)
    md.append("\nHistogram (share of rows with resolution_days):\n")
    md.append(md_table(["days"] + GROUPS, out))
    md.append("")

    # (d) outcome classification ---------------------------------------------
    md.append("## (d) Resolution text -> outcome (keyword rules)\n")
    md.append("Rules run on the lower-cased text, first match wins:\n")
    md.append(
        md_table(
            ["order", "rule", "outcome", "pattern"],
            [[i + 1, n, o, f"`{p}`"] for i, (n, o, p) in enumerate(RULES)]
            + [[len(RULES) + 1, "none", "other", "(no rule matched)"]],
        )
    )
    texts = sorted({r["resolution"] for r in recs if r["resolution"] is not None})
    n_text_disp = len(
        {r["resolution"] for r in recs if r["grp"] != "rest" and r["resolution"]}
    )
    md.append(
        f"\n`resolution` has **{len(texts)} distinct texts** across all {n_all:,} "
        f"complaints ({n_text_disp} in core + extended). Each one and where it lands:\n"
    )
    out = []
    for t in texts:
        o, rule = classify(t)
        out.append(
            [f"'{t}'", o, rule]
            + [f"{sum(r['resolution'] == t for r in by_grp[g]):,}" for g in GROUPS]
        )
    md.append(md_table(["resolution text", "outcome", "rule"] + GROUPS, out))

    md.append("\n### Outcome counts\n")
    md.append(
        "Share of each group's rows with a text (Resolved / Closed). Resolved/Closed "
        "rows without a text and all other statuses are 'no text'.\n"
    )
    out = []
    for o in OUTCOMES + [NO_TEXT]:
        row = [o]
        for g in GROUPS:
            rs = by_grp[g]
            with_text = [r for r in rs if r["outcome"] != NO_TEXT]
            k = sum(r["outcome"] == o for r in rs)
            row.append(
                f"{k:,}" + (f" ({pct(k / len(with_text))})" if o != NO_TEXT else "")
            )
        out.append(row)
    md.append(md_table(["outcome"] + GROUPS, out))
    rules_hit = {rule: sum(r["rule"] == rule for r in recs) for rule, _, _ in RULES}
    md.append(
        "\nRule hits over all complaints: "
        + ", ".join(f"`{k}` {v:,}" for k, v in rules_hit.items())
        + ".\n"
    )

    md.append("### Does the text mean what it says?\n")
    disp = [
        r for r in recs if r["grp"] != "rest" and r["status"] in ("Resolved", "Closed")
    ]
    out = []
    ctab = []
    for t in texts + [None]:
        rs = [r for r in disp if r["resolution"] == t]
        k = sum(r["comp"] > 0 for r in rs)
        ctab.append([k, len(rs) - k])
        days = [r["days"] for r in rs if r["days"] is not None]
        sat = [r["sat"] for r in rs if r["sat"] is not None]
        out.append(
            [
                "'" + t + "'" if t else "*null*",
                classify(t)[0],
                f"{len(rs):,}",
                share(k, len(rs)),
                fmt(statistics.fmean(days)) if days else "n/a",
                f"{fmt(statistics.fmean(sat))} ({len(sat)})" if sat else "n/a",
            ]
        )
    md.append(
        "Core + extended, Resolved / Closed. If the text reflected the decision, "
        "'compensation' and 'adjustment' texts would pay far more often than the "
        "'explanation' text.\n"
    )
    md.append(
        md_table(
            [
                "resolution text",
                "outcome",
                "n",
                "compensation > 0 (95% CI)",
                "mean resolution_days",
                "mean satisfaction (n)",
            ],
            out,
        )
    )
    p_text_comp = chi2_p(ctab)
    cat_names = sorted({r["category"] for r in recs})
    cat_tab = [
        [sum(r["category"] == c and r["resolution"] == t for r in recs) for t in texts]
        for c in cat_names
    ]
    p_text_cat = chi2_p(cat_tab)
    md.append(
        f"\n- Text vs compensation (non-zero / zero): chi-square p = {p_text_comp:.3g}.\n"
        f"- Text vs category over all {len(cat_names)} categories: chi-square "
        f"p = {p_text_cat:.3g}.\n"
    )

    # (e) examples ------------------------------------------------------------
    md.append("## (e) 20 random examples per outcome (core + extended)\n")
    md.append(
        f"Sampled with `random.Random({SEED})` from core + extended rows with a text.\n"
    )
    rng = random.Random(SEED)
    pool = [r for r in recs if r["grp"] != "rest" and r["outcome"] != NO_TEXT]
    for o in OUTCOMES:
        rs = [r for r in pool if r["outcome"] == o]
        md.append(f"### {o} ({len(rs):,} rows)\n")
        if not rs:
            md.append("No row matches. There is nothing to sample.\n")
            continue
        sample = rng.sample(rs, min(N_EXAMPLES, len(rs)))
        md.append(
            md_table(
                [
                    "complaint_id",
                    "category",
                    "status",
                    "rule",
                    "claimed",
                    "compensation",
                    "days",
                    "resolution",
                ],
                [
                    [
                        r["id"],
                        r["category"],
                        r["status"],
                        r["rule"],
                        f"{fmt(r['claimed'])} {r['currency'] or '(no currency)'}"
                        if r["claimed"] is not None
                        else "*null*",
                        fmt(r["comp"]),
                        r["days"] if r["days"] is not None else "n/a",
                        r["resolution"],
                    ]
                    for r in sample
                ],
            )
        )
        md.append("")

    # (f) share closed as legitimate charge ----------------------------------
    md.append("## (f) Share closed as a legitimate charge\n")
    md.append(
        "Denominator: decided complaints (Resolved + Closed + Rejected). Each row is a "
        "different reading of 'closed as a legitimate charge', from strict to lenient.\n"
    )
    est: dict[str, dict[str, tuple[int, int]]] = {}
    defs = [
        (
            "E0 explicit wording ('cargo válido', 'procedente', ...)",
            lambda r: r["rule"] == "valid_explicit",
        ),
        (
            "E1 'explanation' text and no compensation",
            lambda r: r["rule"] == "valid_explained" and r["comp"] == 0,
        ),
        (
            "E2 'explanation' text (any compensation)",
            lambda r: r["rule"] == "valid_explained",
        ),
        ("E3 status Rejected", lambda r: r["status"] == "Rejected"),
        (
            "E4 E1 or Rejected",
            lambda r: (r["rule"] == "valid_explained" and r["comp"] == 0)
            or r["status"] == "Rejected",
        ),
        (
            "E5 decided with no compensation (upper bound)",
            lambda r: r["comp"] == 0,
        ),
    ]
    out = []
    for label, f in defs:
        row = [label]
        est[label] = {}
        for g in GROUPS:
            dec = [r for r in by_grp[g] if r["status"] in DECIDED]
            k = sum(f(r) for r in dec)
            est[label][g] = (k, len(dec))
            row.append(share(k, len(dec)))
        out.append(row)
    md.append(md_table(["estimate"] + [f"{g} (95% CI)" for g in GROUPS], out))
    core_dec = est[defs[0][0]]["core"][1]
    core_all = len(by_grp["core"])
    k1, _ = est[defs[1][0]]["core"]
    k4, _ = est[defs[4][0]]["core"]
    md.append(
        f"\nCore has {core_dec:,} decided complaints out of {core_all:,} "
        f"({pct(core_dec / core_all)}); the rest are still Open, In Process or "
        f"Escalated. As a share of **all** core complaints, E1 is "
        f"{pct(k1 / core_all)} and E4 is {pct(k4 / core_all)}.\n"
    )
    md.append(
        "E1-E4 are proxies built on a text that does not track compensation or "
        "category (section d), so they measure how often the generator picked the "
        "'explanation' sentence, not how often a charge was upheld. They must not be "
        "cited as a measured rate of upheld charges. E5 counts every decided dispute "
        "that was not paid, whatever the reason.\n"
    )

    # verdict -------------------------------------------------------------------
    k0, n0 = est[defs[0][0]]["core"]
    kf = sum(r["outcome"] == "fraud confirmed" for r in by_grp["core"])
    core_text = [r for r in by_grp["core"] if r["outcome"] != NO_TEXT]
    k2 = sum(r["rule"] == "valid_explained" for r in core_text)
    verdict = "not testable with this dataset"
    md[verdict_at] = (
        f"## Verdict: **{verdict}**\n\n"
        f"- **No outcome field.** `resolution` is one of {len(texts)} generic sentences "
        f"shared by every category (text vs category p = {p_text_cat:.2g}). No text "
        f"says the charge was valid ({k0} of {n0:,} decided core disputes) and none "
        f"says fraud ({kf}).\n"
        f"- **The text contradicts the money.** 'Se otorgó compensación' rows are paid "
        f"about as often as the rest (text vs compensation p = {p_text_comp:.2g}), so "
        f"the text is not the decision.\n"
        f"- **Best proxy.** Reading 'explanation, no adjustment' as 'charge upheld' "
        f"gives {pct(k2 / len(core_text))} of core disputes with a text, and "
        f"{share(k1, n0)} of decided core disputes when also requiring no "
        f"compensation ({share(k4, n0)} adding Rejected). This is a template "
        f"frequency (1 in {len(texts)}), not evidence.\n"
        f"- **Everything looks like the rest.** Status (p = {p_status:.2g}), "
        f"compensation (p = {p_comp:.2g}) and resolution_days match Technical, Branch "
        f"and Service.\n"
        f"- **Consequence (from 'Si falla'):** the 'closed as valid charge' thesis can "
        f"only be supported by industry evidence, not by this dataset.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "A2.md").write_text(report, encoding="utf-8")
    line = (
        f"- A2 (disputes closed as valid charge): {verdict}. `resolution` is "
        f"{len(texts)} generic texts independent of category and of compensation; 0 "
        f"say 'valid charge', 0 say fraud; best proxy ('explanation' text, no "
        f"compensation) {pct(k1 / n0)} of decided core disputes; status, compensation "
        f"and resolution_days match other categories; see docs/findings/day1/A2.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- A2 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
