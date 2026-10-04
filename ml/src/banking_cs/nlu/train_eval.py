"""Intent classifier comparison, conformal sets and export (docs/eval_plan.md 8.2 to 8.4).

Run from ml/ after banking_cs.nlu.dataset:
    python -m banking_cs.nlu.train_eval            # CV, final fit, test, conformal, export
    python -m banking_cs.nlu.train_eval --cv-only  # model selection on train only

Protocol:
- Candidates: majority class, the rule parser, TF-IDF (word 1-2 + char 2-5 grams) + logistic
  regression, and two multilingual sentence encoders + logistic regression.
- Selection: 5-fold group cross-validation inside train (folds stratified by intent, grouped
  by `leak_group`). The CV winner is the best mean macro-F1; ties within 0.01 go to the
  cheaper model (eval plan 8.3). The deployed model is TF-IDF + LR regardless of the winner,
  for size and latency (team decision taken before the test split was scored).
- Final models are fit on train only; calibration is used only for the conformal threshold;
  the test split is scored once.

Outputs: artifacts/nlu/{model.joblib, conformal.json, metadata.json, eval_results.json} and
data/nlu/test_predictions.parquet (git-ignored, read by the LLM baseline).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault(
    "HF_HUB_OFFLINE", "1"
)  # encoders come from the local HF cache only
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import polars as pl  # noqa: E402
import sklearn  # noqa: E402
import yaml  # noqa: E402
from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.model_selection import StratifiedGroupKFold  # noqa: E402
from sklearn.pipeline import FeatureUnion, Pipeline  # noqa: E402

from banking_cs.nlu import conformal, metrics, rules  # noqa: E402
from banking_cs.nlu.dataset import (  # noqa: E402
    CORPUS_DIR,
    ML_ROOT,
    NEAR_DUP_DISTANCE,
    OUT_DIR,
    near_duplicate_pairs,
)
from banking_cs.nlu.rules import INTENTS, SLOTS, extract_slots  # noqa: E402

SEED = 2026
CV_FOLDS = 5
TIE_MARGIN = 0.01
ALPHA = 0.10
ALPHA_SWEEP = (0.02, 0.05, 0.10, 0.15, 0.20)
MAX_SET = 2
MONDRIAN_TRIGGER = 0.85
MONDRIAN_MIN_N = 40
N_BOOT = 2000
LATENCY_SAMPLE = 200
TFIDF_C_GRID = (1.0, 3.0, 10.0, 30.0, 100.0)
EMBEDDING_C_GRID = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0)
DEPLOYED = "tfidf_lr"
ENCODERS = {
    "mpnet_lr": {
        "model": "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "revision": "4328cf26390c98c5e3c738b4460a05b95f4911f5",
        "prefix": "",
    },
    "e5_lr": {
        "model": "intfloat/multilingual-e5-base",
        "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
        "prefix": "query: ",
    },
}
# Lower is cheaper to run; used for the tie rule.
COST_RANK = {"majority": 0, "rules": 1, "tfidf_lr": 2, "mpnet_lr": 3, "e5_lr": 3}
ARTIFACT_DIR = ML_ROOT / "artifacts" / "nlu"
GOLDEN_YAML = CORPUS_DIR / "dev" / "golden_turns.yaml"
K = len(INTENTS)


# Models ----------------------------------------------------------------------


def make_tfidf(c: float) -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    analyzer="word",
                    ngram_range=(1, 2),
                    strip_accents="unicode",
                    sublinear_tf=True,
                ),
            ),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(2, 5),
                    strip_accents="unicode",
                    sublinear_tf=True,
                    min_df=2,
                ),
            ),
        ]
    )
    return Pipeline([("features", features), ("clf", make_lr(c))])


def make_lr(c: float) -> LogisticRegression:
    return LogisticRegression(C=c, max_iter=5000, random_state=SEED)


def encode(name: str, texts: list[str]) -> np.ndarray:
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    spec = ENCODERS[name]
    model = SentenceTransformer(spec["model"], revision=spec["revision"], device="cpu")
    return model.encode(
        [spec["prefix"] + t for t in texts],
        batch_size=64,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=False,
    )


def rule_predictions(texts: list[str]) -> np.ndarray:
    return np.array([INTENTS.index(rules.classify(t)[0]) for t in texts])


# Cross-validation ------------------------------------------------------------


def cross_validate(train: pl.DataFrame, embeddings: dict[str, np.ndarray]) -> dict:
    """Mean and per-fold macro-F1 for every candidate configuration."""
    y = train["y"].to_numpy()
    texts = train["text"].to_list()
    cv = StratifiedGroupKFold(n_splits=CV_FOLDS, shuffle=True, random_state=SEED)
    folds = list(cv.split(np.zeros(len(y)), y, train["leak_group"].to_numpy()))
    rule_pred = rule_predictions(texts)
    configs = {"majority": None, "rules": None}
    configs.update({f"tfidf_lr@C={c:g}": c for c in TFIDF_C_GRID})
    for name in ENCODERS:
        configs.update({f"{name}@C={c:g}": c for c in EMBEDDING_C_GRID})
    scores = {k: [] for k in configs}
    for tr, va in folds:
        majority = Counter(y[tr].tolist()).most_common(1)[0][0]
        scores["majority"].append(
            metrics.macro_f1(y[va], np.full(len(va), majority), K)
        )
        scores["rules"].append(metrics.macro_f1(y[va], rule_pred[va], K))
        for c in TFIDF_C_GRID:
            model = make_tfidf(c).fit([texts[i] for i in tr], y[tr])
            pred = model.predict([texts[i] for i in va])
            scores[f"tfidf_lr@C={c:g}"].append(metrics.macro_f1(y[va], pred, K))
        for name, emb in embeddings.items():
            for c in EMBEDDING_C_GRID:
                model = make_lr(c).fit(emb[tr], y[tr])
                scores[f"{name}@C={c:g}"].append(
                    metrics.macro_f1(y[va], model.predict(emb[va]), K)
                )
    configs_out = {
        k: {"mean": float(np.mean(v)), "sd": float(np.std(v)), "folds": v}
        for k, v in scores.items()
    }
    best = {}
    for family in ("majority", "rules", "tfidf_lr", *ENCODERS):
        cands = {k: v for k, v in configs_out.items() if k.split("@")[0] == family}
        key = max(cands, key=lambda k: cands[k]["mean"])
        best[family] = {
            "config": key,
            "C": configs[key],
            "mean": cands[key]["mean"],
            "sd": cands[key]["sd"],
        }
    top = max(v["mean"] for v in best.values())
    tied = [f for f, v in best.items() if v["mean"] >= top - TIE_MARGIN]
    winner = min(tied, key=lambda f: (COST_RANK[f], -best[f]["mean"]))
    return {
        "folds": CV_FOLDS,
        "configs": configs_out,
        "best_per_family": best,
        "winner": winner,
        "tied_within_margin": tied,
        "fold_sizes": [int(len(va)) for _, va in folds],
    }


# Evaluation ------------------------------------------------------------------


def evaluate(test: pl.DataFrame, pred: np.ndarray, weights: np.ndarray) -> dict:
    y = test["y"].to_numpy()
    groups = test["leak_group"].to_numpy()
    lang = test["language"].to_numpy()
    variant = test["variant"].to_numpy()
    kind = test["group_kind"].to_numpy()
    counts = metrics.group_counts(y, pred, groups, K)
    boot = metrics.bootstrap_macro_f1(counts, weights)
    out = {
        "n": int(len(y)),
        "accuracy": float((y == pred).mean()),
        "macro_f1": metrics.macro_f1(y, pred, K),
        "macro_f1_ci95": metrics.interval(boot),
        "per_intent": metrics.per_class_report(y, pred, list(INTENTS)),
        "confusion": metrics.confusion(y, pred, K),
        "by_language": {},
        "by_variant": {},
    }
    for name, mask in (
        *[(lv, lang == lv) for lv in ("es", "pt")],
        ("pt_translated", (lang == "pt") & (kind != "pt_native")),
        ("pt_native", kind == "pt_native"),
    ):
        sub = metrics.group_counts(y[mask], pred[mask], groups[mask], K)
        # Groups absent from the slice get zero counts, so the same weights apply.
        full = [np.zeros_like(counts[0]) for _ in range(4)]
        idx = np.searchsorted(np.unique(groups), np.unique(groups[mask]))
        for a, b in zip(full, sub):
            a[idx] = b
        out["by_language"][name] = {
            "n": int(mask.sum()),
            "macro_f1": metrics.macro_f1(y[mask], pred[mask], K),
            "accuracy": float((y[mask] == pred[mask]).mean()),
            "macro_f1_ci95": metrics.interval(
                metrics.bootstrap_macro_f1(full, weights)
            ),
        }
    for v in ("es-MX", "es-CO", "es-AR", "pt-BR"):
        mask = variant == v
        out["by_variant"][v] = {
            "n": int(mask.sum()),
            "macro_f1": metrics.macro_f1(y[mask], pred[mask], K),
            "accuracy": float((y[mask] == pred[mask]).mean()),
        }
    return out, boot


VARIANTS = ("es-MX", "es-CO", "es-AR", "pt-BR")


def _subset(sets, df, mask):
    return set_stats([s for s, m in zip(sets, mask) if m], df.filter(mask))


def conformal_report(
    probs_cal: np.ndarray,
    cal: pl.DataFrame,
    probs_test: np.ndarray,
    test: pl.DataFrame,
    method: str = "aps",
) -> dict:
    """Split conformal sets with one score ("aps" pre-registered, "lac" exploratory)."""
    score_fn, sets_fn = conformal.SCORES[method], conformal.SETS[method]
    y_cal, y_test = cal["y"].to_numpy(), test["y"].to_numpy()
    scores = score_fn(probs_cal, y_cal)
    block = INTENTS.index("card_block")
    sweep = {}
    for alpha in ALPHA_SWEEP:
        q = conformal.conformal_quantile(scores, alpha)
        sweep[f"{alpha:.2f}"] = {
            "threshold": q,
            **set_stats(sets_fn(probs_test, q), test),
        }
    q = conformal.conformal_quantile(scores, ALPHA)
    sets = sets_fn(probs_test, q)
    main = {"threshold": q, **set_stats(sets, test)}
    main["by_language"] = {
        lv: _subset(sets, test, test["language"] == lv) for lv in ("es", "pt")
    }
    main["by_variant"] = {
        v: _subset(sets, test, test["variant"] == v) for v in VARIANTS
    }
    main["pt_native"] = _subset(sets, test, test["group_kind"] == "pt_native")
    main["by_intent_coverage"] = {
        name: float(np.mean([y_test[i] in sets[i] for i in np.where(y_test == k)[0]]))
        for k, name in enumerate(INTENTS)
    }
    main["false_card_block_singletons"] = int(
        sum(1 for s, t in zip(sets, y_test) if s == [block] and t != block)
    )
    main["non_block_sets_containing_card_block"] = int(
        sum(1 for s, t in zip(sets, y_test) if block in s and t != block)
    )
    main["calibration_coverage"] = float(
        np.mean([t in s for s, t in zip(sets_fn(probs_cal, q), y_cal)])
    )
    # Pre-registered fallback (8.4): Mondrian by language if a variant falls below 0.85.
    triggered = [
        v
        for v, st in main["by_variant"].items()
        if st["n"] >= MONDRIAN_MIN_N and st["coverage"] < MONDRIAN_TRIGGER
    ]
    mondrian = {"triggered_by": triggered}
    if triggered:
        qs = conformal.mondrian_thresholds(scores, cal["language"].to_numpy(), ALPHA)
        m_sets = [
            sets_fn(probs_test[i : i + 1], qs[lv])[0]
            for i, lv in enumerate(test["language"].to_list())
        ]
        m_cal = [
            sets_fn(probs_cal[i : i + 1], qs[lv])[0]
            for i, lv in enumerate(cal["language"].to_list())
        ]
        cal_by_variant = {
            v: float(
                np.mean(
                    [y_cal[i] in m_cal[i] for i in np.where(cal["variant"] == v)[0]]
                )
            )
            for v in VARIANTS
        }
        mondrian.update(
            thresholds=qs,
            test=set_stats(m_sets, test),
            test_by_variant={
                v: _subset(m_sets, test, test["variant"] == v) for v in VARIANTS
            },
            calibration_coverage_by_variant=cal_by_variant,
            adopted=all(c >= 1 - ALPHA for c in cal_by_variant.values()),
        )
    main["mondrian"] = mondrian
    return {
        "method": method,
        "pre_registered": method == "aps",
        "alpha": ALPHA,
        "max_set": MAX_SET,
        "n_calibration": len(y_cal),
        "main": main,
        "alpha_sweep": sweep,
        "calibration_crossfit": calibration_crossfit(probs_cal, cal, method),
    }


def calibration_crossfit(probs_cal: np.ndarray, cal: pl.DataFrame, method: str) -> dict:
    """Coverage and set size estimated inside calibration only (2-fold by leak group).

    Shows what a score choice would look like without touching the test split: the
    threshold is fit on one half of the calibration groups and applied to the other.
    """
    score_fn, sets_fn = conformal.SCORES[method], conformal.SETS[method]
    y = cal["y"].to_numpy()
    groups = cal["leak_group"].to_numpy()
    uniq = np.unique(groups)
    rng = np.random.default_rng(SEED)
    half = set(rng.permutation(uniq)[: len(uniq) // 2].tolist())
    in_a = np.array([g in half for g in groups])
    stats = []
    for fit, ev in ((in_a, ~in_a), (~in_a, in_a)):
        q = conformal.conformal_quantile(score_fn(probs_cal[fit], y[fit]), ALPHA)
        stats.append(set_stats(sets_fn(probs_cal[ev], q), cal.filter(ev)))
    return {k: float(np.mean([s[k] for s in stats])) for k in stats[0] if k != "n"}


def set_stats(sets: list[list[int]], df: pl.DataFrame) -> dict:
    y = df["y"].to_numpy()
    sizes = np.array([len(s) for s in sets])
    return {
        "n": int(len(sets)),
        "coverage": float(np.mean([t in s for s, t in zip(sets, y)]))
        if len(sets)
        else float("nan"),
        "mean_set_size": float(sizes.mean()) if len(sets) else float("nan"),
        "share_singleton": float((sizes == 1).mean()) if len(sets) else float("nan"),
        "share_size_2": float((sizes == MAX_SET).mean()) if len(sets) else float("nan"),
        "share_empty_or_over_max": float(((sizes == 0) | (sizes > MAX_SET)).mean())
        if len(sets)
        else float("nan"),
    }


def slot_report(test: pl.DataFrame) -> dict:
    """Exact-match P/R/F1 per slot of the rule extractor, given the gold intent."""
    tp, fp, fn = Counter(), Counter(), Counter()
    for row in test.iter_rows(named=True):
        found = extract_slots(row["text"], row["intent"])
        for s in SLOTS:
            gold = row[f"slot_{s}"]
            pred = found.get(s)
            norm = (lambda v: v.casefold()) if s == "merchant" else (lambda v: v)
            if gold is not None and pred is not None and norm(gold) == norm(pred):
                tp[s] += 1
            else:
                fp[s] += pred is not None
                fn[s] += gold is not None
    out = {}
    for s in (*SLOTS, "all"):
        t = sum(tp.values()) if s == "all" else tp[s]
        p_ = sum(fp.values()) if s == "all" else fp[s]
        n_ = sum(fn.values()) if s == "all" else fn[s]
        precision = t / (t + p_) if t + p_ else 0.0
        recall = t / (t + n_) if t + n_ else 0.0
        out[s] = {
            "support": t + n_,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(2 * precision * recall / (precision + recall), 4)
            if precision + recall
            else 0.0,
        }
    return out


def golden_report(preds: dict[str, np.ndarray], golden: list[dict]) -> dict:
    y = np.array([INTENTS.index(t["intent"]) for t in golden])
    single = np.array([not t.get("context_dependent") for t in golden])
    return {
        name: {
            "n": int(len(y)),
            "accuracy": float((p == y).mean()),
            "n_single_turn": int(single.sum()),
            "accuracy_single_turn": float((p[single] == y[single]).mean()),
            "errors": [
                {"text": t["text"], "gold": t["intent"], "pred": INTENTS[pi]}
                for t, pi, yi in zip(golden, p, y)
                if pi != yi
            ],
        }
        for name, p in preds.items()
    }


def latency_ms(fn, texts: list[str]) -> dict:
    times = []
    for t in texts:
        start = time.perf_counter()
        fn(t)
        times.append((time.perf_counter() - start) * 1000)
    return {
        "p50": float(np.percentile(times, 50)),
        "p95": float(np.percentile(times, 95)),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def corpus_sha256() -> str:
    h = hashlib.sha256()
    for p in sorted(CORPUS_DIR.rglob("*.yaml")):
        h.update(p.relative_to(CORPUS_DIR).as_posix().encode())
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ML_ROOT,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _r(obj):
    """Round floats for readable JSON."""
    if isinstance(obj, float):
        return round(obj, 4)
    if isinstance(obj, dict):
        return {k: _r(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_r(v) for v in obj]
    return obj


# Main ------------------------------------------------------------------------


def main(argv=None):  # noqa: PLR0915
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cv-only", action="store_true")
    args = parser.parse_args(argv)

    df = pl.read_parquet(OUT_DIR / "utterances.parquet").with_columns(
        pl.col("intent").map_elements(INTENTS.index, return_dtype=pl.Int64).alias("y")
    )
    golden = yaml.safe_load(GOLDEN_YAML.read_text(encoding="utf-8"))["turns"]
    train = df.filter(pl.col("split") == "train")
    cal = df.filter(pl.col("split") == "calibration")
    test = df.filter(pl.col("split") == "test")
    print(f"train {train.height}  calibration {cal.height}  test {test.height}")  # noqa: T201

    all_texts = df["text"].to_list() + [t["text"] for t in golden]
    t0 = time.perf_counter()
    embeddings_all = {name: encode(name, all_texts) for name in ENCODERS}
    encode_seconds = time.perf_counter() - t0
    row_of = {u: i for i, u in enumerate(df["utterance_id"].to_list())}

    def emb(name, part):
        return embeddings_all[name][[row_of[u] for u in part["utterance_id"].to_list()]]

    golden_emb = {name: e[df.height :] for name, e in embeddings_all.items()}

    cv = cross_validate(train, {name: emb(name, train) for name in ENCODERS})
    print(json.dumps(_r(cv["best_per_family"]), indent=1), "winner:", cv["winner"])  # noqa: T201
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    if args.cv_only:
        (ARTIFACT_DIR / "cv_results.json").write_text(json.dumps(_r(cv), indent=1))
        return

    # Final fit on train only.
    y_train = train["y"].to_numpy()
    best = cv["best_per_family"]
    tfidf = make_tfidf(best["tfidf_lr"]["C"]).fit(train["text"].to_list(), y_train)
    heads = {
        name: make_lr(best[name]["C"]).fit(emb(name, train), y_train)
        for name in ENCODERS
    }
    majority = Counter(y_train.tolist()).most_common(1)[0][0]

    probs = {
        "tfidf_lr": (
            tfidf.predict_proba(cal["text"].to_list()),
            tfidf.predict_proba(test["text"].to_list()),
        )
    }
    for name, head in heads.items():
        probs[name] = (
            head.predict_proba(emb(name, cal)),
            head.predict_proba(emb(name, test)),
        )
    test_pred = {
        "majority": np.full(test.height, majority),
        "rules": rule_predictions(test["text"].to_list()),
        **{name: p[1].argmax(axis=1) for name, p in probs.items()},
    }
    golden_texts = [t["text"] for t in golden]
    golden_pred = {
        "majority": np.full(len(golden), majority),
        "rules": rule_predictions(golden_texts),
        "tfidf_lr": tfidf.predict(golden_texts),
        **{name: head.predict(golden_emb[name]) for name, head in heads.items()},
    }

    # Test split, scored once.
    groups = test["leak_group"].to_numpy()
    weights = metrics.resample_weights(len(np.unique(groups)), N_BOOT, SEED)
    results, boots = {}, {}
    for name, pred in test_pred.items():
        results[name], boots[name] = evaluate(test, pred, weights)
    winner = cv["winner"]
    paired = {}
    for other in test_pred:
        if other == DEPLOYED:
            continue
        diff = boots[DEPLOYED] - boots[other]
        paired[f"{DEPLOYED}_minus_{other}"] = {
            "point": results[DEPLOYED]["macro_f1"] - results[other]["macro_f1"],
            "ci95": metrics.interval(diff),
        }
    if winner != DEPLOYED:
        diff = boots[winner] - boots[DEPLOYED]
        paired[f"{winner}_minus_{DEPLOYED}"] = {
            "point": results[winner]["macro_f1"] - results[DEPLOYED]["macro_f1"],
            "ci95": metrics.interval(diff),
        }

    conformal_results = {
        f"{name}|{method}": conformal_report(
            probs[name][0], cal, probs[name][1], test, method
        )
        for name in sorted({DEPLOYED, winner} & set(probs))
        for method in ("aps", "lac")
    }

    # Size and latency of the deployed model and the best encoder.
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    model_path = ARTIFACT_DIR / "model.joblib"
    joblib.dump(tfidf, model_path, compress=3)
    sample = test["text"].to_list()[:LATENCY_SAMPLE]
    cost = {
        "tfidf_lr": {
            "artifact_bytes": model_path.stat().st_size,
            "latency_ms_per_utterance_cpu": latency_ms(
                lambda t: tfidf.predict_proba([t]), sample
            ),
            "runtime_dependencies": ["scikit-learn", "numpy", "scipy", "joblib"],
        }
    }
    best_encoder = max(ENCODERS, key=lambda n: best[n]["mean"])
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    spec = ENCODERS[best_encoder]
    st_model = SentenceTransformer(
        spec["model"], revision=spec["revision"], device="cpu"
    )
    head = heads[best_encoder]
    weights_bytes = sum(
        p.stat().st_size
        for p in (
            Path.home()
            / ".cache"
            / "huggingface"
            / "hub"
            / f"models--{spec['model'].replace('/', '--')}"
            / "snapshots"
            / spec["revision"]
        ).rglob("*")
        if p.is_file()
    )
    cost[best_encoder] = {
        "artifact_bytes": len(joblib_bytes(head)) + weights_bytes,
        "encoder_weights_bytes": weights_bytes,
        "latency_ms_per_utterance_cpu": latency_ms(
            lambda t: head.predict_proba(
                st_model.encode(
                    [spec["prefix"] + t],
                    normalize_embeddings=True,
                    show_progress_bar=False,
                )
            ),
            sample,
        ),
        "runtime_dependencies": [
            "torch",
            "sentence-transformers",
            "transformers",
            "scikit-learn",
        ],
        "encode_all_seconds": encode_seconds / len(ENCODERS),
    }

    # Leak checks reported in the model card.
    golden_pairs = near_duplicate_pairs(
        [t["text"] for t in golden] + train["text"].to_list(),
        ["golden"] * len(golden) + train["seed_group_id"].to_list(),
    )
    build_report = json.loads(
        (OUT_DIR / "build_report.json").read_text(encoding="utf-8")
    )
    leaks = {
        "exact_cross_split_pairs": build_report["exact_cross_split_pairs"],
        "near_duplicate_cross_split_pairs": build_report[
            "near_duplicate_cross_split_pairs"
        ],
        "near_duplicate_threshold": NEAR_DUP_DISTANCE,
        "golden_turns_near_duplicate_of_train": len(
            {i for i, j, _ in golden_pairs if i < len(golden) <= j}
        ),
        "features": "utterance text only (no main_topics, detected_intents or fraud_score)",
    }

    # Export.
    conf = conformal_results[f"{DEPLOYED}|aps"]
    lac = conformal_results[f"{DEPLOYED}|lac"]
    mondrian = conf["main"]["mondrian"]
    conformal_json = {
        "method": "split_conformal_aps_nonrandomized",
        "alpha": ALPHA,
        "threshold": conf["main"]["threshold"],
        "max_set": MAX_SET,
        "classes": list(INTENTS),
        "n_calibration": conf["n_calibration"],
        "mondrian_by_language": mondrian.get("thresholds")
        if mondrian.get("adopted")
        else None,
        "pre_registered": True,
        "alternatives": {
            "lac": {
                "threshold": lac["main"]["threshold"],
                "status": "exploratory, not pre-registered; adopting it needs an "
                "eval-plan amendment before held-out A",
            }
        },
    }
    (ARTIFACT_DIR / "conformal.json").write_text(json.dumps(conformal_json, indent=1))
    metadata = {
        "model_type": "tfidf_word1-2_char2-5_logistic_regression",
        "C": best["tfidf_lr"]["C"],
        "model_sha256": _sha256(model_path),
        "sklearn_version": sklearn.__version__,
        "intents_version": rules.INTENTS_VERSION,
        "dataset_version": df["dataset_version"][0],
        "corpus_sha256": corpus_sha256(),
        "trained_on": "train split only",
        "n_train": train.height,
        "git_commit": git_commit(),
        "data_provenance": "team-generated, LLM-assisted, not yet human-reviewed",
        "cv_winner": winner,
        "deployed_reason": "TF-IDF + LR deployed regardless of the CV winner, for size and latency (team decision before test scoring)",
    }
    (ARTIFACT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=1))
    eval_results = {
        "split_sizes": {
            "train": train.height,
            "calibration": cal.height,
            "test": test.height,
        },
        "cv": cv,
        "deployed": DEPLOYED,
        "test": results,
        "paired_bootstrap": paired,
        "conformal": conformal_results,
        "slots_rules_gold_intent": slot_report(test),
        "golden_turns": golden_report(golden_pred, golden),
        "cost": cost,
        "leak_checks": leaks,
        "encoders": ENCODERS,
        "n_boot": N_BOOT,
    }
    (ARTIFACT_DIR / "eval_results.json").write_text(
        json.dumps(_r(eval_results), indent=1)
    )
    pl.DataFrame(
        {
            "utterance_id": test["utterance_id"],
            "leak_group": test["leak_group"],
            "y": test["y"],
            **{f"pred_{k}": v for k, v in test_pred.items()},
        }
    ).write_parquet(OUT_DIR / "test_predictions.parquet")
    summary = {
        k: {
            "macro_f1": v["macro_f1"],
            "es": v["by_language"]["es"]["macro_f1"],
            "pt": v["by_language"]["pt"]["macro_f1"],
        }
        for k, v in results.items()
    }
    print(json.dumps(_r(summary), indent=1))  # noqa: T201
    mains = {k: v["main"]["coverage"] for k, v in conformal_results.items()}
    print("conformal coverage:", mains)  # noqa: T201


def joblib_bytes(obj) -> bytes:
    import io  # noqa: PLC0415

    buf = io.BytesIO()
    joblib.dump(obj, buf, compress=3)
    return buf.getvalue()


if __name__ == "__main__":
    main()
