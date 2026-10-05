# Contract: gold tables read by the mock bank

| Field | Value |
|---|---|
| Contract version | `gold-0.2` |
| Date | 2026-09-29 |
| Owner | Aldair (tables, checks, pipeline) · Martín (mock bank reader) |
| Producer | `ml/` Kedro pipeline `gold` (planned), reading `ml/data/03_primary/` |
| Consumer | Mock identity (`authenticate` reads `customer_status`) and mock bank in `backend/` (tools `list_cards`, `get_card_status`, `list_transactions`, `describe_transaction`, `list_balance_products`, `get_balance`); eval harness for hidden state |
| Location | `ml/data/03_primary/gold/{customers,cards,card_transactions,balance_products}.parquet` (git-ignored, never committed) |
| Refresh | `docs/contracts/freshness_policy.md` (`fresh-0.2`) |
| Evidence | `docs/findings/day1/C1.md` (data quality and proposed contracts), `docs/findings/day1/P2_card_support.md`, `docs/findings/day2/personas.md`; counts re-checked on `ml/data/02_intermediate/` on 2026-09-29 (section 4b counts computed the same day) |

The mock bank reads these four tables and nothing else from `ml/`. It never imports Kedro and
never reads `02_intermediate` or `03_primary` directly. Every column that is not listed here is
unavailable to the backend, and so to the LLM, by construction (POL-PII-02 and 03).

Changes in `gold-0.2`: balance inquiry was approved (proposal v3.1), so the fourth table
`balance_products` (section 4b) serves `list_balance_products` and `get_balance`, with checks
GQ-23 to GQ-29. `customers.customer_status` is now used by POL-AUTH-09. Both open questions of
`gold-0.1` are closed (section 7).

## 1. Lineage

```
01_raw (CSV, read-only)
  customers.csv, products.csv                      one snapshot file each
  transactions/year=YYYY/month=MM/day=DD/*.csv     daily partitions by process_date
    │  pipeline data_ingestion (exists): TRY_CAST to dictionary types, all rows kept,
    │  source_file = raw path relative to 01_raw
    ▼
02_intermediate/{customers,products,transactions}.parquet
    │  pipeline data_quality → 03_primary (planned): C1 contracts asserted, dedup rule
    │  applied (C1: 0 duplicates today), Spanish labels kept as observed
    ▼
03_primary/{customers,products,transactions}.parquet
    │  pipeline gold (planned): column selection, card filter, keyed hash of card numbers,
    │  checks in section 5, batch columns added
    ▼
03_primary/gold/{customers,cards,card_transactions,balance_products}.parquet  → mock bank
```

Every gold table carries three lineage columns:

| Column | Type | Content |
|---|---|---|
| `source_file` | VARCHAR | Raw file the row came from, as in `02_intermediate` (for example `transactions/year=2026/month=06/day=09/transactions_20260609.csv`, or `products.csv`). For a row changed by an incremental delivery, the delta file. |
| `gold_batch_id` | VARCHAR | ID of the gold load that last **inserted or changed** the row. An unchanged row keeps its batch ID. |
| `gold_loaded_at` | TIMESTAMP | When that load finished. The mock bank's `as_of` for the table is the max of this column (policy section 3b). |

Every load also writes one row per table to `03_primary/gold/_load_log.parquet`: batch ID,
partitions read, rows inserted / updated / unchanged / rejected, check results, and a content
checksum of the table (freshness policy section 4).

## 2. `customers`

Only the columns the backend needs. Names, document numbers, contact data, date of birth,
gender, credit score, income, occupation, marital status and education are **not** in gold.

| Column | Type | Required | Source (`03_primary.customers`) | Allowed values | Used for |
|---|---|---|---|---|---|
| `customer_id` | VARCHAR | yes, **PK** | `customer_id` | `^CLI-[A-Z0-9]{12}$` | Session binding (POL-AUTH-05) |
| `country` | VARCHAR | yes | `country` | `México` (74,907), `Colombia` (45,251), `Argentina` (29,842) | Number formatting in templates (policy 3b); eval slices |
| `segment` | VARCHAR | yes | `segment` | `Basic` (89,756), `Plus` (37,547), `Premium` (15,207), `Student` (7,490) | Eval slices only. The backend must not use it in any decision. |
| `customer_status` | VARCHAR | yes | `customer_status` | `Active` (127,700), `Inactive` (14,914), `Suspended` (4,407), `Closed` (2,979) | Returned by `authenticate`. `Suspended` or `Closed` (7,386 customers, 4.92%; 4,410 of them hold a card) get only a handoff (POL-AUTH-09, T-51) |
| lineage columns | | yes | | | Section 1 |

- **Grain:** one row per customer. 150,000 rows, including 58,916 customers without cards (persona S4).
- `country` keeps the observed spelling `México`; the dictionary says `Mexico` (C1 value domains).
- The mock identity service maps test credentials to a `customer_id`. Nothing in this table
  authenticates anyone (POL-AUTH-02).

## 3. `cards`

One row per card product (`products.product_type` in `Tarjeta Crédito`, `Tarjeta Débito`).

| Column | Type | Required | Source (`03_primary.products`) | Allowed values / rule |
|---|---|---|---|---|
| `card_id` | VARCHAR | yes, **PK** | `product_id` | `^PRD-[A-Z0-9]{12}$` |
| `customer_id` | VARCHAR | yes, FK → `customers` | `customer_id` | 0 orphans (C1) |
| `last4` | VARCHAR(4) | yes | `right(product_number, 4)` | `^[0-9]{4}$` |
| `card_number_hmac` | VARCHAR(64) | yes, unique | `HMAC-SHA256(CARD_HASH_KEY, product_number)` | Hex. Used only by the gateway's ownership check on a typed full number (POL-ESC-10). The full `product_number` is not in gold. |
| `product_type` | VARCHAR | yes | `product_type` | `Tarjeta Crédito` (100,102), `Tarjeta Débito` (39,938). Tools return the stored value as `type`; reply templates render it as "de crédito" / "de débito" (policy POL-ACT-11). |
| `status` | VARCHAR | yes | `product_status` | `Active` (118,839), `Blocked` (7,044), `Suspended` (2,860), `Closed` (11,297) |
| `opening_date` | DATE | yes | `opening_date` | 2018-06-18 to 2026-06-17 |
| `expiration_date` | DATE | no | `expiration_date` | Null for 6,879 cards (4.9%, random). 2021-06-17 to 2031-06-16. **Unreliable, never shown** (section 6). |
| `last_updated` | TIMESTAMP | yes | `last_updated` | **Unreliable** (section 6). Not used to order updates. |
| lineage columns | | yes | | Section 1 |

- **Grain:** one row per card. 140,040 rows today (35.01% of products).
- `CARD_HASH_KEY` is a secret. It lives in `ml/conf/local/credentials.yml` and the backend
  `.env`, both git-ignored. A plain hash of a 16-digit number could be brute-forced, so a keyed
  hash is used.
- The backend's `block_card` does not write to this table (freshness policy section 5).

## 4. `card_transactions`

Transactions whose `product_id` is a card in `cards`.

| Column | Type | Required | Source (`03_primary.transactions`) | Allowed values / rule |
|---|---|---|---|---|
| `transaction_id` | VARCHAR | yes, **PK** | `transaction_id` | Unique. Supplied IDs match `^TRX-[A-Z0-9]{20}$`; fixture IDs start with `TRX-FIXTURE`. |
| `card_id` | VARCHAR | yes, FK → `cards` | `product_id` | 0 orphans |
| `customer_id` | VARCHAR | yes | `customer_id` | Equals `cards.customer_id` of the card (0 mismatches today). Kept to let the mock bank filter by session customer without a join. |
| `transaction_datetime` | TIMESTAMP | yes | `transaction_date` | No time zone in the source (section 6). 2023-06-17 06:03 to 2026-06-18 05:57 today. |
| `process_date` | DATE | yes | `process_date` | Partition date. `process_date = CAST(transaction_datetime - INTERVAL 6 HOUR AS DATE)` (06:00 business-day cutoff; 99.999% agree, C1). 2023-06-17 to 2026-06-17. |
| `transaction_type` | VARCHAR | yes | `transaction_type` | On cards only: `Purchase` (1,083,406), `Withdrawal` (232,392), `Payment` (231,634). The other source types (`Transfer`, `Deposit`, `Adjustment`) never appear on cards. |
| `amount` | DECIMAL(15,2) | yes | `amount` | > 0 (0 violations). In `currency`, not converted. |
| `currency` | VARCHAR(3) | yes | `currency` | `USD`, `COP`, `ARS`. Equals the card product's currency (0 mismatches). **Never `MXN`.** |
| `merchant_name` | VARCHAR | no | `merchant_name` | One of the 24 names in C1. Null for every `Withdrawal` and `Payment` (structural) and for 54,172 purchases (5.0%, random). |
| `status` | VARCHAR | yes | `transaction_status` | `Approved` (1,423,048), `Declined` (77,714), `Pending` (30,885), `Reversed` (15,785) |
| `response_code` | VARCHAR(2) | no | `response_code` | `00`, `05`, `14`, `51`, `54`; null for 77,134 rows (4.98%, random). `Approved` ⇒ `00` or null; any other status ⇒ `05`, `14`, `51`, `54` or null (0 violations each, P2). |
| lineage columns | | yes | | Section 1 |

- **Grain:** one row per transaction. 1,547,432 rows today, one per `transaction_id`.
- **Excluded source columns:** `is_fraud` and `fraud_score` (`fraud_score` leaks the label, Day 1
  A5; POL-ANS-12), `amount_usd`, `transaction_category`, `merchant_category`, `channel`,
  `branch_id`, `transaction_country`, `transaction_city`, `latitude`, `longitude`.
- Transactions on non-card products are not in gold. They are out of scope (POL-ANS-14).

## 4b. `balance_products`

*(new in `gold-0.2`)* One row per credit card or savings account (`products.product_type` in
`Tarjeta Crédito`, `Cuenta Ahorro`), **including Closed ones**: rows are never deleted by an
incremental load (freshness policy section 3), so a product that closes later must stay as a
row with `status = Closed`. The mock bank applies the POL-ANS-17 filter (`status` ≠ `Closed`)
when it answers `list_balance_products` and `get_balance`.

| Column | Type | Required | Source (`03_primary.products`) | Allowed values / rule |
|---|---|---|---|---|
| `product_id` | VARCHAR | yes, **PK** | `product_id` | `^PRD-[A-Z0-9]{12}$`. For a credit card it equals `cards.card_id`. |
| `customer_id` | VARCHAR | yes, FK → `customers` | `customer_id` | 0 orphans |
| `kind` | VARCHAR | yes | from `product_type` | `credit_card` (`Tarjeta Crédito`, 100,102), `savings_account` (`Cuenta Ahorro`, 120,203) |
| `last4` | VARCHAR(4) | yes | `right(product_number, 4)` | `^[0-9]{4}$`. Source numbers are 16 digits for credit cards and 10 for savings accounts. The full number is not in this table. |
| `status` | VARCHAR | yes | `product_status` | Credit cards: `Active` 85,090, `Blocked` 4,932, `Suspended` 2,027, `Closed` 8,053. Savings accounts: `Active` 102,148, `Blocked` 5,923, `Suspended` 2,416, `Closed` 9,716. |
| `currency` | VARCHAR(3) | yes | `currency` | `USD`, `COP`, `ARS`. **Never `MXN`.** |
| `current_balance` | DECIMAL(15,2) | yes | `current_balance` | ≥ 0 (0 violations). Credit cards 0.00 to 18,392,153.91; savings 0.00 to 59,614,477.73, in `currency`. The dictionary defines it only as "Current balance"; for a credit card its sign and meaning are not defined, so it is shown as recorded (POL-ANS-15). |
| `credit_limit` | DECIMAL(15,2) | no | `credit_limit` | Null for every savings account (structural) and for 5,059 credit cards (5.05%, random). |
| lineage columns | | yes | | Section 1. `as_of` for balances = `max(gold_loaded_at)` of this table (policy section 3b). |

- **Grain:** one row per product. 220,305 rows today; 202,536 not `Closed` (eligible), held by
  111,200 customers.
- **Excluded source columns:** `product_number` (only `last4` is kept), `interest_rate`,
  `days_past_due`, `opening_date`, `expiration_date`, `last_updated` (not a balance timestamp:
  6.27% of values are after the data ends, F-29), branch and channel columns. Debit cards,
  current accounts, loans, investments and insurance are not in this table (POL-ANS-14, 17).
- A credit card is in both `cards` and `balance_products` under the same ID. Both rows come from
  the same source row in the same load, and GQ-28 checks that they agree.

## 5. Quality checks

Run by the `gold` pipeline on every load, after the upsert and before the tables are published.
**Fail** = the load is rejected and the previous gold stays live (freshness policy section 4).
**Warn** = the load is published and the count goes to the load log and the data-quality
report. "Today" is the count on the current full load.

| ID | Table | Rule | Level | Today |
|---|---|---|---|---|
| GQ-01 | all | PK not null and unique | fail | 0 violations |
| GQ-02 | all | Required columns not null | fail | 0 |
| GQ-03 | all | Lineage columns not null; `source_file` exists in the load's input list | fail | 0 |
| GQ-04 | customers | `country`, `segment`, `customer_status` in the allowed sets | warn (new value) | 0 |
| GQ-05 | cards | `customer_id` exists in `customers` | fail | 0 orphans |
| GQ-06 | cards | `last4` matches `^[0-9]{4}$`; source `product_number` is 16 digits | fail | 0 (all 140,040 are 16 digits) |
| GQ-07 | cards | `card_number_hmac` unique | fail | 0 (card numbers are unique; the 6 duplicate `product_number` values in C1 are all loans and current accounts) |
| GQ-08 | cards | `product_type`, `status` in the allowed sets | fail | 0 |
| GQ-09 | cards | `expiration_date >= opening_date` when both are present | warn | 0 |
| GQ-10 | cards | `last_updated` after the close of the newest partition in gold (`max(process_date) + 1 day, 06:00`) | warn | 8,681 cards (6.2%) after 2026-06-18 06:00 |
| GQ-11 | cards | Customers with two cards sharing `last4` | warn (report count) | 6 customers (P2); handled by POL-ANS-08 |
| GQ-12 | card_transactions | `card_id` exists in `cards`, and `customer_id` equals the card's `customer_id` | fail | 0 |
| GQ-13 | card_transactions | `currency` equals the card product's currency (checked against `03_primary.products`) | fail | 0 |
| GQ-14 | card_transactions | `amount > 0` | fail | 0 |
| GQ-15 | card_transactions | `transaction_type`, `status` in the allowed sets | warn (new value); the row is kept and the backend handles it by POL-ESC-05 | 0 |
| GQ-16 | card_transactions | `response_code` in `00`, `05`, `14`, `51`, `54` or null | warn (new code); POL-DEC-91 handles it | 0 |
| GQ-17 | card_transactions | Status and code agree (`Approved` ⇒ `00`/null; not `Approved` ⇒ not `00`) | warn | 0 |
| GQ-18 | card_transactions | `merchant_name` null when `transaction_type` ≠ `Purchase` | warn | 0 |
| GQ-19 | card_transactions | `process_date = CAST(transaction_datetime - 6 h AS DATE)` | warn | 99.999% agree (C1) |
| GQ-20 | card_transactions | Transaction on a card whose `status` is not `Active`, with `process_date` on or after the delivery date of the card's gold row (history before a status change is expected and kept) | warn | 0 (P2: blocked, suspended and closed cards never transact) |
| GQ-21 | card_transactions | `transaction_datetime` outside `[opening_date, expiration_date]` of the card | info only | 18.65% before opening, 29.88% after expiration (P2) |
| GQ-22 | all | Row count change vs previous load outside the delivered delta (for example rows lost) | fail | n/a on first load |
| GQ-23 | balance_products | `kind`, `status`, `currency` in the allowed sets; `kind` matches `product_type` | fail | 0 |
| GQ-24 | balance_products | `customer_id` exists in `customers` | fail | 0 orphans |
| GQ-25 | balance_products | `current_balance` not null and ≥ 0 | fail | 0 |
| GQ-26 | balance_products | `credit_limit` null for every savings account; share of credit cards with a null limit | fail (savings with a limit); warn (report the credit-card count) | 0; 5,059 credit cards (5.05%), handled by POL-BAL-06 + POL-BAL-04 |
| GQ-27 | balance_products | Credit cards with `current_balance` > `credit_limit` | warn (report count) | 1,203 (1.27% of credit cards with a limit); handled by POL-BAL-06 + POL-BAL-04 |
| GQ-28 | balance_products | For credit cards: a row in `cards` with the same ID, `last4` and `status` | fail | 0 |
| GQ-29 | balance_products | Customers with two non-Closed products sharing `last4` | warn (report count) | 16 customers; handled by POL-ANS-08 (type decides) |

C1 flags 1,352 transactions (0.031%) "outside the dataset range" (`transaction_date` after
2026-06-17). They are not errors: they fall between 00:00 and 05:59 on 2026-06-18 and belong to
partition 2026-06-17 by the 06:00 cutoff. 465 of them are card transactions. Gold keeps them.

## 6. Known limitations

These are properties of the synthetic source, not defects gold can fix. The policy rule that
handles each is listed.

| Limitation | Evidence | Consequence | Policy |
|---|---|---|---|
| **No block or status history.** `cards` holds the current status only. Blocked, Suspended and Closed cards have no transactions and no `last_transaction_date`, and nothing records when or why the status changed. | P2 (0 transactions on 7,044 blocked cards) | The assistant can state the current status, never a cause or a date. Gold is type-1 (overwrite): a status change seen in a later delivery replaces the old value. | POL-ANS-02, 11, POL-ESC-02 |
| **Response codes are random.** The 4 decline codes have equal shares for every status and type; 51 does not track amount, 54 does not track expiration, 05/14 do not track fraud. | P2 section (c) | Codes are translated with a fixed template and a disclaimer, never used as a cause. | POL-DEC-*, POL-ANS-10 |
| **Validity dates are unreliable.** 18.65% of card transactions predate the card's `opening_date` and 29.88% postdate its `expiration_date`; 47.72% of Active cards expired before the end of the data; 4.9% have no expiration date. | P2 | `opening_date` and `expiration_date` are stored for completeness and data-quality reporting only. They are never shown and never used to call a card expired. | POL-ANS-13, POL-ESC-05 |
| **`last_updated` is unreliable.** Values run to 2027-06-13; 6.2% of cards are updated after the data ends. | P2 section (a), GQ-10 | Not used as the update order (freshness policy section 3) and not used as balance `as_of`. | POL-GEN-07, policy 3b |
| **MXN is absent.** Mexican customers' cards and transactions are in USD; Colombia uses COP and USD; Argentina ARS and USD. | C1 "Currency" | Amounts are shown in the recorded currency. No conversion, no assumption that a Mexican customer pays in pesos. | POL-GEN-02 |
| **No time zone.** `transaction_datetime` has no offset and customers span three countries. | Dictionary, C1 | Dates and times are shown as recorded, with no conversion. | — |
| **Sparse activity.** Median 0 card transactions in a random 30-day window; 61.45% of windows are empty. | P2 section (e) | Real rows rarely produce "which of these charges?". The evaluation injects look-alike transactions as a declared fixture. | `docs/eval_plan.md` 3.5 |
| **Merchants are random per transaction.** 24 generic names; repeat rate equals the shuffled baseline. | P2 section (d) | No "your usual merchant" reasoning. | POL-GEN-02 |
| **Registration dates are unrelated to activity.** 18.8% of transactions predate the customer's registration. | C1 problem 3 | Not in gold; tenure is never used. | — |
| **Static delivery.** Products and customers are one snapshot file each; no update deliveries were supplied. | C1 row counts | Incremental behaviour is shown with a labeled test fixture (freshness policy section 6). | — |
| **No balance timestamp.** Products are one snapshot; `last_updated` is unreliable. | P4 follow-up, F-29 | A balance is as fresh as the load: `as_of` = `max(gold_loaded_at)`, stated with every balance (POL-GEN-07). | POL-GEN-07, POL-BAL-03 |
| **Card balance meaning undefined.** No sign or meaning for credit-card `current_balance`; 1.27% of credit cards with a limit are above it and 5.05% have no limit. | Dictionary, GQ-26, GQ-27, F-28 | Values are stated as recorded; available credit is never computed. | POL-ANS-15, POL-BAL-04 to 06 |

## 7. Open questions

None. Both questions of `gold-0.1` are closed:

1. *(closed in 0.2)* `customer_status` = `Suspended` or `Closed` (4.92% of customers): they may
   authenticate but get only an immediate handoff (POL-AUTH-09, `docs/contracts/state_machine.md`
   T-51, INV-14).
2. *(closed in 0.2)* The balance tools read `balance_products` (section 4b).
