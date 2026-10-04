"""LLM zero-shot intent baseline on the test split only (docs/eval_plan.md 8.3).

Run from ml/ after banking_cs.nlu.train_eval:
    python -m banking_cs.nlu.llm_baseline

Model gpt-4o-mini (team decision; the eval plan's "same model ID as the agents" is not used
here), temperature 0, the intent list with one-line definitions from docs/intents.md
section 1, JSON output. The API key is read from OPENAI_API_KEY by the OpenAI client; it is
never logged or written. If the key is not set, the baseline is recorded as "not run".

Responses are cached in data/nlu/llm_cache.jsonl (git-ignored), so a rerun does not bill the
test split twice. Token usage and cost at the list prices below are logged; the run stops
before starting if the projected cost exceeds MAX_USD. Writes artifacts/nlu/llm_baseline.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import polars as pl

from banking_cs.nlu import metrics
from banking_cs.nlu.dataset import OUT_DIR
from banking_cs.nlu.rules import INTENTS
from banking_cs.nlu.train_eval import ARTIFACT_DIR, DEPLOYED, N_BOOT, SEED, evaluate

MODEL = "gpt-4o-mini"
# USD per million tokens, OpenAI list price for gpt-4o-mini assumed at the time of writing.
PRICE_INPUT_PER_M = 0.15
PRICE_OUTPUT_PER_M = 0.60
MAX_USD = 1.0
EST_INPUT_TOKENS = 450
EST_OUTPUT_TOKENS = 12
WORKERS = 8
RETRIES = 4
CACHE_PATH = OUT_DIR / "llm_cache.jsonl"
FALLBACK = "out_of_scope"

DEFINITIONS = {
    "balance_inquiry": "asks for an amount held in or owed on one of their products: balance, credit limit, available credit, amount owed, minimum payment or due date",
    "card_list": "asks which cards they have",
    "card_status": "asks the current status of a card (active, blocked, suspended, closed)",
    "transaction_list": "wants to see transactions on a card, optionally filtered by date, amount, merchant or status",
    "transaction_detail": "asks what one transaction is, what its status or response code means, or why it was declined, pending or reversed",
    "card_block": "wants a card blocked now, or reports it lost or stolen",
    "charge_dispute": "says a charge is not theirs, is duplicated or wrong, or wants it reversed or refunded",
    "block_reason": "asks why or when a card was blocked or suspended",
    "card_unblock": "wants a card unblocked, reactivated or replaced",
    "human_request": "asks for a person, in any wording",
    "conversation_end": "closes the conversation with no new request",
    "out_of_scope": "any request no other intent covers, or a greeting with no request",
}
SYSTEM_PROMPT = (
    "You classify one customer message sent to a bank's card and account assistant into "
    "exactly one intent. Messages are in Spanish or Portuguese.\n\nIntents:\n"
    + "\n".join(f"- {k}: the customer {v}." for k, v in DEFINITIONS.items())
    + "\n\nIf the message holds several requests, choose by this precedence: human_request > "
    "charge_dispute > card_block > card_unblock > block_reason > the first read intent "
    "mentioned > conversation_end > out_of_scope.\n"
    'Answer with JSON only: {"intent": "<one intent name>"}.'
)
PROMPT_SHA = hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()


def _cache_key(text: str) -> str:
    return hashlib.sha256(f"{MODEL}|{PROMPT_SHA}|{text}".encode()).hexdigest()


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    rows = [
        json.loads(line)
        for line in CACHE_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]
    return {r["key"]: r for r in rows}


def classify_one(client, text: str) -> dict:
    """One API call with retries; returns intent, raw answer and token usage."""
    for attempt in range(RETRIES):
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": text},
                ],
            )
            raw = resp.choices[0].message.content or ""
            try:
                intent = json.loads(raw).get("intent")
            except (json.JSONDecodeError, AttributeError):
                intent = None
            return {
                "intent": intent if intent in INTENTS else None,
                "raw": raw[:200],
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - network or rate-limit errors are retried
            if attempt == RETRIES - 1:
                return {
                    "intent": None,
                    "raw": "",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "error": type(exc).__name__,
                }
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


def classify_all(client, texts: list[str], cache: dict) -> list[dict]:
    todo = [t for t in dict.fromkeys(texts) if _cache_key(t) not in cache]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        fresh = list(pool.map(lambda t: classify_one(client, t), todo))
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("a", encoding="utf-8") as f:
        for text, res in zip(todo, fresh):
            if res["error"] is None:
                row = {"key": _cache_key(text), **res}
                cache[row["key"]] = row
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    by_text = dict(zip(todo, fresh))
    return [cache.get(_cache_key(t)) or by_text[t] for t in texts]


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (
        input_tokens / 1e6 * PRICE_INPUT_PER_M
        + output_tokens / 1e6 * PRICE_OUTPUT_PER_M
    )


def main(client=None):
    out_path = ARTIFACT_DIR / "llm_baseline.json"
    base = {"model": MODEL, "split": "test", "prompt_sha256": PROMPT_SHA}
    if client is None and not os.environ.get("OPENAI_API_KEY"):
        out_path.write_text(
            json.dumps(
                {**base, "status": "not run", "reason": "OPENAI_API_KEY not set"},
                indent=1,
            )
        )
        print("LLM baseline not run: OPENAI_API_KEY not set")  # noqa: T201
        return
    df = pl.read_parquet(OUT_DIR / "utterances.parquet").filter(
        pl.col("split") == "test"
    )
    df = df.with_columns(
        pl.col("intent").map_elements(INTENTS.index, return_dtype=pl.Int64).alias("y")
    )
    cache = load_cache()
    texts = df["text"].to_list()
    uncached = sum(1 for t in dict.fromkeys(texts) if _cache_key(t) not in cache)
    projected = cost_usd(uncached * EST_INPUT_TOKENS, uncached * EST_OUTPUT_TOKENS)
    if projected > MAX_USD:
        raise SystemExit(
            f"projected cost ${projected:.2f} exceeds the ${MAX_USD:.2f} cap"
        )
    if client is None:
        from openai import OpenAI  # noqa: PLC0415

        client = OpenAI()
    start = time.perf_counter()
    results = classify_all(client, texts, cache)
    seconds = time.perf_counter() - start
    pred = np.array(
        [
            INTENTS.index(r["intent"]) if r["intent"] else INTENTS.index(FALLBACK)
            for r in results
        ]
    )
    groups = df["leak_group"].to_numpy()
    weights = metrics.resample_weights(len(np.unique(groups)), N_BOOT, SEED)
    report, boot = evaluate(df, pred, weights)
    paired = None
    preds_path = OUT_DIR / "test_predictions.parquet"
    if preds_path.exists():
        other = pl.read_parquet(preds_path)
        assert other["utterance_id"].to_list() == df["utterance_id"].to_list()
        dep_report, dep_boot = evaluate(
            df, other[f"pred_{DEPLOYED}"].to_numpy(), weights
        )
        paired = {
            "point": dep_report["macro_f1"] - report["macro_f1"],
            "ci95": metrics.interval(dep_boot - boot),
            "comparison": f"{DEPLOYED} minus {MODEL}",
        }
    input_tokens = sum(r["input_tokens"] for r in results)
    output_tokens = sum(r["output_tokens"] for r in results)
    summary = {
        **base,
        "status": "run",
        "n": len(texts),
        "invalid_or_failed": int(sum(1 for r in results if not r["intent"])),
        "invalid_mapped_to": FALLBACK,
        "usage_this_split": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd_at_list_price": round(cost_usd(input_tokens, output_tokens), 4),
            "price_per_million": {
                "input": PRICE_INPUT_PER_M,
                "output": PRICE_OUTPUT_PER_M,
            },
            "api_calls_this_run": uncached,
            "wall_seconds_this_run": round(seconds, 1),
        },
        "test": report,
        "paired_bootstrap": paired,
    }
    out_path.write_text(json.dumps(summary, indent=1, default=float))
    usage = summary["usage_this_split"]
    print("n", len(texts), "usage", usage)  # noqa: T201
    print("macro-F1", round(report["macro_f1"], 4))  # noqa: T201


if __name__ == "__main__":
    main()
