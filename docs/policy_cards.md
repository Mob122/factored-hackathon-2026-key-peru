# SYNTHETIC service policy: card and transaction inquiries

> **SYNTHETIC POLICY. Not a real bank policy.** Written by the team for the Factored AI & Data
> Hackathon 2026 prototype. No bank reviewed or approved it. Its rules, time limits and templates are design choices
> made over a synthetic dataset. Do not present it as a regulatory or institutional
> standard.

| Field | Value |
|---|---|
| Policy version | `cards-synthetic-0.4` |
| Date | 2026-09-29 |
| Scope | Card and account inquiries assistant, in Spanish and Portuguese: balance inquiries for credit cards and savings accounts (the core intent), card status, card transactions, card block and handoff (`docs/proposal.md` v3.1) |
| Owner | Aldair (policy text) · Martín (enforcement in services, gateway and orchestrator) |
| State machine | `docs/contracts/state_machine.md` (`sm-0.3`) |
| Intents | `docs/intents.md` (`intents-1.0`) |
| Evidence used | `docs/proposal.md`, `docs/requirements_matrix.md`, `docs/findings/day1/P2_card_support.md`, `docs/findings/day2/personas.md`, `docs/golden_conversations.md` (flag register) |

## Change log

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-09-29 | First version. |
| 0.2 | 2026-09-29 | Fixes for the flag register of `docs/golden_conversations.md` (F-02, F-06, F-08 to F-11, F-13, F-15 to F-19, F-21 to F-26). Balance inquiry for credit cards and savings accounts (POL-ANS-14 narrowed; POL-ANS-15 to 17 and POL-BAL-* added). Language is the customer's preference (POL-GEN-03). Stale-data rule (POL-GEN-07). Two new tools, `list_balance_products` and `get_balance`, which change the tool contracts frozen in `docs/proposal.md` section 8 and need Martín's sign-off. |
| 0.3 | 2026-09-29 | Consistency fixes against `docs/contracts/`, no new scope. POL-ANS-02: `get_card_status` also returns card type and last 4 (POL-ACT-11 renders `{tipo}` from the verification read). POL-PII-05 and POL-PII-07: raw third-party identifiers are not stored anywhere; the audit log keeps a keyed hash (`docs/contracts/audit_log.md` AL-P5), matching POL-PII-04. References in section 3b and POL-PII-06 updated. |
| 0.4 | 2026-09-29 | Balance inquiry approved by the team (proposal v3.1); the balance tools are part of the frozen contracts. New POL-AUTH-09 and template POL-HND-07: customers with `customer_status` `Suspended` or `Closed` get only an immediate handoff (requirements matrix gap 4). POL-ANS-15 and new template POL-BAL-06: a credit card with no recorded limit (5.05%) or a balance above it gets the balance alone with POL-BAL-04. Final intent names from `docs/intents.md` in the eligibility table. POL-ANS-14 is also reached when the customer names a product kind the intent does not serve. POL-PII-06 points to `docs/operations.md`. |

## 0. How to read and cite this policy

- Every rule has a stable ID of the form `POL-<AREA>-<NN>`. IDs are never reused or renumbered.
  A changed rule keeps its ID and the policy version is bumped. A removed rule is marked
  *retired* and stays in the document.
- Areas: `GEN` general, `AUTH` authentication, `ANS` answers, `BAL` balance templates, `ACT`
  actions, `ESC` abstain/transfer, `DEC` decline-code templates, `TXS` transaction-status
  templates, `HND` handoff, `PII` privacy and retention, `REL` reliability, `AUD` audit.
- Every audit-log event, handoff case file and customer-facing explanation cites the rule IDs
  it applied together with `policy_version`. Explanations are built from rule IDs, tool results
  and execution records, never from model reasoning (POL-AUD-02).
- "Enforced in" says which component enforces the rule. The LLM is never listed there. It only
  words replies from facts and decisions that were already made. A sentence marked as a
  template is rendered by code with placeholders filled from tool results. The LLM does not
  rewrite it.
- Tunable values (time limits, retry counts, thresholds) are collected in section 11 so they can
  change without editing rule text.

## 1. General (GEN)

| ID | Rule | Enforced in |
|---|---|---|
| POL-GEN-01 | Permissions, actions, transfers and allowed tools are decided by deterministic rules in the service, tool gateway and orchestrator. Text produced by the LLM never grants a permission, triggers an action or skips a check. | Orchestrator, tool gateway |
| POL-GEN-02 | The assistant states as fact only values returned by a tool call in the current session (card, status, amount, currency, date, merchant, code, balance). A reply containing a fact that no tool call in the session returned is blocked by the grounding check and replaced with a template reply (POL-REL-04). | Grounding check |
| POL-GEN-03 | *(changed in 0.2)* The reply language is the **customer's preference**: Spanish (`usted` register) or Portuguese (`você`). The preference is the language chosen at sign-in or stated in the conversation; if none was stated, the language of the first message. It is never inferred from the customer's country or segment. If it cannot be determined, POL-ESC-11 applies. Data note: the dataset has no Brazilian customers (only México, Colombia, Argentina). Portuguese is served to any customer who prefers it, and Portuguese results are reported as such. | Orchestrator (language setting), templates |
| POL-GEN-04 | Default rule: a request that no rule in section 3 covers is out of scope. The assistant says what it can help with and offers a transfer (POL-ESC-09). It never improvises an answer or an action. | Orchestrator |
| POL-GEN-05 | Rule precedence: authentication (AUTH) > privacy (PII) > abstain/transfer (ESC) > actions (ACT) > answers (ANS). If two rules conflict, the more restrictive one applies. | Policy engine |
| POL-GEN-06 | *(new in 0.2, F-09)* If only part of a customer message maps to an intent, the assistant answers that part and says in one sentence which part it did not answer. | Orchestrator |
| POL-GEN-07 | *(new in 0.2, F-22)* Stale data. (a) A fact presented as current is read again before it is stated or filed in a case file if the tool result is older than `FACT_MAX_AGE_SEC`, or if an action with effect ran after it was read. Facts filed as history (for example "status before the action") are labeled as such and are not re-read. (b) Balances are never reused: every balance stated is read by `get_balance` in the same turn. (c) Every balance is stated with its `as_of` time from the tool. If `as_of` is older than `BALANCE_SNAPSHOT_MAX_AGE_H` at reply time, the reply adds POL-BAL-03. | Orchestrator (fact cache with read times), templates |

## 2. Authentication and sessions (AUTH)

| ID | Rule | Enforced in |
|---|---|---|
| POL-AUTH-01 | Levels. **L0** anonymous: no customer data and no tools except `authenticate`. **L1** session: established by `authenticate` with test credentials issued by the mock identity service. Allows read tools. **L2** step-up: L1 plus a one-time code from `step_up`. Required for any action with effect (`block_card`). | Mock identity, tool gateway |
| POL-AUTH-02 | A national ID (`document_number`), `customer_id`, card number, name or date of birth typed in chat never authenticates or raises the level. Authentication happens only through the identity service. | Mock identity |
| POL-AUTH-03 | Session expiry: idle timeout `SESSION_IDLE_MIN`, absolute timeout `SESSION_MAX_MIN`. After expiry every tool call returns `SESSION_EXPIRED`, the assistant discloses no further data and asks the customer to authenticate again. | Mock identity, tool gateway |
| POL-AUTH-04 | Step-up validity: `STEPUP_TTL_MIN` minutes, single use, bound to one card and one action. It is consumed by the first `block_card` call that uses it, whatever the result. | Mock identity, action gateway |
| POL-AUTH-05 | *(changed in 0.2, F-18)* A session is bound to exactly one `customer_id`. Every tool filters by the session's customer. A request for a card, account or transaction that is not the session customer's gets the same reply as a card that does not exist (POL-ANS-18), so the assistant never reveals whether another customer's card exists. The only lookup outside the session customer is the gateway's **ownership check** on a full card number typed by the customer (POL-ESC-10). Its result goes only to the security counter and the audit log, never to a reply, the LLM or the customer-visible conversation. | Tool gateway, mock bank |
| POL-AUTH-06 | After `STEPUP_MAX_FAILS` failed step-up attempts in a session, step-up is locked for that session, the pending action is cancelled and the case is transferred (POL-ESC-10). | Mock identity, orchestrator |
| POL-AUTH-07 | *(changed in 0.2, F-23)* Re-authenticating after expiry starts a new session. Pending confirmations, confirmation tokens, step-up and tool results are not carried over. The orchestrator keeps only `resume_intent`: the intent name and the slots the customer typed, with no tool-derived data. After sign-in the assistant may ask a fact-free resume question (for example "¿Quiere retomar lo que estaba haciendo?"). If the customer accepts, the intent is routed from the start with fresh reads and a new step-up. | Orchestrator |
| POL-AUTH-08 | Credentials and one-time codes are never entered in the chat. If a customer types one, it is redacted (POL-PII-04) and the customer is told not to share it in the chat. | Redaction layer |
| POL-AUTH-09 | *(new in 0.4)* Customer status. `authenticate` returns the session customer's `customer_status` (gold `customers`). A customer whose status is `Suspended` or `Closed` may authenticate, but gets **no answers and no actions**: the orchestrator opens a handoff right after sign-in, with `reason_rule_ids` = [`POL-AUTH-09`], priority `normal` (unless POL-HND-15 gives a higher one), and the unresolved question "customer status requires human review". No tool except `authenticate` and `open_handoff` runs in that session. The reply is POL-HND-07 followed by POL-HND-03 and states no customer data, not even the status itself. Later messages are appended to the case (POL-HND-06). `Active` and `Inactive` customers are served normally. The same check runs on every re-authentication (POL-AUTH-07). | Mock identity (status in the session), orchestrator |

## 3. What the assistant may answer (ANS)

Each answer is allowed only at L1 or higher, only about the session customer's products, and
only with data returned by the tool listed.

| ID | The assistant may answer | Tool | Fields it may state | Limits |
|---|---|---|---|---|
| POL-ANS-01 | Which cards the customer has | `list_cards` | last 4 digits, card type (credit/debit), status | Never the full card number. |
| POL-ANS-02 | *(changed in 0.3)* A card's current status | `get_card_status` | status (`Active`, `Blocked`, `Suspended`, `Closed`), with the card type and last 4 digits | Current status only. No history, date or cause of a status change (P2: blocked cards have no history). Cause questions go to POL-ESC-02. |
| POL-ANS-03 | *(changed in 0.2, F-08)* Recent transactions on a card | `list_transactions` | date, amount, currency, transaction type, merchant (if present), status | Window defaults to the last `TX_DEFAULT_DAYS` days, capped at `TX_MAX_DAYS` days and `TX_MAX_ROWS` rows. If the customer needs older history, the assistant states the limit and offers a transfer. If the list is empty, say so and nothing more (POL-ANS-06). |
| POL-ANS-04 | What one transaction is | `describe_transaction` | the POL-ANS-03 fields plus status meaning (POL-TXS) and response-code meaning (POL-DEC) | Fixed templates only. No root cause. |
| POL-ANS-05 | What the assistant can and cannot do | none (static text) | this list and the section 4 actions | Static text versioned with this policy. |
| POL-ANS-06 | "No data" answers | the tool that returned nothing | the fact that no record was found in the searched window | Never infer anything from an absence (for example "so you were not charged"). |
| POL-ANS-15 | *(new in 0.2)* A credit card's balance | `get_balance` | `current_balance`, `credit_limit`, currency, `as_of`, rendered with POL-BAL-01 | Values are stated as recorded. The assistant never computes or states available credit, a minimum payment or a due date: the data dictionary does not define the sign or meaning of a card balance, and 1.27% of credit cards have a balance above their limit. If `current_balance` > `credit_limit`, or *(0.4)* `credit_limit` is null (5.05% of credit cards, random), it states the balance only with POL-BAL-06 and adds POL-BAL-04. A request for available credit gets POL-BAL-05. |
| POL-ANS-16 | *(new in 0.2)* A savings account's balance (`Cuenta Ahorro`) | `get_balance` | `current_balance`, currency, `as_of`, status if not `Active`, rendered with POL-BAL-02 | No interest, movements or statements. Account transactions are out of scope. |
| POL-ANS-17 | *(new in 0.2)* Which products have a balance the assistant can give | `list_balance_products` | product kind (credit card or savings account), last 4, status | Eligible: credit cards and savings accounts with status other than `Closed`. Debit cards, current accounts, loans and investments are not eligible (a debit card's own `current_balance` has no defined relation to the linked account). |

Product identification:

| ID | Rule | Enforced in |
|---|---|---|
| POL-ANS-07 | *(changed in 0.2, F-13)* For each intent the orchestrator computes the **eligible** products (table below). Exactly one eligible → the assistant does not ask; it names the product in the reply ("su tarjeta de crédito terminada en 2952"). Two or more eligible and the request does not identify one → ask for the last 4 digits, listing the candidates as type + last 4 (P2: 30.99% of card holders have 2+ active cards). None eligible → say so (for example "no tiene tarjetas activas") and apply POL-GEN-04. | Orchestrator |
| POL-ANS-08 | If two eligible products share the same last 4 digits (P2: 6 customers), also ask for the type. If type + last 4 is still not unique, transfer (POL-ESC-05). A shared last 4 is not a miss (POL-ANS-18). | Orchestrator |
| POL-ANS-09 | *(changed in 0.2, F-10)* If several transactions match the customer's description, list them and ask the customer to choose. Never pick one silently. Before a transaction is attached to a dispute, the customer confirms it, **even when only one matches**. | Orchestrator |
| POL-ANS-18 | *(new in 0.2, F-17)* Card miss: the customer names a card (last 4 or full number) that matches none of their eligible cards. The assistant lists the customer's eligible cards by type + last 4 and asks once. The reply is identical whether the named card belongs to another customer, does not exist, or is a typo. A second consecutive miss is an unauthorized attempt and is transferred (POL-ESC-10). | Orchestrator, tool gateway |

Eligible products per intent (POL-ANS-07):

| Intent | Eligible products |
|---|---|
| `card_list` | none needed |
| `card_status`, `transaction_list`, `transaction_detail`, `charge_dispute` | all the customer's cards |
| `card_block` | cards with status `Active` |
| `block_reason` | cards with status `Blocked` or `Suspended` |
| `card_unblock` | cards with status `Blocked` |
| `balance_inquiry` | POL-ANS-17 products, narrowed by the `product_kind` slot ("tarjeta" → credit cards; "cuenta de ahorros"/"caja de ahorro"/"poupança" → savings accounts) |

Intent names and slots are defined in `docs/intents.md`. If the `product_kind` slot names a
product the intent does not serve (a debit card or current account balance, savings account
movements), no eligible products are computed and POL-ANS-14 applies.

Explicitly not answered (each leads to the rule shown):

| ID | Not answered | Why | Goes to |
|---|---|---|---|
| POL-ANS-10 | Why a transaction was declined, beyond the code's meaning | Response codes are assigned at random in the data (P2), so they carry no cause | POL-DEC templates, then POL-ESC-04 if the customer asks for the cause |
| POL-ANS-11 | Why or when a card was blocked or suspended | No status history exists (P2) | POL-ESC-02 |
| POL-ANS-12 | Whether a transaction is fraudulent, or any fraud score | `fraud_score` leaks the `is_fraud` label and is excluded (Day 1 A5). Fraud assessment is a human task. | POL-ESC-01 |
| POL-ANS-13 | Card opening or expiration dates, or "your card is expired" | Validity dates contradict the transactions (P2: 29.88% of card transactions postdate the expiration date) | POL-ESC-04 |
| POL-ANS-14 | *(changed in 0.2)* Available credit, minimum payments, due dates, debit-card or current-account balances, account movements, loans, investments, credit | Not in scope, or not defined in the data | POL-BAL-05 for available credit; POL-GEN-04 for the rest (T-10) |

## 3b. Balance templates (BAL)

`{saldo}`, `{limite}` and amounts in every template are formatted by the renderer with the
number convention of the customer's country (México: 1,234.56; Colombia and Argentina:
1.234,56). `{as_of}` is rendered as date and time in the reply language.

| ID | Case | Español | Português |
|---|---|---|---|
| POL-BAL-01 | Credit card balance | "El saldo actual de su tarjeta de crédito terminada en {ultimos4} es de {saldo} {moneda} y su límite de crédito es de {limite} {moneda}, según los datos del {as_of}." | "O saldo atual do seu cartão de crédito final {ultimos4} é de {saldo} {moeda} e o limite de crédito é de {limite} {moeda}, segundo os dados de {as_of}." |
| POL-BAL-02 | Savings account balance | "El saldo actual de su cuenta de ahorros terminada en {ultimos4} es de {saldo} {moneda}, según los datos del {as_of}." | "O saldo atual da sua conta poupança final {ultimos4} é de {saldo} {moeda}, segundo os dados de {as_of}." |
| POL-BAL-03 | `as_of` older than `BALANCE_SNAPSHOT_MAX_AGE_H` | "Estos datos pueden no incluir los movimientos más recientes." | "Esses dados podem não incluir as movimentações mais recentes." |
| POL-BAL-04 | Balance above the recorded limit | "No puedo confirmar el límite de crédito de esta tarjeta." | "Não consigo confirmar o limite de crédito deste cartão." |
| POL-BAL-05 | Available credit requested | "No puedo calcular el crédito disponible; solo puedo indicarle el saldo y el límite registrados. Si lo necesita, puedo transferirle con un asesor." | "Não consigo calcular o crédito disponível; só posso informar o saldo e o limite registrados. Se precisar, posso transferir você para um atendente." |
| POL-BAL-06 | *(new in 0.4)* Credit card balance without a usable limit (limit null, or balance above it) | "El saldo actual de su tarjeta de crédito terminada en {ultimos4} es de {saldo} {moneda}, según los datos del {as_of}." | "O saldo atual do seu cartão de crédito final {ultimos4} é de {saldo} {moeda}, segundo os dados de {as_of}." |

`as_of` is the time the daily gold load finished, `max(gold_loaded_at)`
(`docs/contracts/freshness_policy.md` section 2). It is not `products.last_updated`: that field
is not tied to the balance, and 6.27% of its values are after the end of the data.

## 4. Actions (ACT)

The only action with an effect is `block_card`. Every other change goes to a human.

| ID | Rule | Enforced in |
|---|---|---|
| POL-ACT-01 | `block_card` preconditions: (a) the session is at L2 with a valid, unused step-up bound to this card (POL-AUTH-04); (b) the card belongs to the session customer (POL-AUTH-05); (c) the card's current status, read with `get_card_status` in this turn, is `Active`. If it is `Blocked`, tell the customer it is already blocked and do not call the tool. If it is `Suspended` or `Closed`, transfer (POL-ESC-12). | Action gateway |
| POL-ACT-02 | Explicit confirmation. Before calling `block_card` the assistant shows a confirmation prompt that names the card type and last 4 digits and states that the card will stop working and that the assistant cannot unblock it. Only a clear yes in the next customer turn counts. The gateway then issues a confirmation token bound to (session, card, action), valid `CONFIRM_TTL_SEC` seconds and single use. A "yes" in the same message as the request does not count. | Orchestrator, action gateway |
| POL-ACT-03 | A confirmation that names a different last 4 digits, is ambiguous ("I think so", "ok but first…"), or is not an affirmation cancels the pending action. The assistant confirms the cancellation and nothing is executed. | Orchestrator |
| POL-ACT-04 | One confirmation, one card. Blocking several cards needs one confirmation per card. | Action gateway |
| POL-ACT-05 | *(changed in 0.2, F-24, F-26)* Post-action verification. After `block_card` returns, the gateway reads `get_card_status`. The assistant reports the block as done (POL-ACT-11) only if that read returns `Blocked`. If `block_card` errors or times out, or the read returns another status or fails after retries (POL-REL-01), the assistant replies with POL-ACT-10 and transfers with priority `urgent` (POL-HND-15). | Action gateway |
| POL-ACT-06 | `block_card` is sent at most once per confirmation token (the token is the idempotency key). It is never retried blindly. Only the verification read is retried. | Action gateway |
| POL-ACT-07 | Unblocking, reactivating or replacing a card always goes to a human (POL-ESC-03). The assistant has no tool for it, because nothing in the data shows whether a block was legitimate. | Tool registry (no such tool) |
| POL-ACT-08 | No money movement: no transfers, payments, refunds, reversals, chargebacks, limit changes or fee waivers. There is no tool for any of them. Requests go to POL-ESC-01 (charge disputes) or POL-GEN-04 (everything else). | Tool registry (no such tool) |
| POL-ACT-09 | *(changed in 0.2, F-25)* Actions are recorded in the audit log and the case file with `requested`, `executed` (`true`, `false` or `unknown`) and `verified` (`true` or `false`). `executed` is `unknown` when the write call errors or times out without saying whether it was applied. Only `verified = true` is described to the customer as done. | Action gateway, audit log |

Action templates:

| ID | Case | Español | Português |
|---|---|---|---|
| POL-ACT-10 | *(new in 0.2, F-24)* Block outcome unknown or not verified | "No pude confirmar si su tarjeta terminada en {ultimos4} quedó bloqueada. Por seguridad, considere que la tarjeta NO está bloqueada. Transferí su caso a un asesor como urgente, referencia {case_id}." | "Não consegui confirmar se o seu cartão final {ultimos4} foi bloqueado. Por segurança, considere que o cartão NÃO está bloqueado. Transferi o seu caso para um atendente como urgente, referência {case_id}." |
| POL-ACT-11 | *(new in 0.2, F-06)* Block verified | "Listo: su tarjeta {tipo} terminada en {ultimos4} está bloqueada. Para desbloquearla o pedir una tarjeta nueva, tiene que hablar con un asesor; puedo transferirle si lo desea." | "Pronto: o seu cartão {tipo} final {ultimos4} está bloqueado. Para desbloquear ou pedir um cartão novo, é preciso falar com um atendente; posso transferir você, se quiser." |

`{tipo}` is "de crédito" / "de débito" (es) and "de crédito" / "de débito" (pt).

## 5. Abstain and transfer (ESC)

"Transfer" means: call `open_handoff` with the case file (section 8), then tell the customer
the reason and POL-HND-03, only after `open_handoff` returns a case ID. "Abstain" means: state
what is verified, say plainly what the assistant cannot confirm, and offer a transfer.

| ID | Trigger | Behavior | Enforced in |
|---|---|---|---|
| POL-ESC-01 | *(changed in 0.2, F-10, F-11)* Dispute: an unrecognized charge, suspected fraud, a request for a refund or chargeback | (1) Identify the card and the transaction and **confirm the transaction with the customer**, even if only one matches (POL-ANS-09). If none matches, transfer with that as an unresolved question. (2) If the card is `Active`, **offer** to block it: a yes runs the normal flow (step-up, confirmation, verification, POL-ACT-01 to 05). The block is never automatic. A no, or anything else, skips it. (3) Transfer. The assistant never says the charge is valid or fraudulent. | Orchestrator |
| POL-ESC-02 | "Why was my card blocked/suspended?" | State the current status only (POL-ANS-02) and transfer. | Orchestrator |
| POL-ESC-03 | Unblock, reactivate or replace a card | Transfer. | Orchestrator |
| POL-ESC-04 | Unverifiable fact: the customer asks for a cause, intent or fact that no tool returns (the cause of a decline, whether a merchant is legitimate, what was bought, expiration dates) | Abstain. If the customer insists or the fact is needed to resolve the request, transfer. | Orchestrator, grounding check |
| POL-ESC-05 | Missing or inconsistent data: a required field is null, the response code is not in section 6, product identity stays ambiguous after POL-ANS-08, a transaction date falls outside the card's validity dates, or a balance is above the limit | State only the verified fields and say the rest is not available. If the missing part is needed to resolve the request, transfer. | Tool gateway (field checks), orchestrator |
| POL-ESC-06 | Classifier uncertainty. The conformal prediction set at level `CONFORMAL_ALPHA`: **1 label** → act on it; **2 to `CONFORMAL_MAX_SET` labels** → ask one clarifying question naming the candidates in plain words; **empty or larger than `CONFORMAL_MAX_SET`** → transfer. If a set contains an action intent, no action runs until the customer clarifies. After `MAX_CLARIFY_TURNS` clarifications in a row for the same request, transfer. | Orchestrator (not a prompt) |
| POL-ESC-07 | Repeated tool failure: a tool call still fails after the retries in POL-REL-01, or `SESSION_TOOL_FAIL_MAX` failed tool rounds happen in one session, or a block could not be verified (POL-ACT-05) | Safe fallback: say the service cannot complete the request now, make no claim about the outcome, transfer. For an unverified block, use POL-ACT-10. If `open_handoff` also fails, POL-HND-05 and the local fallback queue (POL-REL-03). | Orchestrator |
| POL-ESC-08 | *(changed in 0.2, F-21)* Suspected prompt injection: text that tells the assistant to ignore rules, claims a role or authority ("I am the bank's admin"), contains tool-call or system-prompt syntax, or asks for data about another person | First time: do not follow it, do not quote it back, keep serving the request within policy. Second time in the session: end automated handling and transfer. Any transfer in a session with a suspected injection gets priority `security` (POL-HND-15). Injection cannot grant permissions in any case (POL-GEN-01). | Orchestrator (detector), tool gateway |
| POL-ESC-09 | The customer asks for a human, in any wording | Transfer right away. No retention attempt and no extra questions. | Orchestrator |
| POL-ESC-10 | *(changed in 0.2, F-18)* Unauthorized access attempt. Exactly these count: (a) a full card number typed by the customer that the gateway's ownership check finds on **another customer's** card; (b) a request for another person's data (another customer's ID, name, card or account, "my spouse's card"); (c) a second consecutive card miss (POL-ANS-18); (d) step-up lockout (POL-AUTH-06). A single non-matching last 4 is a typo, not an attempt. A last 4 alone never triggers the ownership check, because it matches thousands of cards. | The reply to (a) is identical to a card miss (POL-ANS-18) and never reveals whether the card exists. On (c), (d), or a second attempt of any kind: transfer with priority `security`. | Tool gateway (ownership check), orchestrator |
| POL-ESC-11 | Language: the message is in neither Spanish nor Portuguese, or mixes them so that intent is unclear, and no preference was stated (POL-GEN-03) | Ask once, in both Spanish and Portuguese, which language to continue in. If it is still unclear, or the language is unsupported, transfer. | Orchestrator |
| POL-ESC-12 | An action requested on a `Suspended` or `Closed` card | Tell the customer the current status and transfer. | Action gateway |

## 6. Transaction and decline-code templates (TXS, DEC)

Response codes in the data are uniform across statuses and do not track amount, expiry or
fraud (P2 section c). The DEC templates therefore state **only what the code means in payment
networks** and always end with the disclaimer. They never say that the customer lacked funds,
that the card is expired or invalid, or anything about fraud.

*(changed in 0.2, F-02)* A reply about one transaction is composed as: **TXS sentence**
(subject with the facts + status) → for a non-approved transaction with a code, **DEC prefix**
+ **meaning** + **disclaimer**. The DEC prefix carries no facts, so nothing is repeated
(POL-DEC-93). Placeholders are filled from `describe_transaction` output only.

**Transaction subject** (used by every TXS template):

| Type | Español (gender) | Português (gender) |
|---|---|---|
| Purchase | "La compra" (f) | "A compra" (f) |
| Payment | "El pago" (m) | "O pagamento" (m) |
| Withdrawal | "El retiro" (m) | "O saque" (m) |

Subject es: "{Tipo} del {fecha} por {monto} {moneda}[ en {comercio}] con la tarjeta terminada en {ultimos4}".
Subject pt: "{Tipo} de {data} no valor de {valor} {moeda}[ em {comercio}] no cartão final {ultimos4}".
The merchant part is omitted when the merchant is null.

| ID | Status | Español (f / m) | Português (f / m) |
|---|---|---|---|
| POL-TXS-01 | Approved | "{subject} fue aprobada." / "fue aprobado." | "{subject} foi aprovada." / "foi aprovado." |
| POL-TXS-02 | Declined | "{subject} fue rechazada." / "fue rechazado." | "{subject} foi recusada." / "foi recusado." |
| POL-TXS-03 | Pending | "{subject} está pendiente: aún no se ha completado." | "{subject} está pendente: ainda não foi concluída." / "…concluído." |
| POL-TXS-04 | Reversed | "{subject} fue revertida: se anuló después de registrarse." / "fue revertido: se anuló…" | "{subject} foi estornada: foi anulada depois de registrada." / "foi estornado: foi anulado depois de registrado." |

Templates never promise that money was or will be returned, or give a time frame.

| Part | Español | Português |
|---|---|---|
| DEC prefix | "Tiene registrado el código de respuesta {codigo}, que en las redes de pago significa:" | "Tem registrado o código de resposta {codigo}, que nas redes de pagamento significa:" |
| DEC disclaimer (always) | "Este código es lo que muestra el registro; no me permite confirmar la causa. Si necesita saber por qué ocurrió, puedo transferirle con un asesor." | "Esse código é o que consta no registro; ele não me permite confirmar a causa. Se precisar saber por que isso aconteceu, posso transferir você para um atendente." |

| ID | Code | Meaning (es) | Meaning (pt) | Never say |
|---|---|---|---|---|
| POL-DEC-05 | 05 | "no autorizada por el emisor, sin un motivo específico." | "não autorizada pelo emissor, sem motivo específico." | that it was fraud, a security block or the customer's fault |
| POL-DEC-14 | 14 | "número de tarjeta inválido." | "número de cartão inválido." | that the card is cloned, damaged or was typed wrong |
| POL-DEC-51 | 51 | "fondos insuficientes." | "saldo insuficiente." | that the customer did not have enough money, or any balance figure |
| POL-DEC-54 | 54 | "tarjeta vencida." | "cartão vencido." | that the customer's card is expired, or any expiration date (POL-ANS-13) |

| ID | Case | Español | Português |
|---|---|---|---|
| POL-DEC-90 | No code recorded (null, ~5% of rows) | "No hay un código de respuesta registrado para esta transacción." | "Não há código de resposta registrado para esta transação." |
| POL-DEC-91 | Code not in this table | "No tengo una descripción aprobada para este código." Then POL-ESC-05. | "Não tenho uma descrição aprovada para este código." Then POL-ESC-05. |
| POL-DEC-92 | Approved transaction (code 00) | Code not mentioned; the TXS sentence is enough. | Same. |
| POL-DEC-93 | *(new in 0.2, F-02)* Composition | The DEC prefix is used only right after the TXS sentence for the same transaction. | Same. |

## 7. Customer-facing wording of transfers

| ID | Rule |
|---|---|
| POL-HND-01 | *(changed in 0.2, F-15)* When transferring, the assistant says why in plain words tied to the triggering rule (for example "I can't see the reason for a block"), then renders POL-HND-03 with the case ID returned by `open_handoff`. It promises no outcome and no time frame. |
| POL-HND-02 | If `open_handoff` did not return a case ID, the assistant does not give one. It renders POL-HND-05 instead (POL-REL-03). |
| POL-HND-06 | *(new in 0.2, F-16)* After a transfer (state `HANDED_OFF`), every customer message is appended to the case, the reply is POL-HND-04, and no tool runs. If the message maps to another ESC rule (for example an unblock request, POL-ESC-03), that rule ID is added to `reason_rule_ids`. A second suspected injection or unauthorized attempt raises the priority to `security`. |

| ID | Case | Español | Português |
|---|---|---|---|
| POL-HND-03 | *(new in 0.2, F-15)* Case opened | "Un asesor revisará su caso, referencia {case_id}." | "Um atendente vai analisar o seu caso, referência {case_id}." |
| POL-HND-04 | *(new in 0.2, F-16)* Message after transfer | "Agregué su mensaje a su caso, referencia {case_id}. Un asesor lo revisará." | "Adicionei sua mensagem ao seu caso, referência {case_id}. Um atendente vai analisá-la." |
| POL-HND-07 | *(new in 0.4)* Customer status requires review (POL-AUTH-09) | "Para atender su solicitud, un asesor necesita revisar su caso." | "Para atender a sua solicitação, um atendente precisa analisar o seu caso." |
| POL-HND-05 | *(new in 0.2)* `open_handoff` failed | "No pude registrar su caso en este momento. Por favor, comuníquese con el centro de contacto del banco." | "Não consegui registrar o seu caso agora. Por favor, entre em contato com a central de atendimento do banco." |

## 8. Handoff case file (HND)

Every transfer creates exactly one case file through `open_handoff`. All five content fields
are required. An empty list is allowed but must be explicit, so a missing field is a contract
violation, not an empty result. Evaluation row E-12 checks this contract.

| ID | Field | Content | Source rule |
|---|---|---|---|
| POL-HND-10 | `request` | What the customer wants: the last relevant customer message (redacted per POL-PII-01) and a one-line summary. The summary is marked `generated_by: model` and is never treated as a fact. Also the top intent and the conformal set. | Orchestrator |
| POL-HND-11 | `verified_facts` | A list of `{fact, value, tool_call_id}`. Every item comes from a tool result in this session and respects POL-GEN-07. No item may come from LLM text. | Orchestrator, grounding check |
| POL-HND-12 | `actions_taken` | *(changed in 0.2, F-25)* A list of `{action, card_last4, confirmation_token_id, requested_at, executed, verified, verification_tool_call_id}`, with `executed` ∈ {`true`, `false`, `unknown`} (POL-ACT-09). It includes cancelled and unverified actions. | Action gateway |
| POL-HND-13 | `evidence` | A list of `{tool_call_id, tool, called_at, status, result_ref}` for every tool call in the session, the IDs of the products and transactions discussed, and `security_events` (type and turn only). | Tool gateway |
| POL-HND-14 | `unresolved_questions` | What the human must answer, in plain words. Always includes the reason the assistant could not resolve the case. | Orchestrator |
| POL-HND-15 | Metadata | *(changed in 0.2, F-21, F-26)* `case_id` (assigned by `open_handoff`), `created_at`, `policy_version`, `reason_rule_ids`, `language`, `customer_id`, `auth_level`, `priority`, `conversation_ref`, `appended_messages` (POL-HND-06). `priority` ∈ {`urgent`, `security`, `normal`}, with precedence urgent > security > normal: `urgent` for an action with effect that is not verified (POL-ACT-05); `security` for POL-ESC-10, for any transfer in a session with a suspected injection (POL-ESC-08), and for step-up lockout; otherwise `normal`. When `urgent` wins over `security`, the `security_events` stay in the evidence. | Orchestrator |

## 9. Privacy and retention (PII)

The dataset is synthetic, but the prototype treats it as if it were real customer data.

| ID | Rule | Enforced in |
|---|---|---|
| POL-PII-01 | Redacted before every LLM call (prompt, tool results and history), with typed placeholders that are restored only when the reply is shown to the same session's customer: first and last name, `document_number` and any typed ID number, full card numbers (any 13-19 digit sequence, kept as last 4 only), `customer_id`, email, phone numbers, address, postal code, date of birth. | Redaction layer |
| POL-PII-02 | Never sent to an LLM, not even redacted: credentials and one-time codes, `credit_score`, `estimated_monthly_income`, `gender`, `marital_status`, `education_level`, `occupation`, `fraud_score`, `is_fraud`. Tool results are reduced to the fields listed in section 3 before they reach the LLM. | Tool gateway (field allowlist) |
| POL-PII-03 | *(changed in 0.2)* The LLM may see: card type, last 4, status, and transaction date, amount, currency, type, merchant name, status and response code; for balance inquiries, product kind, last 4, `current_balance`, `credit_limit`, currency and `as_of`. | Tool gateway (field allowlist) |
| POL-PII-04 | Customer-typed secrets (passwords, codes, full card numbers) are redacted before the LLM, the logs and the traces. The raw text is not stored, except that the gateway's ownership check (POL-ESC-10) sees a typed full card number in memory for that one check. | Redaction layer |
| POL-PII-05 | *(changed in 0.3, F-19)* Logs, traces and stored transcripts hold only redacted text. The case file may hold `customer_id` and internal card and transaction IDs of the session customer, because the human agent works inside the bank's perimeter. Identifiers of **third parties** typed by the customer (another customer's ID, name or card) stay redacted in the case file. The raw value is not stored anywhere. The audit log keeps only a keyed hash of it (`docs/contracts/audit_log.md` AL-P5), which the security role can match against a known identifier. | Audit log, tracing, case store |
| POL-PII-06 | Retention in the prototype (synthetic, see section 11): transcripts `RETAIN_TRANSCRIPT_DAYS`, traces `RETAIN_TRACE_DAYS`, case files and audit log `RETAIN_CASE_DAYS`. Expired records are deleted by created date. The deletion procedure and the production values the bank would set are in `docs/operations.md` section 4. | Operations (`docs/operations.md`) |
| POL-PII-07 | *(changed in 0.3)* Access: customers see only their own session. Human agents see case files. Operators see traces and the audit log. Only the security role can re-identify the keyed pseudonyms and hashes in the audit log, through the backend (POL-PII-05). Nobody sees raw credentials. | Backend roles |
| POL-PII-08 | No real customer data, credentials or `ml/data/` files go into the repository, the public submission or any external model request. Demos use the synthetic personas in `docs/findings/day2/personas.md`. | Git rules, review before submission |
| POL-PII-09 | The LLM provider and its data-handling terms are declared in `docs/data_card.md`. Settings that stop the provider from training on or retaining data must be confirmed before any deployment beyond the prototype. | Documentation |

## 10. Reliability and audit (REL, AUD)

| ID | Rule | Enforced in |
|---|---|---|
| POL-REL-01 | Read tools (`list_cards`, `get_card_status`, `list_transactions`, `describe_transaction`, `list_balance_products`, `get_balance`): timeout `TOOL_TIMEOUT_SEC`, at most `READ_RETRIES` retries with backoff. Retries are recorded as separate tool calls. | Tool gateway |
| POL-REL-02 | Write tools (`block_card`, `open_handoff`) are called at most once per idempotency key. `open_handoff` may be retried with the same key. `block_card` may not (POL-ACT-06). | Action gateway |
| POL-REL-03 | If `open_handoff` fails after retries: render POL-HND-05 in the customer's language and write the case file to a local fallback queue for replay. Do not give a case ID. | Orchestrator |
| POL-REL-04 | If the LLM call fails, times out or produces a reply that fails the grounding check, send a deterministic template reply built from the same verified facts. After `LLM_FAIL_MAX` failures in a session, POL-ESC-07 applies. | Orchestrator |
| POL-AUD-01 | Every turn writes an audit event with `policy_version`, the state before and after, the rule IDs applied, the tool call IDs and results (redacted), and the decision (answer, clarify, act, abstain or transfer). | Audit log |
| POL-AUD-02 | Explanations to customers, agents and reviewers are rebuilt from audit events (rule IDs, tool results, execution records). Model chain-of-thought is not stored as an audit artifact. | Audit log |

## 11. Tunable parameters (synthetic values)

The values below are initial choices for the prototype, not measured requirements. The
conformal values are set in the intent model card on the calibration split, and this table
is updated to match.

| Parameter | Initial value | Used by |
|---|---|---|
| `SESSION_IDLE_MIN` | 15 min | POL-AUTH-03 |
| `SESSION_MAX_MIN` | 60 min | POL-AUTH-03 |
| `STEPUP_TTL_MIN` | 5 min | POL-AUTH-04 |
| `STEPUP_MAX_FAILS` | 3 | POL-AUTH-06 |
| `CONFIRM_TTL_SEC` | 120 s | POL-ACT-02 |
| `TX_DEFAULT_DAYS` / `TX_MAX_DAYS` / `TX_MAX_ROWS` | 30 / 90 / 20 | POL-ANS-03 |
| `CONFORMAL_ALPHA` | 0.10 (final value in model card) | POL-ESC-06 |
| `CONFORMAL_MAX_SET` | 2 | POL-ESC-06 |
| `MAX_CLARIFY_TURNS` | 2 | POL-ESC-06 |
| `CARD_MISS_MAX` | 2 consecutive misses | POL-ANS-18, POL-ESC-10 |
| `FACT_MAX_AGE_SEC` | 120 s | POL-GEN-07 |
| `BALANCE_SNAPSHOT_MAX_AGE_H` | 24 h (one daily batch load) | POL-GEN-07, POL-BAL-03 |
| `TOOL_TIMEOUT_SEC` | 5 s | POL-REL-01 |
| `READ_RETRIES` | 2 (backoff 0.5 s, 1 s) | POL-REL-01 |
| `SESSION_TOOL_FAIL_MAX` | 2 failed tool rounds | POL-ESC-07 |
| `LLM_FAIL_MAX` | 2 | POL-REL-04 |
| `RETAIN_TRANSCRIPT_DAYS` / `RETAIN_TRACE_DAYS` / `RETAIN_CASE_DAYS` | 30 / 30 / 90 | POL-PII-06 |

## 12. Traceability to the requirements matrix

| Matrix rows | Rules |
|---|---|
| D2-3, D2-4 (grounding in data and policy) | POL-GEN-02, POL-GEN-07, POL-ANS-*, POL-BAL-*, POL-DEC-*, POL-TXS-* |
| D2-2 (clarify ambiguity) | POL-ANS-07, 08, 09, 18, POL-ESC-06 |
| D2-6 (report only verified actions) | POL-ACT-05, POL-ACT-09, POL-ACT-10, POL-ACT-11 |
| D3-1 (what it can answer) | POL-ANS-01 to 18, POL-GEN-04, POL-GEN-06, POL-AUTH-09; intents in `docs/intents.md` |
| D3-2 (which actions need confirmation) | POL-ACT-01 to 04, POL-ESC-01 (offered block) |
| D3-3 (abstain or transfer) | POL-ESC-01 to 12, POL-AUTH-09 |
| D3-4, B-9 (enforcement outside prose) | POL-GEN-01, POL-AUTH-05, "Enforced in" column |
| D3-5 to D3-9 (handoff contents) | POL-HND-10 to 15 |
| B-7, B-8, D5-3 (authentication, expired session, customer status) | POL-AUTH-01 to 09 |
| D5-4, D5-5, D5-6, D5-7 (adverse cases) | POL-ESC-10, POL-ESC-08, POL-ESC-07 / POL-REL-*, POL-ESC-11 |
| D5-2 (incorrect or missing data) | POL-ESC-05, POL-DEC-90/91, POL-BAL-04 |
| S-8, S-9, S-10 (languages and their limits) | POL-GEN-03 |
| I-5, B-5, D6-8 (privacy, retention) | POL-PII-01 to 09 |
| D6-2, D6-3, D6-10 (retries, fallback, explanations) | POL-REL-01 to 04, POL-AUD-01/02 |
| B-11 (no money movement) | POL-ACT-08 |
