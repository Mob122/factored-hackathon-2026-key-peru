# Contract: gold refresh and freshness policy

| Field | Value |
|---|---|
| Contract version | `fresh-0.1` |
| Date | 2026-09-29 |
| Owner | Aldair (pipeline, fixture, test) · Martín (mock bank overlay, `as_of`) |
| Tables | `docs/contracts/gold_tables.md` (`gold-0.1`) |
| Closes | `docs/requirements_matrix.md` gap G-1 (D4-5, A-2, A-3) at the design level |

## 1. What the source delivers

| Table | Delivery in the supplied data | Partition key | Event time |
|---|---|---|---|
| `transactions` | One CSV per day, `transactions/year=YYYY/month=MM/day=DD/transactions_YYYYMMDD.csv`, 1,097 files, 2023-06-17 to 2026-06-17, no missing day | `process_date` (the path date; 0 mismatches) | `transaction_date` |
| `products` | One snapshot file, `products.csv` | none | none (`last_updated` is unreliable) |
| `customers` | One snapshot file, `customers.csv` | none | none |

`process_date` is a business day with a **06:00 cutoff**: a transaction at 2026-06-18 05:57 is in
partition 2026-06-17 (C1 section d, 99.999% of rows). C1 found **no late arrivals**: 0 of
22,930,274 fact rows have `process_date` after the event date. No partition is re-delivered in
the supplied data.

The organizers supplied a static dump. **How dimension updates would arrive is our assumption**,
made explicit here so it can be tested:

- **Assumption A1.** Changed products and customers arrive as delta files with the same columns
  as the snapshot, one full row per changed record:
  `products/updates/year=YYYY/month=MM/day=DD/products_YYYYMMDD.csv` (and the same for
  customers). The path date is the delivery's `process_date`.
- **Assumption A2.** A full snapshot may also be re-delivered. It is processed as a delta that
  contains every row (section 3).
- **Delivery date of the supplied snapshots.** `products.csv` and `customers.csv` are registered
  with delivery date **2026-06-17**, the last supplied transaction partition. Every later
  delivery therefore wins over them.

## 2. Refresh schedule

| Item | Value | Why |
|---|---|---|
| Mode | **Daily batch**, not streaming | The source is delivered as daily files. The only sub-daily need, a card blocked by the assistant, is served by the mock bank overlay (section 5), not by gold. Balances are shown with their `as_of` (POL-GEN-07). |
| When | Once a day at 06:30, for partition D-1 (closed at 06:00 on day D) | The 06:00 business-day cutoff closes a partition; 30 minutes of slack for the file to land |
| Freshness SLA | Gold contains every partition up to D-1 by 07:00 on day D | Worst case, a transaction is visible 25 hours after it happens (06:00 on D-1 → 07:00 on D) |
| `as_of` | `max(gold_loaded_at)` of the table, returned by the mock bank with balances and statuses | Policy section 3b; `BALANCE_SNAPSHOT_MAX_AGE_H` = 24 h triggers POL-BAL-03 |
| Stale gold | If the newest processed partition is older than D-1 at 07:00, the load log marks gold `stale` and the backend health check reports it | `docs/operations.md` monitoring (planned; gap G-4) |
| Initial load | Backfill of all 1,097 partitions and both snapshots, as one batch | Same code path as a daily load, with all partitions as input |

In the prototype, "day D" is the simulated clock (2026-06-18, as in the golden conversations and
the evaluation). Nothing runs on a real schedule; the daily load is a CLI command
(`kedro run --pipeline gold --params gold.partitions=<dates>`), and the schedule above is what
production would run.

## 3. How an incremental partition is processed

Input: a list of partition dates (and any dimension delta files for those dates). Output: new
versions of the three gold tables, published atomically.

1. **Register.** For each input file compute SHA-256. If `_load_log` already has the same path
   with the same checksum and status `published`, skip the file (a replay is a no-op). A
   **different** checksum for an already loaded path is processed normally, and the load log
   records it as a re-delivery.
2. **Ingest.** Run `data_ingestion` for those files only (same TRY_CAST, `source_file` column)
   and the `data_quality` checks of the C1 contracts, producing the partition's
   `02_intermediate` / `03_primary` rows.
3. **Build staged rows.** Apply the gold column mapping (`gold_tables.md` sections 2 to 4) to
   the new rows: card filter, `last4`, `card_number_hmac`, column renames.
4. **Upsert by key** into a staging copy of each gold table:

   | Table | Key | Which row wins when the key already exists |
   |---|---|---|
   | `customers` | `customer_id` | The row from the later delivery (`process_date` of the file; a snapshot counts as its load date). Same delivery: the later `source_file` name. |
   | `cards` | `card_id` | Same rule. `last_updated` is **not** used to order deliveries, because 6.2% of its values are in the future (GQ-10); within one delivery, ties break on the greater `last_updated`. |
   | `card_transactions` | `transaction_id` | The row with the later `process_date`, then the later `source_file` (the C1 transaction dedup rule). A status change of an existing transaction (for example `Pending` → `Reversed`) arrives as the same key in a later partition and replaces the row. |

   An incoming row whose content (all non-lineage columns) equals the stored row is
   **unchanged**: nothing is written and the row keeps its `gold_batch_id`, `gold_loaded_at` and
   `source_file`. This is what makes a replay a no-op (step 1 is only a shortcut).
   Rows are never deleted by an incremental load. A closed card stays with `status = Closed`.
5. **Check.** Run the quality checks GQ-01 to GQ-22 on the staged tables.
6. **Publish or reject.** If no `fail` check fired, write the staged tables to new files and
   switch them in with an atomic rename, then append the load log row with status `published`.
   Otherwise keep the previous gold untouched and log status `rejected` with the failing checks.
   The mock bank reloads when `_load_log` has a new `published` row.

**Properties the tests assert:** processing the same partition twice gives byte-identical table
content (idempotent); processing partitions D and D+1 in either order gives the same final state
when they do not share keys, and the later-delivery rule decides when they do; a rejected load
leaves gold unchanged.

## 4. Load log

`ml/data/03_primary/gold/_load_log.parquet`, one row per table per load:

| Column | Content |
|---|---|
| `gold_batch_id` | `gold-YYYYMMDDTHHMMSS-<8 hex>` |
| `table` | `customers`, `cards`, `card_transactions` |
| `started_at`, `finished_at` | Timestamps |
| `input_files` | List of `{path, sha256, process_date}` |
| `rows_inserted`, `rows_updated`, `rows_unchanged`, `rows_rejected` | Counts over the incoming rows of the load |
| `checks` | List of `{id, level, violations}` |
| `status` | `published`, `rejected`, `skipped_replay` |
| `table_checksum` | SHA-256 of the table content sorted by key, lineage columns excluded |
| `max_process_date` | Newest partition in gold after the load |

## 5. Interaction with actions taken by the assistant

`block_card` changes a card's status in the **mock bank overlay** (a backend table, append-only
status events with `card_id`, new status, time, action ID), never in gold. The mock bank's
effective status of a card is:

- the overlay's latest event, if the card has one **and** the event's business day
  (`CAST(event_time - 6 h AS DATE)`, the same cutoff as transactions) is **on or after** the
  delivery date of the gold row for the card;
- otherwise the gold `status`.

So a refresh can never silently undo a block made by the assistant: only a delivery from a
strictly later business day (for example the bank unblocking the card the next day) takes over.
On the same business day the overlay wins, which is the conservative choice for a block. In production the
overlay would be the core banking system itself.

## 6. Test fixture: one day of changes

> **TEST FIXTURE — not supplied data.** Written by the team to demonstrate update correctness,
> because the organizers supplied a static dump (problem statement, "Architecture freedom").

Location (planned): `ml/tests/fixtures/update/` with a `README.md` carrying the label above, and
the test `ml/tests/pipelines/gold/test_incremental_update.py`. The fixture is self-contained, so
the test runs on a clean clone without `ml/data/`.

### 6.1 Base state (day N = partition 2026-06-17 already loaded)

Copied from real rows of the synthetic dataset for customer **CLI-X7VXKV9P7ZC6** (Colombia,
Basic, two Active COP credit cards; not used in the golden conversations or persona examples).
In the fixture's raw files, personal columns (names, document, contact data, address, date of
birth) are replaced with `FIXTURE` placeholders, and each 16-digit `product_number` is replaced
with a test number that keeps the real last 4 digits (for example `4000000000009205`).

`customers` (base):

| customer_id | country | segment | customer_status |
|---|---|---|---|
| CLI-X7VXKV9P7ZC6 | Colombia | Basic | Active |

`cards` (base):

| card_id | customer_id | last4 | product_type | status | opening_date | expiration_date | last_updated | source_file |
|---|---|---|---|---|---|---|---|---|
| PRD-S9E8FA7G5YXX | CLI-X7VXKV9P7ZC6 | 9205 | Tarjeta Crédito | Active | 2022-01-09 | 2026-01-08 | 2022-03-29 11:49:21 | products.csv |
| PRD-I97V8EFELBUP | CLI-X7VXKV9P7ZC6 | 7921 | Tarjeta Crédito | Active | 2022-07-07 | 2026-07-06 | 2023-06-02 09:45:58 | products.csv |

Card 9205's `expiration_date` is before its latest transactions: a real instance of the
validity-date limitation, kept on purpose.

`card_transactions` (base, 3 of the customer's 29 real card transactions):

| transaction_id | card_id | transaction_datetime | process_date | type | amount | currency | merchant_name | status | code |
|---|---|---|---|---|---|---|---|---|---|
| TRX-87U97MFFGRHECCCGNRDR | PRD-S9E8FA7G5YXX | 2026-06-10 03:26:02 | 2026-06-09 | Purchase | 1805684.49 | COP | Tienda Don José | Approved | 00 |
| TRX-ST87M8AJLZ2GJHFR0B3F | PRD-S9E8FA7G5YXX | 2026-06-06 13:31:35 | 2026-06-06 | Purchase | 1488737.81 | COP | Internet Plus | Approved | 00 |
| TRX-YL1I7FAH1DJCCH428P15 | PRD-I97V8EFELBUP | 2025-10-07 15:48:08 | 2025-10-07 | Purchase | 722018.98 | COP | Conciertos Live | Approved | 00 |

### 6.2 Delivery for partition 2026-06-18 (day N+1)

Two files, in the raw CSV format of the supplied data:

1. `products/updates/year=2026/month=06/day=18/products_20260618.csv`: one full row for
   `PRD-I97V8EFELBUP` (card 7921) identical to the base row except
   `product_status = Blocked`, `last_updated = 2026-06-18 15:10:00`, and
   `last_transaction_date` empty (in the supplied data, non-Active cards never have one).
2. `transactions/year=2026/month=06/day=18/transactions_20260618.csv`: one new transaction on
   the **other** card, 9205 (a transaction on the card being blocked would break the observed
   invariant GQ-20 and mix two tests in one):

   | column | value |
   |---|---|
   | transaction_id | `TRX-FIXTURE0000000000001` (matches the supplied ID pattern `^TRX-[A-Z0-9]{20}$`; checked absent from the supplied data) |
   | transaction_date | 2026-06-18 11:42:10 |
   | process_date | 2026-06-18 |
   | product_id / customer_id | PRD-S9E8FA7G5YXX / CLI-X7VXKV9P7ZC6 |
   | transaction_type | Purchase |
   | amount / currency | 245300.00 / COP |
   | merchant_name / merchant_category / transaction_category | Farmacia Salud / Health / Health |
   | channel | POS (so `branch_id` is empty, as in the data) |
   | transaction_country / transaction_city | Colombia / Bogotá |
   | transaction_status / response_code | Approved / 00 |
   | is_fraud | False |
   | amount_usd, fraud_score, latitude, longitude | empty |

   11:42 is after the 06:00 cutoff, so `process_date` 2026-06-18 agrees with GQ-19.

### 6.3 Expected gold state after processing 2026-06-18

`customers`: unchanged. The row keeps its `gold_batch_id`, `gold_loaded_at` and `source_file`.

`cards`:

| card_id | status | last_updated | source_file | gold_batch_id | Change |
|---|---|---|---|---|---|
| PRD-S9E8FA7G5YXX | Active | 2022-03-29 11:49:21 | products.csv | base batch | unchanged |
| PRD-I97V8EFELBUP | **Blocked** | **2026-06-18 15:10:00** | **products/updates/year=2026/month=06/day=18/products_20260618.csv** | **new batch** | updated |

All other columns of card 7921 (`last4`, `card_number_hmac`, dates) are unchanged.

`card_transactions`: 4 rows. The 3 base rows are unchanged (same batch, same `source_file`).
The new row:

| transaction_id | card_id | customer_id | transaction_datetime | process_date | type | amount | currency | merchant_name | status | code | source_file |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TRX-FIXTURE0000000000001 | PRD-S9E8FA7G5YXX | CLI-X7VXKV9P7ZC6 | 2026-06-18 11:42:10 | 2026-06-18 | Purchase | 245300.00 | COP | Farmacia Salud | Approved | 00 | transactions/year=2026/month=06/day=18/transactions_20260618.csv |

The history of card 7921 (TRX-YL1I7FAH1DJCCH428P15) stays: blocking a card does not remove its
past transactions. GQ-20 does not fire, because that transaction predates the delivery that
blocked the card, and the new transaction is on the Active card.

`_load_log` for the new batch:

| table | inserted | updated | unchanged | rejected | status | max_process_date |
|---|---|---|---|---|---|---|
| customers | 0 | 0 | 0 | 0 | published | 2026-06-18 |
| cards | 0 | 1 | 0 | 0 | published | 2026-06-18 |
| card_transactions | 1 | 0 | 0 | 0 | published | 2026-06-18 |

The counts are over **incoming** rows (the delivery has no customers file). Stored rows that
no incoming row touches are not counted; the table checksum shows they did not change.

Mock bank reads after the load (section 5, no overlay events): `get_card_status(7921)` →
`Blocked`; `list_transactions(9205)` on the simulated clock 2026-06-18 (last 30 days) includes
the new purchase first.

### 6.4 Test cases

| ID | Action | Expected |
|---|---|---|
| FX-1 | Load base, then 2026-06-18 | State of 6.3 exactly (compare with committed expected Parquet/CSV in `ml/tests/fixtures/update/expected/`) |
| FX-2 | Process 2026-06-18 a second time | `_load_log` status `skipped_replay`; table checksums equal to after FX-1 |
| FX-3 | Force re-processing of 2026-06-18 (skip step 1) | Every incoming row counted `unchanged` (cards 1, card_transactions 1); table checksums equal to after FX-1 (upsert is idempotent by content) |
| FX-4 | Force re-processing of the base `products.csv` (delivery date 2026-06-17; without forcing, step 1 skips it as a replay) after 2026-06-18 | Card 7921 stays `Blocked`: the 2026-06-17 delivery loses to the 2026-06-18 delta. (A snapshot re-delivered with a **new** date would win; under A2 the source must then send its current state.) |
| FX-5 | Delta row with an unknown `status` value | Load `rejected` (GQ-08 fail); gold identical to before |
| FX-6 | Overlay: `block_card` on 9205 at 2026-06-18 16:00 (business day 2026-06-18), then reprocess 2026-06-18 | Effective status of 9205 is `Blocked`: its gold row was delivered 2026-06-17, before the event's business day. The gold row itself stays `Active`. |
| FX-7 | Same overlay event, then a delta on 2026-06-19 with 9205 `Active` | Effective status `Active`: a strictly later business day takes over (section 5) |

The fixture's rows are declared in the data card (`docs/data_card.md`, planned, requirements
matrix B-2) as team-made and appear
in no evaluation result.
