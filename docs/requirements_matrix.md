# Requirements matrix

Maps every requirement in `docs/problem_statement.pdf` to the plan in `docs/proposal.md` (v3).
One row per atomic requirement. Day and owner come from proposal sections 9 and 10; for gaps
they are the proposed day and owner. Evidence paths that do not exist yet are proposals and
should be kept stable once created.

Status: **planned** = the proposal covers it (some rows already have evidence, noted as
"exists"); **gap** = the proposal does not cover it, or mentions it without a method or artifact.
Gaps are expanded with a proposed fix at the end.

## Intro: "Think beyond the demo"

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| I-1 | "understand complex customer interactions, use data and tools securely, complete appropriate service workflows, and involve human agents" | Whole system: classifier + orchestrator + tools + handoff | shared | End-to-end demo recording; `eval/report.json` | 4-8 | planned |
| I-2 | "Use the supplied data to explain why the problem matters" | Day 1 analysis (Transaccional = 35% of interactions) | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists), `docs/decision_day1.md` (exists) | 1 | planned |
| I-3 | "establish a baseline" | Human status quo (FCR 91.5%, 221 s handle, ~120 s wait) + naive LLM agent | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists); naive-agent run in `eval/report.json` | 1, 6 | planned |
| I-4 | "measure whether your approach improves service quality and operational efficiency" | Evaluation harness: our system vs naive agent on the same held-out scenarios | Aldair | `eval/report.json`, `docs/writeup.md` results section | 6-7 | planned |
| I-5 | "Design for privacy" | PII redaction before any LLM call; retention policy | shared | — | — | **gap** (G-3) |
| I-6 | "Design for ... explainability" | Audit log with sources, rule ids and tool results | Martín | Audit log events + sample export in `docs/writeup.md` | 5 | planned |
| I-7 | "Design for ... fairness" | Outcome comparison by language and segment | Aldair | — | — | **gap** (G-2) |
| I-8 | "Design for ... reliability" | Bounded retries, safe fallback, verified actions | Martín | Tool-failure scenarios in `eval/report.json` | 5-7 | planned |
| I-9 | "Design for ... scalability" | Capacity estimate and load test | Martín | — | — | **gap** (G-4) |
| I-10 | "Make explicit trade-offs across autonomy, accuracy, latency, cost, and human oversight" | Conformal threshold sweep (coverage vs clarification vs handoff) + cost/latency per setting | Aldair | — | — | **gap** (G-9) |
| I-11 | "Justify where AI is appropriate, where deterministic logic is preferable" | Proposal section 5 table (classifier + LLM phrasing vs rules/gateway) | shared | `docs/proposal.md` section 5; `docs/writeup.md` architecture section | 2, 8 | planned |
| I-12 | "how you evaluate the system for quality and safety" | Scenario-based eval with grader, pass^k, adverse cases | Aldair | `eval/README.md` (method), `eval/report.json` | 4-7 | planned |

## Scope

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| S-1 | "Deliver a working prototype" | Chat + orchestrator + mock bank + case inbox | Martín | Deployed URL, demo recording | 8 | planned |
| S-2 | "evidence of production readiness" | Tracing, retries, fallback, clean-clone test, audit log | Martín | `docs/operations.md`, trace samples | 5-8 | planned |
| S-3 | "an honest account of the work required before deployment" | Remaining-work section | shared | — | — | **gap** (G-4) |
| S-4 | "Select a coherent workflow" | Card and transaction inquiries (list, status, describe, block, handoff) | shared | `docs/proposal.md` sections 1 and 4 | 1 | planned |
| S-5 | "Include a normal resolution path" | Transaction inquiry; card block with confirmation | shared | Scenarios tagged `normal` in `eval/scenarios/` | 4 | planned |
| S-6 | "an ambiguous or unsupported request" | Multi-card disambiguation (S1 personas); out-of-scope request (S4 no-card customer) | shared | Scenarios tagged `ambiguous` / `unsupported`; `docs/findings/day2/personas.md` (exists) | 4 | planned |
| S-7 | "a case requiring human intervention" | Dispute, unblock, "why was I blocked?" -> handoff with case file | shared | Scenarios tagged `handoff`; case inbox screenshot | 4 | planned |
| S-8 | "Demonstrate interactions in Spanish" | es utterances + es demo | shared | Demo recording (es); per-language rows in `eval/report.json` | 4 | planned |
| S-9 | "... and Portuguese" | pt utterances (team-generated) + pt demo | shared | Demo recording (pt); per-language rows in `eval/report.json` | 5 | planned |
| S-10 | "report limitations in the supplied data or language coverage" | Limitations section (synthetic data, random codes, no pt in data, placeholder transcripts) | Aldair | `docs/proposal.md` section 11; `docs/data_card.md` | 8 | planned |

## What your solution should demonstrate

### 1. A problem supported by data

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D1-1 | "Analyze contact reasons" | Day 1 contact-reason analysis | Aldair | `docs/findings/day1/P1_contact_prioritization.md` (exists) | 1 | planned |
| D1-2 | "relevant demand patterns" | Day 1 B1 failure demand, P2 card activity | Aldair | `docs/findings/day1/B1.md`, `P2_card_support.md` (exist) | 1 | planned |
| D1-3 | "data quality" | Day 1 C1 data-quality audit | Aldair | `docs/findings/day1/C1.md` (exists) | 1 | planned |
| D1-4 | "operational constraints" | Handle time, wait time, FCR baseline; card activity sparsity | Aldair | `docs/findings/day1/P1_contact_prioritization.md`, `P2_card_support.md` (exist) | 1 | planned |
| D1-5 | "Use this evidence to prioritize the workflow" | Day 1 decision and amendment | shared | `docs/decision_day1.md` (exists) | 1 | planned |
| D1-6 | "define the intended customer and business outcomes" | Targets: match human FCR safely, wait near zero | shared | `docs/proposal.md` section 3. Note: Day 2 P4 found transcripts only contain balance inquiries, so "these contacts are card inquiries" is our framing, not a data finding (`docs/findings/day2/personas.md`) | 2 | planned |

### 2. A functioning AI system

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D2-1 | "Maintain relevant conversational context" | State machine holding selected card, pending action, slots | shared | Multi-turn scenarios in `eval/scenarios/`; state machine spec | 3-4 | planned |
| D2-2 | "clarify ambiguity" | Conformal prediction sets -> clarify when >1 candidate; card disambiguation by last 4 | Aldair | Clarification rate + coverage in `eval/report.json` | 5 | planned |
| D2-3 | "ground factual responses in permitted account, transaction" data | Tools over gold tables; LLM only paraphrases verified facts | Martín | Grounding check in grader (every number in the reply appears in a tool result) | 3-6 | planned |
| D2-4 | "... or policy information" | Written card policy the assistant can cite | Aldair | — | — | **gap** (G-5) |
| D2-5 | "Use tools when they serve the workflow" | Tool contracts in proposal section 8 | shared | `backend/` tool contracts doc; tool-call counts per scenario | 2 | planned |
| D2-6 | "report only actions whose outcomes the system has verified" | Action gateway re-reads card status after `block_card` | Martín | `block_card` returns verified status; unsafe-outcome check "claimed but not verified" | 3 | planned |

### 3. Controlled automation

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D3-1 | "Define which requests the system can answer" | Intent taxonomy with in-scope / out-of-scope list | Aldair | `docs/intents.md` (taxonomy + labeling guide) | 2 | planned |
| D3-2 | "which actions require confirmation" | Policy: `block_card` needs step-up + confirmation token | Aldair | Policies as code + tests | 3 | planned |
| D3-3 | "when it must abstain or transfer to a human" | Conformal set empty/too large -> handoff; policy list of handoff intents | Aldair | Policies as code; escalation metrics in `eval/report.json` | 3, 5 | planned |
| D3-4 | "Enforce permissions and policy outside model-generated prose" | Service-layer rules, action gateway | Martín | Unit tests: tool call with another customer's card is refused regardless of LLM output | 3 | planned |
| D3-5 | Handoff includes "the request" | Case file field `request` | Martín | Case file JSON schema; sample case in inbox | 2, 4 | planned |
| D3-6 | Handoff includes "verified facts" | Case file field `verified_facts` (from tool results only) | Martín | Case file JSON schema | 2, 4 | planned |
| D3-7 | Handoff includes "actions taken" | Case file field `actions` (from audit log) | Martín | Case file JSON schema | 2, 4 | planned |
| D3-8 | Handoff includes "supporting evidence" | Case file field `evidence` (transaction ids, tool outputs) | Martín | Case file JSON schema | 2, 4 | planned |
| D3-9 | Handoff includes "unresolved questions" | Case file field `open_questions` | Martín | Case file JSON schema | 2, 4 | planned |

Note: the proposal says "expediente completo" but does not list its fields. D3-5 to D3-9 are
planned only if the case file schema frozen on Day 2 has these five fields.

### 4. Sound data and ML practice

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D4-1 | "repeatable data preparation" | Kedro pipelines `data_ingestion` -> `data_quality` -> gold | Aldair | `kedro run` from clean clone; `ml/src/banking_cs/pipelines/` | 2 | planned |
| D4-2 | "with contracts" | Table contracts (grain, keys, required columns) | Aldair | `docs/findings/day1/C1_contracts.json` (exists); gold schemas | 2 | planned |
| D4-3 | "quality checks" | `data_quality` pipeline asserting contracts | Aldair | Quality report in `ml/data/08_reporting/`; pipeline tests | 2 | planned |
| D4-4 | "lineage" | `source_file` column from raw file to gold row | Aldair | `source_file` in 02_intermediate (exists) and gold; kedro-viz graph | 2 | planned |
| D4-5 | "an update/freshness policy" | Incremental load by partition date, dedup rule, freshness SLA | Aldair | — | — | **gap** (G-1) |
| D4-6 | "Evaluate at least one learned component against an appropriate baseline" | Intent/slot classifier vs rules, TF-IDF+LR, LLM zero-shot | Aldair | `docs/model_card_intent.md`; classifier eval table | 3, 5 | planned |
| D4-7 | "Use valid labels or relevance judgments" | Team-generated utterances + human-validated sample with kappa (native transcript label dropped: P5 refuted) | Aldair | Labeling guide; kappa in model card; `docs/findings/day2/personas.md` (exists) | 4 | planned |
| D4-8 | "prevent leakage" | Split by seed group so paraphrases do not cross; `fraud_score` and `main_topics` excluded | Aldair | Split code + leakage section in model card | 3 | planned |
| D4-9 | "justify representations" | TF-IDF vs embeddings vs LLM baseline comparison | Aldair | Model card | 5 | planned |
| D4-10 | "justify ... metrics" | Macro-F1, empirical coverage, clarification rate | Aldair | Model card | 5 | planned |
| D4-11 | "justify ... thresholds" | Conformal alpha chosen on calibration split | Aldair | Model card; threshold sweep (see G-9) | 5 | planned |
| D4-12 | "justify ... evaluation splits" | Group split; pt evaluated separately | Aldair | Model card | 3 | planned |

### 5. Measured quality and failure handling

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D5-1 | "Evaluate on held-out cases" | 40 held-out scenarios with hidden state | Aldair | `eval/scenarios/` (held-out split marked) | 4 | planned |
| D5-2 | "Include incorrect or missing data" | Adverse scenarios with bad or missing tool data | Aldair | — | — | **gap** (G-8) |
| D5-3 | "expired sessions" | Adverse scenario | Martín | Scenario + result row in `eval/report.json` | 6 | planned |
| D5-4 | "unauthorized access attempts" | Adverse scenario: another customer's card | Martín | Scenario + result row | 6 | planned |
| D5-5 | "prompt injection" | Adverse scenario | Martín | Scenario + result row | 6 | planned |
| D5-6 | "tool failures" | Adverse scenario + bounded retries | Martín | Scenario + result row | 6 | planned |
| D5-7 | "multilingual ambiguity" | Adverse scenario (es/pt mixed, regional variants) | Aldair | Scenario + result row | 6 | planned |
| D5-8 | "Report successful outcomes" | Safe automated resolution (see E-9, E-10) | Aldair | `eval/report.json` | 7 | planned |
| D5-9 | "unsafe outcomes" | See E-14, E-15 | Aldair | `eval/report.json` | 7 | planned |
| D5-10 | "handoff behavior" | See E-12, E-13 | Aldair | `eval/report.json` | 7 | planned |
| D5-11 | "latency" | p50/p95 end-to-end | Martín | `eval/report.json` | 7 | planned |
| D5-12 | "and cost" | Token cost per case | Martín | `eval/report.json` | 7 | planned |
| D5-13 | "together with sample sizes and limitations" | n per cell and limitations in report | Aldair | `eval/report.json`, `docs/writeup.md` | 7 | planned |

### 6. A credible route to operation

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| D6-1 | "Demonstrate tracing" | Per-request trace ids across orchestrator and tools | Martín | Trace sample in `docs/operations.md` | 5 | planned |
| D6-2 | "bounded retries" | Retry policy with max attempts | Martín | Tool-failure scenario result | 7 | planned |
| D6-3 | "safe fallback" | Fallback to handoff on repeated failure | Martín | Tool-failure scenario result | 7 | planned |
| D6-4 | "reproducible setup" | Clean-clone test, README, lock files | Martín | README; clean-clone log | 7-8 | planned |
| D6-5 | "Explain capacity limits" | Operations write-up | Martín | — | — | **gap** (G-4) |
| D6-6 | "monitoring" | Operations write-up | Martín | — | — | **gap** (G-4) |
| D6-7 | "access controls" | Operations write-up | Martín | — | — | **gap** (G-4) |
| D6-8 | "data retention" | Retention policy for transcripts, traces, case files | shared | — | — | **gap** (G-3) |
| D6-9 | "the remaining deployment work" | Operations write-up | shared | — | — | **gap** (G-4) |
| D6-10 | "explanations based on sources, policy rules, and execution records" | Audit log citing tool results and rule ids; no chain-of-thought | Martín | Audit log schema; sample case explanation | 5 | planned |

## Architecture freedom (requirements it contains)

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| A-1 | Rigor via "component selection, relevance or intent labels, representations, leakage prevention, held-out evaluation, and error analysis" | Classifier model card + error analysis | Aldair | `docs/model_card_intent.md`; error analysis section | 5, 7 | planned |
| A-2 | "Use batch, incremental, or streaming processing according to ... latency and freshness needs" | Batch Kedro load; justification | Aldair | — | — | **gap** (G-1) |
| A-3 | "If only static data is supplied, demonstrate update correctness with a clearly labeled test fixture" | Update/freshness fixture | Aldair | — | — | **gap** (G-1) |

## Data and execution boundaries

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| B-1 | "Use only organizer-approved data and permitted external resources" | Supplied dataset + declared LLM provider | shared | `docs/data_card.md` sources section | 8 | planned |
| B-2 | "Identify which inputs are real, de-identified, synthetic, or team-generated" | Provenance table (dataset synthetic; utterances, pt, fixtures team-generated) | Aldair | `docs/data_card.md` | 8 | planned |
| B-3 | "follow the published data-use terms" | Terms checked and cited | shared | `docs/data_card.md` | 8 | planned |
| B-4 | "Do not include private customer records, credentials, or restricted data in public submissions" | Git rules (no `ml/data/`, no credentials) | shared | `.gitignore`; CLAUDE.md rules; pre-submission check | 8 | planned |
| B-5 | "... or external model requests" | PII redaction before LLM calls | shared | — | — | **gap** (G-3) |
| B-6 | "Sandbox services and mock banking tools ... contracts and limitations are documented" | Mock bank over gold, tool contracts | Martín | Tool contract doc incl. limitations section | 2 | planned |
| B-7 | "Demonstrate authentication with a trusted test session or identity service" | Mock identity with session expiry | Martín | Auth tests; expired-session scenario | 2 | planned |
| B-8 | "a national ID or customer number alone does not prove identity" | Login requires test credentials, not `customer_id` / `document_number` | Martín | Auth test: customer number alone is rejected | 2 | planned |
| B-9 | "Enforce access to each customer's records and action permissions in the service or tool layer" | Session-scoped tools; step-up for actions | Martín | Unauthorized-access scenario; unit tests | 3 | planned |
| B-10 | Credit workflows: separate conversation, risk estimates, eligibility policy | Not applicable: no credit workflow (Day 1 P3: credit signal AUC 0.50) | shared | `docs/proposal.md` section 2; write-up scope note | 8 | planned |
| B-11 | "No live lending decisions or movement of money" | Out of scope by design; no money-moving tool | shared | `docs/proposal.md` section 4 | 2 | planned |

## Evaluation evidence

| ID | Requirement (short quote) | Our component | Owner | Evidence artifact | Day | Status |
|---|---|---|---|---|---|---|
| E-1 | "Compare your baseline and proposed system on the same held-out workload" | Naive LLM agent (same tools, no policy engine) vs our system | Aldair | `eval/report.json` both systems | 6 | planned |
| E-2 | "Report the number and mix of cases" | Scenario counts by type, language, intent | Aldair | `eval/report.json` workload section | 7 | planned |
| E-3 | "label quality" | Kappa on human-validated sample | Aldair | Model card; eval report | 4 | planned |
| E-4 | "model and prompt versions" | Versioned prompts and model ids in every run record | Martín | — | — | **gap** (G-10) |
| E-5 | "repeated-run variability where relevant" | Multiple full runs with spread | Aldair | — | — | **gap** (G-7) |
| E-6 | "Include failures in the results" | Error analysis with failing cases listed | Aldair | `docs/writeup.md` error analysis | 7 | planned |
| E-7 | "If you use a model to judge answers, document its rubric" | Grader rubric | Aldair | — | — | **gap** (G-6) |
| E-8 | "validate a sample against human or deterministic judgments" | Judge agreement on a hand-labeled sample | Aldair | — | — | **gap** (G-6) |
| E-9 | Safe automated resolution: "rate over all in-scope test cases" | Grader label `resolved_safe` | Aldair | `eval/report.json` | 7 | planned |
| E-10 | "... plus the share of cases on which automation was attempted" | Attempted flag per case | Aldair | `eval/report.json` | 7 | planned |
| E-11 | Containment: "A case ends without transfer" (not proof of resolution) | Containment rate reported next to E-9 | Aldair | `eval/report.json` | 7 | planned |
| E-12 | Escalation quality: "transferred correctly and include useful handoff context" | Handoff reference labels + case-file completeness check | Aldair | `eval/report.json` | 7 | planned |
| E-13 | "Report both missed and unnecessary transfers" | Confusion of expected vs actual handoff | Aldair | `eval/report.json` | 7 | planned |
| E-14 | Unsafe outcomes "with counts and denominators" | Unauthorized disclosure/action, materially incorrect outcome | Aldair | `eval/report.json` | 7 | planned |
| E-15 | "Zero observed failures in a small test set does not establish zero risk" | Upper confidence bound on unsafe rate | Aldair | — | — | **gap** (G-11) |
| E-16 | Operating efficiency: "p50/p95 latency" | End-to-end timing per case | Martín | `eval/report.json` | 7 | planned |
| E-17 | "cost per attempted case and per successful automated resolution" | Token cost / attempted and / resolved_safe | Martín | `eval/report.json` | 7 | planned |
| E-18 | "State the workload, sample size, and cost assumptions; use 'not defined'" | Report header with workload and price table; "not defined" when 0 resolutions | Martín | `eval/report.json` | 7 | planned |
| E-19 | "Compare relevant service outcomes by language and authorized customer segments" | Per-language and per-segment breakdown | Aldair | — | — | **gap** (G-2) |
| E-20 | "state small-sample limitations, and investigate disparities" | CIs per cell; disparity write-up | Aldair | — | — | **gap** (G-2) |
| E-21 | "Label offline measurements, simulations, and projected business savings separately" | Separate report sections; savings as projection | Aldair | `docs/writeup.md` | 8 | planned |
| E-22 | "Do not describe an offline comparison as a measured production improvement" | Wording rule in write-up review | shared | `docs/writeup.md` | 8 | planned |

## Gaps and proposed fixes

| Gap | Rows | Problem | Proposed fix | Owner | Day |
|---|---|---|---|---|---|
| G-1 Update/freshness test fixture | D4-5, A-2, A-3 | Data is a static dump; the proposal has no update policy or fixture. | Write the policy in `docs/data_card.md`: batch daily load keyed on partition date, idempotent upsert on primary key, last-write-wins by `last_updated`, freshness SLA of one day for the mock bank. Add a fixture labeled `TEST FIXTURE - not supplied data` under `ml/tests/fixtures/update/`: day N+1 partition with a new transaction, a card status change to Blocked, and a duplicate row. A pytest asserts gold after re-run: new row present, status updated, no duplicate, rerun is a no-op. Justify batch over streaming in one paragraph. | Aldair | 3 |
| G-2 Segment and language comparison | I-7, E-19, E-20 | The Day 7 plan says "results by language and segment" but defines no segments, cells or method. Portuguese is team-generated, so language differences partly measure our own writing. | Define segments from `customers.segment` and country (authorized attributes only; no gender or age). Balance the scenarios so each language x segment cell has a stated n. Report every E-9 to E-17 metric per cell with Wilson 95% CIs, flag any gap whose CI excludes zero, and look at the failing cases behind each flag. State that pt results measure team-written utterances. | Aldair | 4 (design), 7 (report) |
| G-3 PII redaction and data retention | I-5, B-5, D6-8 | "PII redaction" appears in one table cell with no design, test or retention rule. | Redaction step before every LLM call: replace names, document numbers, full card numbers, email and phone with typed placeholders and restore them after. Unit tests on synthetic PII. Audit log check that no raw PII reaches the provider. Retention section in `docs/operations.md`: what is stored (transcripts, traces, case files), how long, who can read it, deletion path; prototype stores only synthetic data. | Martín (redaction), Aldair (policy) | 5 |
| G-4 Operations write-up | S-3, I-9, D6-5, D6-6, D6-7, D6-9 | The proposal covers tracing and deploy but not capacity, monitoring, access controls or remaining work. | `docs/operations.md` with four sections. Capacity: measured throughput from a small load test plus LLM rate limits, and the resulting concurrent-session limit. Monitoring: the metrics and alerts we would run (unsafe-outcome proxy, handoff rate, p95 latency, tool error rate, classifier coverage drift). Access controls: roles (customer, agent, operator), service-layer checks, secrets handling. Remaining deployment work: real IdP, core-banking integration, pt data from real customers, security review, human-labeled production sample, legal review. | Martín, with shared review | 7 |
| G-5 Written card policy | D2-4 | "Policies as code" exist, but no human-readable policy that answers can be grounded in or cited from. The statement asks to ground responses in "policy information". | `docs/policy/card_policy.md`, labeled as a synthetic policy: which requests are answered, block rules, what needs confirmation and step-up, handoff triggers, what is never explained (decline and block causes). Each rule has an id; policies as code and audit-log entries cite the same ids. | Aldair | 3 |
| G-6 LLM judge validation | E-7, E-8 | The Day 4 plan has a "grader" but does not say whether it is deterministic or an LLM, and has no rubric or validation. | Keep the grader deterministic wherever the hidden state decides the outcome (card status, handoff flag, tool calls). Use an LLM judge only for reply quality and handoff-context usefulness, with a written rubric in `eval/judge_rubric.md`. Validate it on at least 50 cases hand-labeled by both of us: report agreement and kappa with the human labels, and version the judge prompt. | Aldair | 4 (rubric), 6 (validation) |
| G-7 Repeated-run variability | E-5 | pass^k measures per-scenario consistency but gives no spread for the headline metrics. | Run the full eval k = 5 times per system with fixed scenarios and a fixed temperature. Report mean and min-max for each metric in E-9 to E-17, and pass^k alongside. | Aldair | 6 |
| G-8 Incorrect or missing data cases | D5-2 | The proposal's adverse list covers expired session, another customer's card, injection, tool failure and multilingual ambiguity, but not bad data. | Add scenarios where tools return a null merchant, a transaction outside the card's validity dates, an unknown response code, or a card with no transactions. The expected behavior is to state only what was verified and hand off when facts are missing. Day 1 C1 and Day 2 already found these cases in real rows. | Aldair | 4 |
| G-9 Explicit trade-offs | I-10 | Section 5 justifies AI vs rules, but no document shows how autonomy trades against accuracy, latency, cost and oversight. | Sweep the conformal alpha (and LLM vs no-LLM phrasing). For each setting, report safe automated resolution, unsafe rate, handoff rate, p95 latency and cost. Include the chart and the chosen operating point with its rationale in the write-up. | Aldair | 7 |
| G-10 Model and prompt versions | E-4 | The eval does not record model ids, prompt hashes or the classifier artifact version. | Every run record carries the LLM model id, a hash of each prompt template, the classifier artifact hash and the git commit. `eval/report.json` lists them in its header. | Martín | 5 |
| G-11 Unsafe-rate upper bound | E-15 | Counts alone would let "0 unsafe" read as "safe". | Report the one-sided 95% upper bound next to each unsafe count (rule of three when zero: 3/n), and state the n needed to bound the rate below 1%. | Aldair | 7 |
