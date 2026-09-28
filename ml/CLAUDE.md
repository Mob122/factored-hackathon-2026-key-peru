# ml/ – data and analysis rules

## Environment
- Run Python through the venv: `ml/.venv/Scripts/python` (Windows, Git Bash).
  Run Kedro as `cd ml && .venv/Scripts/python -m kedro ...`.
- Dependencies: add to ml/requirements.txt, then
  `uv pip compile requirements.txt --universal --python-version 3.11 -o requirements.lock`.

## Data
- ml/data/01_raw/ is the untouched S3 dump. READ-ONLY. Never modify or delete it.
- ml/data/02_intermediate/: one Parquet per table, typed, ALL rows kept (no dedup),
  plus a source_file column for lineage.
- Deduplication and cleaning happen later, in 03_primary.
- Use DuckDB (or Polars lazy) over Parquet. Never load digital_events or transactions
  fully into pandas.

## Analysis (Day 1 hypotheses)
- One script per hypothesis: ml/analysis/day1/<ID>_<slug>.py, rerunnable end to end.
- Each writes ml/data/08_reporting/day1/<ID>.md with: the query, row counts and
  denominators, key numbers, 3-5 sample rows, verdict (supported / refuted /
  inconclusive), and the consequence from the "Si falla" column.
- Append a one-line summary to ml/data/08_reporting/day1/FINDINGS.md and update the
  Estado column in docs/hypotheses.md.
- Report raw duplicates and nulls before any deduplication.
- Never state a verdict without the numbers that support it.