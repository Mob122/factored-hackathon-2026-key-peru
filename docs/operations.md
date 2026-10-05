# Operations: route to production

| Field | Value |
|---|---|
| Version | `ops-0.3`, 2026-10-04, **draft** |
| Status | Sections 2 to 5 are drafted from the written policy and contracts (Aldair). Section 1 (capacity and load test) and the trace sample in section 3.3 are placeholders for Martín, Day 7. Both review the whole document before feature freeze. |
| Owners | Aldair (draft, sections 2 to 5) · Martín (section 1, section 3.3, implementation of the deletion job and health checks) |
| Sources | `docs/policy_cards.md` `cards-synthetic-0.9` (SYNTHETIC), `docs/contracts/state_machine.md` `sm-0.4`, `docs/contracts/audit_log.md` `audit-0.2`, `docs/contracts/gold_tables.md` `gold-0.2`, `docs/contracts/freshness_policy.md` `fresh-0.2`, `docs/eval_plan.md` `eval-plan-0.3` |
| Requirements | `docs/requirements_matrix.md` S-2, S-3, I-9, D6-1, D6-5 to D6-9 (gaps G-3, G-4) |
| Changes in 0.2 | The mock identity is built as a labeled test IdP (POL-AUTH-10 to 13): roles `cliente`, `agente` and `jurado` in sections 2.1 and 2.2, `SEED_PASSWORD` and required secrets in 2.3, identity records in 4.1, and a real identity provider as remaining work in section 5. |
| Changes in 0.3 | The agent runs in the backend (`backend/services/agente/`): LLM settings and their startup checks in 2.3, the fallback queue's location in 4.1, and the agent's remaining work in section 5. |

Everything here describes a **prototype on synthetic data**. Values marked *prototype* are
design choices, not measurements or bank requirements. Nothing in this document has been run
under production load.

## 1. Capacity limits

> **Placeholder, Martín, Day 7.** Fill from a load test on the deployed prototype. Until then,
> no capacity number may be quoted.

Planned test (to confirm or change):

| Item | Plan |
|---|---|
| Setup | The deployed prototype (backend, mock identity, mock bank, orchestrator, classifier), the same LLM model IDs as the evaluation, simulated customers from the dev scenarios (never held-out) |
| Load steps | 1, 5, 10, 20 concurrent conversations, 10 minutes each |
| Measured per step | Per-turn p50 / p95 latency (eval plan 5.6 definition), error and timeout rate per tool, LLM 429 responses, template-fallback rate (POL-REL-04), CPU and memory of each process |
| Limit definition | The highest step where p95 ≤ 10 s (target T8) and no turn fails closed |
| Known inputs | Tokens per conversation: about 8,500 input and 410 output for the proposed system (eval plan 13.2). The LLM provider's per-minute token and request limits for the account (to be written here). One conversation at a time was the evaluation setup, so eval latencies say nothing about load (eval plan 5.6). |

Results table (to fill):

| Concurrent conversations | Turns | p50 (s) | p95 (s) | Errors | LLM 429s | Notes |
|---|---|---|---|---|---|---|
| 1 | | | | | | |
| 5 | | | | | | |
| 10 | | | | | | |
| 20 | | | | | | |

Resulting limit and the bottleneck that sets it: *(to fill)*.

## 2. Access controls

### 2.1 Roles

From POL-PII-07, POL-AUTH-01 to 09 and `docs/contracts/audit_log.md` section 6.

| Role | Can see | Cannot see | Enforced in |
|---|---|---|---|
| Customer (`cliente`) | Their own session: replies built from their own products (POL-AUTH-05) | Other customers' data, whether another customer's card exists (POL-ANS-18, INV-10), the audit log, traces | Mock identity (session bound to one `customer_id`), tool gateway |
| Customer with `customer_status` `Suspended` or `Closed` | Nothing but the handoff reply (POL-AUTH-09, T-51, INV-14) | Any product, balance, transaction or their own status | Orchestrator, tool gateway |
| Human agent (`agente`) | Case files: the session customer's `customer_id` and internal product and transaction IDs (POL-PII-05) | Raw third-party identifiers (redacted in the case file), raw credentials | Case inbox (backend role) |
| Operator | Traces and the audit log, with keyed pseudonyms (AL-P3) | Re-identification of pseudonyms and hashes, raw credentials | Backend role |
| Security | Traces and the audit log; can re-identify pseudonyms and match keyed hashes through the backend (AL-P3, AL-P5) | Raw credentials, one-time codes | Backend role |
| Evaluator (`jurado`) | Through the test IdP only (POL-AUTH-11): a customer search with `customer_id`, country and segment (20 per page, 10 searches a minute), a test session for one customer at a time, and one-time step-up codes for live customer sessions. Inside a test session the evaluator sees what that customer would see. | Customer names (gold has none), bulk lists of customers, the audit log, case files. Every session opened and every code issued is in the audit log with the evaluator's user ID. | Test IdP (`backend/routers/identidad.py`), audit log |
| LLM provider | Redacted, allowlisted fields only (POL-PII-01 to 03, INV-09) | Everything in POL-PII-02 | Redaction layer, tool gateway |

### 2.2 Checks in the service layer, not in model text

| Check | Rule | Where |
|---|---|---|
| Every tool call filtered by the session's customer | POL-AUTH-05, INV-07 | Tool gateway, mock bank |
| Tools allowed per state; anything else returns `TOOL_NOT_ALLOWED_IN_STATE` | `sm-0.4` section 2 | Tool gateway |
| Step-up (L2) bound to one card and one action, single use | POL-AUTH-04, INV-02 | Mock identity, action gateway |
| Confirmation token bound to (session, card, action), from a later turn | POL-ACT-02, INV-03 | Action gateway |
| Session expiry: idle 15 min, absolute 60 min (*prototype*), checked on the server-side session record at every request and tool call | POL-AUTH-03, POL-AUTH-12, INV-01 | Mock identity (`backend/services/identidad.py`) |
| Customer status check at every sign-in | POL-AUTH-09 | Orchestrator |
| Identifiers typed in chat never authenticate; no data tool has a `customer_id` parameter | POL-AUTH-02, POL-AUTH-12, B-8 | Mock identity, tool layer (`backend/services/banco.py`) |
| Only `jurado` calls `/identidad/*`; the customer search is paginated, rate-limited and has no bulk export | POL-AUTH-11 | Test IdP |
| Open registration only with `ENV=development`; it creates a `cliente` with no customer and no privileged role | POL-AUTH-10 | Test IdP |
| Ownership check on a typed full card number; result only to the security counter | POL-ESC-10, POL-AUTH-05 | Tool gateway |

### 2.3 Secrets

| Secret | Used for | Where it lives in the prototype | Never |
|---|---|---|---|
| `SECRET_KEY`, `ALGORITHM` | Signing the backend's session JWT. The backend does not start without `SECRET_KEY` (POL-AUTH-10) | `backend/.env` (git-ignored) | In the repository, logs or traces |
| `CARD_HASH_KEY` | `card_number_hmac` in gold and the ownership check (`gold_tables.md` section 3) | `ml/conf/local/credentials.yml` and `backend/.env` (both git-ignored) | Same |
| `AUDIT_KEY` | Keyed pseudonyms and hashes in the audit log (AL-P3, AL-P5) | `backend/.env`; required at startup | Same; operators have no access to it |
| `SEED_PASSWORD` | Password of the seeded test users (`backend/scripts/sembrar_usuarios.py`, POL-AUTH-10) | `backend/.env` | Same; it protects every seeded user, so it must not be reused anywhere else |
| LLM provider API key | LLM calls | `backend/.env` | Same; never sent to the browser |
| `LLM_MODE`, `LLM_MODEL`, `LLM_ALLOWED_MODELS`, `LLM_BASE_URL` | Not secrets. `LLM_MODE=mock` (the default) never calls the provider; `openai` calls `LLM_MODEL`. The backend does not start if `LLM_MODEL` is not in `LLM_ALLOWED_MODELS`, or if `LLM_MODE=openai` has no API key | `backend/.env` | A model outside the allowed list |
| Test credentials and one-time codes | Test IdP | Password hashes (Argon2) in `usuarios`; one-time codes only as an HMAC in `codigos_otp_prueba`; the code is shown once to the evaluator | In the chat (POL-AUTH-08), the audit log (AL-P2) |

Rotation, a secrets manager and per-environment keys are not implemented (section 5).

## 3. Monitoring

### 3.1 Signals

*Prototype* thresholds come from the evaluation targets where one exists; the others are
initial values to revisit once there is traffic.

| ID | Signal | Source | Definition | Threshold (*prototype*) | Action |
|---|---|---|---|---|---|
| M-1 | Unsafe-outcome proxies | Audit log | Per hour: grounding-check failures (`policy_decision.grounding_check.passed = false`), `TOOL_NOT_ALLOWED_IN_STATE` events, `pii_blocked` events (AL-P7), unverified blocks (T-35, `verification.verified = false`) | Any `TOOL_NOT_ALLOWED_IN_STATE` or `pii_blocked`: page; unverified blocks: every one reviewed (they are `urgent` cases) | Investigate the conversation from its audit events (POL-AUD-02) |
| M-2 | Handoff rate and priority mix | `handoff` events | Share of conversations transferred, by `priority` and by `reason_rule_ids` | Move of more than 10 pp in a day against the previous 7 days | Check classifier drift (M-5) and tool errors (M-4) first |
| M-3 | Latency | `policy_decision` and `llm_call` events | Per-turn p50 and p95 over the last hour | p95 > 10 s (T8) for 15 minutes | Check LLM latency and tool timeouts |
| M-4 | Tool errors | `tool_call` events | Share of calls with status `error` or `timeout`, per tool; failed rounds (POL-ESC-07) | > 2% for any tool over 15 minutes | Check the mock bank or core system; G-06 transfers are the expected customer effect |
| M-5 | Classifier coverage drift | `classification` events | Share of `routing` = `clarify` and `transfer` (POL-ESC-06), mean conformal set size, by language, against the calibration split (eval plan 8.4) | Set size or transfer share more than 1.5× the calibration value over a day | Label a sample of recent messages; recalibrate on new data |
| M-6 | Stale gold | Gold `_load_log` | Newest processed partition older than D-1 at 07:00 (`freshness_policy.md` section 2) | Any | Health check reports `stale`; balances already carry POL-BAL-03 after 24 h |
| M-7 | LLM failures and template fallbacks | `llm_call`, `policy_decision` | Share of turns answered with the POL-REL-04 fallback | > 5% over an hour | Check the provider status and rate limits |
| M-8 | Audit integrity | Hash-chain verification job (AT-3) | Conversations whose chain fails verification | Any | Security review |
| M-9 | Handoff fallback queue | Fallback queue (POL-REL-03) | Cases waiting for replay | Any case older than 15 minutes | Replay; check the case service |
| M-10 | Cost | `llm_call` token counts | Cost per conversation at list prices (eval plan 5.7) | Above US$0.05 per attempted case (T9) over a day | Check prompt size and retries |
| M-11 | Security events | `security` events | Injection hits, unauthorized attempts, step-up lockouts per hour | Spike above 3× the 7-day hourly mean | Security review |

### 3.2 Health checks

| Check | Healthy when |
|---|---|
| Backend | Responds, and can write an audit event (a failed write fails the turn closed, audit log section 1) |
| Gold | Latest `_load_log` row `published` and not `stale` (M-6) |
| Mock identity | Issues and validates a test session |
| LLM provider | A minimal call succeeds within `TOOL_TIMEOUT_SEC` |

### 3.3 Trace sample

> **Placeholder, Martín, Day 5.** One traced conversation (golden dialogue 2, the verified
> block) showing `trace_id` and `span_id` across orchestrator, classifier, tool gateway, action
> gateway, LLM and handoff service (requirements matrix D6-1).

## 4. Data retention and deletion

### 4.1 Retention by store

Values from policy section 11 (*prototype*, synthetic data).

| Store | Content | Retention (*prototype*) | Deleted by | Rule |
|---|---|---|---|---|
| Transcripts | Redacted customer and assistant text | 30 days (`RETAIN_TRANSCRIPT_DAYS`) | Created date | POL-PII-06, POL-PII-05 |
| Traces | Spans with redacted payloads | 30 days (`RETAIN_TRACE_DAYS`) | Created date | POL-PII-06 |
| Case files | The five content fields and metadata (POL-HND-10 to 15) | 90 days (`RETAIN_CASE_DAYS`) | Created date | POL-PII-06 |
| Audit log | Append-only events, pseudonymized | 90 days (`RETAIN_CASE_DAYS`) | `occurred_at` | Audit log section 6 |
| Handoff fallback queue | Case files waiting for replay, as JSON Lines in `FALLBACK_QUEUE_PATH` (default `backend/var/cola_casos.jsonl`, git-ignored, outside the database) | Until replayed, then as case files | Replay (not built yet) | POL-REL-03 |
| Mock bank overlay | Status events written by `block_card` | Reset between evaluation runs (flag F-04, open); in production this is the core banking system | Reset procedure (open) | `freshness_policy.md` section 5 |
| Identity records | Server-side sessions, step-ups and hashed one-time codes of the test IdP | Not in the deletion job yet (open); expired sessions grant nothing | — | POL-AUTH-03, POL-AUTH-12 |
| Gold tables | Synthetic customers, cards, transactions, balance products | Life of the prototype; never committed (POL-PII-08) | — | `gold_tables.md` |
| Never stored | Credentials, one-time codes, raw third-party identifiers, POL-PII-02 fields | — | — | AL-P2, POL-PII-04, 05 |

### 4.2 Deletion procedure

Designed, not implemented (Martín implements it by Day 7):

1. A daily job (after the gold load) deletes, per store, the records whose created date is older
   than the store's retention, in one transaction per store.
2. The audit log is deleted by `occurred_at` through the same job, which is the only delete path
   the audit table has (audit log section 1). Hash chains are per conversation, so deleting
   older conversations does not break newer ones.
3. A case file is deleted only after every audit event of its conversation has been deleted or
   is past retention, so an explanation (POL-AUD-02) never points to a missing case.
4. The job writes a run record: store, cutoff date, rows deleted. The record holds no content.
5. A test runs the job on a fixture with records on both sides of each cutoff and checks the
   counts.

### 4.3 Production values

Not ours to set. The bank's legal and compliance teams would set retention per store under the
applicable law in each country (México, Colombia, Argentina) and the bank's own policies,
including legal holds that suspend deletion. The prototype's values above are placeholders.

## 5. Remaining work before deployment

What the prototype does not have and a real deployment would need. None of it is started.

| Area | Prototype today | Needed before deployment |
|---|---|---|
| Identity | Test IdP (POL-AUTH-10 to 13): seeded users with one shared password, evaluator impersonation, the step-up code shown to the evaluator, an in-process search rate limit, no MFA and no lockout after wrong passwords | A real identity provider: the bank's IdP (OIDC or SAML) for sign-in, with MFA and account lockout and recovery; step-up delivered to the customer's own device (OTP or app push) and bound to the action; sessions managed and reviewed by security; rate limits in a shared store. `/identidad/*`, open registration and the seeded users are removed from any deployed environment |
| Core banking | Gold tables built from a static synthetic dump; blocks written to a mock overlay | Read APIs of the core system for cards, balances and transactions; `block_card` against the real card-management system, with its own idempotency and status read |
| Data | Synthetic data; no balance timestamp; random decline codes; no status history (`gold_tables.md` section 6) | Real data with real timestamps, block history and decline causes; re-evaluation of every policy rule that exists only because of the synthetic data (POL-ANS-10, 11, 13, 15) |
| Language | Portuguese and regional variants written by the team; no Brazilian customers | Messages from real Portuguese- and Spanish-speaking customers, labeled by the bank's agents; re-calibration of the conformal sets per language |
| Classifier | Trained on team-written utterances | A human-labeled sample of production messages; drift monitoring (M-5) with a retraining procedure |
| Policy | `docs/policy_cards.md` is SYNTHETIC; no bank reviewed it | Legal, compliance and operations review of every rule and template, in both languages |
| LLM provider | Declared in `docs/data_card.md` (planned) | Contract terms confirmed: no training on or retention of data (POL-PII-09); data residency |
| Secrets | `.env` and `conf/local` files | A secrets manager, rotation of `CARD_HASH_KEY` and `AUDIT_KEY` (with re-keying of stored hashes), separate keys per environment |
| Security | Unit and scenario tests of the rules (INV-01 to 14, AT-1 to 6) | Independent security review and penetration test, including prompt injection beyond our 2 templates |
| Agent | Orchestrator, tool gateway and mock bank in one process; tools have no preemptive timeout; read retries and the LLM's backoff block the request; case-file summaries come from a template; the fallback queue has no replay job; elliptical follow-ups use one heuristic rule (POL-ESC-14) | Tools behind network clients with their own `TOOL_TIMEOUT_SEC`; asynchronous retries; a replay job for the fallback queue with alerting (M-9); a model-written case summary marked `generated_by: model` (POL-HND-10); a classifier trained on dialogue context instead of the follow-up rule |
| Capacity | Section 1 (placeholder) | Load test against the real LLM rate limits and core latency; horizontal scaling of the orchestrator |
| Operations | Signals defined in section 3; no alerting | Dashboards, alert routing, on-call, incident runbooks, the deletion job in production |
| Human agents | A case inbox for the demo | Integration with the bank's case management; agent training on the case file; SLA for `urgent` and `security` cases |
| Evaluation | Offline simulation on 160 held-out cases (1.85% upper bound on the unsafe rate with zero events) | A shadow period on real traffic with human review before any automated resolution |
