# Model card: intent and slot classifier

| Field | Value |
|---|---|
| Card version | `model-card-intent-0.3`, 2026-10-04 (0.2: 2026-10-04; 0.1: 2026-10-03) |
| Status | **Provisional.** The utterances have still not been reviewed by a person (eval plan 8.1), and the label-quality sample is not labeled (C7). The test split was **rescored** after training data was added on the basis of test errors (section 3.2). |
| Owner | Aldair |
| Deployed artifact | `ml/artifacts/nlu/model.joblib` (TF-IDF + logistic regression), SHA-256 `a03e2969febf16b860e87d4020f01b6ab0a3be99f4325191a60bb6b8d6969c82`, scikit-learn 1.9.1 |
| Conformal | `ml/artifacts/nlu/conformal.json`: split conformal, **LAC** (`docs/eval_plan.md` 8.4, amendment 0.3), `CONFORMAL_ALPHA` = 0.10, threshold 0.6684, `CONFORMAL_MAX_SET` = 2; APS kept as an alternative. Runtime safety overrides: block and dispute (section 8.3) |
| Training code | `ml/src/banking_cs/nlu/`, commit `f053468` (recorded in `metadata.json`) |
| Data | `nlu-utt-0.2`, corpus SHA-256 `70d8a62b…` (`ml/nlu_corpus/`, 4,444 utterances) |
| Taxonomy, plan, policy | `docs/intents.md` `intents-1.0` · `docs/eval_plan.md` `eval-plan-0.3` sections 8 and 9.2 · `docs/policy_cards.md` `cards-synthetic-0.6` POL-ESC-06, POL-ESC-13, POL-ACT-12 |
| Decisions | `docs/decisions_log.md` D-01 to D-16 |
| Full results | `ml/artifacts/nlu/eval_results.json`, `ml/artifacts/nlu/llm_baseline.json` |

Every number here is an **offline result on team-generated, synthetic messages**. None of it is a
measurement on real customers.

## 0. Summary

**Card 0.3 (2026-10-04).** A dispute safety override joins the block override in `predict()`:
on dispute or fraud wording, `charge_dispute` is added to the conformal set, so a lone
`card_block` becomes a clarifying question. With both overrides, false `card_block`
singletons on test fall from **7 to 3** (calibration: 1 to 1). C6 is still not met (section
8.4). Policy 0.6 adds POL-ACT-12: after a verified block whose request carried theft or fraud
wording, the assistant invites the customer to name charges they do not recognize. The
classifier was retrained on the same data; every metric outside the overrides is identical
to card 0.2.

### 0.1 What changed since card 0.1

1. **Conformal score: APS → LAC** for the deployed model. This is an eval-plan amendment
   (0.3), decided after the APS result was seen and before held-out A, and justified from the
   calibration split alone (section 8.1).
2. **35 seed groups added** (`nlu-utt-0.2`) for the meanings missed in card 0.1: freeze,
   travar, report stolen, lost card, and card delivery, app login and phone top-up (out of
   scope). The test split was **rescored** (section 3.2).
3. **Block safety override** in `predict()`: when the rules see a block or theft request,
   `card_block` is added to the conformal set (section 8.3).
4. **Policy:** a set of exactly {`out_of_scope`} now offers a human handoff (POL-ESC-13,
   template POL-HND-08).
5. **LLM zero-shot baseline run** with gpt-4o-mini on the test split (section 10).

### 0.2 Results

- **Deployed TF-IDF + LR:** test macro-F1 **0.919** [95% CI 0.885, 0.944] on the rescored
  test split (card 0.1: 0.889).
  - On the 824 test rows that existed in 0.1, it scores 0.913. The previous model scores 0.889
    on the same rows. The gain is optimistic, because the additions were chosen from these
    rows' errors.
  - The 56 new test rows are all correct.
- **Other models:**

  | Model | Test macro-F1 [95% CI] | Difference vs TF-IDF [95% CI] |
  |---|---|---|
  | e5 + LR (cross-validation winner, not deployed) | 0.949 [0.919, 0.969] | +0.030 [0.001, 0.064] |
  | gpt-4o-mini zero-shot | 0.933 [0.883, 0.968] | +0.014 [−0.038, 0.062], not distinguishable |
  | Rules | 0.826 | −0.093 |

- **Conformal (LAC, alpha 0.10):** coverage 0.920 (every variant ≥ 0.89), mean set size 1.00,
  95% singletons. **C4 and C5 are met.**
- **Override:** `card_block` coverage goes from 0.961 to **1.000** on test. It fires on 7
  messages, 4 of them block requests.
- **C6 not met:** the model alone gives 7 non-block messages a {`card_block`} singleton (0 in
  card 0.1). Four come from one charge-dispute group, "reportar un fraude…", that now resembles
  the new "reportar el robo" training wording. The dispute override (card 0.3) fixes those 4;
  3 remain (section 8.4).

## 1. Intended use

- **Use:** classify one customer message, already redacted (POL-PII-01), in `IDLE` into one of
  the 12 intents of `docs/intents.md`. The conformal set feeds POL-ESC-06:
  - one intent: act;
  - 2 intents: ask one clarifying question;
  - an empty set or more than 2: transfer.

  A set of exactly {`out_of_scope`} gets a handoff offer (POL-ESC-13). Slots narrow the
  eligible products and filters (POL-ANS-07).
- **Not for:** answers given in a waiting state (rule 7), injection or third-party detection,
  languages other than Spanish and Portuguese, or any decision without the policy layer. A label
  never authorizes an action: blocks still need step-up and confirmation (POL-ACT).
- **Runtime:** `from banking_cs.nlu.predict import predict` returns
  `predict(text) -> {intent_set, slots, scores, safety_override, signals}`.
  - `safety_override` lists the intents the overrides added (`[]`, `["card_block"]`,
    `["charge_dispute"]` or both), for the audit log. It was a boolean in card 0.2.
  - `signals` gives the rule signals `block_or_theft`, `theft` and `dispute_or_fraud`. The
    orchestrator keeps them with a pending block for POL-ACT-12.
  - `method="aps"` gives the APS set, and `override=False` turns the overrides off for
    evaluation.
  - Before unpickling, the loader checks the model's SHA-256 and the scikit-learn version. It
    has no Kedro import.

## 2. Data

### 2.1 Provenance

The utterances were **team-generated and LLM-assisted**. The team prompted Claude Opus 5.5
with the labeling guide (`docs/intents.md`). Every row carries `origin = team_generated`,
`authoring = llm_assisted` and `human_reviewed = false`.
- No row comes from the dataset's transcripts (Day 2, P4 and P5).
- The regional variants and the Portuguese measure how we wrote those languages, not how real
  customers write.
- The pt-native subset was written directly in Portuguese, but not by a native speaker.

### 2.2 Composition

| Part | Source | Groups | Rows | Split |
|---|---|---|---|---|
| Seed groups, `nlu-utt-0.1` | `ml/nlu_corpus/<intent>.yaml` | 480 (40 per intent) | 3,840 | 60 / 20 / 20 by group, frozen by the split lock |
| Seed groups added in `nlu-utt-0.2` | `card_block.yaml`, `out_of_scope.yaml` (`topic` field) | 35 (7 topics × 5) | 280 | 3 / 1 / 1 per topic |
| Labeling-guide examples | `guide.yaml` (verbatim from `docs/intents.md` section 4) | 48 | 144 | train only |
| Hard negatives | `hard_negatives.yaml` (section 5 verbatim + 2 paraphrases) | 36 | 108 | train only |
| pt-native | `pt_native.yaml` | 72 | 72 | test only |
| **Total** | | **671** | **4,444** | |

**The 0.2 topics** (decisions log D-03):

| Topic | Intent | Example | Groups |
|---|---|---|---|
| `freeze` | `card_block` | "Congelen mi tarjeta de crédito, no la voy a usar este mes." | 5 |
| `travar` | `card_block` | "Trava o cartão por um tempinho?" / "Quiero apagar mi tarjeta desde ya." | 5 |
| `report_stolen` | `card_block` | "Necesito levantar un reporte por robo de mi tarjeta." | 5 |
| `lost_card` | `card_block` | "Creo que perdí la tarjeta en el gimnasio." | 5 |
| `card_delivery` | `out_of_scope` | "¿Cómo rastreo el envío de mi tarjeta?" | 5 |
| `app_login` | `out_of_scope` | "Me bloquearon el usuario de la app por intentos fallidos." | 5 |
| `phone_topup` | `out_of_scope` | "Se me acabó el saldo del celular, ¿me ayudas a recargar?" | 5 |

The out-of-scope topics include deliberate traps: "saldo" for phone credit, "reposición" and
"segunda via" used to ask about a delivery, and "bloquearon" applied to an app user.

**Deviation from `docs/intents.md` section 6:** each seed has 2 utterances per variant, not 3
to 5 (team decision).

### 2.3 Labels

Same conventions as card 0.1:
- the 12 intents and 7 slots of `intents-1.0`;
- canonical slot values in `ml/src/banking_cs/nlu/rules.py`;
- corpus rules in `ml/nlu_corpus/README.md`.

The builder rejects slots the intent does not take, values outside the enums, `last4`,
merchant or amount values missing from the text, and duplicate texts.

### 2.4 Label quality (C7)

A blind sample of 100 utterances (25 per variant, 15 hard negatives) is in
`ml/data/nlu/label_quality_sample.csv`. It is unchanged in 0.2, because it is drawn from the
0.1 groups only. Kappa is **not evaluable** until both team members have labeled it.

## 3. Splits

### 3.1 Rules

- Groups are assigned whole. Guide and hard-negative groups go to train; pt-native groups go to
  test.
- The split of every `nlu-utt-0.1` group is frozen in
  `ml/nlu_corpus/locks/split_lock_nlu-utt-0.1.json`. Without new groups, the rebuild reproduces
  the 0.1 split exactly.
- New groups are split per (intent, topic) with their own seed: 3 train, 1 calibration and 1
  test per topic. None of them is a near-duplicate of an existing group.
- Model selection uses 5-fold `StratifiedGroupKFold` inside train. Calibration fits only the
  conformal threshold.

| Split | Rows | Groups | es-MX | es-CO | es-AR | pt-BR |
|---|---|---|---|---|---|---|
| Train | 2,732 | 394 | 707 | 683 | 671 | 671 |
| Calibration | 832 | 104 | 208 | 208 | 208 | 208 |
| Test | 880 | 173 | 202 | 202 | 202 | 274 (202 translated + 72 native) |

### 3.2 The test split was rescored

Card 0.1 scored the test split once. The 35 groups added in 0.2 were chosen **because** of
test errors (card 0.1 section 6), and the test split was scored again (eval plan 8.2,
deviation 0.3). To keep the result readable, section 6 reports:
- the full rescored split (880 rows);
- the **824 rows of 0.1**: the same rows as before, scored by the new model and by the
  previous model;
- the **56 new rows**: one test group per new topic, written in the same pass as the training
  groups.

The gain on the 824 earlier rows is **optimistic**: it is a gain on errors we looked at. The 56
new rows are fresh groups, but the same author wrote them together with their training
neighbors.

## 4. Leakage controls and checks

| Control | Result |
|---|---|
| Near-duplicates (normalized edit distance < 0.1) are merged before splitting | 23 pairs, 35 groups in 16 components; no new group merged |
| Exact and near-duplicate pairs across splits (target 0) | **0 and 0** |
| Guide and hard negatives in train only; pt-native in test only | Enforced by the builder; tested |
| Split lock | Every 0.1 group keeps its split; tested |
| CV folds grouped by merged component | Yes |
| Features | Utterance text only |
| Golden conversations (dev set) kept out of the dataset | Yes; 6 of 27 golden turns are near-duplicates of train rows |
| Rules baseline frozen before the data | `rules.classify` unchanged since `fb05246`. The 0.2 safety detector is a separate function and does not affect the baseline |
| **Test-set reuse** | The 0.2 additions were chosen from test errors (section 3.2) |

**Remaining leak (not controllable here):** one author, a single LLM, wrote both train and
test.

## 5. Model selection (train only)

Cross-validated macro-F1 (5 folds, mean ± sd):

| Family | Best configuration | CV macro-F1 | Card 0.1 |
|---|---|---|---|
| Majority class | — | 0.017 | 0.014 |
| Rules | — | 0.843 ± 0.022 | 0.847 |
| TF-IDF + LR | C = 10 | 0.891 ± 0.036 | 0.902 |
| mpnet + LR | C = 10 | 0.889 ± 0.031 | 0.873 |
| multilingual-e5-base + LR | C = 300 | **0.933 ± 0.006** | 0.926 |

The other TF-IDF settings scored 0.882 (C = 1), 0.889 (3), 0.890 (30) and 0.885 (100).

- **CV winner:** e5 + LR again. **Deployed:** TF-IDF + LR, the team decision for size and
  latency (section 9).
- TF-IDF's CV score fell slightly. The new card_block and out_of_scope wordings are harder to
  separate with n-grams within train folds.

## 6. Test results

### 6.1 Rescored test split (880 rows)

| Model | All | Spanish (606) | Portuguese (274) | pt translated (202) | pt-native (72) | Accuracy |
|---|---|---|---|---|---|---|
| Majority class | 0.017 | 0.018 | 0.016 | 0.018 | 0.013 | 0.116 |
| Rules | 0.826 [0.768, 0.863] | 0.843 | 0.786 | 0.824 | 0.662 | 0.791 |
| **TF-IDF + LR (deployed)** | **0.919 [0.885, 0.944]** | 0.928 [0.887, 0.956] | 0.898 [0.854, 0.931] | 0.896 | 0.902 [0.812, 0.961] | 0.918 |
| mpnet + LR | 0.911 [0.871, 0.940] | 0.914 | 0.907 | 0.892 | 0.942 | 0.911 |
| e5 + LR (CV winner) | 0.949 [0.919, 0.969] | 0.954 [0.919, 0.975] | 0.938 [0.898, 0.968] | 0.934 | 0.944 | 0.949 |
| gpt-4o-mini zero-shot | 0.933 [0.883, 0.968] | 0.929 [0.869, 0.969] | 0.941 [0.901, 0.971] | 0.936 | 0.957 | 0.933 |

**By variant (macro-F1):**

| Model | es-MX | es-CO | es-AR | pt-BR |
|---|---|---|---|---|
| Rules | 0.847 | 0.839 | 0.839 | 0.786 |
| TF-IDF + LR | 0.937 | 0.935 | 0.913 | 0.898 |
| mpnet + LR | 0.891 | 0.926 | 0.923 | 0.907 |
| e5 + LR | 0.960 | 0.952 | 0.949 | 0.938 |
| gpt-4o-mini | 0.926 | 0.930 | 0.931 | 0.941 |

**Paired bootstrap of the macro-F1 difference:**

| Comparison | Difference | 95% interval |
|---|---|---|
| TF-IDF − majority | +0.902 | [0.866, 0.928] |
| TF-IDF − rules | +0.093 | [0.051, 0.142] |
| TF-IDF − mpnet | +0.008 | [−0.033, 0.049] |
| e5 − TF-IDF | +0.030 | [0.001, 0.064] |
| TF-IDF − gpt-4o-mini | −0.014 | [−0.062, 0.038] |

### 6.2 Same rows as card 0.1, and the new rows

The "previous" model is the 0.1 artifact (`2752575`), scored on the same rows:

| Rows | Metric | Previous TF-IDF (0.1) | TF-IDF (0.2) | e5 (0.2) |
|---|---|---|---|---|
| 824 rows of 0.1 | macro-F1 | 0.889 | 0.913 | 0.945 |
| 824 rows of 0.1 | `card_block` recall | 0.757 | 0.929 | 0.971 |
| 56 new rows | accuracy | 0.768 | 1.000 | 1.000 |

**Accuracy on the test groups card 0.1 flagged:**

| Topic | Group | Previous | TF-IDF (0.2) |
|---|---|---|---|
| freeze | `blk-008` "congelar la tarjeta" (8 rows) | 0.00 | 1.00 |
| travar | `ptn-blk-3` "Quero travar meu cartão…" | 0.00 | 1.00 |
| report stolen | `blk-018` "reportar como robada" (8 rows) | 0.25 | 0.75 |
| lost card | `ptn-blk-2` "Esqueci o cartão no caixa…" | 0.00 | 0.00 |
| card delivery | `oos-030` (8 rows) | 0.13 | 0.75 |
| app login | `oos-013` (8 rows) | 0.50 | 0.88 |
| phone top-up | `oos-031` (8 rows) | 0.63 | 1.00 |

### 6.3 By intent and errors

**F1 per intent:**

| Intent | TF-IDF | e5 | gpt-4o-mini | | Intent | TF-IDF | e5 | gpt-4o-mini |
|---|---|---|---|---|---|---|---|---|
| balance_inquiry | 0.968 | 0.929 | 0.947 | | charge_dispute | 0.865 | 0.963 | 0.921 |
| card_list | 0.950 | 0.949 | 0.931 | | block_reason | 0.930 | 0.986 | 0.966 |
| card_status | 0.890 | 0.942 | 0.886 | | card_unblock | 0.880 | 0.923 | 0.947 |
| transaction_list | 0.934 | 0.964 | 0.986 | | human_request | 0.963 | 0.978 | 0.875 |
| transaction_detail | 0.877 | 0.900 | 0.923 | | conversation_end | 0.955 | 0.964 | 1.000 |
| card_block | 0.933 | 0.957 | 0.995 | | out_of_scope | 0.883 | 0.931 | 0.818 |

**`card_block`:**

| Model | Precision | Recall |
|---|---|---|
| TF-IDF | 0.915 | 0.951 |
| e5 | 0.935 | 0.980 |
| gpt-4o-mini | 1.000 | 0.990 |

For TF-IDF, recall rose from 0.757 in card 0.1 and precision fell from 1.00. The new block
wording also pulls some charge disputes into `card_block` (section 8.4).

**Top confusions (TF-IDF):** transaction_detail → charge_dispute (8), human_request →
out_of_scope (5), conversation_end → out_of_scope (5), card_status → card_unblock (4),
charge_dispute → card_block (4), card_unblock → block_reason (4).

**Golden turns** (27, dev set, not held out):

| Model | Correct |
|---|---|
| Rules | 26 (circular: the rules were written against these turns) |
| TF-IDF | 25 |
| e5 | 24 |
| mpnet | 24 |

Every model misses the elliptical "E o do cartão de crédito?". The learned models read "¿Y
antes de eso? Creo que me rechazaron algo." as `transaction_detail`.

**Slots** (the rule extractor given the gold intent, 777 gold values on the test split):

| Slot | F1 |
|---|---|
| product_kind | 0.999 |
| last4 | 1.000 |
| date | 0.993 |
| amount | 1.000 |
| merchant | 0.863 (recall 0.76) |
| tx_status | 0.985 |
| balance_item | 0.887 |
| **All** | **0.980** |

## 7. Representations and metrics

- **TF-IDF with char n-grams** absorbs accents, voseo and typos and runs in 1.6 ms.
- **Sentence embeddings** share meaning across Spanish and Portuguese. Their largest gains over
  TF-IDF are on `charge_dispute` (+0.10 F1), `out_of_scope` (+0.05) and `block_reason` (+0.06).
- **gpt-4o-mini zero-shot** needs no training data. It is the most accurate on `card_block` and
  the weakest on `out_of_scope` (recall 0.69): it routes unsupported requests to the closest
  supported intent, which is exactly the error POL-GEN-04 guards against.
- **Metrics:** macro-F1 is primary, and coverage and set size measure what POL-ESC-06 consumes.

## 8. Conformal sets and the safety override

### 8.1 The amendment: APS → LAC (eval plan 0.3)

- **Card 0.1 result (pre-registered APS):** coverage 1.000, mean set size 7.7, 6.7% singletons.
  89% of messages would have been transferred.
- **The decision:** LAC for the deployed model, recorded in `docs/eval_plan.md` 8.4.
- **Calibration-only cross-fit it rests on (`nlu-utt-0.1`):**

  | Score | Coverage | Mean set size | Singletons |
  |---|---|---|---|
  | APS | 1.000 | 7.4 | 10.5% |
  | LAC | 0.902 | 1.11 | 87.5% |

- **Disclosure:** decided after the APS test result, before held-out A. `CONFORMAL_ALPHA`
  (0.10), `CONFORMAL_MAX_SET` (2), the targets and the Mondrian fallback are unchanged.
  `CONFORMAL_ALPHA` = 0.10 is the final value for `docs/policy_cards.md` section 11.

### 8.2 Results on the rescored test split (`nlu-utt-0.2`, 832 calibration rows)

| Model, score | Threshold | Coverage | Mean set size | Size 1 | Size 2 | Empty or > 2 | False `card_block` singletons |
|---|---|---|---|---|---|---|---|
| **TF-IDF, LAC (deployed)** | 0.6684 (p ≥ 0.332) | **0.920** | **1.00** | **94.8%** | 2.6% | 2.6% (empty) | **7** |
| TF-IDF, APS | 0.9889 | 1.000 | 7.25 | 6.9% | 5.1% | 88.0% | 0 |
| e5, LAC | 0.4407 | 0.931 | 0.97 | 96.6% | 0.0% | 3.4% (empty) | 6 |
| e5, APS | 0.9992 | 1.000 | 5.22 | 8.1% | 13.5% | 78.4% | 0 |

**TF-IDF with LAC by slice:**
- Coverage by variant: es-MX 0.946, es-CO 0.931, es-AR 0.926, pt-BR 0.890; pt-native 0.861.
- Coverage by language: Spanish 0.934, Portuguese 0.890.
- Mondrian fallback: not triggered, because no variant is below 0.85.
- Coverage per intent is lowest for transaction_detail (0.843), charge_dispute (0.886) and
  conversation_end (0.886); `card_block` is at 0.961.
- Calibration-only cross-fit on 0.2: coverage 0.905, mean size 1.03, 90.8% singletons.

**Alpha sweep (TF-IDF with LAC, test):**

| Alpha | Coverage | Mean set size | Singletons |
|---|---|---|---|
| 0.02 | 0.982 | 1.33 | 74% |
| 0.05 | 0.971 | 1.15 | 86% |
| 0.10 | 0.920 | 1.00 | 95% |
| 0.15 | 0.882 | 0.94 | 93% |
| 0.20 | 0.859 | 0.90 | 90% |

### 8.3 Safety overrides

Two rule-based overrides adjust the conformal set after it is computed. Neither applies when the
set holds `human_request` (POL-ESC-09). Both detectors are separate from the frozen rules
baseline.

**Block override (card 0.2).**

`rules.block_signal` detects requests to block, freeze ("congelar", "travar", "apagar la
tarjeta", "pausar"), and reports of loss or theft. When it fires and the set lacks `card_block`,
`predict()` adds `card_block`:
- a singleton of another intent becomes a clarifying question (POL-ESC-06: no action until the
  customer clarifies);
- an empty set becomes {top intent, `card_block`}, or {`card_block`} when card_block is the top
  intent (the block flow still asks for confirmation, POL-ACT-02).

The override is never applied when the set holds `human_request` (POL-ESC-09). The detector is
separate from the frozen rules baseline. It went through two versions (decisions log D-06).

**TF-IDF with LAC, with and without the override:**

| Split | Detector | `card_block` coverage, without → with | Overall coverage | Mean set size | Singletons | Fired (on block requests / others) | Singletons turned into a question | False `card_block` singletons |
|---|---|---|---|---|---|---|---|---|
| Calibration | v1 (designed before evaluation) | 0.865 → 0.979 | 0.901 → 0.915 | 1.023 → 1.037 | 91.0% → 90.0% | 11 (11 / 0) | 9 | 1 → 1 |
| Test | v1 | 0.961 → 0.990 | 0.920 → 0.924 | 1.000 → 1.009 | 94.8% → 93.9% | 8 (3 / 5) | 8 | 7 → 7 |
| Calibration | **v2 (deployed)** | 0.865 → **1.000** | 0.901 → 0.917 | 1.023 → 1.040 | 91.0% → 90.0% | 13 (13 / 0) | 10 | 1 → 1 |
| Test | **v2 (deployed)** | 0.961 → **1.000** | 0.920 → 0.925 | 1.000 → 1.009 | 94.8% → 94.1% | 7 (4 / 3) | 6 | 7 → 7 |

- **What v2 changed:** it fixed verb forms v1 missed ("me apagan", "bloquéeme", "me bloquean",
  "bloqueo temporal", forgot-the-card cues). It also stopped reading Portuguese "robô" (robot) as
  Spanish "robo" (theft): that v1 error would have delayed transfers for "não quero falar com
  robô".
- **Read the v2 test row as post-hoc**, because the revision was made after seeing calibration
  and test misses. The v1 rows are the clean estimate.
- **Detector false positives:** it fires on 0.4% of non-block test messages, 1.5% of non-block
  train messages and none in calibration. On test these are an unblock ("…o cartão travou,
  quero desbloquear"), a dispute ("Clonaram meu cartão…") and a block-reason question ("Por que
  meu cartão de crédito foi travado?"). Each costs one clarifying question.
- **What it does not fix:** the override only adds `card_block`; it cannot remove a false
  {`card_block`} singleton (section 8.4).

**Dispute override (card 0.3, decisions log D-11).** `rules.dispute_signal` detects dispute or
fraud wording: the baseline's dispute patterns plus "fraude", "golpe", "estafa", "no
reconozco" or "não reconheço", "cobro que no hice", "contestar" with a charge word, "no
autorizado", "clonaron". When it fires and the set lacks `charge_dispute`, `predict()` adds
`charge_dispute` after the block override has run, with the same rules for singletons and
empty sets. A lone `card_block` with fraud wording therefore becomes a clarifying question,
instead of a block flow that would skip the dispute handoff (POL-ESC-01).

**TF-IDF with LAC: no override, block only (card 0.2), and block + dispute (card 0.3):**

| Split | Overrides | Coverage | Mean set size | Singletons | `card_block` coverage | `charge_dispute` coverage | False `card_block` singletons | Singletons turned into a question |
|---|---|---|---|---|---|---|---|---|
| Calibration | none | 0.901 | 1.023 | 91.0% | 0.865 | 0.891 | 1 | 0 |
| Calibration | block | 0.917 | 1.040 | 90.0% | 1.000 | 0.891 | 1 | 10 |
| Calibration | **block + dispute** | 0.922 | 1.053 | 88.7% | 1.000 | 0.953 | **1** | 21 |
| Test | none | 0.920 | 1.000 | 94.8% | 0.961 | 0.886 | 7 | 0 |
| Test | block | 0.925 | 1.009 | 94.1% | 1.000 | 0.886 | 7 | 6 |
| Test | **block + dispute** | 0.932 | 1.017 | 93.5% | 1.000 | 0.971 | **3** | 11 |

- **Where the dispute override fired:** on test, 6 times, all on dispute messages. On
  calibration, 11 times: 4 on dispute messages and 7 on block-reason questions such as "¿El
  bloqueo de la tarjeta fue por un intento de fraude?", each of which costs one question.
- **Signal statistics:** it catches 73% of test and 72% of calibration dispute messages. It
  fires on 0% of other test messages and 3.1% of other calibration messages; 16 of those are
  requests for a person, where the override is skipped anyway.
- **No set grows past `CONFORMAL_MAX_SET`** because of the two overrides together.
- **Read the test row as post-hoc.** The dispute detector was written after the 7 false
  singletons were seen, and its word list was chosen to cover them. The calibration rows,
  where false singletons stay at 1, are the clean view: that remaining calibration case,
  "¿Me dieron tarjeta de débito o no?", has no dispute wording.

### 8.4 C6: false `card_block` singletons

With LAC and no override, the TF-IDF model gives a {`card_block`} singleton to **7 non-block
test messages** (card 0.1: 0). The block override cannot remove any of them; the dispute
override (card 0.3) turns the 4 fraud reports into clarifying questions:

| Gold intent | Message | Rows | With both overrides |
|---|---|---|---|
| charge_dispute | "Quiero reportar / denunciar un fraude en la tarjeta terminada en 1188." (es and pt) | 4 | {`card_block`, `charge_dispute`}: clarifying question |
| card_unblock | "Achei o cartão, dá pra destravar?" | 1 | still {`card_block`} |
| block_reason | "¿La tarjeta se bloqueó por poner mal la clave?" | 1 | still {`card_block`} |
| transaction_list | "extrato do cartão" | 1 | still {`card_block`} |

**Cause:** the new "reportar / denunciar el robo" and "travar" training wording generalized to
fraud reports and to "destravar". The block flow asks for confirmation naming the card
(POL-ACT-02), so no block runs without a "yes". But a fraud report routed to the block flow
skips the dispute handoff (POL-ESC-01).

**Result:** **3** false `card_block` singletons remain on test (0.4% of 778 non-block
messages), so C6 is still not met. None of the three has dispute or fraud wording. Each would
reach a block confirmation prompt naming the card, which the customer can decline
(POL-ACT-02). Remaining fix: contrast seed groups for "destravar" → `card_unblock` and
"se bloqueó por…" → `block_reason`, plus a retrain. No override can remove them, because
both overrides only add intents.

## 9. Accuracy versus size and latency (CV winner not deployed)

| | TF-IDF + LR (deployed) | e5 + LR (CV winner) |
|---|---|---|
| Test macro-F1 | 0.919 [0.885, 0.944] | 0.949 [0.919, 0.969] (+0.030 [0.001, 0.064]) |
| Artifact | 1.5 MB | 1.13 GB encoder weights + head |
| CPU latency per message (p50 / p95) | 1.6 / 2.0 ms | 26.6 / 33.0 ms |
| Runtime dependencies | scikit-learn, numpy, scipy, joblib | + torch, transformers, sentence-transformers |
| False `card_block` singletons (LAC, model only, before the overrides) | 7 | 6 |

The accuracy gap narrowed from +0.038 to +0.030, and its lower bound is 0.001. e5 no longer
has a worse action-intent profile than TF-IDF: both have the dispute → block confusion. Size
and latency still favor TF-IDF for this prototype.

## 10. LLM zero-shot baseline (gpt-4o-mini)

- **Setup:** temperature 0 on the **test split only** (880 messages). The prompt is the 12
  intents with one-line definitions from `docs/intents.md` section 1 and the guide's precedence
  rule, with JSON output (prompt SHA-256 `2570605a…`).
- **Deviation:** gpt-4o-mini replaces the eval plan's "same model ID as the agents" (team
  decision).
- **Key:** read at runtime from `OPENAI_API_KEY` in `backend/.env`. Only that variable is
  loaded; the key is never printed, logged or stored (decisions log D-09).
- **Result:** macro-F1 **0.933** [0.883, 0.968], accuracy 0.933, Spanish 0.929, Portuguese
  0.941, pt-native 0.957. All 880 messages got a valid answer.
- **Paired with TF-IDF:** the difference is −0.014 [−0.062, 0.038], so the two can't be told
  apart. It is clearly better than the rules baseline.
- **Usage:** 320,993 input and 6,445 output tokens, about **US$0.052** at the assumed list
  prices ($0.15 / $0.60 per million tokens; check against current pricing).
- **Run notes:** the first run took 9.2 h of wall time (throttling) and left 8 calls failed. A
  rerun with a 30 s timeout sent only those 8 calls, because the others were cached.
- **Not a deployment candidate as is:** latency was not measured per call (the rerun's 8
  parallel calls took 0.9 s, against 1.6 ms for TF-IDF), and there is a network dependency and
  a per-message cost. Also, an LLM label would still need a calibrated set for POL-ESC-06.

## 11. Pre-registered classifier targets (eval plan 9.2), deployed model

| ID | Target | Result | Status |
|---|---|---|---|
| C1 | Chosen model beats TF-IDF + LR | CV winner e5: +0.030 [0.001, 0.064]. The deployed model is TF-IDF | **Met** for the CV winner (barely); not applicable to the deployed model |
| C2 | Macro-F1 ≥ 0.85 overall | 0.919 (lower bound 0.885) | **Met** (on a rescored split) |
| C3 | pt-BR ≥ Spanish − 0.05 | 0.898 vs 0.928 | **Met** |
| C4 | Coverage ≥ 0.90; every variant ≥ 0.85 | LAC 0.920; minimum variant pt-BR 0.890 | **Met** (amended score) |
| C5 | Mean set size ≤ 1.3; singletons ≥ 75% | LAC 1.00 and 94.8% (1.01 and 94.1% with the override) | **Met** (amended score; APS: not met) |
| C6 | 0 false singletons on `card_block` | 3 with both overrides (7 with the model alone or the block override only) | **Not met** (section 8.4) |
| C7 | Kappa ≥ 0.80 | Sample generated, not labeled | **Not evaluable** |

C4 and C5 are met only under the amended score (eval plan 0.3), and C2 to C5 are on a test split
that was rescored after targeted additions. Report them with both caveats.

## 12. Limitations

1. **Synthetic, single-author data.** One LLM wrote all utterances. Real messages will differ.
2. **Not reviewed by a person** (eval plan 8.1). After review, rerun `dataset`, `train_eval`
   and `llm_baseline`.
3. **Test-set reuse.** The 0.2 additions were chosen from test errors, so the gain on earlier
   test rows is optimistic (section 3.2). Held-out A is the clean test.
4. **Targeted additions shift errors.** They fixed the missed meanings but created the
   dispute → block confusion (section 8.4). Each further round of targeted data needs contrast
   groups on the neighboring intents.
5. **Post-hoc choices.** The LAC amendment, block detector v2 and the dispute detector were made
   after seeing results; all are disclosed. The clean estimates are block detector v1 and the
   calibration rows for the dispute override.
6. **Single-turn classifier.** Elliptical follow-ups need the orchestrator's context.
7. **Conformal guarantee is marginal and approximate.** Exchangeability holds at the group
   level (104 calibration groups). Per-intent coverage is not guaranteed (transaction_detail:
   0.84). LAC can return an empty set (2.6% of test messages), which POL-ESC-06 transfers.
8. **Probabilities are not calibrated.** Use the set, not raw scores.
9. **Rule-based slots.** Merchants are found only when capitalized after a preposition (recall
   0.76); amounts in words are missed.
10. **Determinism.** Two runs on identical data produced model files 2 bytes apart, with
    identical predictions and metrics (likely BLAS thread non-determinism). Verify artifacts by
    the SHA-256 in `metadata.json`.

## 13. Reproduction

From `ml/`, with the locked environment and the encoders in the local Hugging Face cache:

```sh
python -m banking_cs.nlu.dataset        # validate, split (with the lock), write data/nlu/ and the fixture
git show 2752575:ml/artifacts/nlu/model.joblib > data/nlu/model_nlu-utt-0.1.joblib
python -m banking_cs.nlu.train_eval --compare-to data/nlu/model_nlu-utt-0.1.joblib
python -m banking_cs.nlu.llm_baseline   # OPENAI_API_KEY from the environment or backend/.env
pytest tests/nlu
```

The backend needs `scikit-learn==1.9.1`, `numpy`, `scipy` and `joblib`, plus `ml/src` on the
import path. It never needs Kedro.
