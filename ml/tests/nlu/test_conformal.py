"""APS conformal sets and grouped bootstrap metrics on toy inputs."""

import numpy as np
from sklearn.metrics import f1_score

from banking_cs.nlu import conformal, metrics


def test_aps_score_includes_classes_ranked_above():
    probs = np.array([[0.6, 0.3, 0.1], [0.6, 0.3, 0.1]])
    np.testing.assert_allclose(
        conformal.aps_scores(probs, np.array([0, 2])), [0.6, 1.0]
    )


def test_threshold_is_finite_sample_quantile():
    scores = np.arange(1, 11) / 10  # n = 10
    # ceil(11 * 0.9) = 10 -> the largest score.
    assert conformal.conformal_quantile(scores, 0.10) == 1.0
    # ceil(11 * 0.8) = 9 -> the 9th smallest.
    assert conformal.conformal_quantile(scores, 0.20) == 0.9


def test_sets_never_empty_and_stop_at_threshold():
    probs = np.array([[0.7, 0.2, 0.1], [0.4, 0.35, 0.25], [0.95, 0.04, 0.01]])
    sets = conformal.aps_sets(probs, 0.8)
    assert sets[0] == [0, 1]  # 0.7 < 0.8 -> add the second class
    assert sets[1] == [0, 1, 2]  # 0.75 < 0.8 -> add the third class
    assert sets[2] == [0]


def test_coverage_holds_on_exchangeable_data():
    rng = np.random.default_rng(0)
    n, k, alpha = 4000, 6, 0.1
    logits = rng.normal(size=(n, k)) * 2
    probs = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    labels = np.array([rng.choice(k, p=p) for p in probs])
    cal, test = slice(0, n // 2), slice(n // 2, n)
    q = conformal.conformal_quantile(
        conformal.aps_scores(probs[cal], labels[cal]), alpha
    )
    sets = conformal.aps_sets(probs[test], q)
    coverage = np.mean([y in s for s, y in zip(sets, labels[test])])
    assert coverage >= 1 - alpha - 0.02


def test_true_label_in_set_whenever_score_within_threshold():
    rng = np.random.default_rng(1)
    probs = rng.dirichlet(np.ones(5), size=500)
    labels = rng.integers(0, 5, size=500)
    q = 0.7
    scores = conformal.aps_scores(probs, labels)
    sets = conformal.aps_sets(probs, q)
    for s, y, sc in zip(sets, labels, scores):
        if sc <= q:
            assert y in s


def test_macro_f1_matches_sklearn():
    rng = np.random.default_rng(2)
    y = rng.integers(0, 5, size=300)
    pred = np.where(rng.random(300) < 0.7, y, rng.integers(0, 5, size=300))
    assert np.isclose(metrics.macro_f1(y, pred, 5), f1_score(y, pred, average="macro"))


def test_bootstrap_with_unit_weights_reproduces_point_estimate():
    rng = np.random.default_rng(3)
    y = rng.integers(0, 4, size=200)
    pred = np.where(rng.random(200) < 0.8, y, rng.integers(0, 4, size=200))
    groups = np.repeat(np.arange(50), 4)
    counts = metrics.group_counts(y, pred, groups, 4)
    ones = np.ones((1, 50))
    assert np.isclose(
        metrics.bootstrap_macro_f1(counts, ones)[0], metrics.macro_f1(y, pred, 4)
    )
    weights = metrics.resample_weights(50, 500, seed=0)
    assert (weights.sum(axis=1) == 50).all()
    lo, hi = metrics.interval(metrics.bootstrap_macro_f1(counts, weights))
    assert lo < metrics.macro_f1(y, pred, 4) < hi


def test_lac_sets_can_be_empty_and_cover():
    probs = np.array([[0.5, 0.3, 0.2], [0.9, 0.06, 0.04]])
    assert conformal.lac_sets(probs, 0.3) == [[], [0]]
    assert conformal.lac_sets(probs, 0.75) == [[0, 1], [0]]
    rng = np.random.default_rng(4)
    logits = rng.normal(size=(4000, 6)) * 2
    p = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    y = np.array([rng.choice(6, p=row) for row in p])
    q = conformal.conformal_quantile(conformal.lac_scores(p[:2000], y[:2000]), 0.1)
    sets = conformal.lac_sets(p[2000:], q)
    assert np.mean([t in s for s, t in zip(sets, y[2000:])]) >= 0.88
