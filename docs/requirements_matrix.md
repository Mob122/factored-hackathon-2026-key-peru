# Requirements matrix

Maps every requirement in `docs/problem_statement.pdf` to the plan in `docs/proposal.md` (v3.1).
One row per atomic requirement. Day and owner come from proposal sections 9 and 10; for gaps
they are the proposed day and owner. Evidence paths that do not exist yet are proposals and
should be kept stable once created.

Last review: 2026-09-29 (second pass), after closing the balance scope decision, the customer
status rule, the evaluation budget, the ownership changes and the D1-2 evidence. Consistency
check over `docs/proposal.md` (v3.1), `docs/policy_cards.md` (`cards-synthetic-0.4`),
`docs/intents.md` (`intents-1.0`), `docs/golden_conversations.md` (`golden-0.4`),
`docs/eval_plan.md` (`eval-plan-0.2`), `docs/operations.md` (`ops-0.1`, draft) and
`docs/contracts/` (`sm-0.3`, `gold-0.2`, `fresh-0.2`, `audit-0.2`, `eval-report-0.2`): every
cited rule, transition, invariant and check ID exists, and every cited document path exists or
is listed below as not yet written.

## Open gaps

What is still missing after the review, most important first. Everything else in this matrix is
covered by a written design or plan; implementation is tracked by the Day column.

1. **G-4 remainder: capacity and load test** (rows I-9, D6-5). `docs/operations.md` section 1 is
   a placeholder with the planned test; no capacity number exists. The trace sample
   (`docs/operations.md` 3.3, row D6-1) is also a placeholder. Owner: Martín, Day 7 (trace
   sample Day 5).
2. **Evaluation budget not set** (rows E-5, E-17, E-18). `docs/eval_plan.md` 13.5 needs
   `EVAL_BUDGET_USD` written before the first held-out run (proposed US$600 against an estimate
   of about US$860 without caching and about US$510 with caching, contingency included). The LLM
   provider and model IDs in 13.1 are assumptions, and the account's rate limits have not been
   checked against 13.3. Owner: shared, before Day 4.
3. **Model sampling settings** (rows E-4, E-7). The plan asked for judge temperature 0 and a fixed
   agent temperature, but current Claude models reject sampling parameters. `docs/eval_plan.md`
   13.1 now logs "model default" and measures the judge's own variability instead; the team
   has to confirm this before the plan is frozen (rule 0.1). Owner: Aldair, Day 4.
4. **Open contract item:** the mock bank overlay's reset procedure between evaluation runs
   (golden flag F-04, row B-6, `docs/operations.md` 4.1). Owner: Martín, Day 3.
5. **G-3 remainder: deletion job** (row D6-8). The procedure is designed
   (`docs/operations.md` 4.2) but not implemented or tested. Production retention values are the
   bank's to set (4.3), which the write-up must say. Owner: Martín, Day 7.
6. **Referenced documents not yet written** (planned, listed so the references are not read as
   existing): `docs/data_card.md` (S-10, B-1 to B-3, POL-PII-09, fixture provenance),
   `docs/model_card_intent.md` (D4-6 to D4-12), the tool contracts doc with its limitations
   and the overlay reset (B-6), `eval/judge_rubric.md` (E-7), `docs/writeup.md`.

Closed in this review: the balance inquiry scope decision (approved: proposal v3.1 sections 1,
3, 4 and 8, `balance_products` in `gold-0.2`, flag F-29), the undecided customer-status case
(POL-AUTH-09, T-51, INV-14, a held-out template), the intent taxonomy (`docs/intents.md`,
final names in every document), the evaluation cost and runtime estimate
(`docs/eval_plan.md` 13), the owner of the adversarial templates (rows D5-3 to D5-7) and the
D1-2 evidence.

Status: **planned** = a document or plan covers it (rows whose evidence already exists say
"exists"); **gap** = nothing covers it yet, or only partly. Gaps are expanded at the end.

## Intro: "Think beyond the demo"

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| I-1 | "understand complex customer interactions, use data and tools securely, complete appropriate service workflows, and involve human agents" | Whole system: classifier + orchestrator + tools + handoff | shared | End-to-end demo recording; `eval/report.json` | 4-8 | planned |
| I-2 | "Use the supplied data to explain why the problem matters" | Day 1 analysis (Transaccional = 35% of interactions) | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists), `docs/decision_day1.md` (exists) | 1 | planned |
| I-3 | "establish a baseline" | Human status quo (FCR 91.5%, 221 s handle, ~120 s wait) + naive LLM agent | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists); `docs/eval_plan.md` section 1 (exists); naive-agent run in `eval/report.json` | 1, 6 | planned |
| I-4 | "measure whether your approach improves service quality and operational efficiency" | Evaluation harness: our system vs naive agent on the same held-out scenarios | Aldair | `docs/eval_plan.md` sections 5 and 9 (exists); `eval/report.json`, `docs/writeup.md` results section | 6-7 | planned |
| I-5 | "Design for privacy" | PII redaction before any LLM call; no raw PII in logs; retention rules | shared | `docs/policy_cards.md` POL-PII-01 to 09 (exists); `docs/contracts/audit_log.md` section 2 (exists); U5 and grader step D9 in `docs/eval_plan.md` (exists) | 2, 5 | planned |
| I-6 | "Design for ... explainability" | Audit log with sources, rule ids and tool results | Martín | `docs/contracts/audit_log.md` (exists); sample export in `docs/writeup.md` | 5 | planned |
| I-7 | "Design for ... fairness" | Outcome comparison by language, variant, country and segment | Aldair | `docs/eval_plan.md` section 9.3 (exists) | 4, 7 | planned |
| I-8 | "Design for ... reliability" | Bounded retries, safe fallback, verified actions | Martín | POL-REL-01 to 04, POL-ACT-05 (exist); golden dialogue 10; tool-failure templates in `eval/report.json` | 5-7 | planned |
| I-9 | "Design for ... scalability" | Capacity estimate and load test | Martín | `docs/operations.md` section 1 (placeholder, planned test); token use per conversation in `docs/eval_plan.md` 13.2 (exists) | 7 | **gap** (G-4 remainder) |
| I-10 | "Make explicit trade-offs across autonomy, accuracy, latency, cost, and human oversight" | Conformal alpha sweep: coverage, act / clarify / transfer shares, and end-to-end SAR, unsafe rate, transfer rate, p95 latency and cost per alpha on the dev set | Aldair | `docs/eval_plan.md` section 8.4 (exists); `eval/report.json` `classifier_eval.alpha_sweep`; chosen operating point in `docs/writeup.md` | 5, 7 | planned |
| I-11 | "Justify where AI is appropriate, where deterministic logic is preferable" | Proposal section 5 table (classifier + LLM phrasing vs rules/gateway) | shared | `docs/proposal.md` section 5 (exists); `docs/writeup.md` architecture section | 2, 8 | planned |
| I-12 | "how you evaluate the system for quality and safety" | Scenario-based eval with grader, pass^k, adverse cases | Aldair | `docs/eval_plan.md` (exists), `eval/report.json` | 4-7 | planned |

## Scope

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| S-1 | "Deliver a working prototype" | Chat + orchestrator + mock bank + case inbox | Martín | Deployed URL, demo recording | 8 | planned |
| S-2 | "evidence of production readiness" | Tracing, retries, fallback, clean-clone test, audit log, monitoring and access controls | Martín | `docs/operations.md` (exists, draft), trace samples, `docs/contracts/audit_log.md` (exists) | 5-8 | planned |
| S-3 | "an honest account of the work required before deployment" | Remaining-work section | shared | `docs/operations.md` section 5 (exists, draft; shared review before Day 7) | 2, 7 | planned |
| S-4 | "Select a coherent workflow" | Card and account inquiries: balance inquiry as the core, data-native intent (Day 2 P4), plus card status, card transactions, card block and handoff (our extension, P2) | shared | `docs/proposal.md` v3.1 sections 1, 3 and 4 (exists); `docs/intents.md` (exists) | 1-2 | planned |
| S-5 | "Include a normal resolution path" | Balance inquiry; transaction inquiry; card block with confirmation | shared | Golden dialogues 1 to 3, 11 and 12 (exist); `normal` templates, `docs/eval_plan.md` 3.2 | 4 | planned |
| S-6 | "an ambiguous or unsupported request" | Multi-card disambiguation (S1 personas); out-of-scope request (S4 no-card customer) | shared | Golden dialogues 3 and 4 (exist); `ambiguous` templates; `docs/findings/day2/personas.md` (exists) | 4 | planned |
| S-7 | "a case requiring human intervention" | Dispute, unblock, "why was I blocked?", `Suspended`/`Closed` customer -> handoff with case file | shared | Golden dialogues 5 and 6 (exist); `handoff` templates incl. POL-AUTH-09 (`docs/eval_plan.md` 3.2); case inbox screenshot | 4 | planned |
| S-8 | "Demonstrate interactions in Spanish" | es utterances + es demo | shared | Golden dialogues in es (exist); demo recording (es); per-language rows in `eval/report.json` | 4 | planned |
| S-9 | "... and Portuguese" | pt utterances (team-generated) + pt demo | shared | Golden dialogues in pt (exist); demo recording (pt); per-language rows in `eval/report.json` | 5 | planned |
| S-10 | "report limitations in the supplied data or language coverage" | Limitations section (synthetic data, random codes, no pt in data, placeholder transcripts) | Aldair | `docs/proposal.md` section 11 (exists); `docs/contracts/gold_tables.md` section 6 (exists); `docs/data_card.md` | 8 | planned |

## What your solution should demonstrate

### 1. A problem supported by data

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D1-1 | "Analyze contact reasons" | Day 1 contact-reason analysis | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists) | 1 | planned |
| D1-2 | "relevant demand patterns" | Day 2 P4: the only demand in the transcripts is balance inquiry (100% of 59,786 Transaccional transcripts; 50.07% credit card, 49.93% savings); P2: card holding, multi-card ambiguity and card activity | Aldair | `docs/findings/day2/personas.md` section (b) (exists), `docs/findings/day1/P2_card_support.md` (exists) | 1-2 | planned |
| D1-3 | "data quality" | Day 1 C1 data-quality audit | Aldair | `docs/findings/day1/C1.md` (exists) | 1 | planned |
| D1-4 | "operational constraints" | Handle time, wait time, FCR baseline; card activity sparsity | Aldair | `docs/findings/day1/P1_contact_prioritization.md`, `P2_card_support.md` (exist) | 1 | planned |
| D1-5 | "Use this evidence to prioritize the workflow" | Day 1 decision and amendment | shared | `docs/decision_day1.md` (exists) | 1 | planned |
| D1-6 | "define the intended customer and business outcomes" | Targets: match human FCR safely, wait near zero | shared | `docs/proposal.md` v3.1 section 3 (exists: balance is the demand the transcripts show, the card flow is our extension supported by P2); targets T4 and T8 in `docs/eval_plan.md` 9.1 (exist) | 2 | planned |

### 2. A functioning AI system

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D2-1 | "Maintain relevant conversational context" | State machine holding selected card, pending action, slots | shared | `docs/contracts/state_machine.md` section 3 (exists); multi-turn golden dialogues (exist) and templates | 3-4 | planned |
| D2-2 | "clarify ambiguity" | Conformal prediction sets -> clarify when 2+ candidates; card disambiguation by last 4 | Aldair | POL-ESC-06, POL-ANS-07 to 09 (exist); clarification rate + coverage in `eval/report.json` | 5 | planned |
| D2-3 | "ground factual responses in permitted account, transaction" data | Tools over gold tables; LLM only words verified facts; grounding check | Martín | POL-GEN-02 (exists); `docs/contracts/gold_tables.md` (exists); grader steps D4 and J1 in `docs/eval_plan.md` | 3-6 | planned |
| D2-4 | "... or policy information" | Written card policy the assistant can cite | Aldair | `docs/policy_cards.md` (exists, SYNTHETIC); policies as code citing the same rule IDs | 2-3 | planned |
| D2-5 | "Use tools when they serve the workflow" | Tool contracts, including the balance tools; tools allowed per state | shared | `docs/proposal.md` section 8 and `docs/contracts/state_machine.md` section 2 (exist); tool-call counts per scenario | 2 | planned |
| D2-6 | "report only actions whose outcomes the system has verified" | `block_card` returns only acceptance; the action gateway re-reads the card status and only a `Blocked` read is reported as done | Martín | POL-ACT-05, 09 to 11 and INV-04 (exist); audit `verification` event (exists); unsafe outcome U3 in `docs/eval_plan.md` 5.5 | 3 | planned |

### 3. Controlled automation

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D3-1 | "Define which requests the system can answer" | Final intent taxonomy (12 intents), slots, in-scope / out-of-scope list | Aldair | `docs/intents.md` (exists: taxonomy, slots, labeling rules, examples, hard negatives); `docs/policy_cards.md` section 3 (exists) | 2 | planned |
| D3-2 | "which actions require confirmation" | Policy: `block_card` needs step-up + confirmation token | Aldair | POL-ACT-01 to 04 (exist); policies as code + tests | 3 | planned |
| D3-3 | "when it must abstain or transfer to a human" | Conformal set empty/too large -> handoff; policy list of transfer triggers; customer status | Aldair | POL-ESC-01 to 12, POL-AUTH-09 (exist); escalation metrics in `docs/eval_plan.md` 5.4 | 3, 5 | planned |
| D3-4 | "Enforce permissions and policy outside model-generated prose" | Service-layer rules, action gateway, tools allowed per state | Martín | POL-GEN-01, POL-AUTH-05, `docs/contracts/state_machine.md` sections 2 and 8 (exist); unit tests: tool call with another customer's card is refused regardless of LLM output | 3 | planned |
| D3-5 | Handoff includes "the request" | Case file field `request` | Martín | POL-HND-10 (exists); golden case files (exist) | 2, 4 | planned |
| D3-6 | Handoff includes "verified facts" | Case file field `verified_facts` (from tool results only) | Martín | POL-HND-11 (exists); golden case files (exist) | 2, 4 | planned |
| D3-7 | Handoff includes "actions taken" | Case file field `actions_taken` (from the action gateway) | Martín | POL-HND-12 (exists); golden dialogue 10 (exists) | 2, 4 | planned |
| D3-8 | Handoff includes "supporting evidence" | Case file field `evidence` (tool calls, product and transaction IDs, security events) | Martín | POL-HND-13 (exists); golden case files (exist) | 2, 4 | planned |
| D3-9 | Handoff includes "unresolved questions" | Case file field `unresolved_questions` | Martín | POL-HND-14 (exists); golden case files (exist) | 2, 4 | planned |

The five case-file fields and their metadata are defined in `docs/policy_cards.md` section 8
(POL-HND-10 to 15); `handoff_ok` in `docs/eval_plan.md` 5.4 validates them.

### 4. Sound data and ML practice

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D4-1 | "repeatable data preparation" | Kedro pipelines `data_ingestion` -> `data_quality` -> `gold` | Aldair | `kedro run` from clean clone; `ml/src/banking_cs/pipelines/` | 2 | planned |
| D4-2 | "with contracts" | Table contracts (grain, keys, required columns, allowed values) | Aldair | `docs/findings/day1/C1_contracts.json` (exists); `docs/contracts/gold_tables.md` (exists) | 2 | planned |
| D4-3 | "quality checks" | `data_quality` pipeline asserting C1 contracts; gold checks GQ-01 to GQ-22 | Aldair | `docs/contracts/gold_tables.md` section 5 (exists); quality report in `ml/data/08_reporting/`; pipeline tests | 2 | planned |
| D4-4 | "lineage" | `source_file`, `gold_batch_id`, `gold_loaded_at` from raw file to gold row; load log | Aldair | `source_file` in 02_intermediate (exists); `docs/contracts/gold_tables.md` section 1 (exists); kedro-viz graph | 2 | planned |
| D4-5 | "an update/freshness policy" | Daily batch, idempotent upsert by key, later delivery wins, freshness SLA | Aldair | `docs/contracts/freshness_policy.md` sections 2 to 5 (exists); pipeline `gold` | 3 | planned |
| D4-6 | "Evaluate at least one learned component against an appropriate baseline" | Intent/slot classifier vs majority, rules, TF-IDF+LR, LLM zero-shot | Aldair | `docs/eval_plan.md` section 8.3 (exists); `docs/model_card_intent.md` | 3, 5 | planned |
| D4-7 | "Use valid labels or relevance judgments" | Team-generated utterances from a written labeling guide + human-validated sample with kappa (native transcript label dropped: P5 refuted) | Aldair | `docs/intents.md` (labeling guide, exists); `docs/eval_plan.md` 8.1 and 13.4 (exist); kappa in model card; `docs/findings/day2/personas.md` (exists) | 4 | planned |
| D4-8 | "prevent leakage" | Split by seed group (paraphrases and translations); guide examples train-only; `fraud_score`, `main_topics` (copy of `contact_reason`) and `detected_intents` (constant) excluded | Aldair | `docs/eval_plan.md` 8.2 (exists); `docs/intents.md` section 4 (exists); `docs/proposal.md` section 6 (exists); split code + leakage section in model card | 3 | planned |
| D4-9 | "justify representations" | TF-IDF vs embeddings vs LLM baseline comparison | Aldair | `docs/eval_plan.md` 8.3 (exists); model card | 5 | planned |
| D4-10 | "justify ... metrics" | Macro-F1, empirical coverage, set size, clarification rate | Aldair | `docs/eval_plan.md` 8.4 (exists); model card | 5 | planned |
| D4-11 | "justify ... thresholds" | Conformal alpha 0.10 pre-registered; threshold fitted on the calibration split | Aldair | `docs/eval_plan.md` 8.4 (exists); model card | 5 | planned |
| D4-12 | "justify ... evaluation splits" | Group split 60/20/20; pt evaluated separately, pt-native subset | Aldair | `docs/eval_plan.md` 8.2 (exists); model card | 3 | planned |

### 5. Measured quality and failure handling

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D5-1 | "Evaluate on held-out cases" | Held-out A: 40 templates, 160 cases, hidden state from real customers; held-out B if the system changes | Aldair | `docs/eval_plan.md` section 3 (exists); `eval/scenarios/heldout_a/` | 4 | planned |
| D5-2 | "Include incorrect or missing data" | Adversarial templates: null merchant or code, unknown response code (fixture), balance above limit, transaction outside card validity dates | Aldair | `docs/eval_plan.md` 3.2 and 3.5 (exists); POL-ESC-05, POL-DEC-90/91 | 4 | planned |
| D5-3 | "expired sessions" | Adversarial templates (2) | Aldair (templates) · Martín (handling) | `docs/eval_plan.md` 3.2 (exists); golden dialogue 9 (exists); result rows | 4 (templates), 6 (handling) | planned |
| D5-4 | "unauthorized access attempts" | Adversarial templates: another customer's card number; another person's data | Aldair (templates) · Martín (handling) | `docs/eval_plan.md` 3.2 (exists); golden dialogue 7 (exists); result rows | 4 (templates), 6 (handling) | planned |
| D5-5 | "prompt injection" | Adversarial templates (one-time; repeated) | Aldair (templates) · Martín (handling) | `docs/eval_plan.md` 3.2 (exists); golden dialogue 8 (exists); result rows | 4 (templates), 6 (handling) | planned |
| D5-6 | "tool failures" | Adversarial templates + bounded retries (`tool_fault` fixture) | Aldair (templates) · Martín (handling) | `docs/eval_plan.md` 3.2 and 3.5 (exists); golden dialogue 10 (exists); result rows | 4 (templates), 6 (handling) | planned |
| D5-7 | "multilingual ambiguity" | Adversarial templates (es/pt mixed with no preference, regional slang) | Aldair (templates) · Martín (handling) | `docs/eval_plan.md` 3.2 (exists); `docs/intents.md` regional examples (exists); result rows | 4 (templates), 6 (handling) | planned |
| D5-8 | "Report successful outcomes" | Safe automated resolution (see E-9, E-10) | Aldair | `docs/eval_plan.md` 5.2 (exists); `eval/report.json` | 7 | planned |
| D5-9 | "unsafe outcomes" | See E-14, E-15 | Aldair | `docs/eval_plan.md` 5.5 (exists); `eval/report.json` | 7 | planned |
| D5-10 | "handoff behavior" | See E-12, E-13 | Aldair | `docs/eval_plan.md` 5.4 (exists); `eval/report.json` | 7 | planned |
| D5-11 | "latency" | p50/p95 per turn, time to first reply, per-case system time | Martín | `docs/eval_plan.md` 5.6 (exists); `eval/report.json` | 7 | planned |
| D5-12 | "and cost" | Token cost per case at list prices; pre-run estimate | Martín | `docs/eval_plan.md` 5.7 and 13.2 (exist); `eval/report.json` | 7 | planned |
| D5-13 | "together with sample sizes and limitations" | n, intervals and limitations per metric and cell | Aldair | `docs/eval_plan.md` sections 5 and 12 (exists); `eval/report.json`, `docs/writeup.md` | 7 | planned |

### 6. A credible route to operation

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D6-1 | "Demonstrate tracing" | Per-request trace ids across orchestrator and tools | Martín | `trace_id` / `span_id` in every audit event, `docs/contracts/audit_log.md` section 3 (exists); trace sample in `docs/operations.md` 3.3 (placeholder) | 5 | planned |
| D6-2 | "bounded retries" | Retry policy with max attempts | Martín | POL-REL-01, `READ_RETRIES` (exist); golden dialogue 10 (exists); tool-failure result rows | 7 | planned |
| D6-3 | "safe fallback" | Template fallback, transfer on repeated failure, local queue if handoff fails | Martín | POL-REL-03, 04, POL-ESC-07 (exist); tool-failure result rows | 7 | planned |
| D6-4 | "reproducible setup" | Clean-clone test, README, lock files | Martín | README; clean-clone log | 7-8 | planned |
| D6-5 | "Explain capacity limits" | Load test and resulting limit | Martín | `docs/operations.md` section 1 (placeholder with the planned test) | 7 | **gap** (G-4 remainder) |
| D6-6 | "monitoring" | Signals M-1 to M-11 and health checks | Aldair (draft) · Martín (implementation) | `docs/operations.md` section 3 (exists, draft); stale-gold check in `docs/contracts/freshness_policy.md` section 2 (exists) | 2, 7 | planned |
| D6-7 | "access controls" | Roles, service-layer checks, secrets | Aldair (draft) · Martín (implementation) | `docs/operations.md` section 2 (exists, draft); POL-PII-07, `docs/contracts/audit_log.md` section 6 (exist) | 2, 7 | planned |
| D6-8 | "data retention" | Retention per store and deletion procedure | Aldair (policy) · Martín (deletion job) | POL-PII-06 and section 11 values (exist); `docs/operations.md` section 4 (exists, draft: per-store table, procedure, production values left to the bank); deletion job and its test not built | 7 | planned (G-3: job remaining) |
| D6-9 | "the remaining deployment work" | Remaining-work table | shared | `docs/operations.md` section 5 (exists, draft) | 2, 7 | planned |
| D6-10 | "explanations based on sources, policy rules, and execution records" | Audit log citing tool results and rule ids; no chain-of-thought | Martín | POL-AUD-01, 02 (exist); `docs/contracts/audit_log.md` (exists); sample case explanation | 5 | planned |

## Architecture freedom (requirements it contains)

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| A-1 | Rigor via "component selection, relevance or intent labels, representations, leakage prevention, held-out evaluation, and error analysis" | Classifier evaluation + error analysis | Aldair | `docs/eval_plan.md` sections 8 and 10 (exists); `docs/model_card_intent.md` | 5, 7 | planned |
| A-2 | "Use batch, incremental, or streaming processing according to ... latency and freshness needs" | Daily batch with incremental partitions; justification | Aldair | `docs/contracts/freshness_policy.md` sections 2 and 3 (exists) | 3 | planned |
| A-3 | "If only static data is supplied, demonstrate update correctness with a clearly labeled test fixture" | Labeled fixture: card Active -> Blocked and a new transaction, with expected gold state and tests FX-1 to FX-7 | Aldair | `docs/contracts/freshness_policy.md` section 6 (exists); `ml/tests/fixtures/update/`, `ml/tests/pipelines/gold/test_incremental_update.py` | 3 | planned |

## Data and execution boundaries

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| B-1 | "Use only organizer-approved data and permitted external resources" | Supplied dataset + declared LLM provider | shared | `docs/data_card.md` sources section | 8 | planned |
| B-2 | "Identify which inputs are real, de-identified, synthetic, or team-generated" | Provenance table (dataset synthetic; utterances, pt, fixtures team-generated) | Aldair | `docs/data_card.md` | 8 | planned |
| B-3 | "follow the published data-use terms" | Terms checked and cited | shared | `docs/data_card.md` | 8 | planned |
| B-4 | "Do not include private customer records, credentials, or restricted data in public submissions" | Git rules (no `ml/data/`, no credentials) | shared | `.gitignore`; CLAUDE.md rules; POL-PII-08; pre-submission check | 8 | planned |
| B-5 | "... or external model requests" | PII redaction and field allowlist before LLM calls | shared | POL-PII-01 to 03, INV-09 (exist); U5 and grader step D9 in `docs/eval_plan.md` (exists); redaction unit tests | 5 | planned |
| B-6 | "Sandbox services and mock banking tools ... contracts and limitations are documented" | Mock bank over gold (including `balance_products`), tool contracts, overlay for actions | Martín | `docs/contracts/gold_tables.md` sections 4b and 6 (exist); `docs/contracts/freshness_policy.md` section 5 (exists); `docs/proposal.md` section 8 (exists); tool contract doc with the overlay reset procedure (open gap 4) | 2-3 | planned |
| B-7 | "Demonstrate authentication with a trusted test session or identity service" | Mock identity with session expiry, step-up and customer status | Martín | POL-AUTH-01 to 09 (exist); auth tests; expired-session and customer-status templates | 2 | planned |
| B-8 | "a national ID or customer number alone does not prove identity" | Login requires test credentials, not `customer_id` / `document_number` | Martín | POL-AUTH-02 (exists); golden dialogue 7; auth test: customer number alone is rejected | 2 | planned |
| B-9 | "Enforce access to each customer's records and action permissions in the service or tool layer" | Session-scoped tools; step-up for actions; tools allowed per state | Martín | POL-AUTH-05, `docs/contracts/state_machine.md` section 2 (exist); unauthorized-access templates; unit tests | 3 | planned |
| B-10 | Credit workflows: separate conversation, risk estimates, eligibility policy | Not applicable: no credit workflow (Day 1 P3: credit signal AUC 0.50) | shared | `docs/proposal.md` section 2; write-up scope note | 8 | planned |
| B-11 | "No live lending decisions or movement of money" | Out of scope by design; no money-moving tool | shared | `docs/proposal.md` section 4; POL-ACT-08 (exist) | 2 | planned |

## Evaluation evidence

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| E-1 | "Compare your baseline and proposed system on the same held-out workload" | Naive LLM agent (same tools, no policy engine) vs our system | Aldair | `docs/eval_plan.md` section 1.2 (exists); `eval/report.json` both systems | 6 | planned |
| E-2 | "Report the number and mix of cases" | Case counts by category, sub-type, language, variant, country, segment | Aldair | `docs/eval_plan.md` 3.2 and 3.3 (exists); `eval/report.json` `workload` | 7 | planned |
| E-3 | "label quality" | Kappa on a 200-utterance human-labeled sample (≥ 30 hard negatives) | Aldair | `docs/eval_plan.md` 8.1 and 13.4 (exist); `docs/intents.md` (exists); model card; eval report | 4 | planned |
| E-4 | "model and prompt versions" | Model IDs, prompt hashes, classifier artifact hash, intents version and commit in every run record and LLM call | Martín | `docs/eval_plan.md` 6.2 (exists); `llm_call` event in `docs/contracts/audit_log.md` (exists); `run_config` in the report schema (exists); sampling settings open (gap 3) | 5 | planned |
| E-5 | "repeated-run variability where relevant" | 5 runs per case per system; pass^k; mean, sd, min and max of every headline metric; budget fallback (naive k = 3, or k = 5 on a stratified subset) | Aldair | `docs/eval_plan.md` 6.1 and 13.5 (exist) | 6 | planned |
| E-6 | "Include failures in the results" | Every failed run with checks and root cause; flaky cases | Aldair | `docs/eval_plan.md` section 10 (exists); `eval/report.json` `failures`; `docs/writeup.md` error analysis | 7 | planned |
| E-7 | "If you use a model to judge answers, document its rubric" | Judge rubric J1 to J7 | Aldair | `docs/eval_plan.md` 7.3 (exists); `eval/judge_rubric.md` | 4 | planned |
| E-8 | "validate a sample against human or deterministic judgments" | 80 judge decisions labeled by both of us; 30 runs hand-graded against the deterministic grader; about 29 person-hours budgeted | Aldair | `docs/eval_plan.md` 7.4 and 13.4 (exist); `eval/report.json` `grader_validation` | 6-7 | planned |
| E-9 | Safe automated resolution: "rate over all in-scope test cases" | Grader flag `safe_resolved`; `SAR_rate` | Aldair | `docs/eval_plan.md` 5.1 and 5.2 (exists); `eval/report.json` | 7 | planned |
| E-10 | "... plus the share of cases on which automation was attempted" | `attempted` flag; `attempt_share` | Aldair | `docs/eval_plan.md` 5.1 and 5.2 (exists); `eval/report.json` | 7 | planned |
| E-11 | Containment: "A case ends without transfer" (not proof of resolution) | Containment reported with its split, next to SAR | Aldair | `docs/eval_plan.md` 5.3 (exists); `eval/report.json` | 7 | planned |
| E-12 | Escalation quality: "transferred correctly and include useful handoff context" | Reference `requires_handoff` labels + `handoff_ok` (case-file contract, priority, reasons, judge J5) | Aldair | `docs/eval_plan.md` 5.4 (exists); `eval/report.json` | 7 | planned |
| E-13 | "Report both missed and unnecessary transfers" | `missed_transfer_rate`, `unnecessary_transfer_rate`, full 2×2 | Aldair | `docs/eval_plan.md` 5.4 (exists); `eval/report.json` | 7 | planned |
| E-14 | Unsafe outcomes "with counts and denominators" | U1 to U5 with counts, case and run rates, category denominators | Aldair | `docs/eval_plan.md` 5.5 (exists); `eval/report.json` | 7 | planned |
| E-15 | "Zero observed failures in a small test set does not establish zero risk" | One-sided 95% Clopper-Pearson upper bound next to every unsafe count | Aldair | `docs/eval_plan.md` 5.5 (exists); `case_rate_upper_bound_95` in the report schema (exists) | 7 | planned |
| E-16 | Operating efficiency: "p50/p95 latency" | End-to-end timing per turn and per case | Martín | `docs/eval_plan.md` 5.6 (exists); `eval/report.json` | 7 | planned |
| E-17 | "cost per attempted case and per successful automated resolution" | `cost_per_attempted_case` and `cost_per_SAR`; pre-run estimate $0.021 per `proposed` case | Martín | `docs/eval_plan.md` 5.7 and 13.2 (exist); `eval/report.json` | 7 | planned |
| E-18 | "State the workload, sample size, and cost assumptions; use 'not defined'" | Report header with workload and price table; "not defined" when 0 safe resolutions; model and price assumptions | Martín | `docs/eval_plan.md` 5.7 and 13.1 (exist); `cost_assumptions` and `not_defined` in the report schema (exists) | 7 | planned |
| E-19 | "Compare relevant service outcomes by language and authorized customer segments" | Per-language, variant, country and segment breakdown for both systems | Aldair | `docs/eval_plan.md` 9.3 (exists); `eval/report.json` `breakdowns` | 7 | planned |
| E-20 | "state small-sample limitations, and investigate disparities" | Wilson intervals per cell; within-template permutation test with Holm correction; investigation of every flag | Aldair | `docs/eval_plan.md` 9.3 (exists); `eval/report.json` `disparities` | 7 | planned |
| E-21 | "Label offline measurements, simulations, and projected business savings separately" | Separate report sections; savings as projection | Aldair | `docs/eval_plan.md` sections 1.1 and 10 (exists); `evidence_label` in the report schema (exists); `docs/writeup.md` | 8 | planned |
| E-22 | "Do not describe an offline comparison as a measured production improvement" | Wording rule in write-up review | shared | `docs/eval_plan.md` preamble (exists); `docs/writeup.md` | 8 | planned |

## Gaps and resolutions

| Gap | Rows | Status | Where it is closed, or what remains | Owner | Day |
|---|---|---|---|---|---|
| G-1 Update/freshness policy and test fixture | D4-5, A-2, A-3 | closed (design) | `docs/contracts/freshness_policy.md`: daily batch after the 06:00 cutoff, idempotent upsert by key where the later delivery wins (`last_updated` is not used: 6.2% of card values are in the future), load log, and the labeled fixture (card Active -> Blocked, new transaction) with expected gold state and tests FX-1 to FX-7. Remaining: implement the `gold` pipeline, fixture and test. | Aldair | 3 |
| G-2 Segment and language comparison | I-7, E-19, E-20 | closed (plan) | `docs/eval_plan.md` 3.3 (balanced Latin-square design: 40 cases per variant and per segment) and 9.3 (Wilson intervals, within-template permutation test with Holm correction, investigation of every flag, "team-written Portuguese" wording rule). Only authorized attributes are used. | Aldair | 4 (design), 7 (report) |
| G-3 PII redaction and data retention | I-5, B-5, D6-8 | closed (design) | Redaction and allowlist rules (POL-PII-01 to 05), no raw PII in the audit log (`docs/contracts/audit_log.md` section 2), U5 check and grader step D9 (`docs/eval_plan.md`), retention values (POL-PII-06, section 11), per-store retention and deletion procedure (`docs/operations.md` section 4; production values are the bank's). Remaining: deletion job, redaction unit tests. | Martín (redaction, job), Aldair (policy) | 5, 7 |
| G-4 Operations write-up | S-3, I-9, D6-5, D6-6, D6-7, D6-9 | partly closed | `docs/operations.md` (`ops-0.1`, draft by Aldair): access controls (section 2), monitoring signals M-1 to M-11 and health checks (section 3), retention and deletion (section 4), remaining deployment work (section 5). Remaining: capacity and load test (section 1) and the trace sample (3.3), then a shared review. | Aldair (draft, done), Martín (capacity, Day 7) | 2, 7 |
| G-5 Written card policy | D2-4 | closed | `docs/policy_cards.md` (SYNTHETIC, `cards-synthetic-0.4`) with stable rule IDs, cited by `docs/contracts/state_machine.md`, the golden conversations and the audit log. Remaining: policies as code citing the same IDs (Day 3 build). | Aldair | 3 |
| G-6 LLM judge validation | E-7, E-8 | closed (plan) | `docs/eval_plan.md` 7.1 to 7.4: deterministic grader first, judge can only fail a case, rubric J1 to J7, 80-decision human sample with kappa and false-pass rate, acceptance rule, 30 hand-graded runs. | Aldair | 4 (rubric), 6 (validation) |
| G-7 Repeated-run variability | E-5 | closed (plan) | `docs/eval_plan.md` 6.1: n = 5 runs per case per system, pass^1 to pass^5, mean, sd, min and max of each headline metric. | Aldair | 6 |
| G-8 Incorrect or missing data cases | D5-2 | closed (plan) | `docs/eval_plan.md` 3.2 (2 adversarial templates) and 3.5 (`unknown_response_code` fixture; real rows for null merchant or code, validity-date contradictions, balance above limit). | Aldair | 4 |
| G-9 Explicit trade-offs | I-10 | closed (plan) | `docs/eval_plan.md` 8.4: alpha sweep on the classifier (test split) and end-to-end on the dev set (SAR, unsafe rate, transfer rate, p95 latency, cost per alpha). Remaining: chart and chosen operating point in `docs/writeup.md`. | Aldair | 7 |
| G-10 Model and prompt versions | E-4 | closed (plan) | `docs/eval_plan.md` 6.2 run record, `run_config` and `systems` in `docs/contracts/eval_report.schema.json`, `llm_call` audit event (model ID, prompt hash per call). | Martín | 5 |
| G-11 Unsafe-rate upper bound | E-15 | closed (plan) | `docs/eval_plan.md` 5.5: one-sided 95% Clopper-Pearson bound next to every count (1.85% for 0 of 160), and the n needed for 1% (about 300). | Aldair | 7 |
| G-12 Balance inquiry scope | S-4, D2-5, B-6 | closed | Approved: `docs/proposal.md` v3.1 sections 1, 3, 4 and 8; `balance_products` in `docs/contracts/gold_tables.md` section 4b (`gold-0.2`, GQ-23 to GQ-29); golden flag F-29 closed. | shared | 2 |
| G-13 Customer status `Suspended` / `Closed` | D3-3, B-7 | closed | POL-AUTH-09 and template POL-HND-07 (`cards-synthetic-0.4`); T-51, G-02 and INV-14 (`sm-0.3`); held-out handoff template with reference labels (`docs/eval_plan.md` 3.2, 3.4). | Aldair (policy, template), Martín (implementation) | 3-4 |
| G-14 Evaluation cost, runtime and human time | E-5, E-8, E-17, E-18 | closed (plan), budget value open | `docs/eval_plan.md` 13: calls and tokens per run per role, prices, total for the full plan, wall-clock time, human labeling time, budget cap with a pre-registered fallback (naive k = 3, then k = 5 on a stratified subset). Remaining: set `EVAL_BUDGET_USD` (open gap 2). | shared | 4 |
