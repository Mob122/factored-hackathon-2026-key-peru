# Day 1 decision: Track A vs Track B

Date: 2026-09-28. Inputs: `docs/findings/day1/` (A1-A5, B1, B3, B4, C1) and the decision rule in section 4 of the proposal (`docs/proposal.pdf`, v1; the post-decision v2 is `docs/proposal.md`). B2 had not been run when this was written.

## The rule, as written

> Elegimos A si al menos tres de los cinco root causes aparecen con prevalencia de 1% o más en compras con tarjeta reales y los cargos no reconocidos son un motivo de contacto relevante. Elegimos B si identificamos contactos de seguimiento posteriores a un reclamo y un modelo simple sobre resolution_days logra un C-index de 0.65 o más frente a 0.5. Si ambas pasan, elegimos A por impacto en la demo; si solo B pasa, B; si ninguna, B con la limitación declarada, porque sus labels existen aunque tengan poca señal.

Both tracks are conjunctions: a track passes only if all of its criteria pass. The five root causes are the ones listed in proposal section 2: pipeline duplicate vs real double charge, preauthorization, currency conversion, recurrence and habitual merchant.

## Criteria

### Track A: Cargo Claro

| # | Criterion | Measured value | Threshold | Result | Source |
|---|---|---|---|---|---|
| A-i.1 | Root cause: pipeline duplicate vs real double charge | 0.00% exact duplicates; 0.00% repeat charges (distinct id, same product/merchant/amount, 10 min) out of 1,083,406 card purchases | >= 1% | Fail | A3 (3a, 3b) |
| A-i.2 | Root cause: preauthorization (Pending -> Reversed/Approved, 7 d) | 44 purchases = 0.004% (shuffled baseline 0.004%) | >= 1% | Fail | A3 (1) |
| A-i.3 | Root cause: currency conversion | 55.05% (10.08% excluding México). Artifact: MXN never appears, so every Mexican purchase counts as foreign, and purchase currency always equals the card's currency. Below the independence baseline (88.29%) | >= 1% | Pass (literal) | A3 (2) |
| A-i.4 | Root cause: recurrence (~30-day cycle) | Monthly pairs 0.066% of merchant purchases (shuffled 0.071%); monthly series 0.000% | >= 1% | Fail | A4 |
| A-i.5 | Root cause: habitual merchant (>= 3 prior purchases) | 1.41% (merchant-shuffle baseline 1.41%) | >= 1% | Pass (literal) | A3 (4) |
| **A-i** | **Root causes at >= 1%** | **2 of 5** (and 0 of 5 above generator noise) | **>= 3 of 5** | **Fail** | A3, A4 |
| A-ii | Unrecognized charges are a relevant contact reason | 20.24% of complaints (rank 1 of 5, but all 5 categories within 0.58 pp of a uniform 20%); 1.80% of all contacts (rank 7 of 11); absent from `contact_reason`, transcript intents and text; no dependence on country, channel or year | "relevant" (not quantified in the proposal) | Not met as a differentiating reason (ambiguous; does not affect the outcome) | A1 |
| **A** | **A-i and A-ii** | | | **Fail** | |

### Track B: Reclamo sin sorpresas

| # | Criterion | Measured value | Threshold | Result | Source |
|---|---|---|---|---|---|
| B-i | Follow-up contacts after a complaint are identified | Contacts during open complaints vs matched equal-length placebo: 22,648 vs 22,297, rate ratio 1.016 [0.996, 1.034] over 32,231 complaints; per customer-day 1.008. `contact_reason` mix p 0.49, `requires_followup` 34.40% vs 34.94%. Only signal: resolved/closed subgroup 1.17x (+1.1 contacts per 100 complaints, 0.02% of call volume), found post hoc. No follow-up reason exists in `contact_reason` and complaints cannot be linked to interactions (B4) | An excess of contacts over baseline that can be identified as follow-up | Fail | B1, B4 |
| B-ii | Simple model on `resolution_days` reaches C-index >= 0.65 | Not measured (B2 pending) | C-index >= 0.65 (vs 0.5) | Not measured | B2 |
| **B** | **B-i and B-ii** | | | **Fail** (B-i fails, so B-ii cannot change the result) | |

## Resulting choice

| A passes | B passes | Branch of the rule | Choice |
|---|---|---|---|
| No | No | "si ninguna, B con la limitación declarada" | **B** |

**Choice: B (Reclamo sin sorpresas), with the limitations below declared.**

The choice does not depend on B2. B already fails on B-i, so a B2 pass would still leave "neither passes" and the same branch. A B2 result only changes what B contains (see limitation 2).

## Limitations to declare

1. **No measurable failure demand (B1).** Customers contact the bank at the same rate whether or not a complaint is open, and those contacts look like any other contacts. The "fewer repeat contacts" business case cannot be measured on this data; any savings from it must be labeled as projected, not measured. This also conflicts with the proposal's section 5 plan, whose "Si falla" for B1 says to drop B. The section 4 rule overrides it for the double-failure case, and we apply the section 4 rule.
2. **ETA predictability not established (B2 pending).** Per proposal section 5, if B2 fails B ships follow-up only, without a model-based ETA. Prior evidence points that way: `resolution_days` is uniform on 1-30 and matches across complaint categories (A1, A2, B1).
3. **Complaint lifecycle data is unreliable (B1, C1).** 76.92% of complaints never get a resolution or closing date. Statuses Open, In Process and Escalated never age out: 34,343 complaints were created more than a year before the data end and are still open. `closing_date` is filled only for status Closed (3.70% of complaints). Open complaints cannot be treated as right-censored at the data end, because every observed `resolution_days` is at most 30. Any status answer or backlog KPI must state how stale cases are handled.
4. **`sla_breached` and the Regulator channel carry no signal (B3).** `sla_breached` is a ~20% flag independent of `resolution_days`, first response, priority, status, channel, country and category. The 717 Regulator complaints (1.07%) are not preceded by more history. The proposal's SLA and Regulator risk classifiers have no learnable target: an SLA target, if used, must be derived from timestamps against a declared threshold, and the dataset's own flag must be reported as unused.
5. **Complaints cannot be linked to interactions (B4).** `origin_interaction_id` is 100% null, and a customer-and-date join matches at chance (lift 1.05x). A customer's contact history is available only at the customer level, never per complaint.
6. **Data quality differs from the dictionary (C1).** 0 duplicates (declared ~2%), 0 late-arriving rows, `customers.registration_branch_id` and `service_agents.assigned_branch_id` FKs almost entirely broken, labels in Spanish, MXN absent (all Mexican amounts in USD). Contracts are adjusted to observed reality and the deviations reported.
7. **Language coverage.** The data is Spanish only (México, Colombia, Argentina). Transcripts hold 546 distinct texts, `detected_intents` is effectively constant, and `main_topics` copies `contact_reason`, so there are no real utterance-level labels. Portuguese interactions and any intent or relevance labels are team-generated and are declared as such.
8. **Synthetic data with little cross-row structure.** A3, A4, B1, B3 and B4 all find rows that behave as drawn independently given a few marginals. Results describe the generator, not a real bank, and models that depend on behavioral signal are expected to perform near their baselines.
9. **`fraud_score` leaks `is_fraud` (A5).** Not relevant to B's models, but any fraud reference in the demo or the mock bank must not use it.
10. **Criterion A-ii has no quantified threshold.** It does not affect the outcome, because A already fails on A-i.

## Amendment (2026-09-29): workflow re-chosen from P1-P3

Neither A nor B passed on its own premises, so the section 4 fallback (B with declared limitations) chose a track whose core thesis the data had refuted (B-i: rate ratio 1.016 [0.996, 1.034]). We dropped it and re-chose the workflow from contact-reason and feasibility evidence, as problem statement point 1 asks ("use this evidence to prioritize the workflow"). This choice is **post hoc**: P1-P3 were run after the Day 1 rule was applied, and the rule did not name them.

- **P1 (contact reasons).** Transaccional is the largest reason: 34.98% of 686,296 contacts, 91.51% FCR. Queja is 17.05% of contacts but 41.18% of unresolved ones. Reason differences are real (FCR range 47.91% vs 0.74% shuffled). Card servicing has no source label of its own.
- **P2 (card support).** Partially supported. 140,040 cards, 5.03% Blocked and 2.04% Suspended; 30.99% of holders have 2+ Active cards, so "which card?" is real ambiguity. Limits: the 4 decline codes are uniform across statuses (p 0.723), blocked/suspended cards have no history, and a card customer has a median of 0 card transactions per 30 days.
- **P3 (credit risk).** Refuted. `credit_score` and application features rank delinquency at chance (test AUC 0.4972-0.5048 vs shuffled 95th percentile 0.5060-0.5096), which rules out a credit-eligibility workflow.

**Choice: card and transaction inquiries assistant** (`docs/proposal.md`, v3). It covers the highest-volume reason (P1 FCR is the status-quo baseline) and rests on entities the data does carry (P2). Per P2 it does not explain decline or block causes, and unblocking always goes to a human. Limitations 3-10 above still apply where relevant.
