"""Tests for the 'data_ingestion' pipeline.

Small CSV fixtures mimic the raw layout: UTF-8 BOM, integers written as floats,
leading-zero codes and Hive-style daily partitions.
"""

from pathlib import Path

import duckdb
import polars as pl
import pytest

from banking_cs.datasets import DuckDBQueryDataset
from banking_cs.pipelines.data_ingestion.nodes import (
    build_cast_failures_query,
    build_ingestion_query,
)
from banking_cs.pipelines.data_ingestion.pipeline import create_pipeline
from banking_cs.pipelines.data_ingestion.schemas import TABLE_SCHEMAS

BOM = "﻿"

TRANSACTIONS_HEADER = ",".join(TABLE_SCHEMAS["transactions"])
TRANSACTIONS_DAY1 = [
    # Valid row with leading-zero response_code and empty optional fields.
    "TRX-1,2023-06-17 14:54:58,2023-06-17,PRD-1,CLI-1,Deposit,,3695.53,USD,,Web,,,,"
    "México,Monterrey,Approved,00,False,0.89,,",
    # Exact duplicate of the row above: must be kept.
    "TRX-1,2023-06-17 14:54:58,2023-06-17,PRD-1,CLI-1,Deposit,,3695.53,USD,,Web,,,,"
    "México,Monterrey,Approved,00,False,0.89,,",
]
TRANSACTIONS_DAY2 = [
    # Dirty values: bad timestamp, bad amount, bad boolean.
    "TRX-2,not-a-date,2023-06-18,PRD-2,CLI-2,Purchase,Food,abc,MXN,12.50,POS,SUC-1,"
    '"Tienda, S.A.",5411,México,CDMX,Approved,05,maybe,10.00,19.4326077,-99.1332080',
]

SURVEYS_HEADER = ",".join(TABLE_SCHEMAS["satisfaction_surveys"])
SURVEYS_ROWS = [
    "SRV-1,2023-06-18 13:07:11,2023-06-17,INT-1,CLI-1,AGT-1,CSAT,Email,3,,,,,,"
    '"¿Volvería?",4.0,"Tardaron mucho,\nmuchísimo.",Negative,8.76,',
    # Fractional integer response must count as a cast failure, not be rounded.
    "SRV-2,2023-06-18 01:25:31,2023-06-17,INT-2,CLI-2,AGT-2,CSAT,Email,1,,q1,3.5,,,,,"
    ",Negative,10.14,20.13",
]


def _write_csv(path: Path, header: str, rows: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        BOM + header + "\n" + "\n".join(rows) + "\n", encoding="utf-8", newline="\n"
    )


@pytest.fixture
def raw_root(tmp_path: Path) -> Path:
    root = tmp_path / "01_raw"
    _write_csv(
        root / "transactions/year=2023/month=06/day=17/transactions_20230617.csv",
        TRANSACTIONS_HEADER,
        TRANSACTIONS_DAY1,
    )
    _write_csv(
        root / "transactions/year=2023/month=06/day=18/transactions_20230618.csv",
        TRANSACTIONS_HEADER,
        TRANSACTIONS_DAY2,
    )
    _write_csv(root / "satisfaction_surveys.csv", SURVEYS_HEADER, SURVEYS_ROWS)
    return root


def _ingest(raw_root: Path, table: str, table_glob: str) -> pl.DataFrame:
    query = build_ingestion_query(str(raw_root), table_glob, table)
    return duckdb.sql(query).pl().sort("source_file", maintain_order=True)


class TestBuildIngestionQuery:
    def test_keeps_all_rows_including_duplicates(self, raw_root):
        df = _ingest(raw_root, "transactions", "transactions/**/*.csv")
        assert df.height == 3
        assert df["transaction_id"].to_list().count("TRX-1") == 2

    def test_casts_to_dictionary_types(self, raw_root):
        df = _ingest(raw_root, "transactions", "transactions/**/*.csv")
        assert df.schema["transaction_date"] == pl.Datetime("us")
        assert df.schema["process_date"] == pl.Date
        assert df.schema["amount"] == pl.Decimal(15, 2)
        assert df.schema["is_fraud"] == pl.Boolean
        assert df.schema["response_code"] == pl.String
        assert df["response_code"].to_list() == ["00", "00", "05"]

    def test_bom_is_stripped_from_first_column(self, raw_root):
        df = _ingest(raw_root, "transactions", "transactions/**/*.csv")
        assert df.columns[0] == "transaction_id"

    def test_dirty_values_become_null_without_dropping_rows(self, raw_root):
        df = _ingest(raw_root, "transactions", "transactions/**/*.csv")
        dirty = df.filter(pl.col("transaction_id") == "TRX-2").row(0, named=True)
        assert dirty["transaction_date"] is None
        assert dirty["amount"] is None
        assert dirty["is_fraud"] is None
        assert dirty["merchant_name"] == "Tienda, S.A."

    def test_source_file_is_relative_to_raw_root(self, raw_root):
        df = _ingest(raw_root, "transactions", "transactions/**/*.csv")
        assert df["source_file"].unique().sort().to_list() == [
            "transactions/year=2023/month=06/day=17/transactions_20230617.csv",
            "transactions/year=2023/month=06/day=18/transactions_20230618.csv",
        ]

    def test_float_formatted_integers_and_multiline_text(self, raw_root):
        df = _ingest(raw_root, "satisfaction_surveys", "satisfaction_surveys.csv")
        assert df.schema["main_score"] == pl.Int32
        assert df["question_3_response"].to_list() == [4, None]
        assert df["question_1_response"].to_list() == [None, None]
        assert df["open_comments"][0] == "Tardaron mucho,\nmuchísimo."
        assert df["source_file"].to_list() == ["satisfaction_surveys.csv"] * 2


class TestBuildCastFailuresQuery:
    def test_counts_failures_per_column(self, raw_root, monkeypatch):
        tables = {
            "transactions": "transactions/**/*.csv",
            "satisfaction_surveys": "satisfaction_surveys.csv",
        }
        monkeypatch.setattr(
            "banking_cs.pipelines.data_ingestion.nodes.TABLE_SCHEMAS",
            {t: TABLE_SCHEMAS[t] for t in tables},
        )
        report = duckdb.sql(build_cast_failures_query(str(raw_root), tables)).pl()
        failures = {
            (r["table_name"], r["column_name"]): r["n_failures"]
            for r in report.iter_rows(named=True)
        }
        assert failures[("transactions", "transaction_date")] == 1
        assert failures[("transactions", "amount")] == 1
        assert failures[("transactions", "is_fraud")] == 1
        assert failures[("transactions", "amount_usd")] == 0
        assert failures[("satisfaction_surveys", "question_1_response")] == 1
        assert ("transactions", "response_code") not in failures
        n_rows = dict(report.select("table_name", "n_rows").unique().iter_rows())
        assert n_rows == {"transactions": 3, "satisfaction_surveys": 2}


class TestDuckDBQueryDataset:
    def test_parquet_round_trip(self, tmp_path):
        dataset = DuckDBQueryDataset(filepath=str(tmp_path / "out/x.parquet"))
        assert not dataset.exists()
        dataset.save("SELECT 1 AS a, 'x' AS b")
        assert dataset.exists()
        assert dataset.load().collect().to_dicts() == [{"a": 1, "b": "x"}]
        assert not (tmp_path / "out/x.parquet.tmp").exists()

    def test_csv_round_trip(self, tmp_path):
        dataset = DuckDBQueryDataset(
            filepath=str(tmp_path / "x.csv"), file_format="csv"
        )
        dataset.save("SELECT 1 AS a")
        assert dataset.load().collect().to_dicts() == [{"a": 1}]

    def test_failed_query_leaves_no_output(self, tmp_path):
        dataset = DuckDBQueryDataset(filepath=str(tmp_path / "x.parquet"))
        with pytest.raises(Exception):
            dataset.save("SELECT * FROM missing_table")
        assert list(tmp_path.iterdir()) == []


def test_pipeline_has_one_node_per_table_plus_report():
    pipeline = create_pipeline()
    assert set(pipeline.outputs()) == {f"{t}_intermediate" for t in TABLE_SCHEMAS} | {
        "ingestion_cast_failures"
    }
