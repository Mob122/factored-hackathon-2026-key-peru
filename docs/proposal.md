# Two proposals and a data-driven decision

Cargo Claro and Reclamo sin sorpresas. Proposal for the Factored AI & Data Hackathon 2026. Team: Aldair and Martín.

Version 2 (2026-09-28, after the Day 1 decision). Version 1 is `docs/proposal.pdf` (Spanish, pre-decision draft). Changes from v1: sections 1, 3, 4, 5, 6, 8 and 9 reflect the Day 1 decision (`docs/decision_day1.md`); sections 2, 7 and 10 are translated without changes of substance.

## 1. Summary

We had two strong candidates for the same challenge. A, Cargo Claro, resolves an unrecognized charge before it becomes a dispute. B, Reclamo sin sorpresas, handles what happens after the customer has already complained: follow-up, an honest resolution date and escalation before the case blows up. They share architecture, stack and roles. We do not combine them, because the rules say more workflows do not earn points [10].

**Day 1 decision: B.** Neither track passed the section 4 rule, and the rule's fallback for that case is B with declared limitations. The findings also changed what B contains: the failure-demand thesis, the survival model as the headline ML and the SLA and Regulator classifiers were all refuted or left without a learnable target, so B is reframed (section 3).

## 2. Proposal A: Cargo Claro (not chosen)

**Problem.** Many "unrecognized" charges are legitimate: a preauthorization, a purchase in another currency, a subscription or a purchase with another card the customer owns. Mastercard reports that almost half of consumers have at some point disputed a charge that turned out to be legitimate, and that Sicredi cut its chargebacks by 22% by showing better merchant information [1].

**Solution.** A transaction-dispute intake workflow with two exits. Deterministic root cause detectors (pipeline duplicate vs real double charge, preauthorization, currency conversion, recurrence, habitual merchant, in line with Visa CE 3.0 [8]) explain the charge with computed evidence. A risk guard prevents explaining a high-risk charge as legitimate. If no cause is found or the customer insists, it offers an informed block (which subscriptions would fail) and hands a case file to the analyst.

Flow: customer says "I don't recognize this charge" -> auth + grounding (identify the transaction) -> risk guard + root cause (model + detectors) -> exit A, safe resolution (explain with computed evidence) if risk is low and a cause is found; exit B, investigation (informed block + case file) if risk is high, no cause is found or the customer insists. The charge is never argued.

**ML component.** A self-supervised per-customer sequence model inspired by Nubank's nuFormer [2][3] and Stripe's Payments Foundation Model [4], with per-field prediction (category, amount, country, hour, channel): per-field surprise is the risk explanation. Evaluation label: `is_fraud`, temporal split. Baselines: rules and LightGBM. The deflection threshold is chosen with Conformal Risk Control [6] to bound the rate of fraud explained as legitimate.

**Day 1 outcome.** Only 2 of the 5 root causes reach 1% of card purchases, and neither is above generator noise (A3, A4). Unrecognized charges are one of five uniform complaint categories and are absent from interactions and transcripts (A1). There is no customer-level sequence structure (A4), and `fraud_score` leaks `is_fraud` (A5).

## 3. Proposal B: Reclamo sin sorpresas (chosen, v2)

**Problem (v1).** A large share of contact-center volume is failure demand [9]: customers who call back because their problem was not solved or nobody told them when it would be.

**Problem (v2, what the data supports).** The failure-demand premise did not hold: customers contact the bank at the same rate whether or not a complaint is open (B1, rate ratio 1.016 [0.996, 1.034]). What the data does show is that complaint contacts are the worst-served contact reason in the call center: 'Queja' is 17.05% of interactions with 43.60% first-contact resolution (`was_resolved`) against 91.51% for 'Transaccional', the highest `requires_followup` (62.97%) and the lowest CSAT (2.43 vs 2.91) (A1, section d). On top of that, complaint status data cannot be trusted as is: 76.92% of complaints never get a resolution or closing date and 34,343 were created more than a year before the data end and still show Open, In Process or Escalated (B1). A customer asking "how is my complaint going?" today gets either no answer or an answer nobody verified.

**Solution.** A complaint follow-up workflow with three pieces.

1. **Verified follow-up.** The customer authenticates, the system identifies which of their complaints they mean (clarifying when they have several) and answers with the status verified from `complaints`. Read-only, low risk, high automation. A status that fails the staleness policy (for example, open for longer than any observed resolution, 30 days) is never reported as verified; the case is escalated instead.
2. **Honest date.** An estimated resolution range from the empirical distribution of `resolution_days`, conditional on how long the case has been open. A learned time-to-event model replaces it only if it beats that baseline on the B2 test.
3. **Escalation with a full case file.** Stale status, several open complaints, repeat contact, an explicit request for a human or a mention of the regulator send the case to a human with the request, verified facts, actions taken, evidence and open questions. Escalation triggers are policy rules as code, not model output.

Flow: customer asks "how is my complaint going?" -> auth + identify the complaint (clarify if several) -> status check + date range + policy rules -> exit A, safe answer (verified status + date range) if the status is verifiable and no trigger fires; exit B, escalation with case file otherwise.

**ML components (v2).**

- **(a) Request understanding, the evaluated learned component.** Intent (status, date, new complaint, out of scope, human request), complaint reference resolution and the clarify/escalate decision, in Spanish and Portuguese, using a pretrained LLM with structured outputs. Evaluated on a held-out, team-labeled set against a keyword and rule baseline, with error analysis by language and ambiguity type. The labels are team-generated because the dataset has none (transcripts hold 546 distinct texts and a constant `detected_intents`).
- **(b) Resolution date.** Baseline: empirical conditional range from resolved and closed complaints. Candidate: gradient-boosting or Cox model on intake-time features, fit on resolved and closed complaints only (open complaints cannot be treated as censored at the data end, see limitation 3 in `docs/decision_day1.md`). Metric: C-index and interval coverage against the baseline. Kept only if B2 passes.
- **Dropped from v1:** the `sla_breached` and later-Regulator risk classifiers (B3: no signal) and conformalized survival as the headline model.

Ethical line (unchanged): the system never discourages going to the regulator; it mentions the right to complain when relevant.

## 4. Comparison and decision rule

### Comparison (v1, before Day 1)

| Criterion | A: Cargo Claro | B: Reclamo sin sorpresas |
|---|---|---|
| Consistency with the rules | High | High |
| Data support | Medium: depends on synthetic patterns | High: native labels in complaints |
| Differentiation from other teams | Medium-high: the workflow is popular | High: almost nobody will pick it |
| Expected safe automated resolution | Medium | High: read-only operation |
| Business impact | Avoidable disputes, handle time | Repeat contacts, SLA, regulator complaints |
| Customer impact | Immediate answer and informed block | Certainty about their case and its date |
| Demo effect | High | Medium: offset by the repeat-customer scene |
| Distinctive ML rigor | Sequence model + conformal risk control | Censored survival + conformal intervals |
| Feasible with 2 people in 8 days | Medium | High |

**Shared differentiation.** Other teams will likely ship chat + tools + RAG + classifier + handoff summary, evaluated in a single run. Both proposals add a statistical guarantee on their most expensive error, a model whose explanation comes from the model itself and not the LLM, grading by final state with pass^k [5], and a naive LLM agent as a visible baseline in the demo.

### Comparison after Day 1

The Day 1 findings change three of the v1 cells:

| Criterion | A: Cargo Claro | B: Reclamo sin sorpresas |
|---|---|---|
| Data support | Low: 0 of 5 root causes above generator noise (A3, A4); theme only in complaints, uniform with other categories (A1) | Medium: no failure demand (B1), no SLA or Regulator signal (B3); complaint contacts have the worst FCR and CSAT (A1) and status data is stale (B1) |
| Business impact | Unmeasurable on this data | Repeat contacts not measurable; complaint-contact FCR and verified-status coverage are |
| Distinctive ML rigor | Sequence model refuted (A4); `fraud_score` leaks (A5) | Survival likely at baseline (B2 pending); request understanding evaluated on held-out team labels |

### Decision rule at the end of Day 1 (as written in v1)

> We choose A if at least three of the five root causes appear with a prevalence of 1% or more in real card purchases and unrecognized charges are a relevant contact reason. We choose B if we identify follow-up contacts after a complaint and a simple model on `resolution_days` reaches a C-index of 0.65 or more vs 0.5. If both pass, we choose A for demo impact; if only B passes, B; if neither, B with the limitation declared, because its labels exist even if they carry little signal.

### Outcome (2026-09-28)

| Track | Criterion | Measured | Threshold | Result |
|---|---|---|---|---|
| A | Root causes at >= 1% of card purchases | 2 of 5 (foreign currency 55.05%, an artifact of MXN being absent; habitual merchant 1.41% = shuffled baseline) | >= 3 of 5 | Fail |
| A | Unrecognized charges a relevant contact reason | 20.24% of complaints (5 uniform categories), 1.80% of all contacts | "relevant" (unquantified) | Not met as differentiating |
| B | Follow-up contacts after a complaint identified | Rate ratio 1.016 [0.996, 1.034] vs matched placebo | Excess over baseline | Fail |
| B | C-index of a simple model on `resolution_days` | Not measured (B2 pending) | >= 0.65 | Not measured |

Neither track passes, so the rule gives **B with the limitations declared**. B2 cannot change this, because B already fails its first criterion. The full table and the ten limitations are in `docs/decision_day1.md`.

The rule overrides section 5's "if it fails" column for A1 ("drop A") and B1 ("drop B"), since both failed and the rule handles that case explicitly.

## 5. Hypotheses and Day 1 query plan

The full table with measured values is in `ml/docs/hypotheses.md`. Status on 2026-09-28:

| # | Hypothesis | Status | Consequence for B |
|---|---|---|---|
| C1 | Actual vs declared quality | Refuted as stated | Contracts adjusted to observed reality |
| A1 | Unrecognized charges are relevant demand | Not supported | A not chosen |
| A2 | Charge complaints closed as a valid charge | Not testable | A not chosen |
| A3 | Preauthorizations, foreign currency and double charges exist | Refuted as data-backed | Detectors kept with fixtures only |
| A4 | Recurrence and per-customer temporal structure | Refuted | A not chosen |
| A5 | `fraud_score` does not leak `is_fraud` | Refuted (leaks) | Never used |
| B1 | Measurable failure demand | Refuted as material | Problem reframed to complaint-contact FCR and stale status |
| B2 | `resolution_days` is predictable | Pending | Decides model vs empirical range for the date |
| B3 | Regulator volume and breached SLAs | Volume confirmed, structure refuted | SLA and Regulator classifiers dropped |
| B4 | Complaints join to interactions | Refuted | Contact history only at customer level |
| B5 | Complaint contacts are the worst-served reason | Supported (A1 section d) | Main data justification of v2 |
| B6 | Request understanding beats a keyword/rule baseline | Pending (Days 4-6) | Evaluated learned component |

## 6. Shared architecture

Unchanged from v1 except the track-specific layer, now fixed to B.

- **UIs:** customer chat (Spanish and Portuguese), case inbox (analyst or human agent), ops panel (metrics and evaluation).
- **API + mock identity** (session tokens with expiry) + role checks.
- **Orchestrator** (explicit state machine) -> **LLM layer** (extract, draft, PII redaction) -> **policy engine** (rules as code) -> **action gateway** (capabilities, confirmation).
- **Models + rules**, **cases + audit log** (append-only, provenance), **mock bank services** (complaints, customers).
- **Data:** bronze (raw S3 + metadata) -> silver (contracts, dedup, quarantine) -> gold (serving + training).
- **Eval harness:** user simulator, state-based grading, pass^k, calibration, tracing.

| Layer | B (v2) |
|---|---|
| Models | Request understanding (LLM + structured outputs) vs keyword/rule baseline; resolution-date estimator (empirical range; learned model only if B2 passes) |
| Deterministic logic | Complaint state machine, staleness policy and escalation triggers as a labeled synthetic policy |
| Tools | `list_complaints`, `get_complaint_status`, `estimate_resolution`, `escalate_case` |
| Case inbox | Contact history, status and whether it was verified, date range, escalation reason |

## 7. Tasks per person

**Aldair (data science).** Day 1 query plan and decision. Data pipeline, contracts, lineage and late-arrival fixture. Status-quo baseline metrics. Models, baselines and calibration. Complaint detectors or rules. Policy rules as code. Prompts and structured outputs with PII redaction. Scenarios with hidden state, customer simulator, Portuguese set and error analysis. Data card and model cards.

**Martín (web and deployment).** Repo, docker-compose and CI. Mock identity and mock bank services. Orchestrator and action gateway. Chat, case inbox and ops panel. Case store, audit log and PDF export. Tracing (OpenTelemetry + Langfuse or Phoenix), bounded retries and safe fallback. Deployment and one-command setup. Almost none of his work depends on the Day 1 decision.

**Shared:** the state machine (Aldair specifies it, Martín implements it), the demo and the rehearsal. Interfaces frozen on Day 1: gold schemas, tool contracts, audit log event schema and eval report JSON format.

## 8. 8-day schedule

| Day | Aldair | Martín | Checkpoint |
|---|---|---|---|
| 1 | Ingestion, quality report, A and B query plan | Repo, contracts v1, web skeleton, empty deploy | Decision: B (done) |
| 2 | Silver and gold, baseline metrics, B2 test, labeling guide for request understanding | Mock identity and mock bank on gold | Data ready |
| 3 | Staleness policy and escalation rules, prompts, date-range baseline | State machine, gateway, case store | Happy path in terminal |
| 4 | First 40 scenarios and grader, first labeled held-out set | Chat and inbox connected, staging | End-to-end in Spanish |
| 5 | Request-understanding model vs baseline, Portuguese set, customer simulator | Tracing, ops panel, PDF export | Portuguese working |
| 6 | Calibration, full run against baselines | Expired session, cross-customer access, tool failures, prompt injection | First results |
| 7 | Error analysis, pass^k, breakdowns by language and segment | Fixes, p50 and p95, clean-clone test | Feature freeze |
| 8 | Data card, model cards, write-up | Final deploy, README, demo recording | Submission and rehearsal |

**Cut order:** first the learned resolution-date model (the empirical range stays and the attempt is reported), then the live ops panel (a static report stays), then Postgres (SQLite stays). Not cut: Portuguese, adverse cases, evaluation against baseline, latency and cost.

## 9. Metrics and assumptions

- **Safe automated resolution** over all in-scope cases, plus the share of cases where automation was attempted.
- **Unsafe outcomes** with counts and denominators: a wrong status or date reported as verified, a stale status reported as current, and disclosure of another customer's complaints.
- **Escalation quality** (missed and unnecessary), case file completeness, pass^k, p50 and p95, cost per attempted case and per automated resolution, and results by language, country and segment.
- **Request understanding** accuracy against the keyword/rule baseline on the held-out team-labeled set, by language and ambiguity type.
- **Business framing** is offline: complaint-contact FCR and verified-status coverage are measured on the data; reductions in repeat contacts are projected and labeled as such (B1 found none in the data).
- The dataset is synthetic and contains only Spanish from México, Colombia and Argentina. Portuguese is team-generated (Brazilian customers living in those countries) and declared as such. From MED 2.0 [11] we only take design principles.
- Conformal guarantees, if used, assume exchangeability; we also report their empirical coverage on the temporal test. AWS credentials live only in environment variables.

## 10. Sources

1. Mastercard. Ethoca Consumer Clarity. mastercard.com/global/en/business/cybersecurity-fraud-prevention/dispute-management/ethoca-consumer-clarity.html
2. Nubank AI Core. "Your Spending Needs Attention: Modeling Financial Habits with Transformers". arXiv:2507.23267, 2025.
3. Building Nubank. "How Nubank uses transformers to model financial habits at scale", 2026. building.nu.com
4. PaymentsJournal. "Stripe's AI model touted to be more effective against fraud", May 8, 2025.
5. Yao, Shinn, Razavi, Narasimhan (Sierra). "tau-bench: A Benchmark for Tool-Agent-User Interaction in Real-World Domains". arXiv:2406.12045, 2024.
6. Angelopoulos, Bates, Fisch, Lei, Schuster. "Conformal Risk Control". ICLR 2024. arXiv:2208.02814.
7. Candès, Lei, Ren. "Conformalized Survival Analysis". Journal of the Royal Statistical Society Series B, 2023. arXiv:2103.09763.
8. Visa. Evolution of Compelling Evidence, Merchant FAQs (CE 3.0), March 2023.
9. Seddon, J. "Freedom from Command and Control". Vanguard Press, 2003 (concept of failure demand).
10. Factored. AI & Data Hackathon 2026, Problem Statement; LATAM Bank Complete Data Dictionary v1.0.0.
11. Agência Brasil. "Novas regras de segurança do Pix entram em vigor" (MED 2.0), February 2026.
