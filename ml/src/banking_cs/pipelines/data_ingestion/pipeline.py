"""
'data_ingestion' pipeline: raw CSVs (01_raw) -> one typed Parquet per table
(02_intermediate), plus a cast-failure report (08_reporting).
"""

from functools import partial, update_wrapper

from kedro.pipeline import Node, Pipeline

from .nodes import build_cast_failures_query, build_ingestion_query
from .schemas import TABLE_SCHEMAS


def _ingestion_func(table: str):
    func = partial(build_ingestion_query, table=table)
    update_wrapper(func, build_ingestion_query)
    return func


def create_pipeline(**kwargs) -> Pipeline:
    ingestion_nodes = [
        Node(
            func=_ingestion_func(table),
            inputs=[
                "params:data_ingestion.raw_root",
                f"params:data_ingestion.tables.{table}",
            ],
            outputs=f"{table}_intermediate",
            name=f"ingest_{table}",
        )
        for table in TABLE_SCHEMAS
    ]
    report_node = Node(
        func=build_cast_failures_query,
        inputs=["params:data_ingestion.raw_root", "params:data_ingestion.tables"],
        outputs="ingestion_cast_failures",
        name="report_cast_failures",
    )
    return Pipeline([*ingestion_nodes, report_node])
