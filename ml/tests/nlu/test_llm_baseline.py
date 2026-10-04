"""LLM baseline plumbing with a fake client (no network, no API key)."""

from types import SimpleNamespace

from banking_cs.nlu import llm_baseline


class FakeCompletions:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        assert kwargs["model"] == llm_baseline.MODEL
        assert kwargs["temperature"] == 0
        text = kwargs["messages"][-1]["content"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.answers[text]))
            ],
            usage=SimpleNamespace(prompt_tokens=400, completion_tokens=8),
        )


def fake_client(answers):
    return SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions(answers)))


def test_parses_validates_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_baseline, "CACHE_PATH", tmp_path / "cache.jsonl")
    answers = {
        "Hola": '{"intent": "out_of_scope"}',
        "Perdí la tarjeta": '{"intent": "card_block"}',
        "raro": '{"intent": "not_an_intent"}',
        "roto": "not json",
    }
    client = fake_client(answers)
    texts = ["Hola", "Perdí la tarjeta", "raro", "roto", "Hola"]
    results = llm_baseline.classify_all(client, texts, {})
    assert [r["intent"] for r in results] == [
        "out_of_scope",
        "card_block",
        None,
        None,
        "out_of_scope",
    ]
    assert client.chat.completions.calls == 4  # duplicates are sent once
    # A second run reads every answer from the cache and calls nothing.
    client2 = fake_client(answers)
    cache = llm_baseline.load_cache()
    again = llm_baseline.classify_all(client2, texts, cache)
    assert client2.chat.completions.calls == 0
    assert [r["intent"] for r in again] == [r["intent"] for r in results]


def test_cost_at_list_price():
    assert llm_baseline.cost_usd(1_000_000, 1_000_000) == (
        llm_baseline.PRICE_INPUT_PER_M + llm_baseline.PRICE_OUTPUT_PER_M
    )


def test_prompt_lists_every_intent():
    for intent in llm_baseline.DEFINITIONS:
        assert f"- {intent}:" in llm_baseline.SYSTEM_PROMPT
    assert set(llm_baseline.DEFINITIONS) == set(llm_baseline.INTENTS)
