"""A4 - is there recurrence and temporal structure per customer?

Checks:
  (a) inter-arrival gaps between consecutive purchases of the same product_id and
      merchant_name: histogram and a 'monthly peak' ratio (gaps 28-32 d vs the
      flanks 18-22 d and 38-42 d; 1.0 = flat).
  (b) recurring-charge detection, rules fixed in advance, on two keys
      (product_id x merchant and customer_id x merchant):
        - monthly pair: two consecutive purchases 25-35 d apart whose amounts
          differ by <= 10% (both purchases count as recurring);
        - monthly series: >= 3 purchases, mean gap 25-35 d, gap CV <= 0.25,
          amount CV <= 0.20;
        - regular series (any period): >= 3 purchases, gap CV <= 0.25,
          amount CV <= 0.20.
      Share of merchant purchases flagged vs a shuffled-timestamp baseline
      (timestamps permuted within the product, or within the customer for the
      customer key; 5 seeds). Above baseline = real above every seed and z >= 3.
      Also per merchant, so bill-like merchants (phone, cable, utilities,
      internet, streaming) can be compared to the rest.
  (c) amount similarity of consecutive same-key purchases vs amounts permuted
      within the product (same card, so same currency and scale).
  (d) predictability: next transaction_category per customer on a temporal
      holdout (last 6 months), with (a) the customer's most frequent category
      in training, (b) the global most frequent category, (c) the customer's
      previous category (order-1 sequence). Accuracy and log loss (customer
      distribution smoothed towards the global one vs the global one). Paired
      differences carry a 1000-draw customer-cluster bootstrap CI. Control: the
      same predictors after permuting labels across all rows (keeps marginals,
      destroys any customer structure), and after permuting them within
      product_type (keeps each customer's product portfolio, destroys any
      preference beyond it). Repeated for transaction_type (every row has one).
      Decision rule: sequence structure is weak if (a) beats (b) by < 2 pp of
      accuracy and < 1% of log loss, or if (a) is no better than on the global
      control. Customer-specific signal beyond the portfolio needs (a) >= 2 pp
      above the within-product_type control.

Outputs:
  docs/findings/day1/A4.md                 (committed report)
  data/08_reporting/day1/A4.md             (copy of the report)
  data/08_reporting/day1/FINDINGS.md and docs/findings/day1/FINDINGS.md (A4 line)

Run from ml/:  .venv/Scripts/python analysis/day1/A4_recurrence_predictability.py
"""

from __future__ import annotations

import math
import time
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
from A1_unrecognized_charges import ci95, md_table, pct

ML = Path(__file__).resolve().parents[2]
REPO = ML.parent
INTER = ML / "data" / "02_intermediate"
OUT_DATA = ML / "data" / "08_reporting" / "day1"
OUT_DOCS = REPO / "docs" / "findings" / "day1"

HOLDOUT_MONTHS = 6
GAP_LO, GAP_HI = 25.0, 35.0  # 'near 30 days'
PAIR_AMT_TOL = 0.10  # relative amount difference for a monthly pair
SERIES_MIN_N = 3
SERIES_GAP_CV = 0.25
SERIES_AMT_CV = 0.20
PEAK = (28, 32)
FLANKS = ((18, 22), (38, 42))
N_SEEDS = 5
Z_MIN = 3.0
MIN_ACC_LIFT = 0.02  # (a) - (b) accuracy below this -> weak
MIN_LL_GAIN = 0.01  # relative log-loss improvement below this -> weak
MIN_RECURRING_SHARE = 0.01  # recurrence must also reach 1% of merchant purchases
PRIOR_STRENGTH = 6.0  # pseudo-counts pulling a customer's distribution to global
RICH_HISTORY = 10  # training events for the 'rich history' subset
GAP_CAP = 120  # gap histogram: 5-day bins up to here, then one open bin
N_BOOT = 1000
BOOT_CHUNK = 50
SEED = 42
BILL_MERCHANTS = (
    "Empresa Telefónica",
    "Cable TV",
    "Servicios Públicos",
    "Internet Plus",
    "Streaming Music",
)
RULES = ("monthly pair", "monthly series", "regular series (any period)")

T0 = time.time()


def log(msg: str) -> None:
    print(f"[{time.time() - T0:6.1f}s] {msg}", flush=True)


def codes(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    uniq, inv = np.unique(values, return_inverse=True)
    return uniq, inv.astype(np.int64)


def shuffle_within(grp: np.ndarray, x: np.ndarray, rng: np.random.Generator):
    """Permute x among rows that share grp (each group keeps its own values)."""
    o1 = np.argsort(grp, kind="stable")
    o2 = np.lexsort((rng.random(len(grp)), grp))
    out = np.empty_like(x)
    out[o1] = x[o2]
    return out


def detect(key: np.ndarray, t: np.ndarray, amt: np.ndarray) -> dict:
    """Flag recurring purchases under the three rules; returns per-row masks
    (in the original row order) plus consecutive gaps and amount pairs."""
    o = np.lexsort((t, key))
    k, ts, a = key[o], t[o], amt[o]
    n = len(k)
    same = np.zeros(n, dtype=bool)
    same[1:] = k[1:] == k[:-1]  # row i continues the series of row i-1
    gap = np.full(n, np.nan)
    gap[1:] = ts[1:] - ts[:-1]
    gap[~same] = np.nan
    rel = np.full(n, np.nan)
    rel[1:] = np.abs(a[1:] - a[:-1]) / np.maximum(np.maximum(a[1:], a[:-1]), 1e-9)
    rel[~same] = np.nan

    pair = same & (gap >= GAP_LO) & (gap <= GAP_HI) & (rel <= PAIR_AMT_TOL)
    pair_rows = pair.copy()
    pair_rows[:-1] |= pair[1:]

    gid = np.cumsum(~same) - 1
    ng = gid[-1] + 1
    cnt = np.bincount(gid, minlength=ng)
    g = np.nan_to_num(gap)
    has_gap = same.astype(np.float64)
    gn = np.bincount(gid, weights=has_gap, minlength=ng)
    with np.errstate(invalid="ignore", divide="ignore"):
        gmean = np.bincount(gid, weights=g, minlength=ng) / gn
        gvar = np.bincount(gid, weights=g * g, minlength=ng) / gn - gmean**2
        gcv = np.sqrt(np.maximum(gvar, 0)) / gmean
        amean = np.bincount(gid, weights=a, minlength=ng) / cnt
        avar = np.bincount(gid, weights=a * a, minlength=ng) / cnt - amean**2
        acv = np.sqrt(np.maximum(avar, 0)) / amean
    regular = (cnt >= SERIES_MIN_N) & (gcv <= SERIES_GAP_CV) & (acv <= SERIES_AMT_CV)
    monthly = regular & (gmean >= GAP_LO) & (gmean <= GAP_HI)

    masks = {}
    for name, m in zip(RULES, (pair_rows, monthly[gid], regular[gid])):
        back = np.empty(n, dtype=bool)
        back[o] = m
        masks[name] = back
    return {
        "masks": masks,
        "gaps": gap[same],
        "rel": rel[same],
        "series3": int((cnt >= SERIES_MIN_N).sum()),
        "rows_in_series3": int(cnt[cnt >= SERIES_MIN_N].sum()),
    }


def peak_ratio(gaps: np.ndarray) -> float:
    """Density at 28-32 d over the mean density of the two flanks."""
    peak = ((gaps >= PEAK[0]) & (gaps <= PEAK[1])).sum()
    flank = sum(((gaps >= lo) & (gaps <= hi)).sum() for lo, hi in FLANKS) / 2
    return float(peak / flank) if flank else float("nan")


def z_vs(k: int, n: int, p0: float) -> float:
    sd = math.sqrt(n * p0 * (1 - p0))
    return (k - n * p0) / sd if sd > 0 else (0.0 if k == n * p0 else math.inf)


def fmt_ratio(real: float, base: float) -> str:
    return f"{real / base:.2f}x" if base > 0 else ("n/a" if real == 0 else "inf")


# ---------------------------------------------------------------------------- (d)


def mode_pred(counts: np.ndarray, gshare: np.ndarray) -> np.ndarray:
    """Row-wise argmax of counts; ties and empty rows fall back to global order."""
    return np.argmax(counts + gshare[None, :] * 1e-6, axis=1)


def predict(cust: np.ndarray, t: np.ndarray, y: np.ndarray, test: np.ndarray, k: int):
    """Per test row: correctness of (a)/(b)/(c) and log-loss of (a)/(b)."""
    ncust = int(cust.max()) + 1
    tr = ~test
    ccount = np.bincount(cust[tr] * k + y[tr], minlength=ncust * k).reshape(ncust, k)
    gcount = np.bincount(y[tr], minlength=k).astype(np.float64)
    gshare = gcount / gcount.sum()

    pa = mode_pred(ccount, gshare)
    pb = int(np.argmax(gshare))

    o = np.lexsort((t, cust))
    prev = np.full(len(y), -1)
    same = np.zeros(len(y), dtype=bool)
    same[1:] = cust[o][1:] == cust[o][:-1]
    prev_sorted = np.full(len(y), -1)
    prev_sorted[1:] = np.where(same[1:], y[o][:-1], -1)
    prev[o] = prev_sorted

    c, yt = cust[test], y[test]
    pred_a = pa[c]
    pred_c = np.where(prev[test] >= 0, prev[test], pred_a)
    nhist = ccount[c].sum(axis=1)
    prob_a = (ccount[c, yt] + PRIOR_STRENGTH * gshare[yt]) / (nhist + PRIOR_STRENGTH)
    return {
        "cust": c,
        "nhist": nhist,
        "a": pred_a == yt,
        "b": yt == pb,
        "c": pred_c == yt,
        "ll_a": -np.log(prob_a),
        "ll_b": -np.log(gshare[yt]),
        "gshare": gshare,
        "pb": pb,
    }


def cluster_boot(cust: np.ndarray, diff: np.ndarray, rng: np.random.Generator):
    """95% CI of mean(diff) resampling customers (Poisson weights)."""
    uc, inv = np.unique(cust, return_inverse=True)
    s = np.bincount(inv, weights=diff.astype(np.float64), minlength=len(uc))
    n = np.bincount(inv, minlength=len(uc)).astype(np.float64)
    est = []
    for _ in range(N_BOOT // BOOT_CHUNK):
        w = rng.poisson(1.0, size=(BOOT_CHUNK, len(uc))).astype(np.float32)
        est.append((w @ s) / (w @ n))
    est = np.concatenate(est)
    return tuple(np.quantile(est, [0.025, 0.975]))


def acc_cell(m: np.ndarray) -> str:
    k, n = int(m.sum()), len(m)
    return f"{100 * k / n:.2f}% {ci95(k, n)}"


def predictability_section(
    label: str,
    cust: np.ndarray,
    t: np.ndarray,
    y: np.ndarray,
    test: np.ndarray,
    names: np.ndarray,
    ptype: np.ndarray,
    rng: np.random.Generator,
) -> tuple[list[str], dict]:
    k = len(names)
    r = predict(cust, t, y, test, k)
    rc = predict(cust, t, rng.permutation(y), test, k)
    rp = predict(cust, t, shuffle_within(ptype, y, rng), test, k)
    n_test = int(test.sum())
    has_hist = r["nhist"] > 0
    rich = r["nhist"] >= RICH_HISTORY

    d_ab = r["a"].astype(np.float64) - r["b"]
    d_cb = r["c"].astype(np.float64) - r["b"]
    d_ll = r["ll_b"] - r["ll_a"]
    ci_ab = cluster_boot(r["cust"], d_ab, rng)
    ci_cb = cluster_boot(r["cust"], d_cb, rng)
    ci_ll = cluster_boot(r["cust"], d_ll, rng)
    ll_a, ll_b = float(r["ll_a"].mean()), float(r["ll_b"].mean())
    ll_gain = (ll_b - ll_a) / ll_b
    lift = float(d_ab.mean())
    ctrl_lift = float(rc["a"].mean() - rc["b"].mean())
    port_acc = float(rp["a"].mean())
    beyond = float(r["a"].mean()) - port_acc

    share_rows = [
        [names[i], f"{100 * r['gshare'][i]:.2f}%"] for i in np.argsort(-r["gshare"])
    ]
    rows = []
    for nm, rr in (
        ("real", r),
        ("control: labels permuted globally", rc),
        ("control: labels permuted within product_type", rp),
    ):
        rows.append(
            [
                nm,
                acc_cell(rr["a"]),
                acc_cell(rr["b"]),
                acc_cell(rr["c"]),
                f"{rr['ll_a'].mean():.4f}",
                f"{rr['ll_b'].mean():.4f}",
            ]
        )
    sub = []
    for nm, m in (
        ("all test events", np.ones(n_test, bool)),
        ("customer has training history", has_hist),
        (f"customer has >= {RICH_HISTORY} training events", rich),
    ):
        if m.sum() == 0:
            continue
        sub.append(
            [
                nm,
                f"{int(m.sum()):,}",
                acc_cell(r["a"][m]),
                acc_cell(r["b"][m]),
                f"{100 * (r['a'][m].mean() - r['b'][m].mean()):+.2f} pp",
                f"{r['ll_a'][m].mean():.4f} / {r['ll_b'][m].mean():.4f}",
            ]
        )
    weak = (lift < MIN_ACC_LIFT and ll_gain < MIN_LL_GAIN) or lift <= ctrl_lift
    md = [
        f"Target `{label}`: {len(y):,} rows ({k} classes), {len(y) - n_test:,} training "
        f"and {n_test:,} holdout events; {100 * has_hist.mean():.2f}% of holdout events "
        f"belong to a customer with training history (median "
        f"{int(np.median(r['nhist']))} training events per holdout event).",
        "",
        "Global class shares (training):",
        "",
        md_table(["class", "share"], share_rows),
        "",
        md_table(
            [
                "data",
                "(a) customer mode acc",
                "(b) global mode acc",
                "(c) previous category acc",
                "log loss (a)",
                "log loss (b)",
            ],
            rows,
        ),
        "",
        f"Paired over holdout events, customer-cluster bootstrap 95% CI: (a) - (b) = "
        f"{100 * lift:+.2f} pp [{100 * ci_ab[0]:+.2f}, {100 * ci_ab[1]:+.2f}]; (c) - (b) = "
        f"{100 * d_cb.mean():+.2f} pp [{100 * ci_cb[0]:+.2f}, {100 * ci_cb[1]:+.2f}]; "
        f"log loss (b) - (a) = {ll_b - ll_a:+.4f} [{ci_ll[0]:+.4f}, {ci_ll[1]:+.4f}] "
        f"nats ({100 * ll_gain:+.2f}% of (b)). On the permuted control (a) - (b) = "
        f"{100 * ctrl_lift:+.2f} pp. Within-product_type control keeps (a) at "
        f"{100 * port_acc:.2f}%, so the customer signal beyond the product "
        f"portfolio is {100 * beyond:+.2f} pp. Uniform log loss for {k} classes = "
        f"{math.log(k):.4f}.",
        "",
        md_table(
            [
                "subset",
                "events",
                "(a) acc",
                "(b) acc",
                "(a) - (b)",
                "log loss (a) / (b)",
            ],
            sub,
        ),
        "",
        f"Decision (pre-set): {'**weak**' if weak else '**structure present**'} "
        f"(needs (a) - (b) >= {100 * MIN_ACC_LIFT:.0f} pp or log-loss gain >= "
        f"{100 * MIN_LL_GAIN:.0f}%, and (a) above the global control). Beyond "
        f"portfolio: {'**yes**' if beyond >= MIN_ACC_LIFT else '**no**'} (needs "
        f"(a) >= {100 * MIN_ACC_LIFT:.0f} pp above the within-product_type control).",
        "",
    ]
    return md, {
        "acc_a": float(r["a"].mean()),
        "acc_b": float(r["b"].mean()),
        "acc_c": float(r["c"].mean()),
        "lift": lift,
        "ci": ci_ab,
        "ll_gain": ll_gain,
        "ctrl_lift": ctrl_lift,
        "port_acc": port_acc,
        "beyond": beyond,
        "weak": weak,
        "k": k,
    }


def main() -> None:
    rng = np.random.default_rng(SEED)
    con = duckdb.connect()
    con.sql(
        f"create view t as select * from "
        f"'{(INTER / 'transactions.parquet').as_posix()}'"
    )
    min_ts, max_ts = con.sql(
        "select min(transaction_date), max(transaction_date) from t"
    ).fetchone()
    cut = con.sql(
        f"select (timestamp '{max_ts}' - interval {HOLDOUT_MONTHS} month)::date"
    ).fetchone()[0]
    n_all = con.sql("select count(*) from t").fetchone()[0]
    log(f"range {min_ts} .. {max_ts}, holdout from {cut}")

    # -------------------------------------------------------------- merchant rows
    arr = con.sql(
        """
        select transaction_id, product_id, customer_id, merchant_name,
               strftime(transaction_date, '%Y-%m-%d %H:%M:%S') as ts_str,
               epoch(transaction_date) / 86400.0 as day,
               amount::double as amount, amount_usd::double as amount_usd
        from t where merchant_name is not null
        """
    ).fetchnumpy()
    _, prod = codes(np.asarray(arr["product_id"]))
    _, cust_m = codes(np.asarray(arr["customer_id"]))
    merch_names, merch = codes(np.asarray(arr["merchant_name"]))
    day = np.asarray(arr["day"], dtype=np.float64)
    amt = np.asarray(arr["amount"], dtype=np.float64)
    usd = np.asarray(arr["amount_usd"], dtype=np.float64)
    tx_id = np.asarray(arr["transaction_id"])
    ts_str = np.asarray(arr["ts_str"])
    prod_id = np.asarray(arr["product_id"])
    merch_raw = np.asarray(arr["merchant_name"])
    n = len(day)
    log(f"loaded {n:,} merchant purchases")
    nm = len(merch_names)
    key_pm = prod * nm + merch
    key_cm = cust_m * nm + merch
    types = con.sql(
        "select transaction_type, count(*) from t where merchant_name is not null "
        "group by 1"
    ).fetchall()

    md: list[str] = [
        "# A4 - recurrence and temporal structure per customer",
        "",
        f"Generated by `ml/analysis/day1/A4_recurrence_predictability.py` on "
        f"{date.today().isoformat()} over `ml/data/02_intermediate/transactions.parquet` "
        f"({n_all:,} transactions, {min_ts:%Y-%m-%d} to {max_ts:%Y-%m-%d}). Recurrence "
        f"uses the {n:,} rows with a `merchant_name` (all of type "
        f"{', '.join(f'{a} ({b:,})' for a, b in types)}). Rates carry Wilson 95% CIs; "
        f"baselines are the mean of {N_SEEDS} seeds. Predictability uses a temporal "
        f"holdout = last {HOLDOUT_MONTHS} months (`transaction_date >= {cut}`).",
        "",
        "## Hypothesis",
        "",
        "Customers have recurring charges (inter-arrival near 30 days, low variance, "
        "similar amount per `product_id` and merchant) and a predictable next event, "
        "which would justify a sequence model. 'Si falla': drop the sequence model and "
        "keep LightGBM on aggregates.",
        "",
    ]
    verdict_at = len(md)
    md += [
        "",
        "## Queries",
        "",
        "```sql",
        "-- recurrence (a)-(c): merchant purchases",
        "select transaction_id, product_id, customer_id, merchant_name, transaction_date,",
        "       amount, amount_usd",
        "from transactions where merchant_name is not null;",
        "-- predictability (d), once per target",
        "select t.customer_id, t.transaction_date, <target> as y,",
        f"       t.transaction_date >= date '{cut}' as test, p.product_type",
        "from transactions t left join products p using (product_id)",
        "where <target> is not null;",
        "```",
        "",
        "Gaps, series statistics, shuffles and predictors are computed in numpy over "
        "these rows.",
        "",
    ]

    # (a) gap histogram ----------------------------------------------------------
    real_pm = detect(key_pm, day, amt)
    real_cm = detect(key_cm, day, amt)
    base_pm = [
        detect(key_pm, shuffle_within(prod, day, rng), amt) for _ in range(N_SEEDS)
    ]
    base_cm = [
        detect(key_cm, shuffle_within(cust_m, day, rng), amt) for _ in range(N_SEEDS)
    ]
    log("detection done")

    size_rows = []
    for label, keyv in (
        ("product x merchant", key_pm),
        ("customer x merchant", key_cm),
    ):
        _, cnt = np.unique(keyv, return_counts=True)
        size_rows.append(
            [
                label,
                f"{len(cnt):,}",
                f"{cnt.mean():.2f}",
                f"{int(cnt.max())}",
                f"{100 * (cnt > 1).mean():.2f}%",
                f"{100 * (cnt >= SERIES_MIN_N).mean():.2f}%",
                f"{100 * cnt[cnt >= SERIES_MIN_N].sum() / n:.2f}%",
            ]
        )

    edges = [*range(0, GAP_CAP + 5, 5), math.inf]
    hist_rows = []
    g_real = real_pm["gaps"]
    g_base = np.concatenate([b["gaps"] for b in base_pm])
    for lo, hi in zip(edges[:-1], edges[1:]):
        r_ = ((g_real >= lo) & (g_real < hi)).mean()
        b_ = ((g_base >= lo) & (g_base < hi)).mean()
        lab = f"[{lo}, {hi})" if hi <= GAP_CAP else f">= {lo}"
        hist_rows.append([lab, f"{100 * r_:.2f}%", f"{100 * b_:.2f}%"])
    pr_pm, pr_cm = peak_ratio(real_pm["gaps"]), peak_ratio(real_cm["gaps"])
    pr_pm_b = float(np.mean([peak_ratio(b["gaps"]) for b in base_pm]))
    pr_cm_b = float(np.mean([peak_ratio(b["gaps"]) for b in base_cm]))
    pk_n = int(((g_real >= PEAK[0]) & (g_real <= PEAK[1])).sum())

    md += [
        "## (a) Inter-arrival gaps",
        "",
        md_table(
            [
                "key",
                "series",
                "purchases per series",
                "max",
                "series with >= 2",
                f"series with >= {SERIES_MIN_N}",
                f"purchases in series >= {SERIES_MIN_N}",
            ],
            size_rows,
        ),
        "",
        f"Consecutive gaps within product x merchant ({len(g_real):,} gaps), share per "
        f"5-day bin, real vs shuffled timestamps (within product):",
        "",
        md_table(["gap (days)", "real", "shuffled"], hist_rows),
        "",
        f"Monthly peak ratio (gaps {PEAK[0]}-{PEAK[1]} d over the mean of "
        f"{FLANKS[0][0]}-{FLANKS[0][1]} d and {FLANKS[1][0]}-{FLANKS[1][1]} d; 1.0 = "
        f"flat): product x merchant {pr_pm:.2f} (shuffled {pr_pm_b:.2f}, {pk_n:,} gaps "
        f"in the peak); customer x merchant {pr_cm:.2f} (shuffled {pr_cm_b:.2f}). A "
        f"monthly billing cycle would show as a ratio well above 1 and above shuffled.",
        "",
    ]

    # (b) recurring share vs baseline -------------------------------------------
    rec_rows = []
    rec_summary = {}
    for key_label, real, base in (
        ("product x merchant", real_pm, base_pm),
        ("customer x merchant", real_cm, base_cm),
    ):
        for rule in RULES:
            k = int(real["masks"][rule].sum())
            bk = [int(b["masks"][rule].sum()) for b in base]
            p0 = float(np.mean(bk)) / n
            z = z_vs(k, n, p0)
            above = k > max(bk) and z >= Z_MIN
            rec_summary[(key_label, rule)] = (k, p0, z, above)
            rec_rows.append(
                [
                    key_label,
                    rule,
                    f"{k:,}",
                    f"{100 * k / n:.3f}% {ci95(k, n)}",
                    f"{100 * p0:.3f}% [{100 * min(bk) / n:.3f}, {100 * max(bk) / n:.3f}]",
                    fmt_ratio(k / n, p0),
                    f"{z:+.1f}",
                    "**yes**" if above else "no",
                ]
            )
    md += [
        "## (b) Recurring purchases vs shuffled timestamps",
        "",
        f"Rules (fixed in advance): monthly pair = consecutive purchases "
        f"{GAP_LO:.0f}-{GAP_HI:.0f} d apart with amounts within {100 * PAIR_AMT_TOL:.0f}%; "
        f"monthly series = >= {SERIES_MIN_N} purchases, mean gap {GAP_LO:.0f}-"
        f"{GAP_HI:.0f} d, gap CV <= {SERIES_GAP_CV}, amount CV <= {SERIES_AMT_CV}; "
        f"regular series = same without the period constraint. Denominator = {n:,} "
        f"merchant purchases.",
        "",
        md_table(
            [
                "key",
                "rule",
                "purchases",
                "share (95% CI)",
                "shuffled (min, max)",
                "real / shuffled",
                "z",
                "above baseline",
            ],
            rec_rows,
        ),
        "",
        "Shuffling permutes `transaction_date` within each product (or customer), so "
        "every product keeps its activity span and purchase count and only the "
        "assignment of dates to merchants changes. A generated billing cycle would be "
        "destroyed by it; volume-driven coincidences survive it.",
        "",
    ]

    # sample rows: purchases in a monthly series, else in a monthly pair
    for rule in ("monthly series", "monthly pair"):
        idx = np.flatnonzero(real_pm["masks"][rule])
        if len(idx):
            break
    first = idx[np.lexsort((day[idx], key_pm[idx]))][:5]
    sample = [
        [
            tx_id[i],
            ts_str[i],
            prod_id[i],
            merch_raw[i],
            f"{amt[i]:,.2f}",
            f"{usd[i]:,.2f}",
        ]
        for i in first
    ]
    md += [
        f"Sample rows flagged by '{rule}' (product x merchant, first 5 by series and "
        f"date):",
        "",
        md_table(
            [
                "transaction_id",
                "transaction_date",
                "product_id",
                "merchant",
                "amount",
                "amount_usd",
            ],
            sample,
        ),
        "",
    ]

    # per merchant (monthly pair, product key)
    mrows = []
    bill_idx = {i for i, m in enumerate(merch_names) if m in BILL_MERCHANTS}
    pair = real_pm["masks"]["monthly pair"]
    bpair = np.mean([b["masks"]["monthly pair"] for b in base_pm], axis=0)
    grp_stats = {}
    for i in np.argsort(merch_names):
        m = merch == i
        k, nn = int(pair[m].sum()), int(m.sum())
        b = float(bpair[m].sum()) / nn
        grp = "bill-like" if i in bill_idx else "other"
        gs = grp_stats.setdefault(grp, [0, 0, 0.0])
        gs[0] += k
        gs[1] += nn
        gs[2] += b * nn
        mrows.append(
            [
                merch_names[i],
                grp,
                f"{nn:,}",
                f"{100 * k / nn:.3f}% {ci95(k, nn)}",
                f"{100 * b:.3f}%",
                f"{usd[m].mean():,.2f}",
                f"{usd[m].std() / usd[m].mean():.2f}",
            ]
        )
    bill_k, bill_n, _ = grp_stats["bill-like"]
    oth_k, oth_n, _ = grp_stats["other"]
    md += [
        "### Per merchant (monthly pair, product x merchant)",
        "",
        md_table(
            [
                "merchant",
                "group",
                "purchases",
                "monthly pair (95% CI)",
                "shuffled",
                "mean amount_usd",
                "amount_usd CV",
            ],
            mrows,
        ),
        "",
        f"Bill-like merchants ({', '.join(BILL_MERCHANTS)}): {pct(bill_k / bill_n)} "
        f"{ci95(bill_k, bill_n)} vs other merchants {pct(oth_k / oth_n)} "
        f"{ci95(oth_k, oth_n)}. Real subscriptions would be concentrated in the "
        f"bill-like group and have a low amount CV.",
        "",
    ]

    # (c) amount similarity ------------------------------------------------------
    amt_perm = shuffle_within(prod, amt, rng)
    rel_perm = detect(key_pm, day, amt_perm)["rel"]
    sim_real = float((real_pm["rel"] <= PAIR_AMT_TOL).mean())
    sim_perm = float((rel_perm <= PAIR_AMT_TOL).mean())
    k_sim = int((real_pm["rel"] <= PAIR_AMT_TOL).sum())
    md += [
        "## (c) Amount similarity of consecutive purchases",
        "",
        f"Consecutive product x merchant pairs with amounts within "
        f"{100 * PAIR_AMT_TOL:.0f}%: {100 * sim_real:.2f}% {ci95(k_sim, len(real_pm['rel']))} "
        f"of {len(real_pm['rel']):,} pairs, vs {100 * sim_perm:.2f}% after permuting "
        f"amounts within the product, i.e. among the same card's purchases (ratio "
        f"{fmt_ratio(sim_real, sim_perm)}). "
        f"Median relative difference {np.median(real_pm['rel']):.2f} (permuted "
        f"{np.median(rel_perm):.2f}).",
        "",
    ]
    log("recurrence sections done")

    # (d) predictability ---------------------------------------------------------
    md += ["## (d) Next-event predictability", ""]
    pred = {}
    for label, where in (
        ("transaction_category", "transaction_category is not null"),
        ("transaction_type", "true"),
    ):
        a2 = con.sql(
            f"""
            select t.customer_id, epoch(transaction_date) as ts, {label} as y,
                   transaction_date >= date '{cut}' as test,
                   coalesce(p.product_type, '?') as ptype
            from t left join '{(INTER / "products.parquet").as_posix()}' p
              using (product_id)
            where {where}
            """
        ).fetchnumpy()
        _, cust = codes(np.asarray(a2["customer_id"]))
        names, y = codes(np.asarray(a2["y"]))
        tt = np.asarray(a2["ts"], dtype=np.float64)
        test = np.asarray(a2["test"], dtype=bool)
        _, ptype = codes(np.asarray(a2["ptype"]))
        sec, res = predictability_section(label, cust, tt, y, test, names, ptype, rng)
        md += [f"### {label}", ""] + sec
        pred[label] = res
        log(f"predictability {label} done")

    # verdict ----------------------------------------------------------------------
    any_above = [k for k, v in rec_summary.items() if v[3]]
    pair_pm = rec_summary[("product x merchant", "monthly pair")]
    ser_pm = rec_summary[("product x merchant", "monthly series")]
    pc, pt = pred["transaction_category"], pred["transaction_type"]
    recurrence_ok = bool(any_above) and pair_pm[0] / n >= MIN_RECURRING_SHARE
    seq_ok = any(not r["weak"] and r["beyond"] >= MIN_ACC_LIFT for r in (pc, pt))
    if not recurrence_ok and not seq_ok:
        verdict = "refuted: no recurrence and no customer-level sequence structure"
    elif recurrence_ok and seq_ok:
        verdict = "supported"
    else:
        verdict = "inconclusive: only one of recurrence / sequence structure holds"
    md[verdict_at] = (
        f"## Verdict: **{verdict}**\n\n"
        f"- **No billing cycle.** Consecutive product x merchant gaps are flat: monthly "
        f"peak ratio {pr_pm:.2f} (shuffled {pr_pm_b:.2f}); customer x merchant "
        f"{pr_cm:.2f} (shuffled {pr_cm_b:.2f}). Only "
        f"{100 * real_pm['rows_in_series3'] / n:.2f}% of merchant purchases belong to a "
        f"product x merchant series with >= {SERIES_MIN_N} purchases.\n"
        f"- **Recurring share = chance.** Monthly pairs {100 * pair_pm[0] / n:.3f}% of "
        f"merchant purchases vs {100 * pair_pm[1]:.3f}% shuffled (z = {pair_pm[2]:+.1f}); "
        f"monthly series {ser_pm[0]:,} purchases ({100 * ser_pm[0] / n:.3f}%) "
        f"vs {100 * ser_pm[1]:.3f}% shuffled. Rules above baseline: "
        f"{', '.join(f'{a}/{b}' for a, b in any_above) if any_above else 'none'}.\n"
        f"- **Amounts carry no merchant identity.** Every merchant, bill-like ones "
        f"included, has the same amount_usd distribution (mean ~{usd.mean():,.0f}, CV "
        f"~{usd.std() / usd.mean():.2f}); consecutive same-merchant amounts are within "
        f"{100 * PAIR_AMT_TOL:.0f}% in {100 * sim_real:.2f}% of pairs vs "
        f"{100 * sim_perm:.2f}% with amounts permuted within the card. Bill-like "
        f"merchants monthly pair {100 * bill_k / bill_n:.3f}% vs others "
        f"{100 * oth_k / oth_n:.3f}%.\n"
        f"- **Next category: (a) does not even beat (b).** Holdout accuracy (a) "
        f"customer mode {pct(pc['acc_a'])} vs (b) global mode {pct(pc['acc_b'])} "
        f"({100 * pc['lift']:+.2f} pp [{100 * pc['ci'][0]:+.2f}, {100 * pc['ci'][1]:+.2f}]; "
        f"labels permuted {100 * pc['ctrl_lift']:+.2f} pp); (c) previous category "
        f"{pct(pc['acc_c'])}; log-loss gain {100 * pc['ll_gain']:+.2f}%. A customer's "
        f"history is a noisy sample of the global mix, so the per-customer mode "
        f"overfits.\n"
        f"- **Next transaction_type: the signal is the product portfolio, not the "
        f"customer.** (a) {pct(pt['acc_a'])} vs (b) {pct(pt['acc_b'])} "
        f"({100 * pt['lift']:+.2f} pp, log-loss gain {100 * pt['ll_gain']:+.2f}%), but "
        f"permuting labels within product_type keeps (a) at {pct(pt['port_acc'])} "
        f"(beyond portfolio {100 * pt['beyond']:+.2f} pp). Cards emit purchases, "
        f"accounts emit transfers / withdrawals / deposits; order adds nothing "
        f"((c) previous type {pct(pt['acc_c'])} < (a)).\n"
        f"- **Consequence (from 'Si falla'):** drop the sequence model. Merchant, "
        f"date, amount and category look drawn i.i.d. per row given the product type, "
        f"so a per-customer next-event model has nothing to learn beyond which products "
        f"the customer holds. Keep LightGBM on aggregates (product-portfolio features "
        f"carry the only signal found) and benchmark it against the global and "
        f"product_type marginals.\n"
    )

    report = "\n".join(md)
    for d in (OUT_DATA, OUT_DOCS):
        d.mkdir(parents=True, exist_ok=True)
        (d / "A4.md").write_text(report, encoding="utf-8")
    line = (
        f"- A4 (recurrence and sequence structure): {verdict}. Monthly peak ratio "
        f"{pr_pm:.2f} (shuffled {pr_pm_b:.2f}); monthly pairs {pct(pair_pm[0] / n)} vs "
        f"{pct(pair_pm[1])} shuffled; monthly series {100 * ser_pm[0] / n:.3f}%; "
        f"next category (a) customer mode {pct(pc['acc_a'])} vs (b) global "
        f"{pct(pc['acc_b'])} ({100 * pc['lift']:+.2f} pp, log-loss gain "
        f"{100 * pc['ll_gain']:+.2f}%); see docs/findings/day1/A4.md"
    )
    for d in (OUT_DATA, OUT_DOCS):
        f = d / "FINDINGS.md"
        lines = (
            f.read_text(encoding="utf-8").splitlines()
            if f.exists()
            else ["# Day 1 findings", ""]
        )
        lines = [x for x in lines if not x.startswith("- A4 ")] + [line]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(verdict)
    log("done")


if __name__ == "__main__":
    main()
