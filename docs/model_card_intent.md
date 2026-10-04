# Model card: intent and slot classifier

| Field | Value |
|---|---|
| Card version | `model-card-intent-0.1`, 2026-10-03 |
| Status | **Provisional.** The utterances have not been reviewed by a person (eval plan 8.1), the label-quality sample is not labeled yet (C7), and the LLM zero-shot baseline was not run (no API key). Every number below changes if labels change after review. |
| Owner | Aldair |
| Deployed artifact | `ml/artifacts/nlu/model.joblib` (TF-IDF + logistic regression), SHA-256 `7d123688fe5996cf7e466ec9db982a3741a4b1ebb72cad7151577abd8a1d7453`, scikit-learn 1.9.1 |
| Conformal | `ml/artifacts/nlu/conformal.json`: split conformal, APS (pre-registered), `CONFORMAL_ALPHA` = 0.10, threshold 0.9902, `CONFORMAL_MAX_SET` = 2 |
| Training code | `ml/src/banking_cs/nlu/`, commit `50d833b` (recorded in `metadata.json`) |
| Data | `nlu-utt-0.1`, corpus SHA-256 `3e0ea818…` (`ml/nlu_corpus/`, 4,164 utterances) |
| Taxonomy and plan | `docs/intents.md` `intents-1.0` · `docs/eval_plan.md` `eval-plan-0.2` sections 8 and 9.2 · `docs/policy_cards.md` POL-ESC-06 |
| Full results | `ml/artifacts/nlu/eval_results.json` |
| Requirements | `docs/requirements_matrix.md` D4-6 to D4-12 |

Every number here is an **offline result on team-generated, synthetic messages**. None of it is a
measurement on real customers.

## 0. Summary

- **Deployed model:** TF-IDF (word 1-2 grams + char 2-5 grams) + logistic regression. Test
  macro-F1 **0.889** [95% CI 0.840, 0.922]; Spanish 0.892, Portuguese 0.882.
- **Cross-validation winner:** multilingual-e5-base embeddings + logistic regression. Test
  macro-F1 0.927 [0.890, 0.955], +0.038 over TF-IDF [0.004, 0.075]. It is not deployed. TF-IDF
  is 1.4 MB and takes 1.6 ms per message on CPU; e5 needs 1.1 GB of weights, torch, and 25 ms.
  e5 also makes the error the policy cares most about: it labels charge disputes as
  `card_block` (section 9).
- **Rules baseline:** 0.827. The TF-IDF model beats it by +0.063 [0.009, 0.117].
- **Slots:** the rule extractor reaches micro-F1 0.979 on the test split. Merchant recall is
  0.76.
- **Conformal sets (pre-registered APS, alpha 0.10):** coverage 1.000, but the mean set size is
  7.7 and only 6.7% of sets are singletons. Under POL-ESC-06, 89% of messages would be
  transferred. Target C5 is **not met**. An exploratory LAC score, not pre-registered and
  chosen after seeing this result, gives coverage 0.925 with 91% singletons. Switching to it
  needs an amendment to the eval plan before held-out A (section 8.3).

## 1. Intended use

- **Use:** classify one customer message, already redacted (POL-PII-01), in `IDLE` into one of
  the 12 intents of `docs/intents.md`. The conformal set feeds POL-ESC-06: one intent means act,
  2 intents mean clarify, an empty set or more than 2 means transfer. Slots narrow the eligible
  products and filters (POL-ANS-07).
- **Not for:** answers given in a waiting state ("sí", "la de crédito"). The state machine
  parses those (`docs/intents.md` rule 7). Also not for injection or third-party detection
  (pipeline step 4), languages other than Spanish and Portuguese, or any decision without the
  policy layer. A label is never an authorization: blocks still need confirmation and step-up
  (POL-ACT).
- **Runtime:** `from banking_cs.nlu.predict import predict` returns
  `predict(text) -> {intent_set, slots, scores}`. The module has no Kedro import. Before
  unpickling, it checks the model's SHA-256 and the scikit-learn version.

## 2. Data

### 2.1 Provenance

The utterances were **team-generated and LLM-assisted**. The team prompted Claude Opus 5.5
with the labeling guide (`docs/intents.md`). Every row carries `origin = team_generated`,
`authoring = llm_assisted` and `human_reviewed = false`. The transcripts in the dataset give no
usable intent labels (Day 2, P4 and P5), so no row comes from them. The regional variants and
the Portuguese measure how we wrote those languages, not how real customers write (eval plan
3.3). The "pt-native" subset was written directly in Portuguese without a Spanish seed, but it
was not written by a native speaker.

### 2.2 Composition

| Part | Source file(s) | Groups | Rows | Split |
|---|---|---|---|---|
| Seed groups | `ml/nlu_corpus/<intent>.yaml` | 480 (40 per intent) | 3,840 (2 per variant per group) | 60 / 20 / 20 by group |
| Labeling-guide examples | `guide.yaml` (verbatim from `docs/intents.md` section 4) | 48 (intent × variant) | 144 | train only |
| Hard negatives | `hard_negatives.yaml` (section 5 verbatim + 2 paraphrases each) | 36 | 108 | train only |
| pt-native | `pt_native.yaml` | 72 (6 per intent) | 72 | test only |
| **Total** | | **636** | **4,164** | |

About a quarter of each intent's seed groups sit on the confusions of `docs/intents.md` section
5, worded differently from those rows. Examples: "Bloqueé la tarjeta por error, ¿la pueden
desbloquear?" (`card_unblock`), "¿Ya desbloquearon mi tarjeta?" (`card_status`), "Quiero
recargar saldo al celular" (`out_of_scope`). Because the hard-negative rows themselves are
train-only, these groups are how the test split measures the same confusions.

**Deviation from `docs/intents.md` section 6:** each seed has 2 utterances per variant, not 3
to 5. This was a team decision: more seed groups (40 per intent, against a minimum of 15) give
a better split and bootstrap than more paraphrases of one seed.

### 2.3 Labels

The labels are the 12 intents and 7 slots of `intents-1.0`, applied with the guide's rules.
Canonical slot values are documented in `ml/src/banking_cs/nlu/rules.py`, and the corpus
conventions in `ml/nlu_corpus/README.md`. The main conventions:
- `merchant` is set only for a named, capitalized merchant.
- `product_kind = card` for any card mention without a type.
- `balance_item` is set on every balance row.
- Amounts are canonical, for example `245300 PESO` or `75 USD`.

The builder (`python -m banking_cs.nlu.dataset`) rejects:
- a slot the intent does not take;
- a value outside the enums;
- a `last4`, merchant or amount that does not appear in the text;
- a duplicate text.

### 2.4 Label quality (C7)

A blind sample of **100** utterances, 25 per variant, including 15 hard negatives, is written
to `ml/data/nlu/label_quality_sample.csv`; its key is in `label_quality_key.csv`. The eval plan
asks for 200; 100 is a team decision. Guide examples are excluded because the annotators know
them. Both team members still have to label the sample independently. Kappa is **not
evaluable** until then.

## 3. Splits

- A **seed group** is one meaning with its paraphrases and translations. Groups are assigned
  whole: train / calibration / test = 60 / 20 / 20 of groups, stratified by intent, seed 2026.
- Guide and hard-negative groups are forced to train. pt-native groups are forced to test.
- Model and hyperparameter selection use 5-fold `StratifiedGroupKFold` inside train. The
  calibration split fits only the conformal threshold. The test split was scored once for
  selection purposes.
- The script was rerun twice after the first scoring with nothing about the models changed.
  The first rerun added the exploratory LAC section; the second recorded the commit hash. The
  intent results were byte-identical across the three runs.

| Split | Rows | Groups | es-MX | es-CO | es-AR | pt-BR | Seed groups per intent |
|---|---|---|---|---|---|---|---|
| Train | 2,564 | 373 | 665 | 641 | 629 | 629 | 23 to 26 (+ guide, hard negatives) |
| Calibration | 776 | 97 | 194 | 194 | 194 | 194 | 7 to 9 |
| Test | 824 | 166 | 188 | 188 | 188 | 260 (188 translated + 72 native) | 7 or 8 (+ 6 pt-native) |

## 4. Leakage controls and checks

| Control | Result |
|---|---|
| Near-duplicates (normalized edit distance < 0.1) across groups are merged **before** splitting, so a pair can never cross splits | 23 pairs merged 35 groups into 16 components. Some pairs have different labels ("Primero bloquee la tarjeta…" vs "Primero desbloquee…"); they stay together in one split |
| Exact and near-duplicate pairs across splits (eval plan 8.2, target 0) | **0 and 0** |
| Guide examples and hard negatives in train only; pt-native in test only | Enforced by the builder; tested |
| CV folds grouped by the merged component (`leak_group`) | Yes |
| Features | Utterance text only; no `main_topics`, `detected_intents` or `fraud_score` |
| Golden conversations (the dev set) kept out of the dataset | Yes (`ml/nlu_corpus/dev/`). 6 of the 27 golden turns are near-duplicates of train rows, so the golden slice is not held out |
| Rule baseline written before the data | `rules.py` committed at `fb05246`, before the corpus (`c4e8992`). It is tuned on the guide and the golden turns only |

**Remaining leak (not controllable here):** one author, a single LLM, wrote both train and
test. Phrasing habits are shared across splits in a way no split by seed group can remove.

## 5. Model selection

Cross-validated macro-F1 on train (5 folds of about 513 rows), mean ± sd over folds:

| Family | Best configuration | CV macro-F1 | Other configurations |
|---|---|---|---|
| Majority class | — | 0.014 ± 0.000 | — |
| Rules (`rules.py`) | — | 0.847 ± 0.031 | — |
| TF-IDF + LR | C = 10 | 0.902 ± 0.007 | C = 1: 0.894, 3: 0.899, 30: 0.900, 100: 0.899 |
| paraphrase-multilingual-mpnet-base-v2 + LR | C = 10 | 0.873 ± 0.039 | C = 3: 0.870, 30: 0.872 |
| multilingual-e5-base + LR | C = 300 | **0.926 ± 0.014** | C = 10: 0.919, 30: 0.924, 100: 0.925 |

- **CV winner (eval plan 8.3 rule):** e5 + LR. Its margin over TF-IDF is 0.024, above the 0.01
  tie margin.
- The e5 curve is flat for C ≥ 30, so its pick at the edge of the grid does not matter.
- The encoders are pinned to Hugging Face revisions `d1287505…` (e5) and `4328cf26…` (mpnet).
- **Deployed:** TF-IDF + LR, regardless of the CV winner. The team made this decision for size
  and latency before the test split was scored. Section 9 gives the trade-off.

## 6. Test results (scored once)

Macro-F1 with 95% intervals from 2,000 bootstrap resamples over test groups:

| Model | All (824) | Spanish (564) | Portuguese (260) | pt translated (188) | pt-native (72) | Accuracy |
|---|---|---|---|---|---|---|
| Majority class | 0.012 [0.005, 0.019] | 0.012 | 0.012 | 0.012 | 0.013 | 0.075 |
| Rules | 0.827 [0.774, 0.861] | 0.845 [0.784, 0.885] | 0.784 [0.719, 0.830] | 0.823 | 0.662 [0.514, 0.749] | 0.795 |
| **TF-IDF + LR (deployed)** | **0.889 [0.840, 0.922]** | 0.892 [0.838, 0.928] | 0.882 [0.834, 0.919] | 0.869 | 0.915 [0.824, 0.971] | 0.888 |
| mpnet + LR | 0.895 [0.850, 0.928] | 0.891 | 0.902 | 0.881 | 0.957 | 0.897 |
| e5 + LR (CV winner) | 0.927 [0.890, 0.955] | 0.935 [0.894, 0.965] | 0.910 [0.863, 0.948] | 0.897 | 0.945 | 0.927 |
| LLM zero-shot (gpt-4o-mini) | not run (section 10) | | | | | |

**By variant (macro-F1):**

| Model | es-MX | es-CO | es-AR | pt-BR |
|---|---|---|---|---|
| Rules | 0.852 | 0.839 | 0.841 | 0.784 |
| TF-IDF + LR | 0.894 | 0.898 | 0.885 | 0.882 |
| mpnet + LR | 0.877 | 0.896 | 0.899 | 0.902 |
| e5 + LR | 0.942 | 0.942 | 0.920 | 0.910 |

**Paired bootstrap of the macro-F1 difference:**

| Comparison | Difference | 95% interval |
|---|---|---|
| TF-IDF − majority | +0.878 | [0.829, 0.911] |
| TF-IDF − rules | +0.063 | [0.009, 0.117] |
| TF-IDF − mpnet | −0.006 | [−0.051, 0.038] |
| e5 − TF-IDF | +0.038 | [0.004, 0.075] |

**F1 per intent:**

| Intent | TF-IDF | e5 | | Intent | TF-IDF | e5 |
|---|---|---|---|---|---|---|
| balance_inquiry | 0.938 | 0.937 | | charge_dispute | 0.841 | 0.949 |
| card_list | 0.957 | 0.941 | | block_reason | 0.938 | 0.986 |
| card_status | 0.878 | 0.916 | | card_unblock | 0.809 | 0.904 |
| transaction_list | 0.934 | 0.956 | | human_request | 0.948 | 0.978 |
| transaction_detail | 0.877 | 0.909 | | conversation_end | 0.963 | 0.964 |
| card_block | 0.862 | 0.866 | | out_of_scope | 0.727 | 0.820 |

**Action intent (`card_block`):**
- TF-IDF: precision 1.00, recall 0.76.
- e5: precision 0.91, recall 0.83. It labels 4 charge disputes as blocks.

**Error analysis (TF-IDF).** Errors cluster in whole test groups whose meaning has no
counterpart in train:
- "congelar / travar la tarjeta" (a temporary block): all 8 missed, plus the pt-native
  "Quero travar meu cartão…";
- "reportar / denunciar la tarjeta como robada": 6 of 8, mostly predicted `out_of_scope`;
- card-delivery questions ("¿cuándo me llega la tarjeta nueva?"), which are `out_of_scope`:
  7 of 8 predicted as `card_unblock` or `card_status`;
- app-login problems, predicted as `charge_dispute`;
- "recargar saldo al celular", predicted as `balance_inquiry`.

The top confusions are transaction_detail → charge_dispute (8), card_block → out_of_scope (8)
and out_of_scope → card_unblock (7). The split works as intended: unseen meanings, not unseen
wording, drive the errors. The fix is coverage in the training data (section 12).

**Golden turns** (27 classifier inputs of the 12 golden conversations; dev set, not held out):

| Model | Correct |
|---|---|
| Rules | 26/27. This is circular: the rules were written against these turns |
| TF-IDF | 25/27 |
| mpnet | 24/27 |
| e5 | 23/27 |

- Every model misses the elliptical "E o do cartão de crédito?", whose intent comes from the
  previous turn.
- Every learned model reads "¿Y antes de eso? Creo que me rechazaron algo." as
  `transaction_detail`.
- e5 also labels dialogue 5's "No reconozco un cobro… Quiero reclamarlo." as `card_block`.

**Slots** (the rule extractor given the gold intent, test split, exact match of canonical
values):

| Slot | Gold values | Precision | Recall | F1 |
|---|---|---|---|---|
| product_kind | 423 | 1.000 | 0.998 | 0.999 |
| last4 | 46 | 1.000 | 1.000 | 1.000 |
| date | 72 | 1.000 | 0.986 | 0.993 |
| amount | 19 | 1.000 | 1.000 | 1.000 |
| merchant | 54 | 1.000 | 0.759 | 0.863 |
| tx_status | 69 | 1.000 | 0.971 | 0.985 |
| balance_item | 62 | 0.887 | 0.887 | 0.887 |
| **All** | 745 | 0.990 | 0.968 | 0.979 |

## 7. Representations and metrics (D4-9, D4-10)

- **Why TF-IDF with char n-grams:** they absorb accents, voseo endings ("bloqueá", "decime")
  and typos without a tokenizer per language. The model trains in seconds and is fully
  inspectable.
- **Why embeddings:** they share meaning across Spanish and Portuguese. The gains show where
  meaning matters more than keywords: `charge_dispute` (+0.11 F1), `card_unblock` (+0.10) and
  `out_of_scope` (+0.09).
- **Why macro-F1 is primary:** all 12 classes matter equally to routing, and the classes are
  balanced by design. Accuracy is shown next to it.
- **Coverage and set size** measure what POL-ESC-06 consumes: act, clarify or transfer.

## 8. Conformal prediction sets (D4-11)

### 8.1 Pre-registered: split conformal with the APS score, alpha 0.10

The method is deterministic, non-randomized APS. A set adds intents in descending probability
until their mass reaches the threshold, so it is never empty (`ml/src/banking_cs/nlu/conformal.py`).
The threshold is fit on the 776 calibration utterances.

| Model | Threshold | Coverage (test) | Mean set size | Size 1 (act) | Size 2 (clarify) | > 2 (transfer) | False `card_block` singletons |
|---|---|---|---|---|---|---|---|
| **TF-IDF (deployed)** | 0.9902 | **1.000** (every variant 1.000; pt-native 1.000) | **7.73** | **6.7%** | 4.5% | **88.8%** | 0 |
| e5 | 0.9993 | 1.000 | 5.43 | 7.8% | 12.5% | 79.7% | 0 |

- **Alpha sweep (TF-IDF, test):** for alpha = 0.02, 0.05, 0.10, 0.15, 0.20 the mean set sizes
  are 10.5, 9.3, 7.7, 6.7 and 5.5. Coverage is 1.000 at every alpha.
- **Calibration-only cross-fit:** fitting on half the calibration groups and testing on the
  other half gives coverage 1.000 and mean set size 7.4. The same conclusion is visible
  without the test split.
- **Mondrian fallback (8.4):** not triggered, because no variant is below 0.85.

**Why the sets are large:**
- 14% of calibration messages are misclassified, and many of those errors are confident. The
  APS score of such an example is the mass of every intent ranked at or above the true one,
  close to 1.
- The 90th percentile of the scores is therefore 0.990, and each set must hold 99% of the
  probability mass.
- TF-IDF + LR spreads its residual probability over all 12 intents (median top probability
  0.85), which takes 5 to 10 intents.
- This is a known weakness of APS with diffuse probabilities. It is not a coverage failure.

### 8.2 Exploratory, not pre-registered: LAC score

This analysis was added after the APS result was seen. LAC (Sadinle et al., 2019) uses the
score 1 − p(true intent); a set holds every intent whose probability is at least
1 − threshold, and it can be empty (POL-ESC-06 then transfers).

| Model | Threshold | Coverage | Mean set size | Size 1 | Size 2 | Empty | False `card_block` singletons |
|---|---|---|---|---|---|---|---|
| **TF-IDF** | 0.7436 (p ≥ 0.256) | **0.925** | **1.06** | **90.7%** | 7.5% | 1.8% | **0** |
| e5 | 0.4847 (p ≥ 0.515) | 0.909 | 0.96 | 96.2% | 0.0% | 3.8% | **4** |

- **TF-IDF LAC by slice:** coverage is es-MX 0.942, es-CO 0.936, es-AR 0.920, pt-BR 0.908,
  pt-native 0.917.
- **Per intent:** coverage is lowest for **card_block (0.771)** and out_of_scope (0.800). Under
  LAC, one in four block requests in this test set would not contain `card_block` (see 8.3).
- **Calibration-only cross-fit:** coverage 0.902, mean size 1.11, 87.5% singletons.
- **Alpha sweep:**

  | Alpha | Coverage | Mean set size | Singletons |
  |---|---|---|---|
  | 0.02 | 0.967 | 1.53 | 66% |
  | 0.05 | 0.954 | 1.29 | 77% |
  | 0.15 | 0.869 | 0.94 | 93% |
  | 0.20 | 0.829 | 0.88 | 88% |

### 8.3 What is exported, and the decision left to the team

- `conformal.json` holds the **pre-registered APS threshold as the default**. The LAC threshold
  is listed under `alternatives` with its status. `predict(text, method="lac")` uses it.
- `CONFORMAL_ALPHA` stays at **0.10**, the final value for `docs/policy_cards.md` section 11,
  so that table needs no change.
- **Recommendation:** adopt LAC for the deployed TF-IDF model through a logged amendment to
  `docs/eval_plan.md` 8.4, before held-out A. The choice can be justified from calibration
  alone (the cross-fit above).
- **Also needed, whichever score is used:** add training coverage for the block wordings
  missed in section 6 ("congelar", "travar", "reportar como robada"). Alternatively, fit
  class-conditional (Mondrian by intent) thresholds for `card_block`.
- Keeping APS means the classifier hands off nearly every message, and C5 stays missed.

## 9. Accuracy versus size and latency (CV winner not deployed)

| | TF-IDF + LR (deployed) | e5 + LR (CV winner) |
|---|---|---|
| Test macro-F1 | 0.889 [0.840, 0.922] | 0.927 [0.890, 0.955] (+0.038 [0.004, 0.075]) |
| Artifact | 1.4 MB | 1.13 GB encoder weights + 35 KB head |
| CPU latency per message (p50 / p95) | 1.6 / 2.0 ms | 25.4 / 27.6 ms |
| Runtime dependencies | scikit-learn, numpy, scipy, joblib | + torch, transformers, sentence-transformers |
| `card_block` precision | 1.00 | 0.91 (4 disputes labeled as blocks) |
| False `card_block` singletons (LAC) | 0 | 4 |
| Golden dialogue 5 (dispute) | correct | labeled `card_block` |

e5 is more accurate overall, and the gap is statistically distinguishable but small (lower
bound 0.004). Its errors fall on the action intent: a dispute routed to the block flow skips
the dispute handoff (POL-ESC-01). Size and latency alone justify TF-IDF for this prototype.
The safety numbers point the same way. If e5 is reconsidered, it needs the C6 check on the
amended conformal score first.

## 10. LLM zero-shot baseline (not run)

- `python -m banking_cs.nlu.llm_baseline` runs gpt-4o-mini at temperature 0 on the **test split
  only**. It uses the intent list with one-line definitions from `docs/intents.md` section 1,
  the guide's precedence rule, and JSON output. The prompt SHA-256 is `2570605a…`.
- The key is read from `OPENAI_API_KEY` by the client; it is never logged or stored.
- Responses are cached, so a rerun does not bill the test split twice. Token usage and cost
  are logged, and the run refuses to start if the projected cost exceeds US$1.
- **Status:** `not run`, because `OPENAI_API_KEY` was not set in the environment
  (`ml/artifacts/nlu/llm_baseline.json`).
- **Projected cost:** about 371k input and 10k output tokens, about US$0.06 at the list prices
  assumed in the module ($0.15 / $0.60 per million tokens; check against current pricing).
- **Deviation:** the eval plan specifies "same model ID as the agents"; gpt-4o-mini is a team
  decision.

## 11. Pre-registered classifier targets (eval plan 9.2)

| ID | Target | Result | Status |
|---|---|---|---|
| C1 | Chosen model beats TF-IDF + LR | The CV winner e5 beats TF-IDF by +0.038 [0.004, 0.075]. The deployed model is TF-IDF itself | **Met** for the CV winner; not applicable to the deployed model |
| C2 | Macro-F1 ≥ 0.85 overall | TF-IDF 0.889 (lower bound 0.840); e5 0.927 | **Met** (point estimate) |
| C3 | pt-BR ≥ Spanish − 0.05 | TF-IDF 0.882 vs 0.892; e5 0.910 vs 0.935 | **Met** |
| C4 | Coverage ≥ 0.90; every variant ≥ 0.85 | APS 1.000 everywhere | **Met** |
| C5 | Mean set size ≤ 1.3; singletons ≥ 75% | APS 7.73 and 6.7% | **Not met** (LAC, exploratory: 1.06 and 90.7%) |
| C6 | 0 false singletons on `card_block` | APS 0 (TF-IDF and e5); LAC: TF-IDF 0, e5 4 | **Met** for the deployed model |
| C7 | Kappa ≥ 0.80 | 100-row blind sample generated, not labeled | **Not evaluable** |

## 12. Limitations

1. **Synthetic, single-author data.** One LLM wrote every utterance from the team's guide. The
   test split measures generalization to unseen meanings written in the same style, not to
   customers. Real messages will have more typos, code-switching, voice transcription errors
   and requests outside the taxonomy.
2. **Not reviewed by a person.** Eval plan 8.1 requires that review before training, so these
   results are provisional. After review, rerun `dataset`, `train_eval` and `llm_baseline`, and
   report any label changes.
3. **Unseen meanings fail.** Section 6 shows whole meanings missed: freezing a card, "report as
   stolen", delivery questions. Adding seed groups for those wordings matters more than the
   model choice.
4. **Single-turn classifier.** Elliptical follow-ups ("E o do cartão de crédito?") and
   context-dependent turns need the orchestrator to carry the previous intent. One golden turn
   depends on it.
5. **Conformal guarantee is marginal and approximate.** Exchangeability holds at the group
   level (groups are assigned at random), while utterances within a group are correlated. The
   effective calibration size is closer to 97 groups than to 776 utterances. Per-intent
   coverage is not guaranteed (LAC: `card_block` 0.77).
6. **Probabilities are not calibrated.** `scores` are logistic-regression outputs. Use the
   conformal set, not raw scores, for decisions.
7. **Slots are rule-based.** Merchants are found only when capitalized after a preposition
   (recall 0.76). Amounts written in words ("cien dólares") and dates outside the canonical
   patterns are missed. `balance_item` defaults to `balance`.
8. **Below the guide's paraphrase target** (section 2.2), and the label-quality sample is 100
   rows instead of 200.
9. **The rules baseline and the golden slice share an author** with the data. The rules'
   golden score (26/27) is not evidence of generalization.

## 13. Reproduction

From `ml/`, with the locked environment (`requirements.lock`, encoders in the local Hugging Face
cache):

```sh
python -m banking_cs.nlu.dataset        # validate corpus, split, write data/nlu/ and the fixture
python -m banking_cs.nlu.train_eval     # CV, fit, test, conformal, export to artifacts/nlu/
python -m banking_cs.nlu.llm_baseline   # needs OPENAI_API_KEY in the environment
pytest tests/nlu                        # rules, corpus, conformal, loader, LLM plumbing
```

The backend needs `scikit-learn==1.9.1`, `numpy`, `scipy` and `joblib`, plus `ml/src` on the
import path (for example `pip install -e ml --no-deps`). It never needs Kedro.
