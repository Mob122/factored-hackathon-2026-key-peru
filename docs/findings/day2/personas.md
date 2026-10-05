# Day 2: demo personas, Transaccional transcripts (P4) and text vs contact_reason (P5)

Script: `ml/analysis/day2/personas.py` (rerunnable). Source: `ml/data/02_intermediate/` (all rows, no dedup; ids checked unique below).

## Verdicts

- **(a) Personas: supported.** Every scenario has real customers; the smallest has 3,773. S1 20,962, S2 28,785, S3 3,773, S4 58,916, S5 34,112 (of 150,000 customers). Blocked cards have 0 transactions, so S3 shows a blocked card with no history. S1's "last 30 active days" spans most of a customer's history; with a decline in the last 30 calendar days S1 still has 1,155 customers.
- **(b) P4: refuted.** All 546 distinct Transaccional texts are balance inquiries (100.00% of transcripts): savings-account balance or credit-card balance, followed by generic filler turns. No transcript asks about a charge, a declined payment, a transfer or blocking a card (0 transcripts). Every transcript in the table, for any reason, opens with one of the same 2 lines, and amounts are unfilled placeholders (`{monto}`).
- **(c) P5: refuted.** Text does not predict contact_reason. Each reason sees almost all 546 texts; grouped-split accuracy 0.3488 vs majority 0.3488, the same as with shuffled labels (0.3488). Even with no split the ceiling is 34.96%. The label is independent of the text, as in generator noise.

## What this means for the scope (docs/proposal.md v3)

- Keep the card workflow and its tool contracts (`list_cards`, `get_card_status`, `list_transactions`, `describe_transaction`, `block_card`, `open_handoff`). The data has customers for every demo scene: multi-card disambiguation with a decline (S1), a simple single-card inquiry (S2), a blocked + active pair (S3), the out-of-scope no-card customer that goes to handoff (S4), and pending/reversed items to describe (S5). Use the example ids below as fixtures for mock-bank tests and scenarios.
- S3 confirms section 4 and 11: a blocked card has no transactions, so "why was I blocked?" can only go to a human.
- Section 6 ("native transcript label if P5 shows it helps"): drop it. Transcripts carry two balance-inquiry openings and a label that is independent of the text, so they give neither utterances nor intent labels. The classifier is trained only on team-generated utterances, declared as such, as section 6 already allows.
- Section 3 cites Transaccional at 35% of interactions as the evidence for the track. That number stays, but nothing in the transcripts says what those contacts were about, so the claim that they are card or transaction inquiries is our framing, not something the data shows. State it that way in the write-up.
- Balance inquiry is the only request the transcripts contain, and 50.07% of Transaccional transcripts ask for the credit-card balance and available limit. It is cheap to add as a read-only intent (`get_card_status` already returns the card; add current_balance and credit_limit from products) and gives the demo one request grounded in the dataset's own conversations.
- Do not use `main_topics` or `detected_intents` from call_transcripts as labels or features: main_topics copies contact_reason in 100.00% of rows and detected_intents only takes the values `consulta_general`, `null`.

## (a) Demo personas

Customers: 150,000. Card holders: 91,084 (60.72%). Card transactions: 1,547,432; latest transaction in the dataset: 2026-06-18. Duplicate ids in 02_intermediate: customers 0, products 0, transactions 0; card transactions whose customer differs from the card owner: 0.

Distinct values used as filters (checked before filtering):

| product_type | product_status | cards |
|---|---|---|
| Tarjeta Crédito | Active | 85,090 |
| Tarjeta Crédito | Blocked | 4,932 |
| Tarjeta Crédito | Closed | 8,053 |
| Tarjeta Crédito | Suspended | 2,027 |
| Tarjeta Débito | Active | 33,749 |
| Tarjeta Débito | Blocked | 2,112 |
| Tarjeta Débito | Closed | 3,244 |
| Tarjeta Débito | Suspended | 833 |

Card transactions by status: Approved 1,423,048, Declined 77,714, Pending 30,885, Reversed 15,785. By type: Purchase 1,083,406, Withdrawal 232,392, Payment 231,634. customer_status: Active 127,700, Inactive 14,914, Suspended 4,407, Closed 2,979.

### Counts

| id | scenario | customers | % of customers | of which customer_status = Active |
|---|---|---|---|---|
| S1 | 2+ Active cards and a Declined card transaction in the last 30 active days | 20,962 | 13.97% | 17,905 |
| S2 | exactly 1 Active card with a Purchase on it in the last 90 days | 28,785 | 19.19% | 24,536 |
| S3 | exactly 1 Blocked card plus at least 1 Active card | 3,773 | 2.52% | 3,206 |
| S4 | no cards | 58,916 | 39.28% | 50,103 |
| S5 | a Pending or Reversed card transaction | 34,112 | 22.74% | 29,056 |

Context for each count:

- S1: 28,226 customers have 2+ Active cards; 20,962 of them
  (74.26%) have a Declined card transaction in their last
  30 active days, and 21,631 have one at any time. Customers have few
  card transactions, so the last 30 active days cover on average
  97.51% of a customer's card transactions: the window is close to "ever".
  With a calendar window instead (a decline in the last 30 days before
  2026-06-18) S1 has 1,155 customers. Among the 53,912 customers with
  exactly 1 Active card the active-days condition holds for 25,860
  (47.97%). Null check: the per-transaction decline rate is
  5.01% for 1-Active-card holders (702,345 transactions) and
  5.03% for 2+ (845,087), so the higher S1 rate comes from
  more transactions per customer, not from more declines per transaction.
- S2: "recent" means on or after 90 days before 2026-06-18. Customers with a
  card transaction in that window have a median of 2
  card transactions in it (mean 2.1).
- S3: 3,849 customers have at least 1 Blocked and 1 Active card; 2,533 have
  exactly one of each. Blocked cards with any transaction: 0 of
  7,044 (0 transactions), so a blocked card has no history
  to show.
- S4: of the 58,916 customers without cards, 48,494 hold some other product.
- S5: Pending 24,997 customers, Reversed 14,047 customers.
- Customers with two cards sharing the same last 4 digits: 6.

### Examples

Three customers per scenario, chosen by a seeded hash of customer_id (seed 2026). Cards: last 4 of product_number, type, status. Transactions: the last 10 card transactions of the customer across all their cards.

#### S1: 2+ Active cards and a Declined card transaction in the last 30 active days

**CLI-JAS4V4U7H60H** (Jorge Santiago Ramírez Ruiz, México, Basic). Cards: 2; card transactions in the dataset: 25.

| last 4 | type | status |
|---|---|---|
| 0044 | Tarjeta Crédito | Active |
| 7042 | Tarjeta Crédito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-06-06 17:43 | 7042 | Purchase | 478.41 | USD | Streaming Music | Approved | 00 |
| 2026-05-23 01:17 | 7042 | Purchase | 25.27 | USD | Boutique Moda | Approved | 00 |
| 2026-03-31 04:55 | 7042 | Purchase | 300.51 | USD |  | Approved | 00 |
| 2026-01-12 11:06 | 0044 | Purchase | 140.71 | USD | Internet Plus | Approved | 00 |
| 2025-12-07 11:59 | 0044 | Purchase | 251.38 | USD | Boutique Moda | Approved | 00 |
| 2025-11-20 16:35 | 7042 | Withdrawal | 311.25 | USD |  | Approved | 00 |
| 2025-11-04 10:28 | 7042 | Purchase | 473.72 | USD | Super Ahorro | Approved | 00 |
| 2025-10-23 02:16 | 7042 | Purchase | 383.39 | USD | Streaming Music | Declined | 54 |
| 2025-10-18 17:16 | 7042 | Purchase | 174.94 | USD | Centro Comercial | Approved | 00 |
| 2025-09-12 04:06 | 7042 | Purchase | 425.36 | USD | Restaurante El Buen Sabor | Approved | 00 |

**CLI-PETSG0SJC2G2** (Daniel Daniel López Jiménez, México, Plus). Cards: 3; card transactions in the dataset: 37.

| last 4 | type | status |
|---|---|---|
| 3968 | Tarjeta Crédito | Active |
| 6000 | Tarjeta Crédito | Active |
| 9130 | Tarjeta Crédito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-05-20 16:42 | 6000 | Purchase | 398.34 | USD | Empresa Telefónica | Approved | 00 |
| 2026-05-13 03:06 | 6000 | Payment | 1,408.00 | USD |  | Declined | 05 |
| 2026-04-11 04:06 | 9130 | Purchase | 438.79 | USD | Cable TV | Approved | 00 |
| 2026-04-08 14:22 | 6000 | Purchase | 169.33 | USD | Laboratorio Central | Approved | 00 |
| 2026-03-24 02:56 | 3968 | Purchase | 188.99 | USD | Ferretería | Approved | 00 |
| 2026-02-17 16:49 | 6000 | Purchase | 86.19 | USD | Cable TV | Declined | 51 |
| 2026-02-17 04:12 | 9130 | Purchase | 182.78 | USD | Uber | Approved | 00 |
| 2026-01-19 17:09 | 6000 | Purchase | 482.34 | USD | Streaming Music | Approved | 00 |
| 2026-01-10 01:35 | 9130 | Payment | 1,513.05 | USD |  | Approved | 00 |
| 2025-12-18 11:57 | 3968 | Withdrawal | 83.61 | USD |  | Approved | 00 |

**CLI-AYAHYQEG16BZ** (Gustavo Medina Ruiz, México, Basic). Cards: 2; card transactions in the dataset: 23.

| last 4 | type | status |
|---|---|---|
| 1883 | Tarjeta Débito | Active |
| 4950 | Tarjeta Crédito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-06-01 04:20 | 4950 | Purchase | 392.25 | USD | Empresa Telefónica | Approved | 00 |
| 2026-04-01 01:17 | 4950 | Purchase | 79.49 | USD | Uber | Approved | 00 |
| 2026-02-27 03:02 | 4950 | Purchase | 213.44 | USD | Super Ahorro | Approved | 00 |
| 2026-02-11 03:14 | 1883 | Purchase | 325.27 | USD | Cable TV | Approved | 00 |
| 2026-02-06 05:17 | 4950 | Purchase | 73.14 | USD | Internet Plus | Approved | 00 |
| 2025-05-29 01:35 | 1883 | Purchase | 437.54 | USD | Conciertos Live | Approved | 00 |
| 2025-05-09 07:20 | 1883 | Purchase | 388.53 | USD | Tienda General | Approved | 00 |
| 2025-04-24 14:27 | 1883 | Purchase | 146.39 | USD | Conciertos Live | Declined | 05 |
| 2025-03-20 08:16 | 1883 | Purchase | 20.27 | USD | Super Ahorro | Approved | 00 |
| 2025-01-04 14:24 | 1883 | Purchase | 498.21 | USD | Empresa Telefónica | Approved | 00 |

#### S2: exactly 1 Active card with a Purchase on it in the last 90 days

**CLI-SQJOCEDJJNCZ** (Camila Herrera Hernández, Colombia, Basic). Cards: 2; card transactions in the dataset: 13.

| last 4 | type | status |
|---|---|---|
| 5070 | Tarjeta Crédito | Active |
| 5419 | Tarjeta Débito | Closed |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-03-25 06:00 | 5070 | Purchase | 1,980,932.35 | COP | Teatro Nacional | Approved | 00 |
| 2025-11-13 01:36 | 5070 | Purchase | 1,616,632.72 | COP | Tienda General | Approved | 00 |
| 2025-08-29 02:45 | 5070 | Withdrawal | 232,902.67 | COP |  | Approved | 00 |
| 2025-08-26 04:33 | 5070 | Purchase | 1,395,895.55 | COP | Clínica Médica | Pending | 05 |
| 2025-06-25 04:31 | 5070 | Purchase | 684,978.78 | COP | Teatro Nacional | Approved | 00 |
| 2025-04-08 12:00 | 5070 | Purchase | 246,888.40 | COP | Boutique Moda | Approved | 00 |
| 2025-03-15 19:24 | 5070 | Purchase | 460,273.90 | COP | Cine Premium | Approved | 00 |
| 2025-02-25 13:44 | 5070 | Purchase | 1,455,936.44 | COP | Super Ahorro | Approved | 00 |
| 2024-07-26 06:27 | 5070 | Purchase | 1,391,975.50 | COP | Restaurante El Buen Sabor | Approved | 00 |
| 2023-12-26 13:26 | 5070 | Purchase | 1,273,325.60 | COP | Empresa Telefónica | Approved | 00 |

**CLI-JPK27B33SV65** (Verónica Rodríguez Moreno, México, Student). Cards: 1; card transactions in the dataset: 10.

| last 4 | type | status |
|---|---|---|
| 8407 | Tarjeta Crédito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-03-25 01:49 | 8407 | Purchase | 112.99 | USD | Gasolinera Express | Approved | 00 |
| 2026-02-13 00:15 | 8407 | Purchase | 222.76 | USD |  | Reversed | 14 |
| 2025-10-10 03:54 | 8407 | Payment | 1,415.16 | USD |  | Pending | 14 |
| 2025-06-01 00:09 | 8407 | Purchase | 25.39 | USD | Taxi Seguro | Approved | 00 |
| 2025-05-13 14:44 | 8407 | Payment | 1,097.87 | USD |  | Approved | 00 |
| 2024-09-09 17:15 | 8407 | Purchase | 144.66 | USD | Uber | Approved | 00 |
| 2024-09-09 16:23 | 8407 | Withdrawal | 159.13 | USD |  | Approved | 00 |
| 2024-04-18 00:08 | 8407 | Purchase | 452.10 | USD | Laboratorio Central | Approved | 00 |
| 2023-08-23 17:03 | 8407 | Purchase | 334.38 | USD | Farmacia Salud | Approved | 00 |
| 2023-08-10 08:14 | 8407 | Purchase | 119.37 | USD | Ferretería | Approved | 00 |

**CLI-LD6QVNCSTR43** (Leonardo Juan Castillo Romero, Colombia, Plus). Cards: 1; card transactions in the dataset: 10.

| last 4 | type | status |
|---|---|---|
| 4214 | Tarjeta Débito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-04-18 03:15 | 4214 | Purchase | 1,717,429.50 | COP | Tienda General | Approved | 00 |
| 2026-01-09 04:11 | 4214 | Payment | 964,999.82 | COP |  | Approved | 00 |
| 2025-10-03 19:30 | 4214 | Purchase | 320,986.91 | COP | Teatro Nacional | Approved | 00 |
| 2025-09-03 02:52 | 4214 | Payment | 2,806,487.64 | COP |  | Approved | 00 |
| 2025-06-03 15:41 | 4214 | Purchase | 613,081.38 | COP | Restaurante El Buen Sabor | Approved | 00 |
| 2024-12-26 09:54 | 4214 | Purchase | 1,188,437.74 | COP | Tienda Don José | Approved | 00 |
| 2024-11-23 10:13 | 4214 | Purchase | 1,241,124.23 | COP | Super Ahorro | Approved | 00 |
| 2024-03-26 18:22 | 4214 | Purchase | 1,036,592.31 | COP | Super Ahorro | Approved | 00 |
| 2024-02-15 22:23 | 4214 | Purchase | 748,391.32 | COP | Mercado Central | Approved | 00 |
| 2023-08-05 04:22 | 4214 | Purchase | 1,799,839.34 | COP | Cine Premium | Approved | 00 |

#### S3: exactly 1 Blocked card plus at least 1 Active card

**CLI-5B9VSCP2GSML** (Samuel Sebastián Mendoza Gutiérrez, México, Basic). Cards: 3; card transactions in the dataset: 30.

| last 4 | type | status |
|---|---|---|
| 6873 | Tarjeta Crédito | Active |
| 6898 | Tarjeta Débito | Active |
| 0727 | Tarjeta Crédito | Blocked |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-06-06 19:43 | 6873 | Purchase | 127.37 | USD | Uber | Declined | 54 |
| 2026-05-26 02:17 | 6873 | Purchase | 259.15 | USD | Cine Premium | Approved | 00 |
| 2026-05-12 13:00 | 6873 | Purchase | 132.63 | USD | Restaurante El Buen Sabor | Approved | 00 |
| 2026-04-21 20:21 | 6873 | Withdrawal | 259.65 | USD |  | Approved | 00 |
| 2025-12-15 10:47 | 6873 | Payment | 1,343.50 | USD |  | Approved |  |
| 2025-12-06 20:04 | 6898 | Purchase | 319.57 | USD | Estación de Servicio | Approved | 00 |
| 2025-09-05 01:07 | 6898 | Withdrawal | 143.35 | USD |  | Approved | 00 |
| 2025-09-02 19:10 | 6898 | Purchase | 89.17 | USD | Estación de Servicio | Approved | 00 |
| 2025-08-08 08:18 | 6873 | Purchase | 489.50 | USD | Mercado Central | Approved | 00 |
| 2025-04-11 03:50 | 6873 | Withdrawal | 195.89 | USD |  | Approved | 00 |

**CLI-EHVV6YJ6SL5W** (Jesús Medina García, Colombia, Basic). Cards: 4; card transactions in the dataset: 37.

| last 4 | type | status |
|---|---|---|
| 0245 | Tarjeta Crédito | Active |
| 7131 | Tarjeta Débito | Active |
| 8283 | Tarjeta Débito | Active |
| 7663 | Tarjeta Crédito | Blocked |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-05-21 18:15 | 0245 | Withdrawal | 95,978.45 | COP |  | Declined | 54 |
| 2026-05-15 15:55 | 8283 | Purchase | 201,117.21 | COP | Restaurante El Buen Sabor | Approved | 00 |
| 2026-03-06 12:01 | 0245 | Purchase | 21,033.96 | COP | Mercado Central | Approved | 00 |
| 2026-02-25 13:00 | 0245 | Withdrawal | 135,718.85 | COP |  | Approved | 00 |
| 2026-01-26 14:17 | 8283 | Purchase | 1,523,459.44 | COP | Cable TV | Approved | 00 |
| 2025-12-25 20:21 | 8283 | Purchase | 70,406.70 | COP | Centro Comercial | Approved | 00 |
| 2025-12-03 11:54 | 7131 | Purchase | 402,318.42 | COP | Empresa Telefónica | Approved | 00 |
| 2025-10-30 01:54 | 8283 | Purchase | 1,160,368.01 | COP | Internet Plus | Approved | 00 |
| 2025-10-14 21:18 | 8283 | Purchase | 713,990.02 | COP |  | Approved | 00 |
| 2025-09-23 23:48 | 0245 | Withdrawal | 269,045.94 | COP |  | Approved | 00 |

**CLI-AN7KXGR09TB2** (Rafael Cortés García, México, Basic). Cards: 3; card transactions in the dataset: 21.

| last 4 | type | status |
|---|---|---|
| 2960 | Tarjeta Crédito | Active |
| 7858 | Tarjeta Crédito | Active |
| 2952 | Tarjeta Crédito | Blocked |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-05-11 23:46 | 2960 | Purchase | 398.70 | USD | Conciertos Live | Approved | 00 |
| 2026-05-07 21:19 | 2960 | Purchase | 84.87 | USD | Teatro Nacional | Approved | 00 |
| 2026-04-14 00:00 | 7858 | Payment | 1,693.42 | USD |  | Approved | 00 |
| 2026-03-26 13:39 | 7858 | Purchase | 481.67 | USD | Farmacia Salud | Approved | 00 |
| 2025-11-08 12:31 | 2960 | Purchase | 216.65 | USD | Gasolinera Express | Approved | 00 |
| 2025-10-04 10:49 | 2960 | Purchase | 268.82 | USD | Estación de Servicio | Approved |  |
| 2025-09-11 22:45 | 7858 | Purchase | 351.14 | USD | Empresa Telefónica | Approved | 00 |
| 2025-07-17 15:27 | 7858 | Purchase | 432.60 | USD | Gasolinera Express | Approved | 00 |
| 2025-07-04 15:07 | 2960 | Purchase | 48.41 | USD | Restaurante El Buen Sabor | Approved | 00 |
| 2025-06-10 07:53 | 7858 | Purchase | 146.15 | USD | Restaurante El Buen Sabor | Approved | 00 |

#### S4: no cards

**CLI-FW98UJSYFLWX** (Pilar Contreras Cortés, México, Basic). Cards: 0; card transactions in the dataset: 0.

No cards.


**CLI-32SOFV0TBO24** (Isabella González Gutiérrez, México, Basic). Cards: 0; card transactions in the dataset: 0.

No cards.


**CLI-376Q3EAWFOCV** (Pedro Ramos Contreras, México, Student). Cards: 0; card transactions in the dataset: 0.

No cards.


#### S5: a Pending or Reversed card transaction

**CLI-SQJOCEDJJNCZ** (Camila Herrera Hernández, Colombia, Basic). Cards: 2; card transactions in the dataset: 13.

| last 4 | type | status |
|---|---|---|
| 5070 | Tarjeta Crédito | Active |
| 5419 | Tarjeta Débito | Closed |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-03-25 06:00 | 5070 | Purchase | 1,980,932.35 | COP | Teatro Nacional | Approved | 00 |
| 2025-11-13 01:36 | 5070 | Purchase | 1,616,632.72 | COP | Tienda General | Approved | 00 |
| 2025-08-29 02:45 | 5070 | Withdrawal | 232,902.67 | COP |  | Approved | 00 |
| 2025-08-26 04:33 | 5070 | Purchase | 1,395,895.55 | COP | Clínica Médica | Pending | 05 |
| 2025-06-25 04:31 | 5070 | Purchase | 684,978.78 | COP | Teatro Nacional | Approved | 00 |
| 2025-04-08 12:00 | 5070 | Purchase | 246,888.40 | COP | Boutique Moda | Approved | 00 |
| 2025-03-15 19:24 | 5070 | Purchase | 460,273.90 | COP | Cine Premium | Approved | 00 |
| 2025-02-25 13:44 | 5070 | Purchase | 1,455,936.44 | COP | Super Ahorro | Approved | 00 |
| 2024-07-26 06:27 | 5070 | Purchase | 1,391,975.50 | COP | Restaurante El Buen Sabor | Approved | 00 |
| 2023-12-26 13:26 | 5070 | Purchase | 1,273,325.60 | COP | Empresa Telefónica | Approved | 00 |

**CLI-JPK27B33SV65** (Verónica Rodríguez Moreno, México, Student). Cards: 1; card transactions in the dataset: 10.

| last 4 | type | status |
|---|---|---|
| 8407 | Tarjeta Crédito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-03-25 01:49 | 8407 | Purchase | 112.99 | USD | Gasolinera Express | Approved | 00 |
| 2026-02-13 00:15 | 8407 | Purchase | 222.76 | USD |  | Reversed | 14 |
| 2025-10-10 03:54 | 8407 | Payment | 1,415.16 | USD |  | Pending | 14 |
| 2025-06-01 00:09 | 8407 | Purchase | 25.39 | USD | Taxi Seguro | Approved | 00 |
| 2025-05-13 14:44 | 8407 | Payment | 1,097.87 | USD |  | Approved | 00 |
| 2024-09-09 17:15 | 8407 | Purchase | 144.66 | USD | Uber | Approved | 00 |
| 2024-09-09 16:23 | 8407 | Withdrawal | 159.13 | USD |  | Approved | 00 |
| 2024-04-18 00:08 | 8407 | Purchase | 452.10 | USD | Laboratorio Central | Approved | 00 |
| 2023-08-23 17:03 | 8407 | Purchase | 334.38 | USD | Farmacia Salud | Approved | 00 |
| 2023-08-10 08:14 | 8407 | Purchase | 119.37 | USD | Ferretería | Approved | 00 |

**CLI-GHRMPXT32BKK** (Raúl González Delgado, México, Basic). Cards: 2; card transactions in the dataset: 23.

| last 4 | type | status |
|---|---|---|
| 2771 | Tarjeta Crédito | Active |
| 7167 | Tarjeta Débito | Active |

| date | card | type | amount | cur | merchant | status | code |
|---|---|---|---|---|---|---|---|
| 2026-06-17 21:31 | 7167 | Purchase | 151.83 | USD | Teatro Nacional | Approved | 00 |
| 2026-02-26 20:54 | 2771 | Purchase | 75.14 | USD | Empresa Telefónica | Pending | 54 |
| 2026-02-25 15:35 | 7167 | Purchase | 30.99 | USD | Óptica Visión | Approved | 00 |
| 2026-02-01 00:43 | 2771 | Payment | 1,499.16 | USD |  | Approved | 00 |
| 2025-11-05 19:20 | 7167 | Purchase | 434.83 | USD | Tienda General | Approved | 00 |
| 2025-11-05 14:42 | 2771 | Purchase | 238.68 | USD | Restaurante El Buen Sabor | Approved | 00 |
| 2025-10-31 05:16 | 7167 | Purchase | 198.70 | USD | Tienda Don José | Approved | 00 |
| 2025-10-11 03:51 | 2771 | Withdrawal | 190.05 | USD |  | Approved | 00 |
| 2025-09-16 18:50 | 2771 | Purchase | 307.06 | USD | Taxi Seguro | Approved | 00 |
| 2025-08-09 00:12 | 7167 | Purchase | 310.67 | USD | Super Ahorro | Approved |  |

## (b) P4: what Transaccional customers ask

contact_reason values: Transaccional 240,056, Producto 150,863, Queja 117,021, Técnico 102,899, Comercial 54,879, Retención 20,578. Transaccional interactions: 240,056; with a transcript: 59,786 (24.91%). Transcripts without a matching interaction: 0. Distinct full_text among them: 546.

Each text is grouped by the customer's opening turn with keyword rules (block: `bloque`; declined: `rechaz|declin|no pasó`; charge: `cargo|cobro|no reconozco`; transfer: `transferencia|giro`; balance: `saldo`). All groups are listed, including empty ones.

| customer asks | distinct texts | transcripts | share |
|---|---|---|---|
| block card | 0 | 0 | 0.00% |
| declined payment | 0 | 0 | 0.00% |
| charge explanation | 0 | 0 | 0.00% |
| transfer status | 0 | 0 | 0.00% |
| balance | 546 | 59,786 | 100.00% |
| other | 0 | 0 | 0.00% |

Within balance: credit-card balance 29,936 transcripts (50.07%), savings-account balance 29,850.

Two examples per non-empty group (most frequent texts):

*balance*

- (18,002x) Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}.
- (17,894x) Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}.

Customer opening turns across **all** transcripts (every contact_reason):

| opening line | distinct texts | transcripts |
|---|---|---|
| Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. | 273 | 85,910 |
| Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. | 273 | 85,411 |

The 50 most frequent distinct Transaccional texts (turns separated by ` / `):

| # | transcripts | group | full_text |
|---|---|---|---|
| 1 | 18,002 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. |
| 2 | 17,894 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. |
| 3 | 423 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Perfecto, ¿necesita algo más? |
| 4 | 400 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Claro, estoy para servirle. |
| 5 | 395 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Perfecto, ¿necesita algo más? |
| 6 | 394 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: No hay problema, que tenga buen día. |
| 7 | 393 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Claro, estoy para servirle. |
| 8 | 392 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 9 | 389 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Perfecto, ¿necesita algo más? |
| 10 | 388 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 11 | 384 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 12 | 384 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 13 | 383 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Claro, estoy para servirle. |
| 14 | 380 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Claro, estoy para servirle. |
| 15 | 379 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: No hay problema, que tenga buen día. |
| 16 | 379 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 17 | 376 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. |
| 18 | 374 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Claro, estoy para servirle. |
| 19 | 374 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Perfecto, ¿necesita algo más? |
| 20 | 373 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Claro, estoy para servirle. |
| 21 | 371 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Perfecto, ¿necesita algo más? |
| 22 | 370 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Perfecto, ¿necesita algo más? |
| 23 | 364 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: No hay problema, que tenga buen día. |
| 24 | 364 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Perfecto, ¿necesita algo más? |
| 25 | 364 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: No hay problema, que tenga buen día. |
| 26 | 358 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 27 | 357 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: No hay problema, que tenga buen día. |
| 28 | 355 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 29 | 351 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Claro, estoy para servirle. |
| 30 | 347 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 31 | 344 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. |
| 32 | 339 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: No hay problema, que tenga buen día. |
| 33 | 333 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Claro, estoy para servirle. |
| 34 | 330 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Perfecto, ¿necesita algo más? |
| 35 | 39 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Perfecto, ¿necesita algo más? / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 36 | 39 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. / Cliente: Entiendo, muchas gracias. / Agente: No hay problema, que tenga buen día. |
| 37 | 38 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: No hay problema, que tenga buen día. |
| 38 | 38 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Perfecto, ¿necesita algo más? / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 39 | 37 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Perfecto, ¿necesita algo más? / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: No hay problema, que tenga buen día. |
| 40 | 35 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: No hay problema, que tenga buen día. / Cliente: Entiendo, muchas gracias. / Agente: No hay problema, que tenga buen día. |
| 41 | 35 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. |
| 42 | 33 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Entiendo, muchas gracias. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. |
| 43 | 33 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Claro, estoy para servirle. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. |
| 44 | 33 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? / Cliente: Entiendo, muchas gracias. / Agente: Perfecto, ¿necesita algo más? |
| 45 | 33 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: No hay problema, que tenga buen día. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 46 | 33 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Claro, estoy para servirle. |
| 47 | 33 | balance | Cliente: Hola, buenos días. Quisiera saber cuál es mi saldo actual en mi cuenta de ahorros. / Agente: Buenos días, con gusto le ayudo. Permítame un momento para verificar su saldo. Su saldo actual es de {monto} {moneda}. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: No hay problema, que tenga buen día. / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Claro, estoy para servirle. |
| 48 | 32 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: No hay problema, que tenga buen día. / Cliente: Entiendo, muchas gracias. / Agente: Claro, estoy para servirle. |
| 49 | 32 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: No hay problema, que tenga buen día. / Cliente: Muy bien, ¿hay algo más que deba saber? / Agente: Con gusto. ¿Hay algo más en lo que pueda ayudarle? |
| 50 | 32 | balance | Cliente: Buenas tardes, necesito consultar el saldo de mi tarjeta de crédito. / Agente: Buenas tardes, claro que sí. Déjeme revisar esa información. Su saldo actual es {monto} {moneda} y su límite disponible es de {limite} {moneda}. / Cliente: Perfecto, eso es lo que necesitaba. / Agente: Perfecto, ¿necesita algo más? / Cliente: ¿Y eso cuánto tiempo tarda? / Agente: Claro, estoy para servirle. |

## (c) P5: does full_text predict contact_reason?

Unit: one transcript joined to its interaction (171,321 rows, 546 distinct full_text). Classes: Comercial, Producto, Queja, Retención, Transaccional, Técnico.

| contact_reason | transcripts | distinct full_text | % of all distinct texts |
|---|---|---|---|
| Transaccional | 59,786 | 546 | 100.00% |
| Producto | 37,658 | 546 | 100.00% |
| Queja | 29,198 | 546 | 100.00% |
| Técnico | 25,691 | 546 | 100.00% |
| Comercial | 13,808 | 545 | 99.82% |
| Retención | 5,180 | 490 | 89.74% |

Number of different contact_reason values each distinct text appears with:

| reasons per text | distinct texts |
|---|---|
| 5 | 57 |
| 6 | 489 |

Separability of the label by text alone, on all rows (no model):

- Majority class: Transaccional, 34.90% of transcripts.
- Ceiling for any text-only classifier (each distinct text predicts its own most common
  reason, fitted and scored on the same rows): 34.96%; same with shuffled labels:
  34.98%.
- Average total-variation distance between a text's reason distribution and the overall
  one: 0.0275; with shuffled labels: 0.0278.

TF-IDF (word 1-2 grams) + logistic regression, 5-fold CV, mean (sd):

| split | model accuracy | model macro-F1 | majority accuracy | majority macro-F1 |
|---|---|---|---|---|
| grouped by distinct full_text | 0.3488 (0.0021) | 0.0862 (0.0004) | 0.3488 (0.0021) | 0.0862 (0.0004) |
| random rows (text leaks across folds) | 0.3490 (0.0019) | 0.0862 (0.0003) | 0.3490 (0.0019) | 0.0862 (0.0003) |
| grouped, shuffled labels (null) | 0.3488 (0.0031) | 0.0862 (0.0006) | 0.3488 (0.0031) | 0.0862 (0.0006) |

Side note: call_transcripts.main_topics equals contact_reason in 171,321 of 171,321 rows (100.00%); it is a copy of the label, not a feature. detected_intents values: consulta_general 162,864, null 8,457.
