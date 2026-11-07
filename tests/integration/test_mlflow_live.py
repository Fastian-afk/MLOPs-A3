"""Opt-in read-only integration check against an already seeded MLflow server."""

import os

import pytest

from agent.tools.mlflow_tools import ArtifactsQuery, BestRunQuery, MLflowTools, RunQuery

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 for real services"),
]


def test_five_live_runs_have_rankable_metrics_lineage_and_artifacts():
    adapter = MLflowTools(
        os.getenv("MLOPS_MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"),
        "mlops-assignment-03",
    )
    selection = adapter.select_best_run(BestRunQuery(limit=5))
    assert len(selection.candidates) == 5, "seed five real runs with python -m training.train --runs 5"
    best = selection.best_run
    assert best is not None
    details = adapter.get_run_details(RunQuery(run_id=best.run_id))
    assert details.run.status == "FINISHED"
    assert details.run.metrics["f1"] == max(run.metrics["f1"] for run in selection.candidates)
    assert len(details.run.tags["dataset.git_revision"]) == 40
    assert len(details.run.tags["dataset.hash"]) == 32
    assert details.run.tags["dataset.path"] == "data/dataset.csv"
    assert details.run.tags["quality_gate.status"] in {"passed", "failed"}
    assert details.production_ready is False
    artifacts = adapter.get_run_artifacts(ArtifactsQuery(run_id=best.run_id, path="model"))
    assert {item.path for item in artifacts.artifacts} >= {"model/evaluated.joblib", "model/metadata.json"}
