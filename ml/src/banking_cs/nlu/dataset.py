"""Build the NLU utterance dataset from ml/nlu_corpus/ (docs/eval_plan.md 8.1, 8.2).

Run from ml/:  python -m banking_cs.nlu.dataset

Steps: load and validate the YAML corpus, merge seed groups that hold near-duplicate
utterances (normalized Levenshtein distance < 0.1) so that no near-duplicate pair can
cross splits, assign splits by group (train / calibration / test = 60 / 20 / 20,
stratified by intent; guide and hard-negative groups forced to train, pt-native groups
forced to test), and write:
- data/nlu/utterances.parquet (git-ignored): one row per utterance.
- data/nlu/build_report.json: counts, merges and leak checks.
- data/nlu/label_quality_sample.csv and label_quality_key.csv: the blind sample for the
  two-annotator kappa (eval plan 8.1; 100 rows by team decision, not 200).
- tests/fixtures/nlu_utterances_sample.csv (committed): a small stratified sample.

Training-time module: imports yaml, polars and rapidfuzz, which the runtime loader
does not need.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import polars as pl
import yaml
from rapidfuzz import process
from rapidfuzz.distance import Levenshtein

from banking_cs.nlu.rules import (
    BALANCE_ITEMS,
    INTENT_SLOTS,
    INTENTS,
    PRODUCT_KINDS,
    SLOTS,
    TX_STATUSES,
    normalize,
)

DATASET_VERSION = "nlu-utt-0.2"
VARIANTS = ("es-MX", "es-CO", "es-AR", "pt-BR")
LANGUAGE = {"es-MX": "es", "es-CO": "es", "es-AR": "es", "pt-BR": "pt"}
SPLITS = ("train", "calibration", "test")
SPLIT_SHARES = (0.6, 0.2, 0.2)
SPLIT_SEED = 2026
NEAR_DUP_DISTANCE = 0.1
UTTERANCES_PER_VARIANT = 2
MAX_TEXT_LEN = 300
ORIGIN = "team_generated"
AUTHORING = "llm_assisted"
AUTHOR_MODEL = "claude-opus-5-5"
FORCED_SPLIT = {"guide": "train", "hard_negative": "train", "pt_native": "test"}
SPECIAL_FILES = {
    "guide.yaml": "guide",
    "hard_negatives.yaml": "hard_negative",
    "pt_native.yaml": "pt_native",
}
LABEL_SAMPLE_SIZE = 100
LABEL_SAMPLE_MIN_HARD_NEGATIVES = 15
FIXTURE_PER_INTENT_VARIANT = 2

ML_ROOT = Path(__file__).resolve().parents[3]
CORPUS_DIR = ML_ROOT / "nlu_corpus"
OUT_DIR = ML_ROOT / "data" / "nlu"
FIXTURE_PATH = ML_ROOT / "tests" / "fixtures" / "nlu_utterances_sample.csv"

SLOT_COLUMNS = tuple(f"slot_{s}" for s in SLOTS)
DATE_RE = re.compile(
    r"^(?:today|yesterday|day_before_yesterday|few_days_ago|this_week|last_week|"
    r"last_weekend|this_month|last_month|n_days_ago:\d+|last_n_days:\d+|"
    r"month:(?:0[1-9]|1[0-2])|(?:date|since):(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])|"
    r"weekday:(?:mon|tue|wed|thu|fri|sat|sun))$"
)
AMOUNT_RE = re.compile(r"^\d+(?:\.\d{1,2})?(?: (?:USD|BRL|COP|ARS|MXN|PESO))?$")
SLOT_ENUMS = {
    "product_kind": set(PRODUCT_KINDS),
    "tx_status": set(TX_STATUSES),
    "balance_item": set(BALANCE_ITEMS),
}


# Loading --------------------------------------------------------------------


def _utterances(group: dict, variant: str) -> list[tuple[str, dict]]:
    items = group.get(variant) or []
    out = []
    for item in items:
        if isinstance(item, str):
            out.append((item.strip(), {}))
        else:
            out.append((item["text"].strip(), item.get("slots") or {}))
    return out


def load_corpus(corpus_dir: Path = CORPUS_DIR) -> list[dict]:
    """One dict per utterance, before splitting."""
    rows = []
    for path in sorted(corpus_dir.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        kind = SPECIAL_FILES.get(path.name, "seed")
        file_intent = doc.get("intent")
        for group in doc["groups"]:
            intent = group.get("intent", file_intent)
            base_slots = {k: v for k, v in (group.get("slots") or {}).items()}
            first = True
            for variant in VARIANTS:
                # Guide groups are one group per intent and variant (docs/intents.md 4).
                group_id = (
                    f"{group['id']}-{variant}" if kind == "guide" else group["id"]
                )
                for i, (text, override) in enumerate(_utterances(group, variant)):
                    slots = {**base_slots, **override}
                    slots = {k: v for k, v in slots.items() if v is not None}
                    rows.append(
                        {
                            "utterance_id": f"{group['id']}-{variant}-{i + 1}",
                            "seed_group_id": group_id,
                            "group_kind": kind,
                            "text": text,
                            "language": LANGUAGE[variant],
                            "variant": variant,
                            "intent": intent,
                            "slots": {k: str(v) for k, v in slots.items()},
                            "is_seed": first,
                            "topic": group.get("topic"),
                            "source_file": path.name,
                        }
                    )
                    first = False
    return rows


# Validation -----------------------------------------------------------------


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _slot_errors(row: dict) -> list[str]:
    errors = []
    text, slots, intent = row["text"], row["slots"], row["intent"]
    for name, value in slots.items():
        if name not in INTENT_SLOTS[intent]:
            errors.append(f"slot {name} not allowed for {intent}")
            continue
        if name in SLOT_ENUMS and value not in SLOT_ENUMS[name]:
            errors.append(f"{name}={value!r} not in enum")
        if name == "last4" and (not re.fullmatch(r"\d{4}", value) or value not in text):
            errors.append(f"last4 {value!r} not in text")
        if name == "merchant" and value not in text:
            errors.append(f"merchant {value!r} not in text")
        if name == "date" and not DATE_RE.match(value):
            errors.append(f"bad date {value!r}")
        if name == "amount":
            if not AMOUNT_RE.match(value):
                errors.append(f"bad amount {value!r}")
            else:
                number = value.split()[0].split(".")[0]
                folded = normalize(text)
                spelled = re.search(r"\b(?:mil|lucas?)\b", folded)
                if not spelled and number not in _digits(text):
                    errors.append(f"amount {value!r} not in text")
    if intent == "balance_inquiry" and "balance_item" not in slots:
        errors.append("balance_inquiry without balance_item")
    return errors


def validate(rows: list[dict]) -> list[str]:
    errors = []
    texts = Counter(r["text"] for r in rows)
    for r in rows:
        where = f"{r['source_file']}:{r['utterance_id']}"
        if r["intent"] not in INTENTS:
            errors.append(f"{where}: unknown intent {r['intent']!r}")
            continue
        if not r["text"] or len(r["text"]) > MAX_TEXT_LEN:
            errors.append(f"{where}: empty or too long")
        if texts[r["text"]] > 1:
            errors.append(f"{where}: duplicate text {r['text']!r}")
        errors.extend(f"{where}: {e}" for e in _slot_errors(r))
    by_group = defaultdict(list)
    for r in rows:
        by_group[r["seed_group_id"]].append(r)
    for gid, members in by_group.items():
        if len({m["intent"] for m in members}) > 1:
            errors.append(f"{gid}: group with several intents")
        if members[0]["group_kind"] == "seed":
            counts = Counter(m["variant"] for m in members)
            for v in VARIANTS:
                if counts[v] != UTTERANCES_PER_VARIANT:
                    errors.append(f"{gid}: {counts[v]} utterances in {v}")
    return errors


# Near-duplicates and splits -------------------------------------------------


def near_duplicate_pairs(
    texts: list[str], groups: list[str]
) -> list[tuple[int, int, float]]:
    """Index pairs from different groups with normalized edit distance < 0.1."""
    norm = [normalize(t) for t in texts]
    dist = process.cdist(
        norm,
        norm,
        scorer=Levenshtein.normalized_distance,
        dtype=np.float32,
        workers=-1,
    )
    pairs = []
    ii, jj = np.where(dist < NEAR_DUP_DISTANCE)
    for i, j in zip(ii.tolist(), jj.tolist()):
        if i < j and groups[i] != groups[j]:
            pairs.append((i, j, float(dist[i, j])))
    return pairs


def _components(row_groups: list[str], pairs) -> dict[str, str]:
    """Union-find over groups; `pairs` index into `row_groups` (one entry per row)."""
    parent = {g: g for g in sorted(set(row_groups))}

    def find(g):
        while parent[g] != g:
            parent[g] = parent[parent[g]]
            g = parent[g]
        return g

    for i, j, _ in pairs:
        a, b = find(row_groups[i]), find(row_groups[j])
        if a != b:
            parent[max(a, b)] = min(a, b)
    return {g: find(g) for g in parent}


def load_split_locks(corpus_dir: Path = CORPUS_DIR) -> dict[str, str]:
    """Group -> split of earlier dataset versions (locks/*.json); those groups never move."""
    locked = {}
    for path in sorted((corpus_dir / "locks").glob("*.json")):
        locked.update(json.loads(path.read_text(encoding="utf-8"))["splits"])
    return locked


def _stratum_seed(intent: str, topic: str | None) -> int:
    digest = hashlib.sha256(f"{SPLIT_SEED}|{intent}|{topic}".encode()).hexdigest()
    return int(digest[:8], 16)


def assign_splits(
    rows: list[dict], component: dict[str, str], locked: dict[str, str] | None = None
) -> dict[str, str]:
    """Split per component (merged groups).

    A component holding a locked group takes that group's split (new near-duplicates of a
    locked group inherit it). Other components with a train-only or test-only kind are
    forced. The rest are split 60/20/20 within each (intent, topic) stratum, with a seed
    per stratum, so adding groups to one stratum never reshuffles another.
    """
    locked = locked or {}
    members = defaultdict(list)
    for r in rows:
        members[component[r["seed_group_id"]]].append(r)
    split_of = {}
    free = defaultdict(list)
    for comp, rs in sorted(members.items()):
        kinds = {r["group_kind"] for r in rs}
        forced = {FORCED_SPLIT[k] for k in kinds if k in FORCED_SPLIT}
        lock = {locked[r["seed_group_id"]] for r in rs if r["seed_group_id"] in locked}
        if len(lock) > 1:
            raise ValueError(f"component {comp} joins locked groups in splits {lock}")
        if lock:
            split_of[comp] = lock.pop()
        elif forced:
            # A component touching a train-only group goes to train.
            split_of[comp] = "train" if "train" in forced else forced.pop()
        else:
            intent = Counter(r["intent"] for r in rs).most_common(1)[0][0]
            topic = next((r["topic"] for r in rs if r.get("topic")), None)
            free[(intent, topic)].append(comp)
    for (intent, topic), comps in sorted(
        free.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
    ):
        order = sorted(comps)
        np.random.default_rng(_stratum_seed(intent, topic)).shuffle(order)
        n = len(order)
        n_cal = round(n * SPLIT_SHARES[1])
        n_test = round(n * SPLIT_SHARES[2])
        for k, comp in enumerate(order):
            split_of[comp] = (
                "test"
                if k < n_test
                else "calibration"
                if k < n_test + n_cal
                else "train"
            )
    return {g: split_of[c] for g, c in component.items()}


def cross_split_leaks(df: pl.DataFrame) -> dict[str, int]:
    """Exact and near-duplicate pairs whose members sit in different splits."""
    texts = df["text"].to_list()
    splits = df["split"].to_list()
    norm = [normalize(t) for t in texts]
    by_text = defaultdict(list)
    for t, s in zip(norm, splits):
        by_text[t].append(s)
    exact = sum(
        1
        for ss in by_text.values()
        for a in range(len(ss))
        for b in range(a + 1, len(ss))
        if ss[a] != ss[b]
    )
    near = [
        (i, j)
        for i, j, _ in near_duplicate_pairs(texts, df["seed_group_id"].to_list())
        if splits[i] != splits[j]
    ]
    return {
        "exact_cross_split_pairs": exact,
        "near_duplicate_cross_split_pairs": len(near),
    }


# Outputs --------------------------------------------------------------------


def to_frame(
    rows: list[dict], split_of: dict[str, str], component: dict[str, str]
) -> pl.DataFrame:
    """One row per utterance; `leak_group` is the merged component used for CV folds."""
    records = []
    for r in rows:
        rec = {k: r[k] for k in ("utterance_id", "seed_group_id", "group_kind", "text")}
        rec.update(
            language=r["language"],
            variant=r["variant"],
            intent=r["intent"],
            **{f"slot_{s}": r["slots"].get(s) for s in SLOTS},
            split=split_of[r["seed_group_id"]],
            leak_group=component[r["seed_group_id"]],
            is_seed=r["is_seed"],
            topic=r.get("topic"),
            origin=ORIGIN,
            authoring=AUTHORING,
            author_model=AUTHOR_MODEL,
            human_reviewed=False,
            dataset_version=DATASET_VERSION,
            source_file=r["source_file"],
        )
        records.append(rec)
    schema = {c: pl.Utf8 for c in records[0]}
    schema.update(is_seed=pl.Boolean, human_reviewed=pl.Boolean)
    return pl.DataFrame(records, schema=schema)


def fixture_sample(df: pl.DataFrame) -> pl.DataFrame:
    seeds = df.filter(pl.col("group_kind") == "seed")
    parts = [
        g.sample(n=min(FIXTURE_PER_INTENT_VARIANT, g.height), seed=SPLIT_SEED)
        for _, g in seeds.group_by(["intent", "variant"], maintain_order=True)
    ]
    for kind in ("pt_native", "hard_negative", "guide"):
        sub = df.filter(pl.col("group_kind") == kind)
        parts.append(sub.sample(n=min(8, sub.height), seed=SPLIT_SEED))
    return pl.concat(parts).sort(["intent", "variant", "utterance_id"])


def label_quality_sample(df: pl.DataFrame) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Blind sample (text only) and its key. Guide rows are excluded: annotators know them."""
    rng = np.random.default_rng(SPLIT_SEED + 1)
    pool = df.filter(pl.col("group_kind") != "guide")
    per_variant = LABEL_SAMPLE_SIZE // len(VARIANTS)
    hn = pool.filter(pl.col("group_kind") == "hard_negative")
    hn_ids = rng.choice(
        hn["utterance_id"].to_numpy(), LABEL_SAMPLE_MIN_HARD_NEGATIVES, replace=False
    )
    chosen = set(hn_ids.tolist())
    for variant in VARIANTS:
        have = pool.filter(
            pl.col("utterance_id").is_in(list(chosen)) & (pl.col("variant") == variant)
        ).height
        rest = pool.filter(
            (pl.col("variant") == variant)
            & ~pl.col("utterance_id").is_in(list(chosen))
            & (pl.col("group_kind") != "hard_negative")
        )
        need = max(per_variant - have, 0)
        # Spread over intents: round-robin over a shuffled per-intent pool.
        order = sorted(set(rest["intent"].to_list()))
        by_intent = {
            i: rng.permutation(
                rest.filter(pl.col("intent") == i)["utterance_id"].to_numpy()
            ).tolist()
            for i in order
        }
        k = 0
        while need > 0 and any(by_intent.values()):
            intent = order[k % len(order)]
            if by_intent[intent]:
                chosen.add(by_intent[intent].pop())
                need -= 1
            k += 1
    sample = pool.filter(pl.col("utterance_id").is_in(list(chosen)))
    sample = sample.with_columns(
        pl.Series("order", rng.permutation(sample.height))
    ).sort("order")
    sample = sample.with_columns(
        pl.format(
            "LQ-{}", pl.int_range(1, sample.height + 1).cast(pl.Utf8).str.zfill(3)
        ).alias("sample_id")
    )
    blind = sample.select(
        "sample_id",
        "variant",
        "text",
        pl.lit("").alias("intent_label"),
        *[pl.lit("").alias(f"{s}_label") for s in SLOTS],
        pl.lit("").alias("annotator"),
    )
    key = sample.select(
        "sample_id", "utterance_id", "group_kind", "intent", *SLOT_COLUMNS
    )
    return blind, key


def build(
    corpus_dir: Path = CORPUS_DIR, out_dir: Path = OUT_DIR, fixture: Path = FIXTURE_PATH
):
    rows = load_corpus(corpus_dir)
    errors = validate(rows)
    if errors:
        raise SystemExit("Corpus validation failed:\n" + "\n".join(errors[:200]))
    texts = [r["text"] for r in rows]
    groups = [r["seed_group_id"] for r in rows]
    pairs = near_duplicate_pairs(texts, groups)
    component = _components(groups, pairs)
    locked = load_split_locks(corpus_dir)
    split_of = assign_splits(rows, component, locked)
    df = to_frame(rows, split_of, component)
    new_groups = sorted(set(groups) - set(locked))
    locked_components = {component[g] for g in locked if g in component}
    leaks = cross_split_leaks(df)
    merged = Counter(component.values())
    report = {
        "dataset_version": DATASET_VERSION,
        "rows": df.height,
        "groups": df["seed_group_id"].n_unique(),
        "near_duplicate_pairs_across_groups": len(pairs),
        "near_duplicate_examples": [
            {"a": texts[i], "b": texts[j], "distance": round(d, 3)}
            for i, j, d in pairs[:50]
        ],
        "groups_merged": sum(n for n in merged.values() if n > 1),
        "locked_groups": len(set(groups) & set(locked)),
        "new_groups": len(new_groups),
        "new_groups_by_split": dict(Counter(split_of[g] for g in new_groups)),
        "new_groups_inheriting_a_locked_split": [
            g for g in new_groups if component[g] in locked_components
        ],
        "components_with_merges": sum(1 for n in merged.values() if n > 1),
        **leaks,
        "counts": {
            "by_split": dict(Counter(df["split"].to_list())),
            "by_kind": dict(Counter(df["group_kind"].to_list())),
            "by_variant_split": {
                f"{v}|{s}": n
                for (v, s), n in Counter(zip(df["variant"], df["split"])).items()
            },
            "groups_by_split": dict(
                Counter(df.unique("seed_group_id")["split"].to_list())
            ),
            "by_intent_split": {
                f"{i}|{s}": n
                for (i, s), n in Counter(zip(df["intent"], df["split"])).items()
            },
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out_dir / "utterances.parquet")
    (out_dir / "build_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    # The blind sample is drawn from the groups of the first locked version only, so adding
    # groups never changes a sample the annotators may already be labeling.
    lq_pool = df.filter(pl.col("seed_group_id").is_in(list(locked))) if locked else df
    blind, key = label_quality_sample(lq_pool)
    blind.write_csv(out_dir / "label_quality_sample.csv")
    key.write_csv(out_dir / "label_quality_key.csv")
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture_sample(df).write_csv(fixture)
    return df, report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="validate only, write nothing"
    )
    args = parser.parse_args(argv)
    if args.check:
        rows = load_corpus()
        errors = validate(rows)
        print("\n".join(errors) if errors else f"ok: {len(rows)} utterances")  # noqa: T201
        raise SystemExit(1 if errors else 0)
    df, report = build()
    summary = {
        k: v
        for k, v in report.items()
        if k not in ("near_duplicate_examples", "counts")
    }
    print(json.dumps(summary, indent=2))  # noqa: T201
    print(json.dumps(report["counts"]["by_split"]))  # noqa: T201


if __name__ == "__main__":
    main()
