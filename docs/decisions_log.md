# Decisions log

Decisions taken while building the system, with the reason and the evidence. Newest last. Each
entry names the files it changed. Pre-registered plan changes are also logged in
`docs/eval_plan.md` (change log).

## NLU classifier, `nlu-utt-0.2` (2026-10-03 to 2026-10-04)

Context: model card 0.1 (`docs/model_card_intent.md`, commit `0618bcf`) reported that the
pre-registered APS conformal score transfers 89% of messages, and that whole meanings were missed
on the test split (freezing a card, "report as stolen", card delivery, app login, phone top-up).
The team asked for six changes. These are the decisions taken while making them.

### D-01. Conformal score APS → LAC for the deployed model (eval plan 0.3)

- **Decision:** the deployed TF-IDF model uses LAC (score 1 − p(true intent)). APS stays reported.
  `conformal.json` defaults to LAC, and APS is listed under `alternatives`.
- **Why:** with APS, the mean set size was 7.7 and 89% of messages would be transferred under
  POL-ESC-06 (C5 missed).
- **Evidence (calibration only, `nlu-utt-0.1`):** 2-fold cross-fit inside calibration. APS gave
  coverage 1.000, mean set size 7.4 and 10.5% singletons. LAC gave coverage 0.902, mean set size
  1.11 and 87.5% singletons.
- **Disclosure:** decided after seeing the APS result on the test split, before held-out A.
  Logged as an amendment in `docs/eval_plan.md` 8.4 (version 0.3).
- **Files:** `docs/eval_plan.md`, `ml/src/banking_cs/nlu/train_eval.py`, `predict.py`,
  `ml/artifacts/nlu/conformal.json`.

### D-02. Existing groups keep their split; new groups split 3/1/1 per meaning

- **Decision:** the split of every `nlu-utt-0.1` group is frozen in
  `ml/nlu_corpus/locks/split_lock_nlu-utt-0.1.json`. New groups carry a `topic` and are split
  within each (intent, topic) stratum, with a seed per stratum. Each of the 7 topics has 5
  groups: 3 train, 1 calibration, 1 test.
- **Why:** without the lock, adding groups would reshuffle other intents' test groups, and the
  rescored test split would not be comparable with the first. Splitting per topic guarantees
  that every new meaning has training coverage and also appears once in calibration and in test.
- **Check:** with no new groups, the rebuild reproduces the `nlu-utt-0.1` split exactly. No new
  group is a near-duplicate of an existing one, so none inherits a locked split.
- **Also:** the blind label-quality sample is drawn from the locked groups only, so it is
  unchanged (byte-identical) for annotators who may already be labeling it.

### D-03. Which seed groups were added

- **Decision:** 35 groups, 280 utterances:
  - `card_block` (20 groups): `freeze` (congelar, pausar), `travar`, `report_stolen`,
    `lost_card`;
  - `out_of_scope` (15 groups): `card_delivery`, `app_login`, `phone_topup`.
- **"travar":** it is the Brazilian Portuguese verb for a temporary lock and has no single
  Spanish equivalent. Its groups pair pt "travar" with es "apagar la tarjeta", "inhabilitar
  temporalmente" and "bloqueo temporal".
- **Contrast cases inside the new groups:** "saldo del celular" (phone top-up), "reposición" or
  "segunda via" used for delivery tracking, and "me bloquearon el usuario de la app" (app
  login). All three are out of scope.

### D-04. The test split is rescored, with the comparison made explicit

- **Decision:** after the additions, the test split (now 880 rows: 824 earlier + 56 new) is
  rescored. The model card reports:
  - the full test split;
  - the 824 earlier test rows;
  - the 56 new test rows;
  - the previous deployed model (`nlu-utt-0.1` artifact, extracted from git) scored on the same
    rows.
- **Why:** the additions were chosen from test errors, so the gain on the earlier test rows is
  optimistic. The 56 new test rows were written in the same pass as the training groups, by the
  same author.

### D-05. Block safety override: design

- **Decision:** `rules.block_signal` is a broad detector of block, loss and theft requests. It
  is separate from `rules.classify`, so the rules baseline stays as committed at `fb05246`.
  `predict.apply_block_override` adds `card_block` to the conformal set when the detector fires:
  - a singleton becomes a clarification;
  - an empty set becomes {top intent, `card_block`}, or {`card_block`} when card_block is the
    top intent (the block flow still asks for confirmation, POL-ACT-02).
- **Output:** `predict` gains `safety_override: bool` for the audit log. This is an additive
  change to the output contract.
- **Exception:** the override is not applied when the set holds `human_request`, because a
  request for a person is transferred with no extra question (POL-ESC-09, `docs/intents.md`
  rule 2).

### D-06. Detector v1 → v2 after seeing misses (post-hoc)

- **v1** (commit `41e5ccd`) was designed before any evaluation:
  - test: `card_block` coverage 0.961 → 0.990 with the override; fired on 8 messages (3 of them
    block requests);
  - calibration: 0.865 → 0.979.
- **What v1 missed:** verb forms ("me apagan", "bloquéeme", "me bloquean"), "poner un bloqueo
  temporal", and forgot-the-card cues. It also read Portuguese "robô" (robot) as Spanish "robo"
  (theft), which would have delayed transfers for "não quero falar com robô".
- **v2** (commit `889759a`) fixes those:
  - test: coverage 0.961 → 1.000; fired on 7 messages (4 block requests, 3 others);
  - calibration: 0.865 → 1.000.
- **Disclosure:** v2 was revised after seeing calibration and test misses, so its test numbers
  are post-hoc. Both versions are reported.

### D-07. C6 regression: reported, not patched

- **Finding:** after the additions, TF-IDF with LAC makes **7 false `card_block` singletons** on
  test (there were 0 before), so C6 is not met.
  - 4 come from one dispute group, "reportar / denunciar un fraude en la tarjeta…". The new
    "reportar / denunciar el robo" wording generalized to fraud reports.
  - The others are "Achei o cartão, dá pra destravar?", "¿La tarjeta se bloqueó por poner mal
    la clave?" and "extrato do cartão".
- **Decision:** I did not add an unrequested runtime guard. Recommended next steps:
  - contrast seed groups: fraud report → `charge_dispute`, "destravar" → `card_unblock`;
  - a precedence guard: when the rules detect `charge_dispute` (which outranks `card_block`,
    `docs/intents.md` rule 2), add it to a {`card_block`} singleton so the customer is asked.
- **Mitigation already in place:** a false {`card_block`} leads to a confirmation prompt naming
  the card (POL-ACT-02), not to a block.

### D-08. Out-of-scope singleton offers a handoff: POL-ESC-13 and POL-HND-08 (policy 0.5)

- **Decision:** new rule POL-ESC-13 (POL-ESC-12 was already taken) and template POL-HND-08. A
  set of exactly {`out_of_scope`} gets one sentence saying the request can't be handled here,
  the capability list, and an explicit offer of a human. If the customer accepts, the request is
  transferred as in POL-ESC-09. POL-ESC-06 now says where the set comes from (LAC + override).
- **"T2" in the request:** no "T2" is defined in the policy, the state machine, the eval plan
  (where T2 is the hypothesis "the policy engine reduces unsafe outcomes") or the problem
  statement. I did not guess a meaning. The rule is attached to transition T-10 (out-of-scope
  singleton), and the question is left to the team.
- **Not changed:** `docs/contracts/state_machine.md` T-10 already says "offer a transfer", but
  its rule column does not cite POL-ESC-13. `docs/intents.md`, `docs/golden_conversations.md`
  and the state machine still reference `cards-synthetic-0.4`. Both are follow-ups for the
  contract owners.

### D-09. LLM zero-shot baseline: key handling and a slow first run

- **Key handling:** the key is read at runtime from `backend/.env` with python-dotenv
  (`dotenv_values`). Only `OPENAI_API_KEY` is loaded; the backend's other variables never enter
  the process. The key is never printed, logged or written. `llm_baseline.json` records only its
  source.
- **First run:** 9.2 h of wall time, with 8 calls failed after retries and counted as
  `out_of_scope`. The likely cause is throttling plus the client's default 10-minute request
  timeout stacked on the module's own retries.
- **Fix and rerun:** added a 30 s timeout, no client-side retries, and separate counts of
  failed calls and invalid answers. The cache made the rerun send only the 8 failed calls
  (0.9 s).
- **Result:** final macro-F1 0.933. Total cost about US$0.052 at the assumed list prices.

### D-10. Smaller items

- python-dotenv is now listed in `ml/requirements.txt` (it was only a transitive dependency).
- Two runs with identical data produced model files 2 bytes apart, with identical predictions
  and metrics. The likely cause is thread-level floating-point non-determinism in BLAS. The
  SHA-256 in `metadata.json` is the one shipped.
- `ml/artifacts/nlu/cv_results.json` (a stale `--cv-only` output) is left untracked. Its
  deletion was not permitted in an earlier session.
