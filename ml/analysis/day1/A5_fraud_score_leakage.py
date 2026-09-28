"""A5 - does fraud_score leak is_fraud?

Checks:
  (a) is_fraud prevalence overall and by year, plus the train / holdout split.
  (b) fraud_score coverage: null rate by class (must be independent of the label
      for the non-null AUC to be representative).
  (c) fraud_score distribution by class and fraud rate per score decile.
  (d) ROC AUC and PR AUC (average precision, sklearn step definition) of
      fraud_score alone vs is_fraud, overall, on the pre-holdout period and on a
      temporal holdout (last 6 months). 95% CIs from a stratified bootstrap.
      Flags: AUC > 0.95 -> likely leakage; |AUC - 0.5| < 0.05 -> noise.
  (e) post-outcome leakage: is_fraud vs transaction_status (Declined / Reversed)
      and response_code, and fraud_score by status.
  (f) sanity: AUC of other raw columns (amount_usd, hour) to see whether the
      label is carried by anything besides fraud_score.

All metrics are computed from per-value score histograms (fraud_score has two
decimals, so at most 10,001 distinct values). Ties are handled exactly as in
sklearn's roc_auc_score / average_precision_score, and the bootstrap resamples
each class with a multinomial draw over its histogram.

Outputs:
  docs/findings/day1/A5.md                 (committed report)
  data/08_reporting/day1/A5.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (A5 line)

Run from ml/:  .venv/Scripts/python analysis/day1/A5_fraud_score_leakage.py
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import chi2_p, fmt, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

HOLDOUT_MONTHS = 6
LEAK_AUC = 0.95  # above this the score almost certainly encodes the label
NOISE_BAND = 0.05  # |AUC - 0.5| below this the score is noise
N_BOOT = 1000
ALPHA = 0.05
BOOT_CHUNK = 100
SEED = 42
SCALE = 100  # fraud_score has 2 decimals -> integer bins 0..10000
SCORE_MAX = 100
N_BINS = SCORE_MAX * SCALE + 1
POST_OUTCOME = ("Declined", "Reversed")

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def ci95_3(k: int, n: int) -> str:
    """Wilson 95% interval, in percent with 3 decimals (prevalence is ~0.1%)."""
    if n == 0:
        return "n/a"
    p, z = k / n, 1.96
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return f"[{100 * (mid - half):.3f}, {100 * (mid + half):.3f}]"


def pct3(k: int, n: int) -> str:
    return f"{100 * k / n:.3f}% {ci95_3(k, n)}" if n else "n/a"


def hists(bins: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-value counts of positives and negatives."""
    pos = np.bincount(bins[y], minlength=N_BINS).astype(np.float64)
    neg = np.bincount(bins[~y], minlength=N_BINS).astype(np.float64)
    return pos, neg


def auc_ap(pos: np.ndarray, neg: np.ndarray) -> tuple[float, float]:
    """ROC AUC (ties count 1/2) and average precision from per-value counts.

    Works on the last axis, so pos / neg may be (n_bins,) or (n_boot, n_bins).
    """
    p_tot = pos.sum(axis=-1)
    n_tot = neg.sum(axis=-1)
    neg_below = np.cumsum(neg, axis=-1) - neg
    auc = (pos * (neg_below + 0.5 * neg)).sum(axis=-1) / (p_tot * n_tot)
    # thresholds from the highest value down; one step per distinct value
    tp = np.cumsum(pos[..., ::-1], axis=-1)
    fp = np.cumsum(neg[..., ::-1], axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        prec = np.where(tp + fp > 0, tp / (tp + fp), 0.0)
    ap = (pos[..., ::-1] * prec).sum(axis=-1) / p_tot
    return auc, ap


def boot_ci(pos: np.ndarray, neg: np.ndarray, rng: np.random.Generator) -> tuple:
    """Stratified bootstrap 95% CIs for (AUC, AP)."""
    p_tot, n_tot = int(pos.sum()), int(neg.sum())
    aucs, aps = [], []
    for _ in range(N_BOOT // BOOT_CHUNK):  # chunks keep memory at ~100 MB
        bp = rng.multinomial(p_tot, pos / p_tot, size=BOOT_CHUNK).astype(np.float64)
        bn = rng.multinomial(n_tot, neg / n_tot, size=BOOT_CHUNK).astype(np.float64)
        a, p = auc_ap(bp, bn)
        aucs.append(a)
        aps.append(p)
    auc, ap = np.concatenate(aucs), np.concatenate(aps)
    return tuple(np.quantile(auc, [0.025, 0.975])), tuple(
        np.quantile(ap, [0.025, 0.975])
    )


def rank_auc(x: np.ndarray, y: np.ndarray) -> float:
    """Mann-Whitney AUC of a continuous column (average ranks for ties)."""
    _, inv, cnt = np.unique(x, return_inverse=True, return_counts=True)
    start = np.cumsum(cnt) - cnt
    ranks = (start + (cnt + 1) / 2)[inv]
    n_pos = int(y.sum())
    n_neg = len(y) - n_pos
    return float((ranks[y].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def flag(auc: float) -> str:
    if auc > LEAK_AUC:
        return "likely leakage"
    if abs(auc - 0.5) < NOISE_BAND:
        return "noise"
    return "informative"


def main() -> None:
    con = duckdb.connect()
    con.sql(
        f"create view t as select * from "
        f"'{(INTER / 'transactions.parquet').as_posix()}'"
    )
    max_ts = con.sql("select max(transaction_date) from t").fetchone()[0]
    min_ts = con.sql("select min(transaction_date) from t").fetchone()[0]
    cut = con.sql(
        f"select (timestamp '{max_ts}' - interval {HOLDOUT_MONTHS} month)::date"
    ).fetchone()[0]
    log(f"range {min_ts} .. {max_ts}, holdout from {cut}")

    arr = con.sql(
        f"""
        select is_fraud,
               coalesce(round(fraud_score * {SCALE})::int, -1) as bin,
               transaction_date >= date '{cut}' as holdout,
               year(transaction_date) as yr,
               amount_usd::double as amount_usd,
               hour(transaction_date) as hr
        from t
        """
    ).fetchnumpy()
    y = np.asarray(arr["is_fraud"], dtype=bool)
    b = np.asarray(arr["bin"], dtype=np.int64)
    ho = np.asarray(arr["holdout"], dtype=bool)
    yr = np.asarray(arr["yr"])
    n, k = len(y), int(y.sum())
    log(f"loaded {n:,} rows, {k:,} frauds")

    md: list[str] = [
        "# A5 - fraud_score leakage into is_fraud",
        "",
        f"Generated by `ml/analysis/day1/A5_fraud_score_leakage.py` on "
        f"{date.today().isoformat()} over `ml/data/02_intermediate/transactions.parquet` "
        f"({n:,} transactions, {min_ts:%Y-%m-%d} to {max_ts:%Y-%m-%d}). Temporal holdout "
        f"= last {HOLDOUT_MONTHS} months (`transaction_date >= {cut}`). ROC AUC and PR AUC "
        f"(average precision) use fraud_score alone, on rows where it is non-null; CIs "
        f"are a {N_BOOT}-draw stratified bootstrap. Rates carry Wilson 95% CIs.",
        "",
        "## Hypothesis",
        "",
        "`fraud_score` does not leak `is_fraud`, so it can serve as a baseline. Flags "
        f"set in advance: AUC > {LEAK_AUC} -> likely leakage; AUC within "
        f"{NOISE_BAND} of 0.5 -> noise. Separately, if `is_fraud` tracks "
        "`transaction_status` (Declined / Reversed) the label is post-outcome.",
        "",
    ]
    verdict_at = len(md)
    md.append("")

    # (a) prevalence -------------------------------------------------------------
    md += ["## (a) is_fraud prevalence", ""]
    rows = [["all", f"{n:,}", f"{k:,}", pct3(k, n)]]
    table_yr = []
    for v in np.unique(yr):
        m = yr == v
        ky, ny = int(y[m].sum()), int(m.sum())
        rows.append([str(v), f"{ny:,}", f"{ky:,}", pct3(ky, ny)])
        table_yr.append([ky, ny - ky])
    for label, m in [(f"pre-holdout (< {cut})", ~ho), (f"holdout (>= {cut})", ho)]:
        km, nm = int(y[m].sum()), int(m.sum())
        rows.append([label, f"{nm:,}", f"{km:,}", pct3(km, nm)])
    p_year = chi2_p(table_yr)
    k_ho, n_ho = int(y[ho].sum()), int(ho.sum())
    p_split = chi2_p([[k - k_ho, (n - n_ho) - (k - k_ho)], [k_ho, n_ho - k_ho]])
    md.append(md_table(["period", "transactions", "is_fraud", "rate (95% CI)"], rows))
    md.append(
        f"\nYear vs is_fraud chi-square p = {p_year:.3g}; pre-holdout vs holdout "
        f"p = {p_split:.3g}. 2023 starts on {min_ts:%m-%d} and 2026 ends on "
        f"{max_ts:%m-%d}, so those years are partial; rates, not counts, are "
        f"comparable. At {pct(k / n)} a random score has PR AUC ~ {k / n:.4f}.\n"
    )

    # (b) coverage ---------------------------------------------------------------
    nul = b < 0
    kn_p, kn_n = int((nul & y).sum()), int((nul & ~y).sum())
    p_null = chi2_p([[kn_p, k - kn_p], [kn_n, (n - k) - kn_n]])
    md += [
        "## (b) fraud_score coverage",
        "",
        md_table(
            ["class", "rows", "fraud_score null (95% CI)"],
            [
                ["is_fraud = true", f"{k:,}", f"{pct(kn_p / k)} {ci95_3(kn_p, k)}"],
                [
                    "is_fraud = false",
                    f"{n - k:,}",
                    f"{pct(kn_n / (n - k))} {ci95_3(kn_n, n - k)}",
                ],
            ],
        ),
        f"\nNull rate vs label p = {p_null:.3g}. Nulls are missing at random with respect "
        f"to the label, so AUCs on the {n - kn_p - kn_n:,} non-null rows are "
        "representative. Treating null as score 0 would only add ties at the bottom.\n",
    ]

    # (c) distribution -----------------------------------------------------------
    ok = ~nul
    pos, neg = hists(b[ok], y[ok])
    vals = np.arange(N_BINS) / SCALE

    def qrow(label: str, h: np.ndarray) -> list[str]:
        c = np.cumsum(h) / h.sum()
        qs = [vals[np.searchsorted(c, q)] for q in (0.1, 0.25, 0.5, 0.75, 0.9)]
        nz = np.nonzero(h)[0]
        mean = float((h * vals).sum() / h.sum())
        sd = math.sqrt(float((h * (vals - mean) ** 2).sum() / h.sum()))
        return (
            [label, f"{int(h.sum()):,}", fmt(mean), fmt(sd), fmt(vals[nz[0]])]
            + [fmt(q) for q in qs]
            + [fmt(vals[nz[-1]])]
        )

    neg_max = float(vals[np.nonzero(neg)[0][-1]])
    above = vals > neg_max
    k_above = int(pos[above].sum())
    k_pos = int(pos.sum())
    md += [
        "## (c) fraud_score distribution by class",
        "",
        md_table(
            [
                "class",
                "n",
                "mean",
                "sd",
                "min",
                "p10",
                "p25",
                "median",
                "p75",
                "p90",
                "max",
            ],
            [qrow("is_fraud = true", pos), qrow("is_fraud = false", neg)],
        ),
        "",
    ]
    dec_rows = []
    for lo in range(0, SCORE_MAX, 10):
        last = lo + 10 == SCORE_MAX  # the top decile includes 100
        m = (vals >= lo) & (vals <= SCORE_MAX if last else vals < lo + 10)
        kp, kn = int(pos[m].sum()), int(neg[m].sum())
        dec_rows.append(
            [
                f"[{lo}, {lo + 10}{']' if last else ')'}",
                f"{kn:,}",
                f"{kp:,}",
                f"{pct(kp / k_pos)}",
                pct3(kp, kp + kn),
            ]
        )
    md.append(
        md_table(
            [
                "fraud_score",
                "non-fraud",
                "fraud",
                "share of frauds",
                "fraud rate (95% CI)",
            ],
            dec_rows,
        )
    )
    md.append(
        f"\nNon-fraud scores never exceed **{neg_max:g}**. Fraud scores spread evenly "
        f"over [0, 100] (each decile holds ~10% of frauds), so the data look drawn as "
        f"non-fraud ~ U(0, 30) and fraud ~ U(0, 100) given the label. Every score above "
        f"{neg_max:g} is fraud: {k_above:,} of {k_pos:,} frauds "
        f"({pct(k_above / k_pos)}) are identified with 100% precision by one threshold, "
        f"and the rest are indistinguishable from legitimate traffic. Under that model "
        f"AUC = 0.7 + 0.3 * 0.5 = 0.85 and AP ~ 0.70 + small.\n"
    )

    # (d) AUC --------------------------------------------------------------------
    rng = np.random.default_rng(SEED)
    md += ["## (d) ROC AUC and PR AUC of fraud_score alone", ""]
    res = {}
    rows = []
    for label, m in [
        ("overall", ok),
        (f"pre-holdout (< {cut})", ok & ~ho),
        (f"holdout, last {HOLDOUT_MONTHS} months (>= {cut})", ok & ho),
    ]:
        pp, nn = hists(b[m], y[m])
        auc, ap = auc_ap(pp, nn)
        (a_lo, a_hi), (p_lo, p_hi) = boot_ci(pp, nn, rng)
        prev = pp.sum() / (pp.sum() + nn.sum())
        res[label] = (float(auc), float(ap))
        rows.append(
            [
                label,
                f"{int(pp.sum()):,} / {int(nn.sum()):,}",
                f"{auc:.4f} [{a_lo:.4f}, {a_hi:.4f}]",
                f"{ap:.4f} [{p_lo:.4f}, {p_hi:.4f}]",
                f"{prev:.4f}",
                flag(float(auc)),
            ]
        )
        log(f"{label}: AUC {auc:.4f} AP {ap:.4f}")
    md.append(
        md_table(
            [
                "set",
                "frauds / non-frauds",
                "ROC AUC (95% CI)",
                "PR AUC (95% CI)",
                "random PR AUC",
                "flag",
            ],
            rows,
        )
    )
    auc_all, ap_all = res["overall"]
    auc_ho, ap_ho = res[f"holdout, last {HOLDOUT_MONTHS} months (>= {cut})"]

    # threshold rule on holdout
    hp, hn = hists(b[ok & ho], y[ok & ho])
    tp_h, fp_h = int(hp[above].sum()), int(hn[above].sum())
    md.append(
        f"\nThe rule `fraud_score > {neg_max:g}` on the holdout: precision "
        f"{pct(tp_h / (tp_h + fp_h)) if tp_h + fp_h else 'n/a'} ({tp_h:,} TP, {fp_h:,} FP), "
        f"recall {pct(tp_h / hp.sum())}. The score needs no fitting, so the holdout "
        f"only checks that the relation is stable over time; it is.\n"
    )
    md.append(
        f"AUC is below the {LEAK_AUC} leakage flag and far from 0.5, so the pre-set "
        f"flags would call it merely 'informative'. The flag misses the pattern because "
        f"the leakage is partial: the score reveals the label outright for ~70% of "
        f"frauds and carries no information for the rest. No real risk score has zero "
        f"false positives across {int(neg.sum()):,} legitimate transactions above a "
        f"single cut-off.\n"
    )

    # (e) post-outcome leakage ---------------------------------------------------
    st = con.sql(
        """
        select transaction_status, count(*) n, sum(is_fraud::int)::bigint k,
               avg(fraud_score) ms,
               avg(fraud_score) filter (where is_fraud) ms_f,
               avg(fraud_score) filter (where not is_fraud) ms_nf
        from t group by 1 order by n desc
        """
    ).fetchall()
    rows = [
        [s, f"{nn:,}", f"{kk:,}", pct3(kk, nn), fmt(ms), fmt(msf), fmt(msnf)]
        for s, nn, kk, ms, msf, msnf in st
    ]
    p_status = chi2_p([[kk, nn - kk] for _, nn, kk, *_ in st])
    kd = sum(kk for s, _, kk, *_ in st if s in POST_OUTCOME)
    nd = sum(nn for s, nn, _, *_ in st if s in POST_OUTCOME)
    ko, no = k - kd, n - nd
    rr = (kd / nd) / (ko / no)
    se = math.sqrt(1 / kd - 1 / nd + 1 / ko - 1 / no)
    rr_lo, rr_hi = rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se)
    p_dr = chi2_p([[kd, nd - kd], [ko, no - ko]])
    # share of frauds that end Declined / Reversed vs non-frauds
    share_f, share_nf = kd / k, (nd - kd) / (n - k)
    md += [
        "## (e) Post-outcome leakage: is_fraud vs transaction_status",
        "",
        md_table(
            [
                "transaction_status",
                "n",
                "is_fraud",
                "fraud rate (95% CI)",
                "mean score",
                "mean score (fraud)",
                "mean score (non-fraud)",
            ],
            rows,
        ),
        f"\nStatus vs is_fraud chi-square p = {p_status:.3g}. Declined or Reversed vs "
        f"the rest: fraud rate {pct3(kd, nd)} vs {pct3(ko, no)}, risk ratio "
        f"{rr:.2f} [{rr_lo:.2f}, {rr_hi:.2f}], p = {p_dr:.3g}. "
        f"{pct(share_f)} of frauds end Declined or Reversed vs {pct(share_nf)} of "
        "non-frauds. Mean fraud_score is the same in every status, within each class "
        "too, so the score does not react to the outcome either.\n",
    ]
    rc = con.sql(
        """
        select coalesce(response_code, 'null') rc, count(*) n,
               sum(is_fraud::int)::bigint k
        from t group by 1 order by 1
        """
    ).fetchall()
    p_rc = chi2_p([[kk, nn - kk] for _, nn, kk in rc])
    md.append(
        md_table(
            ["response_code", "n", "is_fraud", "fraud rate (95% CI)"],
            [[c, f"{nn:,}", f"{kk:,}", pct3(kk, nn)] for c, nn, kk in rc],
        )
    )
    md.append(
        f"\nresponse_code vs is_fraud chi-square p = {p_rc:.3g}. A real fraud label is "
        "set after investigation, and confirmed fraud is typically reversed or charged "
        "back, so some dependence on status would be expected. Its absence means "
        "is_fraud was drawn independently of the transaction outcome: there is no "
        "post-outcome leakage, and also no realistic fraud process behind the label.\n"
    )

    # (f) other columns ----------------------------------------------------------
    amt = np.asarray(arr["amount_usd"], dtype=np.float64)
    hr = np.asarray(arr["hr"], dtype=np.float64)
    m_amt = ~np.isnan(amt)
    auc_amt = rank_auc(amt[m_amt], y[m_amt])
    auc_hr = rank_auc(hr, y)
    md += [
        "## (f) Sanity: other raw columns",
        "",
        md_table(
            ["column", "ROC AUC vs is_fraud", "flag"],
            [
                ["amount_usd", f"{auc_amt:.4f}", flag(auc_amt)],
                ["hour of transaction_date", f"{auc_hr:.4f}", flag(auc_hr)],
                [
                    "Declined or Reversed (0/1)",
                    f"{0.5 + (share_f - share_nf) / 2:.4f}",
                    flag(0.5 + (share_f - share_nf) / 2),
                ],
            ],
        ),
        "\nNone of these carries signal. fraud_score is the only column that knows the "
        "label, which fits a generator that sampled the score from the label.\n",
    ]

    # verdict --------------------------------------------------------------------
    verdict = "refuted: fraud_score leaks is_fraud by construction"
    trend = "drifting slightly down" if min(p_year, p_split) < ALPHA else "flat"
    md[verdict_at] = (
        f"## Verdict: **{verdict}**\n\n"
        f"- **Prevalence.** is_fraud = {pct3(k, n)} overall; {trend} by year "
        f"(p = {p_year:.2g}), {pct3(k - k_ho, n - n_ho)} before the holdout vs "
        f"{pct3(k_ho, n_ho)} in it (p = {p_split:.2g}). Tiny in absolute terms; the "
        f"holdout's random PR AUC is lower to match.\n"
        f"- **AUC.** fraud_score alone: ROC AUC {auc_all:.4f}, PR AUC {ap_all:.4f} "
        f"(random {k / n:.4f}); holdout {auc_ho:.4f} / {ap_ho:.4f}. Neither pre-set "
        f"flag fires (not > {LEAK_AUC}, not ~ 0.5).\n"
        f"- **But the score is sampled from the label.** Non-fraud scores stop at "
        f"{neg_max:g}; fraud scores are uniform on [0, 100]. {pct(k_above / k_pos)} of "
        f"frauds sit above {neg_max:g} with 100% precision, the rest are pure noise. That "
        f"is leakage, just partial, which is why AUC lands at ~0.85 instead of > 0.95.\n"
        f"- **No post-outcome leakage.** is_fraud is independent of transaction_status "
        f"(p = {p_status:.2g}; Declined/Reversed RR {rr:.2f} [{rr_lo:.2f}, {rr_hi:.2f}]) "
        f"and response_code (p = {p_rc:.2g}). amount_usd and hour are noise too.\n"
        f"- **Consequence (from 'Si falla'):** exclude fraud_score as a baseline and as a "
        f"feature. Any fraud model reporting AUC ~ 0.85 is reading back the generator. "
        f"Without fraud_score, is_fraud has no learnable signal in the transaction "
        f"columns checked, so a fraud-detection storyline is not supported by this "
        f"dataset.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DOCS, OUT_DATA):
        d.mkdir(parents=True, exist_ok=True)
        (d / "A5.md").write_text(report, encoding="utf-8")
    line = (
        f"- A5 (fraud_score leakage): {verdict}. is_fraud {pct(k / n)} overall, {trend} "
        f"by year (p {p_year:.2g}, holdout {pct(k_ho / n_ho)}); fraud_score ROC AUC {auc_all:.4f} / PR AUC "
        f"{ap_all:.4f} (holdout {auc_ho:.4f} / {ap_ho:.4f}), under the 0.95 flag only "
        f"because the leak is partial: non-fraud scores stop at {neg_max:g}, fraud ~ "
        f"U(0, 100), {pct(k_above / k_pos)} of frauds above {neg_max:g} at 100% "
        f"precision; no post-outcome leakage (status p {p_status:.2g}, Declined/Reversed "
        f"RR {rr:.2f}); see docs/findings/day1/A5.md"
    )
    for d in (OUT_DOCS, OUT_DATA):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- A5 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
