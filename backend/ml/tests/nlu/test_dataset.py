"""Corpus integrity (ml/nlu_corpus/), the committed fixture, and split invariants."""

from pathlib import Path

import polars as pl
import pytest

from banking_cs.nlu import dataset
from banking_cs.nlu.rules import INTENT_SLOTS, INTENTS, SLOTS
from tests.nlu.test_rules import GUIDE, HARD_NEGATIVES

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "nlu_utterances_sample.csv"


@pytest.fixture(scope="module")
def corpus():
    return dataset.load_corpus()


def test_corpus_validates(corpus):
    assert dataset.validate(corpus) == []


def test_seed_groups_per_intent(corpus):
    groups = {
        (r["intent"], r["seed_group_id"]) for r in corpus if r["group_kind"] == "seed"
    }
    added = {"card_block": 20, "out_of_scope": 15}  # nlu-utt-0.2 topics
    for intent in INTENTS:
        expected = 40 + added.get(intent, 0)
        assert sum(1 for i, _ in groups if i == intent) == expected, intent


def test_guide_matches_labeling_guide(corpus):
    rows = {
        (r["variant"], r["text"], r["intent"])
        for r in corpus
        if r["group_kind"] == "guide"
    }
    assert rows == {(v, t, i) for v, t, i, _ in GUIDE}
    for r in corpus:
        if r["group_kind"] == "guide":
            expected = next(s for v, t, i, s in GUIDE if t == r["text"])
            assert expected.items() <= r["slots"].items(), r["text"]


def test_hard_negatives_match_labeling_guide(corpus):
    seeds = {
        (r["text"], r["intent"])
        for r in corpus
        if r["group_kind"] == "hard_negative" and r["is_seed"]
    }
    assert seeds == {(t, i) for _, t, i, _ in HARD_NEGATIVES}


def test_pt_native_subset(corpus):
    rows = [r for r in corpus if r["group_kind"] == "pt_native"]
    assert len(rows) >= 60
    assert {r["variant"] for r in rows} == {"pt-BR"}


def test_fixture_schema():
    df = pl.read_csv(FIXTURE, infer_schema_length=0)
    expected = {
        "utterance_id",
        "seed_group_id",
        "group_kind",
        "text",
        "language",
        "variant",
        "intent",
        "split",
    }
    assert expected | {f"slot_{s}" for s in SLOTS} <= set(df.columns)
    assert set(df["intent"]) == set(INTENTS)
    assert set(df["split"]) <= set(dataset.SPLITS)
    assert set(df["human_reviewed"]) == {"false"}
    assert set(df["origin"]) == {"team_generated"}
    for row in df.iter_rows(named=True):
        labeled = {s for s in SLOTS if row[f"slot_{s}"] not in (None, "")}
        assert labeled <= set(INTENT_SLOTS[row["intent"]]), row["utterance_id"]
    # A group never spans two splits.
    assert (
        df.group_by("seed_group_id").agg(pl.col("split").n_unique())["split"].max() == 1
    )


def _row(group, kind, intent, text, variant="es-MX"):
    return {
        "utterance_id": f"{group}-{text}",
        "seed_group_id": group,
        "group_kind": kind,
        "text": text,
        "language": dataset.LANGUAGE[variant],
        "variant": variant,
        "intent": intent,
        "slots": {},
        "is_seed": True,
        "source_file": "toy",
    }


def test_split_invariants():
    words = [
        "alfa",
        "bravo",
        "charlie",
        "delta",
        "eco",
        "foxtrot",
        "golf",
        "hotel",
        "india",
        "juliet",
    ]
    rows = [
        _row(f"g{i}", "seed", "card_list", f"{w} " * (i + 2))
        for i, w in enumerate(words)
    ]
    rows.append(_row("gd", "guide", "card_list", "alfa alfa."))
    rows.append(
        _row("pn", "pt_native", "card_list", "frase totalmente diferente", "pt-BR")
    )
    groups = [r["seed_group_id"] for r in rows]
    pairs = dataset.near_duplicate_pairs([r["text"] for r in rows], groups)
    component = dataset._components(groups, pairs)
    split_of = dataset.assign_splits(rows, component)
    # g0 is a near-duplicate of a guide row, so it is merged with it and forced to train.
    assert component["g0"] == component["gd"]
    assert split_of["g0"] == split_of["gd"] == "train"
    assert split_of["pn"] == "test"
    free = [split_of[f"g{i}"] for i in range(1, 10)]
    assert set(free) == {"train", "calibration", "test"}


def test_locked_groups_keep_their_split(corpus):
    locked = dataset.load_split_locks()
    groups = [r["seed_group_id"] for r in corpus]
    pairs = dataset.near_duplicate_pairs([r["text"] for r in corpus], groups)
    split_of = dataset.assign_splits(corpus, dataset._components(groups, pairs), locked)
    assert all(split_of[g] == s for g, s in locked.items())


def test_added_topics_split_three_one_one(corpus):
    locked = dataset.load_split_locks()
    groups = [r["seed_group_id"] for r in corpus]
    pairs = dataset.near_duplicate_pairs([r["text"] for r in corpus], groups)
    split_of = dataset.assign_splits(corpus, dataset._components(groups, pairs), locked)
    topics = {}
    for r in corpus:
        if r.get("topic"):
            topics.setdefault(r["topic"], set()).add(r["seed_group_id"])
    assert len(topics) == 7
    for gids in topics.values():
        assert sorted(split_of[g] for g in gids) == [
            "calibration",
            "test",
            "train",
            "train",
            "train",
        ]
        assert not gids & set(locked)
