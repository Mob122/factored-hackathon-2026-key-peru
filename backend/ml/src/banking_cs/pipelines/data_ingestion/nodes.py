"""Nodes for the 'data_ingestion' pipeline.

Each node returns a DuckDB SQL query; ``DuckDBQueryDataset`` executes it with
``COPY ... TO`` so large tables stream from CSV to Parquet without passing
through Python memory.

Raw CSVs are read with every column as VARCHAR and then cast explicitly to the
data dictionary types with ``TRY_CAST``. Values that fail to cast become NULL
and are counted by ``build_cast_failures_query``. No rows are filtered or
deduplicated.
"""

from pathlib import PurePosixPath

from .schemas import TABLE_SCHEMAS


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _posix(path: str) -> str:
    return str(PurePosixPath(path.replace("\\", "/")))


def _read_csv_sql(raw_root: str, table_glob: str) -> str:
    glob = f"{_posix(raw_root)}/{table_glob}"
    return f"""read_csv(
        {_quote_literal(glob)},
        header = true,
        delim = ',',
        quote = '"',
        escape = '"',
        all_varchar = true,
        union_by_name = true,
        hive_partitioning = false,
        filename = true
    )"""


def _cast_sql(column: str, dtype: str) -> str:
    """Return the expression casting a VARCHAR column to ``dtype``.

    Integers are written as floats in the raw files (``701.0``). DuckDB rounds
    ``'701.5'`` to 702 when casting, so only integral values are accepted.
    """
    col = _quote_ident(column)
    if dtype == "INTEGER":
        as_double = f"TRY_CAST({col} AS DOUBLE)"
        return (
            f"CASE WHEN {as_double} = trunc({as_double}) "
            f"THEN TRY_CAST({as_double} AS INTEGER) END"
        )
    return f"TRY_CAST({col} AS {dtype})"


def _typed_columns(table: str) -> dict[str, str]:
    return {c: t for c, t in TABLE_SCHEMAS[table].items() if t != "VARCHAR"}


def build_ingestion_query(raw_root: str, table_glob: str, table: str) -> str:
    """Build the query that reads all partitions of ``table`` and types them.

    Columns present in the files but missing from the dictionary are kept as
    VARCHAR. ``source_file`` is the file path relative to ``raw_root``.
    """
    replaces = ",\n        ".join(
        f"{_cast_sql(c, t)} AS {_quote_ident(c)}"
        for c, t in _typed_columns(table).items()
    )
    prefix_len = len(_posix(raw_root)) + 1
    return f"""
SELECT
    * EXCLUDE (filename) REPLACE (
        {replaces}
    ),
    substr(replace(filename, '\\', '/'), {prefix_len + 1}) AS source_file
FROM {_read_csv_sql(raw_root, table_glob)}
"""


def _table_failures_sql(raw_root: str, table: str, table_glob: str) -> str:
    typed = _typed_columns(table)
    structs = ",\n        ".join(
        f"{{'target_type': {_quote_literal(t)}, "
        f"'n_non_null': count({_quote_ident(c)}), "
        f"'n_failures': count(*) FILTER ({_quote_ident(c)} IS NOT NULL "
        f"AND ({_cast_sql(c, t)}) IS NULL), "
        f"'example_value': any_value({_quote_ident(c)}) FILTER "
        f"({_quote_ident(c)} IS NOT NULL AND ({_cast_sql(c, t)}) IS NULL)}} "
        f"AS {_quote_ident(c)}"
        for c, t in typed.items()
    )
    return f"""
SELECT
    {_quote_literal(table)} AS table_name,
    column_name,
    n_rows,
    stats.target_type,
    stats.n_non_null,
    stats.n_failures,
    stats.example_value
FROM (
    UNPIVOT (
        SELECT
            count(*) AS n_rows,
            {structs}
        FROM {_read_csv_sql(raw_root, table_glob)}
    )
    ON COLUMNS(* EXCLUDE (n_rows))
    INTO NAME column_name VALUE stats
)"""


def build_cast_failures_query(raw_root: str, tables: dict[str, str]) -> str:
    """Build the query counting, per typed column, raw values that fail to cast.

    A failure is a non-null raw value that becomes NULL after the cast. The
    report also carries the raw row count of each table.
    """
    parts = [
        _table_failures_sql(raw_root, table, tables[table]) for table in TABLE_SCHEMAS
    ]
    return "\nUNION ALL\n".join(parts) + "\nORDER BY table_name, column_name"
