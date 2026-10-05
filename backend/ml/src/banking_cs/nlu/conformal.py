"""Split conformal prediction sets with the APS score (docs/eval_plan.md 8.4).

Non-randomized APS (Romano et al. 2020; Angelopoulos and Bates 2021, section 2.1): the
score of a labeled example is the probability mass of every class ranked at or above its
true class. The threshold is the ceil((n + 1)(1 - alpha)) / n empirical quantile of the
calibration scores. A prediction set adds classes in descending probability until their
cumulative mass reaches the threshold, so it is never empty and its marginal coverage is at
least 1 - alpha when calibration and test examples are exchangeable. Deterministic (no
randomized tie-breaking), so the runtime always returns the same set for the same text.

LAC (least ambiguous set-valued classifier, Sadinle et al. 2019) is also provided: score
1 - p(true class), set = every class whose probability is at least 1 - threshold. It gives
the smallest sets on average but can return an empty set. It is an exploratory alternative
in the model card, not the pre-registered method.

numpy only: imported by the runtime loader.
"""

from __future__ import annotations

import math

import numpy as np


def aps_scores(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Cumulative mass of the classes ranked at or above each true label."""
    true_p = probs[np.arange(len(labels)), labels]
    # Ties count as ranked above, which can only enlarge the score (conservative).
    return np.where(probs >= true_p[:, None], probs, 0.0).sum(axis=1)


def conformal_quantile(scores: np.ndarray, alpha: float) -> float:
    """Finite-sample corrected (1 - alpha) quantile of calibration scores (any score)."""
    n = len(scores)
    rank = math.ceil((n + 1) * (1 - alpha))
    if rank > n:  # too few calibration points for this alpha: every set is all classes
        return 1.0
    return float(np.sort(scores)[rank - 1])


def aps_sets(probs: np.ndarray, threshold: float) -> list[list[int]]:
    """Class indices in each prediction set, most probable first."""
    order = np.argsort(-probs, axis=1, kind="stable")
    sorted_p = np.take_along_axis(probs, order, axis=1)
    mass_before = np.cumsum(sorted_p, axis=1) - sorted_p
    # Include a class while the mass already in the set is below the threshold. A small
    # tolerance keeps float rounding from adding a class whose score equals the threshold.
    keep = mass_before < threshold - 1e-12
    keep[:, 0] = True
    return [order[i, keep[i]].tolist() for i in range(len(probs))]


def mondrian_thresholds(
    scores: np.ndarray, strata: np.ndarray, alpha: float
) -> dict[str, float]:
    """One APS threshold per stratum (the pre-registered by-language fallback, 8.4)."""
    return {
        str(s): conformal_quantile(scores[strata == s], alpha)
        for s in np.unique(strata)
    }


def lac_scores(probs: np.ndarray, labels: np.ndarray) -> np.ndarray:
    return 1.0 - probs[np.arange(len(labels)), labels]


def lac_sets(probs: np.ndarray, threshold: float) -> list[list[int]]:
    """Classes with probability >= 1 - threshold, most probable first (may be empty)."""
    order = np.argsort(-probs, axis=1, kind="stable")
    return [
        [int(k) for k in row if p[k] >= 1.0 - threshold - 1e-12]
        for row, p in zip(order, probs)
    ]


SCORES = {"aps": aps_scores, "lac": lac_scores}
SETS = {"aps": aps_sets, "lac": lac_sets}
