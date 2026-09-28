"""Custom Kedro datasets for the banking_cs project."""

from .duckdb_query_dataset import DuckDBQueryDataset

__all__ = ["DuckDBQueryDataset"]
