"""Project-level tests: pipelines register and their datasets resolve in the catalog."""

from pathlib import Path

from kedro.framework.project import pipelines
from kedro.framework.session import KedroSession
from kedro.framework.startup import bootstrap_project

PROJECT_PATH = Path(__file__).resolve().parents[1]


def test_data_ingestion_outputs_resolve_in_catalog():
    bootstrap_project(PROJECT_PATH)
    with KedroSession.create(project_path=PROJECT_PATH) as session:
        context = session.load_context()
        pipeline = pipelines["data_ingestion"]
        for name in pipeline.outputs():
            dataset = context.catalog.get(name)
            assert type(dataset).__name__ == "DuckDBQueryDataset", name
        params = context.params["data_ingestion"]
        assert params["raw_root"] == "data/01_raw"
