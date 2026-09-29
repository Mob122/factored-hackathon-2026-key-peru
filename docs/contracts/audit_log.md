# Contract: audit log events

| Field | Value |
|---|---|
| Contract version | `audit-0.1` |
| Date | 2026-09-29 |
| Owner | Aldair (specification) · Martín (emission in orchestrator, tool gateway, action gateway, handoff service) |
| Policy | `docs/policy_cards.md` `cards-synthetic-0.3` (SYNTHETIC): POL-AUD-01, POL-AUD-02, POL-PII-01 to 07, POL-ACT-09, POL-HND-10 to 15 |
| State machine | `docs/contracts/state_machine.md` `sm-0.2` |
| Readers | Operators and the security role (POL-PII-07); the evaluation grader (`docs/eval_plan.md` section 7); explanations to customers and agents (POL-AUD-02) |

The audit log is the execution record. Explanations of what the system did are rebuilt from it:
rule IDs, tool results and actions, **never** model chain-of-thought (POL-AUD-02). It holds **no
raw PII** (section 2).

## 1. Storage and integrity

- Append-only table `audit_events` in the backend database, one row per event, the event body
  as JSON. No update or delete path exists in the application; retention deletion (section 6)
  is a separate job.
- **Hash chain.** Each event carries `prev_event_hash` (the `event_hash` of the previous event in
  the same conversation, or null for the first) and `event_hash` = SHA-256 of the canonical JSON
  of the event without `event_hash`. A broken chain is detectable by a verification job.
- Events are written **before** the reply is sent to the customer. If the write fails, the turn
  fails closed: the customer gets the POL-REL-04 template fallback and no action runs.
- `event_id` is a UUIDv7, so IDs sort by time.

## 2. Privacy rules for every event

| ID | Rule |
|---|---|
| AL-P1 | Free text (customer messages, assistant replies, summaries) is stored **only after redaction** (POL-PII-01, 04), with typed placeholders: `[NAME_n]`, `[DOC_n]`, `[CARD_PAN_n]`, `[CUSTOMER_ID_n]`, `[EMAIL_n]`, `[PHONE_n]`, `[ADDRESS_n]`, `[POSTAL_n]`, `[DOB_n]`, `[SECRET_n]`. |
| AL-P2 | **Never stored**, even redacted or hashed: credentials, one-time codes, passwords, and the POL-PII-02 fields (`credit_score`, `estimated_monthly_income`, `gender`, `marital_status`, `education_level`, `occupation`, `fraud_score`, `is_fraud`). |
| AL-P3 | People and products are referenced by **keyed pseudonyms**: `customer_ref` = `HMAC-SHA256(AUDIT_KEY, customer_id)`, `card_ref` = `HMAC-SHA256(AUDIT_KEY, card_id)`, `transaction_ref` = `HMAC-SHA256(AUDIT_KEY, transaction_id)`, each truncated to 32 hex characters. `AUDIT_KEY` is a secret held by the backend; the security role can re-identify through the backend, operators cannot. |
| AL-P4 | Fields the customer may see are allowed in clear: card `last4`, card type, card status, transaction date, amount, currency, type, merchant name, status, response code, balance values and `as_of` (the POL-PII-03 list). |
| AL-P5 | A full card number typed by the customer is stored only as `card_number_hmac` (the keyed hash of `gold_tables.md` section 3, same key as gold) plus its last 4. This lets the security role match it to a card without storing the number. Third-party identifiers typed by the customer (another customer's ID, name, document) are stored only as `HMAC-SHA256(AUDIT_KEY, normalized value)`. |
| AL-P6 | Tool arguments and results are stored after the gateway's field allowlist (POL-PII-02, 03) and pseudonymization (AL-P3). The full result stays in the mock bank; the event holds `result_digest` (SHA-256 of the full result) so it can be checked later. |
| AL-P7 | A PII scan runs on every event before it is written: 13-19 digit sequences, emails, phone patterns, document-number patterns, and the POL-PII-02 field names. A hit replaces the offending value with `[BLOCKED_PII]`, sets `pii_scan.blocked = true` and emits a `security` event. The evaluation counts these (eval plan U5). |

Policy `cards-synthetic-0.3` rewords POL-PII-05 and POL-PII-07 to match AL-P5: no raw
third-party identifier is stored anywhere, and the security role matches the keyed hashes.

## 3. Common envelope

Every event has these fields:

| Field | Type | Required | Content |
|---|---|---|---|
| `schema_version` | string | yes | `audit-0.1` |
| `event_id` | UUIDv7 | yes | |
| `event_type` | enum | yes | Section 4 |
| `occurred_at` | timestamp, UTC, ms | yes | Server time (in evaluation, the simulated clock plus real elapsed time) |
| `conversation_id` | string | yes | Opaque ID; survives re-authentication (POL-AUTH-07) |
| `session_id` | string or null | yes | Opaque ID of the mock identity session; null before authentication |
| `turn_index` | integer | yes | 0 = sign-in, then one per customer message |
| `trace_id`, `span_id` | string | yes | Tracing IDs (requirements matrix D6-1) |
| `actor` | enum | yes | `customer`, `orchestrator`, `tool_gateway`, `action_gateway`, `identity`, `handoff_service`, `human_agent` |
| `customer_ref` | string or null | yes | AL-P3; null before authentication |
| `auth_level` | enum | yes | `L0`, `L1`, `L2` at the time of the event |
| `state` | enum | yes | State-machine state when the event happened (`sm-0.2` section 1) |
| `policy_version`, `state_machine_version` | string | yes | `cards-synthetic-0.3`, `sm-0.2` |
| `rule_ids` | list of string | yes | Policy rules applied; may be empty only for `tool_call` and `llm_call` |
| `prev_event_hash`, `event_hash` | hex | yes | Section 1 |
| `pii_scan` | object | yes | `{"blocked": bool, "placeholders": {"NAME": n, ...}}` |

## 4. Event types

| `event_type` | Emitted by | When |
|---|---|---|
| `session` | identity, orchestrator | Sign-in, step-up, expiry, end |
| `message_received` | orchestrator | Every customer message, after redaction |
| `classification` | orchestrator | Every message classified (IDLE, CLARIFY_INTENT) |
| `tool_call` | tool gateway | Every tool call, including retries and refusals |
| `llm_call` | orchestrator | Every LLM request (supports cost, latency and version logging) |
| `policy_decision` | orchestrator | Once per turn: the transition and the reply |
| `confirmation` | orchestrator, action gateway | Confirmation prompt shown; confirmation resolved |
| `action_result` | action gateway | Every `block_card` call |
| `verification` | action gateway | The status read after `block_card` |
| `handoff` | handoff service | Case opened, fallback queue used, message appended |
| `security` | orchestrator, tool gateway | Injection suspected, unauthorized attempt, step-up lockout, PII blocked |

The user asked for seven types (session, tool call, policy decision, confirmation, action
result, verification, handoff). `message_received`, `classification`, `llm_call` and `security`
are added because POL-AUD-01, the eval plan (cost, model versions, U5) and POL-HND-13
(`security_events`) need them.

### 4.1 `session`

| Field | Type | Content |
|---|---|---|
| `session_event` | enum | `authenticated`, `authentication_failed`, `step_up_requested`, `step_up_succeeded`, `step_up_failed`, `step_up_locked`, `expired`, `ended`, `resumed` |
| `auth_level_before`, `auth_level_after` | enum | |
| `expires_at` | timestamp | Session or step-up expiry |
| `step_up` | object or null | `{step_up_id, card_ref, action: "block_card", expires_at, used}` (POL-AUTH-04) |
| `failure_count` | integer | Step-up failures so far (POL-AUTH-06) |
| `language_preference` | `es` or `pt` or null | Set at sign-in (POL-GEN-03) |
| `resume_intent` | object or null | `{intent, slots}` with customer-typed slots only (POL-AUTH-07); slot values redacted per AL-P1 |

Never: the credentials, the one-time code, or whether a wrong code was close.

### 4.2 `message_received`

| Field | Type | Content |
|---|---|---|
| `text_redacted` | string | AL-P1 |
| `detected_language` | `es`, `pt`, `other`, `mixed` | |
| `typed_card_numbers` | list | `{card_number_hmac, last4}` per 13-19 digit sequence found (AL-P5) |
| `third_party_refs` | list of hex | AL-P5 |
| `secrets_redacted` | integer | Count of `[SECRET_n]` placeholders (POL-AUTH-08) |

### 4.3 `classification`

| Field | Type | Content |
|---|---|---|
| `classifier_artifact_sha256` | hex | |
| `top_intent`, `top_score` | string, number | |
| `conformal_set` | list of string | |
| `conformal_alpha`, `conformal_threshold`, `max_set` | number, number, integer | |
| `slots` | object | Product kind, last 4, date or range, amount, merchant (redacted per AL-P1 if they contain PII) |
| `routing` | enum | `act`, `clarify`, `transfer` (POL-ESC-06) |

### 4.4 `tool_call`

| Field | Type | Content |
|---|---|---|
| `tool_call_id` | string | Unique in the conversation; cited by case files (POL-HND-11, 13) and replies |
| `tool` | enum | `authenticate`, `step_up`, `list_cards`, `list_balance_products`, `get_card_status`, `list_transactions`, `describe_transaction`, `get_balance`, `block_card`, `open_handoff` |
| `attempt`, `retry_of` | integer, string or null | Retries are separate calls (POL-REL-01) |
| `allowed_in_state` | bool | False → `TOOL_NOT_ALLOWED_IN_STATE` (`sm-0.2` section 2) |
| `args` | object | Pseudonymized and allowlisted (AL-P3, AL-P6), for example `{"card_ref": "…", "days": 30}` |
| `status` | enum | `ok`, `empty`, `error`, `timeout`, `refused`, `session_expired`, `not_allowed_in_state` |
| `error_code` | string or null | |
| `latency_ms` | integer | |
| `result` | object or null | Allowlisted fields only (AL-P4), for example `[{"card_ref":"…","last4":"9205","type":"Tarjeta Crédito","status":"Active"}]` (types as stored in gold) |
| `result_digest` | hex | AL-P6 |
| `data_as_of` | timestamp or null | Gold `as_of` of the data read (freshness policy section 2) |
| `fixture` | string or null | Name of an injected evaluation fixture that changed this call (for example `tool_fault:timeout`); null in normal runs |

### 4.5 `llm_call`

| Field | Type | Content |
|---|---|---|
| `llm_call_id` | string | |
| `purpose` | enum | `reply_wording`, `summary` (case-file `request` summary, POL-HND-10), `other` |
| `provider`, `model_id` | string | Exact dated model ID |
| `prompt_template`, `prompt_sha256` | string, hex | |
| `temperature`, `max_tokens` | number, integer | |
| `input_tokens`, `cached_input_tokens`, `output_tokens` | integer | |
| `latency_ms` | integer | |
| `status` | enum | `ok`, `error`, `timeout` |
| `request_pii_scan` | object | `{"blocked": bool, "hits": n}`: the scan of the outgoing request (INV-09). The request itself is not stored. |

### 4.6 `policy_decision`

One per turn, written last, before the reply is sent.

| Field | Type | Content |
|---|---|---|
| `state_before`, `state_after` | enum | |
| `transition_id` | string | `T-01` … `T-50`, `G-01` … `G-07` |
| `decision` | enum | `answer`, `clarify`, `act`, `abstain`, `transfer`, `refuse`, `authenticate`, `none` |
| `intent` | string or null | Intent being served |
| `rule_ids` | list | In the envelope; at least one (INV-08) |
| `tool_call_ids` | list | Calls made in this turn |
| `facts_used` | list | `{fact, value, tool_call_id, read_at}`; value per AL-P4 (POL-GEN-02, 07) |
| `grounding_check` | object | `{"passed": bool, "unsupported_facts": n, "fallback_template": "POL-REL-04" or null}` |
| `reply` | object | `{"text_redacted": "...", "language": "es", "templates": ["POL-TXS-02", "POL-DEC-51"], "llm_call_ids": [...]}` |
| `counters` | object | `clarify_turns`, `card_misses`, `stepup_fails`, `tool_fail_rounds`, `llm_fails`, `injection_hits`, `unauthorized_hits` after the turn |
| `then_handoff`, `dispute` | bool | Flags of `sm-0.2` section 3 |

### 4.7 `confirmation`

| Field | Type | Content |
|---|---|---|
| `confirmation_event` | enum | `requested`, `resolved` |
| `confirmation_token_id` | string | Token ID, not the token secret |
| `action` | `block_card` | |
| `card_ref`, `last4`, `card_type` | string | The card named in the prompt (POL-ACT-02) |
| `prompt_turn_index` | integer | Turn where the prompt was shown |
| `expires_at` | timestamp | `CONFIRM_TTL_SEC` |
| `outcome` | enum or null | On `resolved`: `confirmed`, `declined`, `ambiguous`, `other_card`, `expired`, `same_turn_yes_ignored`, `superseded` (POL-ACT-03) |
| `answer_turn_index` | integer or null | Must be greater than `prompt_turn_index` for `confirmed` (INV-03) |

### 4.8 `action_result`

| Field | Type | Content |
|---|---|---|
| `action_id` | string | |
| `action` | `block_card` | |
| `card_ref`, `last4` | string | |
| `confirmation_token_id`, `step_up_id` | string | The idempotency key and the step-up consumed (POL-ACT-06, POL-AUTH-04) |
| `preconditions` | object | `{"auth_level": "L2", "step_up_valid": true, "owner_match": true, "pre_status": "Active", "pre_status_tool_call_id": "..."}` (POL-ACT-01) |
| `tool_call_id` | string | The `block_card` call |
| `requested_at` | timestamp | |
| `executed` | enum | `true`, `false`, `unknown` (POL-ACT-09) |
| `error_code` | string or null | |

### 4.9 `verification`

| Field | Type | Content |
|---|---|---|
| `action_id` | string | Links to `action_result` |
| `tool_call_ids` | list | The `get_card_status` reads, with retries |
| `expected_status` | `Blocked` | |
| `observed_status` | enum or null | Null if every read failed |
| `verified` | bool | True only if `observed_status = Blocked` (POL-ACT-05) |
| `customer_told` | enum | `POL-ACT-11` (verified) or `POL-ACT-10` (not verified) |

### 4.10 `handoff`

| Field | Type | Content |
|---|---|---|
| `handoff_event` | enum | `opened`, `fallback_queued`, `message_appended`, `priority_raised` |
| `case_id` | string or null | From `open_handoff`; null if `fallback_queued` (POL-HND-02) |
| `idempotency_key` | string | `open_handoff` may be retried with it (POL-REL-02) |
| `priority` | enum | `normal`, `security`, `urgent` (POL-HND-15) |
| `reason_rule_ids` | list | |
| `case_file_fields_present` | object | `{"request": true, "verified_facts": true, "actions_taken": true, "evidence": true, "unresolved_questions": true}` (INV-05) |
| `case_file_digest` | hex | SHA-256 of the case file as sent; the case file itself lives in the case store, not in the audit log |
| `counts` | object | Number of verified facts, actions, evidence items, unresolved questions |

### 4.11 `security`

| Field | Type | Content |
|---|---|---|
| `security_event` | enum | `injection_suspected`, `unauthorized_attempt`, `card_miss`, `step_up_lockout`, `pii_blocked`, `tool_not_allowed_in_state` |
| `subtype` | string or null | For `unauthorized_attempt`: `a_third_party_card`, `b_third_party_data`, `c_second_card_miss`, `d_step_up_lockout` (POL-ESC-10) |
| `occurrence` | integer | 1st, 2nd … in the session |
| `detector` | string | Detector name and version |
| `evidence` | object | Pseudonyms and hashes only (AL-P5), for example `{"card_number_hmac": "…", "owner_match": false}`. The injected text itself is kept only as `text_redacted` in the `message_received` event. |
| `effect` | enum | `ignored_continue`, `refused_continue`, `transfer` |

`owner_match` of the ownership check appears **only** here and never in a reply, the LLM input or
a `policy_decision` (POL-AUTH-05, INV-10).

## 5. Example: a verified block (golden dialogue 2, turns 2 and 3, abbreviated)

Tool call IDs and times follow `docs/golden_conversations.md` dialogue 2: step-up `c4`,
pre-read `c5`, `block_card` `c6`, verification `c7`, token `CT-D2-1`.

```json
{"event_type":"confirmation","turn_index":2,"state":"AWAIT_CONFIRMATION","rule_ids":["POL-ACT-02"],
 "confirmation_event":"requested","confirmation_token_id":"CT-D2-1","action":"block_card",
 "card_ref":"3f9c…","last4":"8407","card_type":"Tarjeta Crédito","prompt_turn_index":2,
 "expires_at":"2026-06-18T10:03:40Z","outcome":null,"answer_turn_index":null}
{"event_type":"confirmation","turn_index":3,"state":"AWAIT_CONFIRMATION","rule_ids":["POL-ACT-02","POL-ACT-04"],
 "confirmation_event":"resolved","confirmation_token_id":"CT-D2-1","outcome":"confirmed","answer_turn_index":3}
{"event_type":"action_result","turn_index":3,"state":"EXECUTING","rule_ids":["POL-ACT-01","POL-ACT-06","POL-ACT-09"],
 "action_id":"act_01J…","action":"block_card","card_ref":"3f9c…","last4":"8407",
 "confirmation_token_id":"CT-D2-1","step_up_id":"stp_01J…",
 "preconditions":{"auth_level":"L2","step_up_valid":true,"owner_match":true,"pre_status":"Active","pre_status_tool_call_id":"c5"},
 "tool_call_id":"c6","requested_at":"2026-06-18T10:02:10Z","executed":"true","error_code":null}
{"event_type":"verification","turn_index":3,"state":"EXECUTING","rule_ids":["POL-ACT-05"],
 "action_id":"act_01J…","tool_call_ids":["c7"],"expected_status":"Blocked","observed_status":"Blocked",
 "verified":true,"customer_told":"POL-ACT-11"}
{"event_type":"policy_decision","turn_index":3,"rule_ids":["POL-ACT-02","POL-ACT-05","POL-ACT-06","POL-ACT-09","POL-ACT-11"],
 "state_before":"AWAIT_CONFIRMATION","state_after":"IDLE","transition_id":"T-34","decision":"act",
 "tool_call_ids":["c5","c6","c7"],"grounding_check":{"passed":true,"unsupported_facts":0,"fallback_template":null},
 "reply":{"text_redacted":"Pronto: o seu cartão de crédito final 8407 está bloqueado. …","language":"pt","templates":["POL-ACT-11"],"llm_call_ids":[]}}
```

Envelope fields (`schema_version`, `event_id`, `occurred_at`, IDs, hashes, `pii_scan`) are left
out of the example for length.

## 6. Retention and access

- Retention: `RETAIN_CASE_DAYS` (90 days in the prototype, policy section 11), deleted by
  `occurred_at`. Deleting old events breaks nothing in the chain of newer conversations, since
  the chain is per conversation.
- Access: operators and the security role read the log (POL-PII-07); only the security role can
  re-identify pseudonyms through the backend. Customers and the LLM never read it.
- The evaluation reads it to compute `attempted`, decisions, transitions and unsafe events
  (`docs/eval_plan.md` sections 5 and 7).

## 7. Tests

| ID | Test |
|---|---|
| AT-1 | Every turn of every golden conversation produces exactly one `policy_decision` with ≥ 1 rule ID and `policy_version` (INV-08). |
| AT-2 | The AL-P7 scanner finds 0 hits in the stored log after running all golden conversations and the evaluation's adversarial cases (typed card numbers, third-party IDs, secrets). |
| AT-3 | The hash chain of every conversation verifies. Editing one stored event breaks it. |
| AT-4 | The replies to a card miss and to a third-party card number are identical, while only the second produces a `security` event with `owner_match: false` (INV-10). |
| AT-5 | For every `block_card`, there is one `action_result` and one `verification`, and `customer_told = POL-ACT-11` only when `verified = true` (INV-04). |
| AT-6 | An audit write failure makes the turn fall back to the POL-REL-04 template and runs no action. |
