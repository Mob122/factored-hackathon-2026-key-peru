"""Classification metrics with bootstrap intervals over groups (docs/eval_plan.md 8.4).

Macro-F1 follows scikit-learn's default: the mean F1 over the classes present in y_true or
y_pred. Bootstrap resamples whole groups (seed groups merged by near-duplicates), so the
interval reflects that paraphrases and translations of one seed are not independent.
"""

from __future__ import annotations

import numpy as np


def group_counts(
    y_true: np.ndarray, y_pred: np.ndarray, groups: np.ndarray, n_classes: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Per-group true positives, false positives, false negatives and support (G x K)."""
    uniq, g_idx = np.unique(groups, return_inverse=True)
    shape = (len(uniq), n_classes)
    tp, fp, fn = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    correct = y_true == y_pred
    np.add.at(tp, (g_idx[correct], y_true[correct]), 1)
    np.add.at(fp, (g_idx[~correct], y_pred[~correct]), 1)
    np.add.at(fn, (g_idx[~correct], y_true[~correct]), 1)
    support = tp + fn
    return tp, fp, fn, support


def macro_f1_from_counts(tp: np.ndarray, fp: np.ndarray, fn: np.ndarray) -> np.ndarray:
    """Macro-F1 over the last axis; classes with no true and no predicted rows are skipped."""
    denom = 2 * tp + fp + fn
    present = denom > 0
    f1 = np.divide(2 * tp, denom, out=np.zeros_like(tp, dtype=float), where=present)
    return f1.sum(axis=-1) / np.maximum(present.sum(axis=-1), 1)


def macro_f1(y_true: np.ndarray, y_pred: np.ndarray, n_classes: int) -> float:
    tp, fp, fn, _ = group_counts(y_true, y_pred, np.zeros(len(y_true)), n_classes)
    return float(macro_f1_from_counts(tp.sum(0), fp.sum(0), fn.sum(0)))


def resample_weights(n_groups: int, n_boot: int, seed: int) -> np.ndarray:
    """How many times each group is drawn in each bootstrap resample (B x G)."""
    rng = np.random.default_rng(seed)
    return rng.multinomial(n_groups, np.full(n_groups, 1 / n_groups), size=n_boot)


def bootstrap_macro_f1(counts, weights: np.ndarray) -> np.ndarray:
    """Macro-F1 of each bootstrap resample, from group counts and resample weights."""
    tp, fp, fn, _ = counts
    return macro_f1_from_counts(weights @ tp, weights @ fp, weights @ fn)


def interval(values: np.ndarray, level: float = 0.95) -> tuple[float, float]:
    lo, hi = np.quantile(values, [(1 - level) / 2, 1 - (1 - level) / 2])
    return float(lo), float(hi)


def per_class_report(y_true: np.ndarray, y_pred: np.ndarray, labels: list[str]) -> dict:
    out = {}
    for k, name in enumerate(labels):
        tp = int(((y_true == k) & (y_pred == k)).sum())
        fp = int(((y_true != k) & (y_pred == k)).sum())
        fn = int(((y_true == k) & (y_pred != k)).sum())
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
        out[name] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }
    return out


def confusion(
    y_true: np.ndarray, y_pred: np.ndarray, n_classes: int
) -> list[list[int]]:
    m = np.zeros((n_classes, n_classes), dtype=int)
    np.add.at(m, (y_true, y_pred), 1)
    return m.tolist()
