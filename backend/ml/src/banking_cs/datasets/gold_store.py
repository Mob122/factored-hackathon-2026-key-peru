"""Kedro dataset for the gold directory read by the mock bank."""

import os
from pathlib import Path
from typing import Any

import polars as pl
from kedro.io import AbstractDataset, DatasetError


class GoldStoreDataset(AbstractDataset[dict[str, Any], dict[str, pl.DataFrame]]):
    """Reads and publishes the gold tables, the load log and the quarantine.

    ``load`` returns ``{name: DataFrame}`` for every ``*.parquet`` in ``path``
    (``_load_log`` included); it is empty before the first load.

    ``save`` takes ``{"batch_id", "tables", "quarantine", "load_log"}``:

    - ``quarantine`` (``{table: DataFrame}``) goes to
      ``_quarantine/<batch_id>/<table>.parquet``.
    - ``tables`` is ``None`` for a rejected load, which leaves the tables untouched.
      Otherwise every table is written to a temporary file first and then renamed
      over the live one.
    - ``load_log`` rows are appended to ``_load_log.parquet`` last. A new
      ``published`` row is the signal for the mock bank to reload.

    Example catalog entry:

    .. code-block:: yaml

        gold_store:
          type: banking_cs.datasets.GoldStoreDataset
          path: data/03_primary/gold
    """

    def __init__(self, path: str, metadata: dict[str, Any] | None = None) -> None:
        self._path = Path(path)
        self.metadata = metadata

    def load(self) -> dict[str, pl.DataFrame]:
        return {
            p.stem: pl.read_parquet(p) for p in sorted(self._path.glob("*.parquet"))
        }

    def save(self, data: dict[str, Any]) -> None:
        missing = {"batch_id", "tables", "quarantine", "load_log"} - set(data)
        if missing:
            raise DatasetError(f"GoldStoreDataset.save is missing {sorted(missing)}.")
        self._path.mkdir(parents=True, exist_ok=True)

        for name, rows in data["quarantine"].items():
            target = self._path / "_quarantine" / data["batch_id"] / f"{name}.parquet"
            target.parent.mkdir(parents=True, exist_ok=True)
            rows.write_parquet(target)

        if data["tables"] is not None:
            staged = []
            try:
                for name, table in data["tables"].items():
                    tmp = self._path / f"{name}.parquet.tmp"
                    table.write_parquet(tmp, compression="zstd")
                    staged.append((tmp, self._path / f"{name}.parquet"))
            except Exception:
                for tmp, _ in staged:
                    tmp.unlink(missing_ok=True)
                raise
            for tmp, target in staged:
                os.replace(tmp, target)

        log_path = self._path / "_load_log.parquet"
        log = data["load_log"]
        if log_path.exists():
            log = pl.concat([pl.read_parquet(log_path), log], how="vertical")
        tmp = log_path.with_name(log_path.name + ".tmp")
        log.write_parquet(tmp)
        os.replace(tmp, log_path)

    def _exists(self) -> bool:
        return (self._path / "_load_log.parquet").exists()

    def _describe(self) -> dict[str, Any]:
        return {"path": str(self._path)}
