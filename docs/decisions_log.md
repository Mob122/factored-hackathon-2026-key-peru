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

## C6 fix, dispute offer after a block, state machine (2026-10-04)

Context: model card 0.2 reported 7 false `card_block` singletons on test (C6 not met). The team
asked for a symmetric dispute override, a post-block dispute offer in the policy, the matching
state-machine and version updates, and a model card update.

### D-11. Dispute safety override

- **Decision:** `rules.dispute_signal` detects dispute or fraud wording:
  - the frozen baseline's dispute patterns;
  - "fraude", "golpe", "estafa", "chargeback", "clonaron";
  - "no reconozco" / "não reconheço";
  - "cobro que no hice";
  - "contestar", "disputar" or "reclamar" followed by a charge word;
  - "no autorizado", "no fui yo".

  `predict.apply_overrides` runs the block override, then the dispute override: when the
  signal fires and `charge_dispute` is missing, it is added, with the same rules for singletons
  and empty sets. Neither override applies when the set holds `human_request`.
- **"contestar":** in Spanish it also means "to answer", so it counts only before a charge
  word. In Portuguese it means "to dispute".
- **Result (TF-IDF, LAC):**
  - test: false `card_block` singletons go from 7 (model alone, or with the block override) to
    **3**; `charge_dispute` coverage goes from 0.886 to 0.971; 5 more singletons become
    questions;
  - calibration: false singletons stay at 1 to 1.
- **Disclosure:** written after the 7 false singletons were seen, with a word list chosen to
  cover them, so the test reduction is post-hoc. The calibration figures are the clean view.
- **Remaining 3:** "destravar", "¿se bloqueó por poner mal la clave?" and "extrato do cartão"
  have no dispute wording. C6 stays not met. The fix is contrast seed groups and a retrain.

### D-12. `predict()` output: `safety_override` becomes a list, and `signals` is added

- **Decision:** `safety_override` lists the intents the overrides added (`[]` when none). It was
  a boolean in card 0.2; a truthiness check still works the same way. The new `signals` field
  is `{block_or_theft, theft, dispute_or_fraud}`.
- **Why:** with two overrides, the audit log needs to know which one fired. POL-ACT-12 needs
  the theft and fraud signals of the message that started a block request; the orchestrator
  keeps them with the pending action.

### D-13. POL-ACT-12 and POL-ACT-13: dispute offer after a theft or fraud block (policy 0.6)

- **Decision:** after a verified block (T-34) whose request carried theft or fraud wording,
  POL-ACT-11 is followed by POL-ACT-13: "Si hay cargos en esta tarjeta que usted no reconoce,
  dígame cuáles y abro un reclamo con un asesor." A loss without theft or fraud wording does
  not trigger it.
- **Why not a yes/no question:** after T-34 the conversation is back in `IDLE`, where a bare
  "sí" is not a classifier input (`docs/intents.md` rule 7). Asking the customer to name the
  charges lets the next message be classified as usual (a dispute goes to T-09). This needs no
  new waiting state.
- **Tier:** your definition was "tier T2 = enforced by template or prompt; tiers are the 'Tier'
  column of policy_cards.md". There is **no Tier column**: I searched every local and remote
  branch, and only an "Enforced in" column exists. I did not invent tiers for the other 107
  rules. Instead:
  - section 0 now defines T1 (deterministic code) and T2 (template rendered by code, or the
    prompt where the rule says so; still never granting a permission, POL-GEN-01);
  - the tier is written in the "Enforced in" cell;
  - POL-ACT-12 is labeled **tier T2**, enforced by the template POL-ACT-13.

  Adding a real column, with a tier for every rule, is a team decision.
- **Also:** POL-HND-08 is reduced to the offer question ("¿Quiere que le pase con un asesor?" /
  "Quer que eu transfira você para um atendente?"). In 0.5 it repeated the refusal and the
  capability list that POL-ESC-13 already requires. The Portuguese text now matches golden
  dialogue 4, sentence 3.

### D-14. State machine `sm-0.4`: where each rule is cited

- **Decision:**
  - T-10 cites POL-ESC-13, and its action names POL-HND-08.
  - POL-ACT-12 is cited at **T-34** (verified block), where it applies.
- **Why not T-10 for POL-ACT-12:** the request asked to cite "POL-ESC-13 and the new rule" at
  T-10. But T-10 routes out-of-scope singletons and never runs a block, so citing POL-ACT-12
  there would be wrong.
- **No new states or transitions:** the overrides only change the set that T-03, T-04 and T-05
  to T-10 already consume.

### D-15. Versions and reference updates

- **Bumped:**

  | Document | New version | What changed |
  |---|---|---|
  | `docs/policy_cards.md` | `cards-synthetic-0.6` | POL-ACT-12, POL-ACT-13, POL-ESC-06, POL-HND-08, tiers in section 0 |
  | `docs/contracts/state_machine.md` | `sm-0.4` | T-10, T-34 |
  | `docs/golden_conversations.md` | `golden-0.5` | dialogue 4 turn 1 cites POL-ESC-13 and tags POL-HND-08; case files cite `policy_version` `cards-synthetic-0.6`. No dialogue blocks after theft or fraud wording, so POL-ACT-12 changes none |

- **References updated without a version bump:**
  - `docs/intents.md`: policy and state-machine references, plus the route column
    (`out_of_scope` adds POL-ESC-13; `card_block` covers POL-ACT-01 to 13). The taxonomy is
    unchanged, so it stays `intents-1.0`.
  - `docs/eval_plan.md`: the System-under-test line and the run-record versions.
- **`tools/check_docs.py`:**
  - current versions set to `cards-synthetic` 0.6, `sm` 0.4, `golden` 0.5, `eval-plan` 0.3;
  - `docs/model_card_intent.md` removed from the not-yet-existing list;
  - stdout forced to UTF-8, because the review list crashed on a Windows console at a "→".
- **Result:** 0 problems. 32 review-only version strings remain:
  - history lines;
  - `docs/contracts/audit_log.md`, `docs/contracts/eval_report.schema.json`,
    `docs/operations.md`, `docs/proposal.md` and `docs/requirements_matrix.md`, which were
    outside this request.

### D-16. Retrain for the override report

The classifier was retrained on unchanged data so `eval_results.json` would carry the
three-configuration override report. Predictions and every non-override metric are identical
to card 0.2. The model file differs again in bytes (D-10), and the new SHA-256 is in
`metadata.json`.

## Policy tiers, test IdP and mock bank in the backend (2026-10-04)

Context: the team asked for (0) a Tier column on every policy rule, (1) roles, a mock identity
service labeled as a test IdP, session expiry and step-up in `backend/`, (2) the mock bank tools in
`backend/services/banco.py` over gold, and (3) tests for every T1 rule this layer enforces.

### D-17. Tier column: how each rule's tier was derived (policy 0.7)

- **Decision:** every rule table has a last column **Tier**. It is derived mechanically from the
  "Enforced in" cell, as the request said:
  - T1 if the cell names a service, gateway, orchestrator or tool layer. The components counted
    as such are listed in section 0, including grounding check, redaction layer, tool registry,
    audit log, case store, tracing and backend roles, because each is code in the pipeline;
  - T2 if it names only templates or the LLM prompt;
  - T3 otherwise (documentation, operations procedure, review).
- **Mixed cells** (code and a template, for example POL-GEN-03) are T1, because the code part needs
  a test.
- **Rules without an "Enforced in" cell:**
  - answer rules (section 3) take it from the "Tool" column: a tool is T1, static text (POL-ANS-05)
    is T2;
  - "not answered" rules (POL-ANS-10 to 14) are T1: the tool layer never returns the field, and
    every "Goes to" route is an orchestrator rule;
  - rules in template tables (BAL, ACT, TXS, DEC and HND templates) are T2;
  - section 7 (POL-HND-01, 02, 06) had no enforcement column, so one was added: HND-01 T2,
    HND-02 and HND-06 T1 (transitions T-37 and T-38).
- **Section 8:** its "Source rule" column already held component names, so it is renamed "Enforced
  in".
- **POL-ACT-12 changes from T2 (0.6, D-13) to T1.** Its cell names the orchestrator, which decides
  when the offer is made (after a verified block, once, only with theft or fraud signals). Its
  wording stays the T2 template POL-ACT-13. This is the one place where the new derivation rule
  overrides an earlier explicit label; revert it if the team prefers the 0.6 label.
- **Result:** 111 rules: T1 79, T2 28, T3 4 (POL-AUTH-13, POL-PII-06, 08, 09). The counts are in
  the policy header.
- **Checker:** `tools/check_docs.py` now fails if a rule has no tier or the header counts disagree
  with the column. It lists, for review only, the T1 rules that no test in `backend/tests` or
  `ml/tests` cites yet.
- **Also fixed:** the 0.6 tier bullet in section 0 had been inserted in the middle of another
  bullet's sentence.

### D-18. Roles and registration

- **Roles:** `cliente`, `agente`, `jurado`. The old `usuario` and `admin` values are migrated to
  `cliente`, the least privileged role, by an idempotent statement in `run_migraciones()`.
  Mapping `admin` to `jurado` would have granted impersonation to accounts nobody reviewed.
- **Registration:**
  - open only when `ENV` is exactly `development`. If `ENV` is missing it is closed: a security
    control fails closed, even though `main.py` treats a missing `ENV` as development for table
    creation;
  - it ignores any `rol` or `customer_id` in the body and creates a `cliente` with no customer,
    which no data tool accepts. Otherwise anyone could register as `jurado`, or claim a customer
    by typing its number.
- **Seeded users:** only `backend/scripts/sembrar_usuarios.py` creates users with a customer or a
  privileged role:
  - one `cliente` per session customer of the 12 golden dialogues (11 customers; CLI-AN7KXGR09TB2
    is in dialogues 6 and 12), with `<customer_id>@clientes.keyperu.example`;
  - `agente@keyperu.example` and `jurado@keyperu.example`.

  `.example` is a reserved domain that email validation accepts. The script is idempotent and
  needs `SEED_PASSWORD` of at least 12 characters. A test checks its list against the dialogue
  overview.
- **`agente`** has no endpoint yet; it is reserved for the case inbox.

### D-19. Sessions, secrets and the existing auth code

- **Session record:** every sign-in creates a row in `sesiones_identidad`, and the JWT only names
  it (`sid`).
  - Idle (15 min) and absolute (60 min) expiry, sign-out and step-up failures live in that row.
    The JWT's `exp` is the absolute expiry, as a second check.
  - Old tokens without `sid` stop working after this change; users sign in again.
- **Response shapes:**
  - `POST /autenticacion/iniciar-sesion` still returns the raw token string, so the frontend
    proxy keeps working;
  - session details are in the new `GET /autenticacion/mi-sesion`, which leaves out
    `customer_status` (INV-14);
  - `mi-perfil` answers 403 for a test-IdP session, which has no registered user behind it.
- **Step-up:** `POST /autenticacion/step-up` takes the one-time code, a card and the action, the
  inputs of the frozen `step_up` contract. It does not check card ownership. A step-up for a card
  that is not the customer's leads to the same "not found" in `block_card`, so it reveals nothing.
- **Secrets:** `SECRET_KEY`, `CARD_HASH_KEY` and `AUDIT_KEY` have no default in code, and the
  backend does not import without them. `ALGORITHM` defaults to HS256 and must be HS256, HS384 or
  HS512.
- **`AUDIT_KEY`:** `docs/operations.md` 2.3 already listed it, but `backend/.env` did not have
  it. A random value was generated and appended to the local `backend/.env`, never printed. It is
  a new key, not one shared with `ml/`, so nothing else has to match it.
- **Datetimes:** SQLModel 0.0.47 rejects naive datetimes, so the new tables store UTC-aware
  values, as `Usuario` already did. Only the overlay's `hora_evento` is naive, because it is on the
  bank clock of the gold data.

### D-20. Test IdP: what the evaluator can do

- **Codes for any live customer session:** `POST /identidad/otp-prueba` issues a code for any live
  customer session, not only the ones the same jurado opened.
  - Seeded `cliente` users sign in with a password and still need a code to block a card; there is
    no other channel to deliver one.
  - The code is useless without that session's token. A jurado can already open a session for any
    customer, so this adds no access.
  - Each code is audited with the jurado's ID.
- **Search without a masked name.** The request asked for a masked name. Gold `customers` has no
  names, and `gold-0.2` says every column not listed is unavailable to the backend
  (`docs/contracts/gold_tables.md` section 2). Reading names from `02_intermediate` would break
  that frozen contract. The search therefore returns `customer_id`, country and segment, and this
  is flagged to the team. Adding a masked name needs a new column in the next gold contract version (for example initials
  only), decided by the contract owners.
- **Search limits:** prefix match on `customer_id`, filters by country, segment and status, at
  most 20 per page, ordered by `customer_id`, and 10 searches a minute per jurado (HTTP 429).
  - The page has `hay_mas` but no total count.
  - The limiter lives in process memory (POL-AUTH-13); a shared store is remaining work.
- **No bulk export:** a test asserts that `/identidad` exposes exactly the three endpoints.

### D-21. Impersonation in the audit log

- **Decision:** an impersonation is a `session` event (`authenticated`, actor `identity`), as
  `audit-0.2` section 4.1 defines.
  - The customer is recorded as `customer_ref`, the keyed pseudonym of AL-P3, and the time is
    `occurred_at`. The request said "customer id"; the frozen contract only allows the pseudonym,
    which the security role can re-identify.
  - The jurado and the endpoint go in an **additive** field
    `test_idp = {idp, issued_by_user_id, issued_by_role, endpoint}`, because the contract has no
    field for the person who opened a session. The jurado ID is a staff user ID, not customer
    data, so it is stored in clear.
  - No existing field changes meaning. The field should be added in the next audit contract version by the contract
    owners.
- **Codes issued:** a `step_up_requested` event with the same field. The code itself is never
  stored (AL-P2).
- **Until the orchestrator exists:** the events written by the test IdP and the tools use
  `turn_index` 0, a state chosen per event (`UNAUTHENTICATED`, `STEP_UP`, `EXECUTING`,
  `HANDOFF`) and generated `trace_id` and `span_id`.
  - The hash chain, UUIDv7 IDs and the AL-P7 scan are implemented. The scan also blocks raw
    `CLI-`, `PRD-` and `TRX-` IDs, to enforce AL-P3.
  - `tool_call` events are left to the tool gateway.

### D-22. Mock bank reader and tools

- **Read-only by construction:** gold is copied into an in-memory DuckDB, with only the columns
  the tools use. Then `enable_external_access = false` and `lock_configuration = true` are set,
  so the connection can neither read nor write files nor turn that back on. `opening_date`,
  `expiration_date` and `last_updated` are not loaded at all (POL-ANS-13).
  - Loading the real gold takes about 3 s.
  - The reader reloads when `_load_log.parquet` changes (a new published load).
- **`GOLD_DIR`:** it may point at the gold folder or at its parent. The local `.env` points at
  `03_primary`, which holds `gold/`, so both work and nobody has to edit `.env`. `.env.example`
  now points at the gold folder.
- **Overlay rule:** `freshness_policy.md` section 5, with the delivery date of each gold row taken
  from the `process_date` of its `source_file` in the published load log. If that date is
  missing, the overlay wins, which is the conservative choice for a block.
- **Bank clock:** optional `RELOJ_SIMULADO` (for example `2026-06-18T10:00:00`, the clock of the
  golden dialogues). It sets "today" for transaction windows and the business day of overlay
  events. Without it, the bank uses real UTC time, and the last-30-days window over the 2026-06
  data is empty.
- **Additive outputs beyond `docs/proposal.md` section 8:**
  - `list_transactions`: the window used, `window_capped` and `truncated`;
  - `describe_transaction`: card `last4` (the TXS subject needs it) and `notices` (POL-ESC-05 for
    an unknown status or code);
  - `get_balance`: `templates` (POL-BAL-01, 02, 03, 04, 06).

  No contracted field was removed or renamed.
- **Confirmation tokens:** the frozen `block_card` input includes a confirmation token, so
  `emitir_token_confirmacion` issues one. It is bound to (session, card, `block_card`), lasts
  120 s, is single use and needs a valid step-up for that card. A new token replaces the
  previous one.
- **Order of checks in `block_card`:**
  1. step-up, consumed whatever the result (POL-AUTH-04);
  2. ownership, with the same error as a missing card;
  3. confirmation token, consumed atomically;
  4. current status.

  Each refusal writes `action_result` with `executed: false` and its error code. Single use is
  enforced with `UPDATE … WHERE usado_en IS NULL` and a row-count check, so two concurrent calls
  cannot both pass.
- **No HTTP routes for the tools:** they are called in process by the orchestrator, which owns
  the state checks (`state_machine.md` section 2). Exposing `block_card` over HTTP would bypass
  INV-02 and INV-03.
- **Ownership check:** `comprobar_numero_tarjeta` uses the HMAC exactly as
  `docs/findings/gold_run.md` (deviation 9) specifies. It returns `propia`, `ajena` or
  `no_encontrada`, with no data of another customer's card, and refuses anything shorter than 13
  digits. The tests compare it with an independent implementation of the same formula.
  - It was not checked against the real gold with the real key, because that would mean loading
    `backend/.env` into a process.
  - Running `banco.hmac_numero_tarjeta(<a product_number>)` once with the real key, against that
    card's `card_number_hmac`, would close this.
- **Case store:** `open_handoff` writes the `casos` table with the field names of policy section
  8, which are a contract, so they stay in English.
  - The server sets `customer_id`, `auth_level`, `conversation_ref`, `created_at` and
    `policy_version`. A different `customer_id` in the case file is rejected.
  - The idempotency key returns the same case on retry (POL-REL-02).
  - It also runs for `Suspended` or `Closed` customers (POL-AUTH-09).

### D-23. Smoke run on the real gold

With a scratch database, dummy secrets and the real `GOLD_DIR`, the tools reproduce three golden
dialogues:
- dialogue 2: card 8407 Active, then step-up, token and block, then the verification read gives
  `Blocked`;
- dialogue 1: `TRX-0OQVC3BDVLGG2VDSXTFM` (127.37 USD, Uber, Declined, 54), with templates
  POL-TXS-02 and POL-DEC-54, as in the dialogue;
- dialogue 11: the credit card 5070 and savings account 1317 balances, with POL-BAL-01 and
  POL-BAL-02.

The audit hash chains verified. The local development database was not touched.

### D-24. Tests: which T1 rules this layer covers

`backend/tests` has 80 tests, all passing; every test's docstring cites the rules it covers.
- `test_cobertura_reglas.py` lists the 44 T1 rules this layer enforces and checks two things:
  - each one is cited by a test;
  - each one is still T1 in the policy.
- **Requested cases:**
  - another customer's card gets the same refusal as a missing card, in every tool;
  - a customer number alone authenticates nothing;
  - only `jurado` reaches `/identidad/*`;
  - expired sessions are refused (idle, absolute, tampered or expired JWT, sign-out);
  - a block without step-up is refused;
  - `block_card` leaves the Parquet files byte-identical, with the same modification time.
- **Also covered:** FX-6 and FX-7 of `freshness_policy.md` 6.4, which `docs/findings/gold_run.md`
  assigned to the backend.
- **Not covered here:** T1 rules of the orchestrator, redaction layer, grounding check and policy
  engine (for example POL-ESC-06, POL-PII-01). They wait for those components; `check_docs.py`
  lists them.
- **Isolation:** the tests never read `backend/.env` (`load_dotenv` is stubbed in `conftest.py`)
  and use a labeled gold test fixture (`backend/tests/gold_prueba.py`), so they run on a clean
  clone.

### D-25. Smaller items

- `backend/.env.example` held a pasted shell heredoc (`cat > … << 'EOF'`). It is now a plain
  template with every required key.
- `backend/requirements.txt` lists what the code imports (sqlmodel, PyJWT, pwdlib with argon2,
  python-dotenv, email-validator, duckdb). pytest and httpx are in `requirements.dev.txt`.
- `backend/models/__init__.py` imports every model, so `create_all` sees the new tables.
- `run_migraciones()` now also runs on SQLite. It adds missing columns after checking them with
  the inspector.
