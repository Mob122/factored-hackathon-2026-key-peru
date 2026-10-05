# NLU utterance corpus (source)

Team-generated, LLM-assisted utterances for the intent and slot classifier
(`docs/eval_plan.md` section 8, `docs/intents.md` `intents-1.0`). **These are not customer
messages.** Every utterance was written by an LLM (Claude Opus 5.5, prompted by the team) and has
**not yet been reviewed by a person for label preservation** (`human_reviewed = false` on every
row). The regional variants and the Portuguese measure our writing of those languages, not real
customers.

`python -m banking_cs.nlu.dataset` (run from `ml/`) validates these files and writes
`ml/data/nlu/utterances.parquet` (git-ignored) with the split column.

## Files

| File | Content | Split |
|---|---|---|
| `<intent>.yaml` (12 files) | 40 seed groups per intent; each group has 2 utterances in each of `es-MX`, `es-CO`, `es-AR`, `pt-BR` | 60 / 20 / 20 by group, stratified by intent |
| `guide.yaml` | The 144 examples of `docs/intents.md` section 4, one group per intent and variant | train only |
| `hard_negatives.yaml` | The 36 rows of `docs/intents.md` section 5, each with 2 paraphrases in the same variant | train only |
| `pt_native.yaml` | Portuguese written directly in Portuguese, not parallel to any Spanish seed | test only |

A **seed group** is one meaning with all its paraphrases and translations; no group is split
across train, calibration and test.

## Format

```yaml
intent: balance_inquiry
groups:
  - id: bal-001
    slots: {product_kind: credit_card, balance_item: balance}
    es-MX:
      - "¿Cuál es el saldo de mi tarjeta de crédito?"
      - {text: "¿Cuánto debo?", slots: {product_kind: null}}
```

Group `slots` apply to every utterance of the group. An utterance written as a mapping overrides
them (`null` removes a slot). `guide.yaml`, `hard_negatives.yaml` and `pt_native.yaml` set
`intent` per group.

## Slot conventions

Canonical values are the ones documented in `src/banking_cs/nlu/rules.py`. Labels follow the
labeling guide (`docs/intents.md` section 3), and in particular rule 9 (slots as typed):

- Only the slots the intent takes (`docs/intents.md` section 1) are labeled. `out_of_scope`,
  `human_request` and `conversation_end` have no slots.
- `product_kind`: `card` for any untyped card mention ("tarjeta", "tarjetas", "plástico",
  "cartão"); `credit_card` or `debit_card` only when the type is said ("la de crédito" counts);
  account types only when named. "Mi cuenta" alone and "fatura" alone are left empty.
- `balance_item` is set on every `balance_inquiry` row (`balance` when the customer asks a
  balance or an amount owed).
- `merchant` is a named merchant as typed (capitalized, as in the transactions table: "Uber",
  "Farmacia Salud"). A generic place ("el súper", "la farmacia", "a loja") is not a merchant.
- `amount` is `"<number> <currency>"` with no thousands separators: `USD` for dólares/US$,
  `PESO` for pesos or lucas without a country, `COP`/`ARS`/`MXN` only when the customer names the
  country's currency, and no currency for a bare number or "$". "20 lucas" is `20000 PESO`.
- `date` is the canonical relative or absolute form (`yesterday`, `last_week`, `month:05`,
  `since:06-01`, `last_n_days:15`, ...).
- `tx_status` only when the customer states the status ("rechazada", "pendiente", "estornada").
