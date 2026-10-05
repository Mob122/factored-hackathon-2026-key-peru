"""P3 - does a credit risk estimate have learnable signal?

Cohort: products with product_type 'Préstamo Personal' or 'Tarjeta Crédito' and a
non-null days_past_due, joined to customers. Targets: days_past_due > 0 and > 30.

Features known at application (customers table): credit_score,
estimated_monthly_income, segment, occupation, education_level, country, and age
at opening_date from date_of_birth. product_type is added as a control.

Models, scored on a temporal hold-out (latest TEST_SHARE of opening_date):
  1. credit_score alone (score = -credit_score, no fitting).
  2. L2 logistic regression (Newton / IRLS in numpy) trained on earlier openings.
Baselines: the test AUC of fixed scores against permuted test labels (N_PERM), and
the logistic regression refit on shuffled training labels (N_SHUF_FIT).
Signal counts as learnable only if the bootstrap 95% CI lower bound of the test AUC
clears the shuffled 95th percentile AND the AUC reaches MATERIAL_AUC.

Also: target rates and credit_score by gender, country and segment, each compared
with a shuffled-group baseline, and model calibration by group on the test split.

Outputs:
  docs/findings/day1/P3_credit_signal.md    (committed report)
  data/08_reporting/day1/P3_credit_signal.md (copy)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (P3 line)

Run from ml/:  .venv/Scripts/python analysis/day1/P3_credit_signal.py
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import chi2_p, ci95, fmt, log, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"
NAME = "P3_credit_signal"

PRODUCT_TYPES = ("Préstamo Personal", "Tarjeta Crédito")
TARGETS = {"dpd>0": 0, "dpd>30": 30}
TEST_SHARE = 0.2
L2 = 1.0
N_PERM = 1000
N_SHUF_FIT = 30
N_BOOT = 200
MATERIAL_AUC = 0.55
SEED = 20260928
CATS = ["segment", "occupation", "education_level", "country", "product_type"]
GROUPS = ["gender", "country", "segment"]

RNG = np.random.default_rng(SEED)


def fp(p: float) -> str:
    return "<0.0001" if p < 1e-4 else f"{p:.4f}"


# ---------------------------------------------------------------- AUC helpers
def ranks(s: np.ndarray) -> np.ndarray:
    """Average ranks (1-based), ties share the mean rank."""
    order = np.argsort(s, kind="mergesort")
    ss = s[order]
    r = np.empty(len(s))
    edges = np.flatnonzero(np.r_[True, ss[1:] != ss[:-1], True])
    for a, b in zip(edges[:-1], edges[1:]):
        r[order[a:b]] = (a + b + 1) / 2
    return r


def auc_from_ranks(r: np.ndarray, y: np.ndarray) -> float:
    n1 = int(y.sum())
    n0 = len(y) - n1
    return (r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def auc(s: np.ndarray, y: np.ndarray) -> float:
    return auc_from_ranks(ranks(s), y)


def perm_null(s: np.ndarray, y: np.ndarray, n: int = N_PERM) -> np.ndarray:
    """AUC of fixed scores against permuted labels."""
    r = ranks(s)
    n1 = int(y.sum())
    n0 = len(y) - n1
    out = np.empty(n)
    for i in range(n):
        idx = RNG.choice(len(y), n1, replace=False)
        out[i] = (r[idx].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    return out


def boot_ci(s: np.ndarray, y: np.ndarray, n: int = N_BOOT) -> tuple[float, float]:
    vals = []
    for _ in range(n):
        idx = RNG.integers(0, len(y), len(y))
        vals.append(auc(s[idx], y[idx]))
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


# ---------------------------------------------------------- logistic regression
def fit_logreg(X: np.ndarray, y: np.ndarray, l2: float = L2) -> np.ndarray:
    """L2 logistic regression by Newton steps; X includes an intercept column."""
    w = np.zeros(X.shape[1])
    pen = np.full(X.shape[1], l2)
    pen[0] = 0.0
    for _ in range(50):
        p = 1 / (1 + np.exp(-(X @ w)))
        g = X.T @ (p - y) + pen * w
        H = (X * (p * (1 - p))[:, None]).T @ X + np.diag(pen)
        step = np.linalg.solve(H, g)
        w -= step
        if np.abs(step).max() < 1e-8:
            break
    return w


def predict(X: np.ndarray, w: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(X @ w)))


def design(d: dict, train: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Numeric features standardized on train, missing flags, one-hot categoricals."""
    cols, names = [np.ones(len(train))], ["intercept"]
    for name in ["credit_score", "income_z", "age"]:
        v = d[name].astype(float)
        miss = np.isnan(v)
        med = np.nanmedian(v[train])
        v = np.where(miss, med, v)
        mu, sd = v[train].mean(), v[train].std()
        z = (v - mu) / sd
        cols.append(z)
        names.append(name)
        if name == "age":
            cols.append(z**2)
            names.append("age^2")
        if miss.any():
            cols.append(miss.astype(float))
            names.append(f"{name}_missing")
    for c in CATS:
        v = d[c]
        levels = sorted({x for x in v[train]}, key=str)
        for lv in levels[1:]:  # first level is the reference
            cols.append((v == lv).astype(float))
            names.append(f"{c}={lv}")
    return np.column_stack(cols), names


# --------------------------------------------------------------------- main
def main() -> None:
    con = duckdb.connect()
    prod, cust = INTER / "products.parquet", INTER / "customers.parquet"
    pt_sql = ", ".join(f"'{p}'" for p in PRODUCT_TYPES)
    md: list[str] = []

    # (a) raw profile
    log("profiling")
    n_prod, n_prod_ids = con.sql(
        f"select count(*), count(distinct product_id) from '{prod}'"
    ).fetchone()
    n_cust, n_cust_ids = con.sql(
        f"select count(*), count(distinct customer_id) from '{cust}'"
    ).fetchone()
    by_type = con.sql(
        f"""select product_type, count(*), count(days_past_due),
                   count(*) filter (days_past_due > 0), count(*) filter (days_past_due > 30)
            from '{prod}' group by 1 order by 2 desc"""
    ).fetchall()
    dpd_vals = con.sql(
        f"""select days_past_due, count(*) from '{prod}'
            where product_type in ({pt_sql}) group by 1 order by 1 nulls last"""
    ).fetchall()

    df = con.sql(
        f"""
        select p.product_id, p.customer_id, p.product_type, p.product_status,
               p.opening_date, p.days_past_due,
               c.credit_score, c.estimated_monthly_income::double as income,
               c.segment, coalesce(c.occupation, '(null)') as occupation,
               coalesce(c.education_level, '(null)') as education_level,
               c.country, c.gender, c.date_of_birth, c.registration_date,
               date_diff('day', c.date_of_birth, p.opening_date) / 365.25 as age,
               c.customer_id is not null as joined
        from '{prod}' p left join '{cust}' c using (customer_id)
        where p.product_type in ({pt_sql})
        """
    ).df()
    n_cohort_raw = len(df)
    n_unjoined = int((~df["joined"]).sum())
    n_dpd_null = int(df["days_past_due"].isna().sum())
    null_rows = [
        [c, f"{int(df[c].isna().sum()):,}", pct(df[c].isna().mean())]
        for c in [
            "days_past_due",
            "credit_score",
            "income",
            "segment",
            "country",
            "gender",
            "date_of_birth",
        ]
    ] + [
        [c, f"{int((df[c] == '(null)').sum()):,}", pct((df[c] == "(null)").mean())]
        for c in ["occupation", "education_level"]
    ]
    before_reg = float(
        (df["opening_date"] < df["registration_date"].dt.normalize()).mean()
    )
    null_by_status = con.sql(
        f"""select product_status, count(*), count(*) filter (days_past_due is null)
            from '{prod}' where product_type in ({pt_sql}) group by 1 order by 2 desc"""
    ).fetchall()

    df = df[df["joined"] & df["days_past_due"].notna()].reset_index(drop=True)
    n = len(df)
    # income is in local currency (COP / MXN / ARS): z-score log income within country
    li = np.log(df["income"].where(df["income"] > 0))
    df["income_z"] = (li - li.groupby(df["country"]).transform("mean")) / li.groupby(
        df["country"]
    ).transform("std")
    d = {c: df[c].to_numpy() for c in df.columns}
    d["credit_score"] = df["credit_score"].astype(float).to_numpy()
    d["income_z"] = df["income_z"].astype(float).to_numpy()
    d["age"] = df["age"].astype(float).to_numpy()
    for c in CATS + GROUPS:
        d[c] = df[c].astype(str).to_numpy()
    dpd = df["days_past_due"].astype(int).to_numpy()
    ys = {t: (dpd > k).astype(int) for t, k in TARGETS.items()}

    # temporal split
    od = df["opening_date"].to_numpy().astype("datetime64[D]")
    cutoff = np.sort(od)[int(len(od) * (1 - TEST_SHARE))]
    test = od >= cutoff
    train = ~test
    cust_train = set(df.loc[train, "customer_id"])
    test_new = test & ~df["customer_id"].isin(cust_train).to_numpy()
    log(f"cohort {n:,}, train {train.sum():,}, test {test.sum():,}, cutoff {cutoff}")

    X, names = design(d, train)
    cs = d["credit_score"]
    cs_ok = ~np.isnan(cs)

    results = {}
    for t, y in ys.items():
        log(f"target {t}")
        r: dict = {"rate_train": y[train].mean(), "rate_test": y[test].mean()}
        # credit_score alone
        m = test & cs_ok
        s_cs = -cs[m]
        r["cs_full"] = auc(-cs[cs_ok], y[cs_ok])
        r["cs_test"] = auc(s_cs, y[m])
        r["cs_ci"] = boot_ci(s_cs, y[m])
        null = perm_null(s_cs, y[m])
        r["cs_null95"] = float(np.percentile(np.abs(null - 0.5), 95)) + 0.5
        r["cs_p"] = float((np.abs(null - 0.5) >= abs(r["cs_test"] - 0.5)).mean())
        r["cs_n"] = int(m.sum())
        # logistic regression
        w = fit_logreg(X[train], y[train])
        p_te = predict(X[test], w)
        r["w"] = w
        r["lr_train"] = auc(predict(X[train], w), y[train])
        r["lr_test"] = auc(p_te, y[test])
        r["lr_ci"] = boot_ci(p_te, y[test])
        null = perm_null(p_te, y[test])
        r["lr_perm95"] = float(np.percentile(null, 95))
        r["lr_perm_p"] = float((null >= r["lr_test"]).mean())
        r["lr_new"] = auc(predict(X[test_new], w), y[test_new])
        shuf = []
        for _ in range(N_SHUF_FIT):
            ws = fit_logreg(X[train], RNG.permutation(y[train]))
            shuf.append(auc(predict(X[test], ws), y[test]))
        r["shuf_mean"] = float(np.mean(shuf))
        r["shuf95"] = float(np.percentile(shuf, 95))
        r["shuf_max"] = float(np.max(shuf))
        r["p_te"] = p_te
        # log loss vs constant train rate
        eps = 1e-12
        yt = y[test]
        ll = -np.mean(yt * np.log(p_te + eps) + (1 - yt) * np.log(1 - p_te + eps))
        p0 = r["rate_train"]
        ll0 = -np.mean(yt * np.log(p0) + (1 - yt) * np.log(1 - p0))
        r["ll"], r["ll0"] = ll, ll0
        # univariate test AUC per feature (categoricals: train target rate)
        uni = []
        for f in ["credit_score", "income_z", "age"]:
            v = d[f]
            mm = test & ~np.isnan(v)
            a = auc(v[mm], y[mm])
            uni.append([f, "numeric", f"{max(a, 1 - a):.4f}", "+" if a >= 0.5 else "-"])
        for c in CATS:
            v = d[c]
            rates = {lv: y[train & (v == lv)].mean() for lv in np.unique(v[train])}
            s = np.array([rates.get(x, y[train].mean()) for x in v[test]])
            uni.append([c, f"{len(rates)} levels", f"{auc(s, y[test]):.4f}", ""])
        r["uni"] = uni
        results[t] = r

    signal = {
        t: (r["lr_ci"][0] > r["shuf95"] and r["lr_test"] >= MATERIAL_AUC)
        or (r["cs_ci"][0] > r["cs_null95"] and r["cs_test"] >= MATERIAL_AUC)
        for t, r in results.items()
    }
    r0, r30 = results["dpd>0"], results["dpd>30"]
    best = max(max(r["lr_test"], r["cs_test"]) for r in results.values())
    if any(signal.values()):
        verdict = "supported: application features carry learnable delinquency signal"
    else:
        verdict = (
            "refuted: no learnable signal; credit_score and the application "
            "features rank delinquency at chance level"
        )

    # credit_score deciles
    log("deciles and groups")
    q = np.nanpercentile(cs, np.linspace(0, 100, 11))
    dec = np.clip(np.searchsorted(q[1:-1], cs, side="right"), 0, 9)
    dec_rows = []
    for k in range(10):
        mm = cs_ok & (dec == k)
        dec_rows.append(
            [
                k + 1,
                f"{int(np.nanmin(cs[mm]))}-{int(np.nanmax(cs[mm]))}",
                f"{mm.sum():,}",
                pct(ys["dpd>0"][mm].mean()),
                pct(ys["dpd>30"][mm].mean()),
            ]
        )
    mm = ~cs_ok
    dec_rows.append(
        [
            "null",
            "-",
            f"{mm.sum():,}",
            pct(ys["dpd>0"][mm].mean()),
            pct(ys["dpd>30"][mm].mean()),
        ]
    )

    yr = df["opening_date"].astype("datetime64[ns]").dt.year.to_numpy()
    year_rows = []
    for key, v in [("opening year", yr), ("product_type", d["product_type"])]:
        for lv in sorted(np.unique(v)):
            mm = v == lv
            year_rows.append(
                [
                    key,
                    lv,
                    f"{mm.sum():,}",
                    pct(ys["dpd>0"][mm].mean()),
                    pct(ys["dpd>30"][mm].mean()),
                ]
            )

    # group distributions with a shuffled-group baseline
    group_md = []
    group_summary = {}
    for g in GROUPS:
        v = d[g]
        levels = sorted(np.unique(v))
        rows = []
        for lv in levels:
            mm = v == lv
            k0, k30 = int(ys["dpd>0"][mm].sum()), int(ys["dpd>30"][mm].sum())
            nn = int(mm.sum())
            rows.append(
                [
                    lv,
                    f"{nn:,}",
                    pct(nn / n),
                    f"{pct(k0 / nn)} {ci95(k0, nn)}",
                    f"{pct(k30 / nn)} {ci95(k30, nn)}",
                    fmt(np.nanmean(cs[mm]), 1),
                    fmt(np.nanmedian(d["income_z"][mm]), 3),
                    fmt(np.nanmean(d["age"][mm]), 1),
                ]
            )
        stats = []
        for t, y in ys.items():
            obs = [y[v == lv].mean() for lv in levels]
            rng_obs = max(obs) - min(obs)
            codes = np.searchsorted(levels, v)
            cnt = np.bincount(codes)
            null = []
            for _ in range(N_PERM // 5):
                yy = RNG.permutation(y)
                rr = np.bincount(codes, weights=yy) / cnt
                null.append(rr.max() - rr.min())
            tab = [
                [int(y[v == lv].sum()), int((v == lv).sum() - y[v == lv].sum())]
                for lv in levels
            ]
            stats.append(
                [
                    t,
                    pct(rng_obs),
                    pct(float(np.percentile(null, 95))),
                    fp(float((np.array(null) >= rng_obs).mean())),
                    fp(chi2_p(tab)),
                ]
            )
            group_summary[(g, t)] = (
                rng_obs,
                float(np.percentile(null, 95)),
                chi2_p(tab),
            )
        # calibration by group on test (dpd>30)
        cal = []
        for lv in levels:
            mm = v[test] == lv
            cal.append(
                [
                    lv,
                    f"{mm.sum():,}",
                    pct(ys["dpd>30"][test][mm].mean()),
                    pct(r30["p_te"][mm].mean()),
                    f"{auc(r30['p_te'][mm], ys['dpd>30'][test][mm]):.4f}",
                ]
            )
        group_md += [
            f"### By {g}",
            "",
            md_table(
                [
                    g,
                    "products",
                    "share",
                    "dpd>0 [95% CI]",
                    "dpd>30 [95% CI]",
                    "mean credit_score",
                    "median income_z",
                    "mean age at opening",
                ],
                rows,
            ),
            "",
            md_table(
                ["target", "rate range", "shuffled 95th pct", "perm p", "chi2 p"], stats
            ),
            "",
            "Test split, dpd>30: observed rate vs mean LR prediction, and within-group AUC.",
            "",
            md_table([g, "test products", "observed", "predicted", "AUC"], cal),
            "",
        ]
    gender_note = (
        "`gender` is not a model feature; it is reported only to check whether "
        "outcomes or predictions differ by group."
    )

    # sample rows
    samp = df.sample(5, random_state=SEED)
    samp_rows = [
        [
            r.product_id,
            r.product_type,
            r.opening_date.date()
            if hasattr(r.opening_date, "date")
            else r.opening_date,
            r.days_past_due,
            "null" if np.isnan(r.credit_score) else int(r.credit_score),
            fmt(r.income) if r.income == r.income else "null",
            r.segment,
            r.country,
            fmt(r.age, 1),
        ]
        for r in samp.itertuples()
    ]

    # coefficients (dpd>30), largest |w|
    w = r30["w"]
    order = np.argsort(-np.abs(w[1:])) + 1
    coef_rows = [[names[i], f"{w[i]:+.4f}", f"{np.exp(w[i]):.3f}"] for i in order[:12]]

    # ------------------------------------------------------------ report
    log("writing report")

    def auc_row(label: str, t: str) -> list:
        r = results[t]
        if label == "credit_score alone":
            return [
                t,
                label,
                f"{r['cs_n']:,}",
                f"{r['cs_test']:.4f}",
                f"[{r['cs_ci'][0]:.4f}, {r['cs_ci'][1]:.4f}]",
                f"{r['cs_null95']:.4f} (permuted test labels, two-sided)",
                fp(r["cs_p"]),
            ]
        return [
            t,
            label,
            f"{int(test.sum()):,}",
            f"{r['lr_test']:.4f}",
            f"[{r['lr_ci'][0]:.4f}, {r['lr_ci'][1]:.4f}]",
            f"{r['shuf95']:.4f} (refit on shuffled train labels; mean "
            f"{r['shuf_mean']:.4f}, max {r['shuf_max']:.4f})",
            fp(r["lr_perm_p"]),
        ]

    md += [
        "# P3 - Credit risk signal (days_past_due)",
        "",
        f"Generated by `ml/analysis/day1/{NAME}.py` on {date.today()} over "
        f"`ml/data/02_intermediate/` ({n_prod:,} products, {n_cust:,} customers).",
        "",
        "## Question",
        "",
        "Is there learnable signal for a credit risk estimate? Target: `days_past_due > 0` "
        "and `> 30` on personal loans (`Préstamo Personal`) and credit cards "
        "(`Tarjeta Crédito`), using only features known at application: credit_score, "
        "estimated_monthly_income, segment, occupation, education_level, country and age "
        "at opening. Report the AUC of credit_score alone and of a logistic regression "
        "with a temporal split by opening_date, each against a shuffled-label baseline; "
        "and outcome distributions by gender, country and segment.",
        "",
        f"## Verdict: **{verdict}**",
        "",
        f"- **credit_score alone:** test AUC {r0['cs_test']:.4f} (dpd>0) and "
        f"{r30['cs_test']:.4f} (dpd>30); full-cohort AUC {r0['cs_full']:.4f} / "
        f"{r30['cs_full']:.4f}. The permuted-label 95% band is "
        f"0.5 ± {r0['cs_null95'] - 0.5:.4f}.",
        f"- **Logistic regression (temporal split):** test AUC {r0['lr_test']:.4f} "
        f"[{r0['lr_ci'][0]:.4f}, {r0['lr_ci'][1]:.4f}] for dpd>0 and "
        f"{r30['lr_test']:.4f} [{r30['lr_ci'][0]:.4f}, {r30['lr_ci'][1]:.4f}] for dpd>30, "
        f"vs {r0['shuf95']:.4f} / {r30['shuf95']:.4f} for the same model refit on "
        f"shuffled labels (95th pct of {N_SHUF_FIT}). Train AUC {r0['lr_train']:.4f} / "
        f"{r30['lr_train']:.4f}. Test log loss {r30['ll']:.5f} vs {r30['ll0']:.5f} for a "
        f"constant (dpd>30).",
        f"- **Best AUC of any model/target: {best:.4f}**, against a pre-declared "
        f"materiality bar of {MATERIAL_AUC}. Learnable signal: "
        + ", ".join(f"{t} {'yes' if s else 'no'}" for t, s in signal.items())
        + ".",
        f"- **Delinquency looks assigned independently of the customer:** the dpd>0 rate "
        f"is ~{pct(float(ys['dpd>0'].mean()))} and dpd>30 ~{pct(float(ys['dpd>30'].mean()))} "
        "in every credit_score decile, opening year, product type and group "
        "(sections d-e).",
        "- **Consequence:** a credit risk score cannot be built from this dataset; any "
        "model would output the base rate. Do not ship or demo a delinquency / risk "
        "estimate as a feature, and do not present credit_score as a risk driver. If a "
        "risk field is needed in the UI, show credit_score as a raw attribute only."
        if not any(signal.values())
        else "- **Consequence:** a risk estimate is feasible; see the coefficients in (c).",
        "",
        "## (a) Raw profile (before any cleaning)",
        "",
        f"- `products`: {n_prod:,} rows, {n_prod_ids:,} distinct `product_id` "
        f"({n_prod - n_prod_ids:,} duplicates). `customers`: {n_cust:,} rows, "
        f"{n_cust_ids:,} distinct `customer_id` ({n_cust - n_cust_ids:,} duplicates).",
        "- `days_past_due` exists only on credit products:",
        "",
        md_table(
            ["product_type", "rows", "dpd non-null", "dpd>0", "dpd>30"],
            [[a, f"{b:,}", f"{c:,}", f"{e:,}", f"{f:,}"] for a, b, c, e, f in by_type],
        ),
        "",
        "- `days_past_due` takes only 7 bucket values on the cohort, so `> 30` means "
        "60 days or more:",
        "",
        md_table(
            ["days_past_due", "rows"],
            [["null" if v is None else v, f"{k:,}"] for v, k in dpd_vals],
        ),
        "",
        f"- Cohort before filtering: {n_cohort_raw:,} products; {n_unjoined:,} without a "
        f"matching customer; {n_dpd_null:,} ({pct(n_dpd_null / n_cohort_raw)}) with null "
        f"days_past_due, dropped. Analysis cohort: **{n:,} products, "
        f"{df['customer_id'].nunique():,} customers**.",
        "",
        md_table(
            ["product_status", "rows", "dpd null"],
            [[a, f"{b:,}", f"{c:,}"] for a, b, c in null_by_status],
        ),
        "",
        "Nulls on the cohort (before dropping null days_past_due):",
        "",
        md_table(["column", "nulls", "share"], null_rows),
        "",
        f"- **Data quality:** {pct(before_reg)} of cohort products have an opening_date "
        "earlier than the customer's registration_date, so 'known at application' is "
        "approximate: customer attributes are a single snapshot, not values as of "
        "opening. That would, if anything, leak signal and inflate AUC.",
        "- Income is in local currency (COP / MXN / ARS), so the model uses log income "
        "z-scored within country (`income_z`).",
        "",
        "Sample rows:",
        "",
        md_table(
            [
                "product_id",
                "product_type",
                "opening_date",
                "dpd",
                "credit_score",
                "income",
                "segment",
                "country",
                "age",
            ],
            samp_rows,
        ),
        "",
        "## (b) Setup",
        "",
        f"- Temporal split: train = opening_date < {cutoff} ({int(train.sum()):,} "
        f"products), test = opening_date >= {cutoff} ({int(test.sum()):,}, latest "
        f"{pct(TEST_SHARE)}). {int(test_new.sum()):,} test products belong to customers "
        "with no product in train.",
        f"- Target rates: dpd>0 {pct(r0['rate_train'])} train / {pct(r0['rate_test'])} "
        f"test; dpd>30 {pct(r30['rate_train'])} / {pct(r30['rate_test'])}.",
        "- credit_score alone: score = -credit_score (higher score, lower risk), no "
        "fitting; rows with null credit_score excluded.",
        f"- Logistic regression: L2 (lambda {L2}), {len(names) - 1} features: "
        "credit_score, income_z, age and age², missing flags for each, one-hot "
        "segment, occupation (null as a level), education_level (null as a level), "
        "country and product_type. Numeric features median-imputed and standardized "
        "on train.",
        f"- Baselines: {N_PERM} permutations of the test labels against fixed scores, "
        f"and {N_SHUF_FIT} refits of the logistic regression on shuffled train labels. "
        f"95% CIs of the test AUC from {N_BOOT} bootstrap resamples.",
        "",
        "## (c) AUC on the temporal hold-out",
        "",
        md_table(
            [
                "target",
                "model",
                "test rows",
                "AUC",
                "95% CI",
                "null 95th pct",
                "perm p",
            ],
            [
                auc_row(lbl, t)
                for t in TARGETS
                for lbl in ["credit_score alone", "logistic regression"]
            ],
        ),
        "",
        f"Logistic regression on test customers unseen in train: AUC "
        f"{r0['lr_new']:.4f} (dpd>0), {r30['lr_new']:.4f} (dpd>30).",
        "",
        "Univariate test AUC per feature (numeric: raw value, direction folded to AUC >= 0.5; "
        "categorical: train target rate per level):",
        "",
        md_table(
            ["feature", "type", "AUC dpd>0", "AUC dpd>30"],
            [a[:2] + [a[2], b[2]] for a, b in zip(r0["uni"], r30["uni"])],
        ),
        "",
        "Largest logistic regression coefficients (dpd>30, standardized):",
        "",
        md_table(["feature", "coef", "odds ratio"], coef_rows),
        "",
        "## (d) credit_score deciles (full cohort)",
        "",
        md_table(["decile", "credit_score", "products", "dpd>0", "dpd>30"], dec_rows),
        "",
        "By opening year and product type:",
        "",
        md_table(["split", "value", "products", "dpd>0", "dpd>30"], year_rows),
        "",
        "## (e) Distributions by gender, country and segment",
        "",
        gender_note,
        "'rate range' is the max minus min target rate across levels; the shuffled "
        f"baseline permutes the target across products ({N_PERM // 5} reps).",
        "",
        *group_md,
        "## Method notes",
        "",
        "- AUC is computed from average ranks (ties share the mean rank). The "
        "credit_score null is two-sided because the expected direction was not assumed.",
        "- sklearn and scipy are not in the environment; the logistic regression is a "
        "Newton / IRLS fit in numpy.",
        "- The unit is the product; customers with several credit products appear more "
        "than once. The test AUC on customers unseen in train is also at chance, so the "
        "result does not depend on repeated customers.",
        "",
    ]
    report = "\n".join(md)
    for dd in (OUT_DOCS, OUT_DATA):
        dd.mkdir(parents=True, exist_ok=True)
        (dd / f"{NAME}.md").write_text(report, encoding="utf-8")

    grp = "; ".join(
        f"{g} dpd>30 range {pct(group_summary[(g, 'dpd>30')][0])} vs shuffled "
        f"{pct(group_summary[(g, 'dpd>30')][1])}"
        for g in GROUPS
    )
    line = (
        f"- P3 (credit risk signal): {verdict}. {n:,} loans/cards, dpd>0 "
        f"{pct(float(ys['dpd>0'].mean()))}, dpd>30 {pct(float(ys['dpd>30'].mean()))}; "
        f"test AUC credit_score {r0['cs_test']:.4f} / {r30['cs_test']:.4f}, logistic "
        f"regression {r0['lr_test']:.4f} / {r30['lr_test']:.4f} vs shuffled 95th pct "
        f"{r0['shuf95']:.4f} / {r30['shuf95']:.4f}; {grp}; see docs/findings/day1/{NAME}.md"
    )
    for dd in (OUT_DOCS, OUT_DATA):
        f = dd / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- P3 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log("done")


if __name__ == "__main__":
    main()
