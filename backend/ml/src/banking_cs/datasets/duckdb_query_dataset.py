"""Kedro dataset that materializes a DuckDB SQL query to Parquet or CSV."""

from pathlib import Path
from typing import Any

import duckdb
import polars as pl
from kedro.io import AbstractDataset, DatasetError

_DEFAULT_COPY_OPTIONS = {
    "parquet": {"FORMAT": "parquet", "COMPRESSION": "zstd"},
    "csv": {"FORMAT": "csv", "HEADER": "true"},
}


class DuckDBQueryDataset(AbstractDataset[str, pl.LazyFrame]):
    """Saves the result of a SQL query with DuckDB ``COPY``; loads it lazily with polars.

    ``save`` takes a SQL query string and streams its result to ``filepath``,
    so tables larger than memory never pass through Python. ``load`` returns a
    ``polars.LazyFrame``.

    Example catalog entry:

    .. code-block:: yaml

        customers_intermediate:
          type: banking_cs.datasets.DuckDBQueryDataset
          filepath: data/02_intermediate/customers.parquet
    """

    def __init__(
        self,
        filepath: str,
        file_format: str = "parquet",
        copy_options: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if file_format not in _DEFAULT_COPY_OPTIONS:
            raise DatasetError(
                f"Unsupported file_format '{file_format}'; "
                f"expected one of {sorted(_DEFAULT_COPY_OPTIONS)}."
            )
        self._filepath = Path(filepath)
        self._file_format = file_format
        self._copy_options = {
            **_DEFAULT_COPY_OPTIONS[file_format],
            **(copy_options or {}),
        }
        self.metadata = metadata

    def load(self) -> pl.LazyFrame:
        if self._file_format == "parquet":
            return pl.scan_parquet(self._filepath)
        return pl.scan_csv(self._filepath)

    def save(self, data: str) -> None:
        if not isinstance(data, str):
            raise DatasetError(
                f"DuckDBQueryDataset expects a SQL query string, got {type(data).__name__}."
            )
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temporary file first so a failed run never leaves a
        # truncated output behind.
        tmp_path = self._filepath.with_name(self._filepath.name + ".tmp")
        target = tmp_path.as_posix().replace("'", "''")
        options = ", ".join(f"{k} {v}" for k, v in self._copy_options.items())
        try:
            with duckdb.connect() as con:
                con.execute(f"COPY ({data}) TO '{target}' ({options})")
            tmp_path.replace(self._filepath)
        finally:
            tmp_path.unlink(missing_ok=True)

    def _exists(self) -> bool:
        return self._filepath.exists()

    def _describe(self) -> dict[str, Any]:
        return {
            "filepath": str(self._filepath),
            "file_format": self._file_format,
            "copy_options": self._copy_options,
        }
