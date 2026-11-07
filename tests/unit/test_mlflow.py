"""Mocked adapter tests; these do not claim a live tracking-server integration."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from agent.tools.mlflow_tools import (
    ArtifactsQuery,
    BestRunQuery,
    CompareRunsQuery,
    ExperimentQuery,
    MLflowTools,
    MLflowUnavailableError,
    RegistryQuery,
    RunQuery,
    RunsQuery,
)


def run(run_id, f1=0.9, *, status="FINISHED", end_time=100, metrics=None, tags=None):
    return SimpleNamespace(
        info=SimpleNamespace(
            run_id=run_id,
            experiment_id="1",
            status=status,
            start_time=1,
            end_time=end_time,
        ),
        data=SimpleNamespace(
            metrics={"f1": f1} if metrics is None else metrics,
            params={"seed": "42"},
            tags={"evaluation.split": "stratified_holdout"} if tags is None else tags,
        ),
    )


@pytest.fixture
def client():
    mocked = MagicMock()
    mocked.get_experiment_by_name.return_value = SimpleNamespace(experiment_id="1")
    mocked.search_runs.return_value = []
    return mocked


def test_rank_excludes_failed_incomplete_missing_and_nonfinite_runs(client):
    client.search_runs.return_value = [
        run("good", 0.8),
        run("failed", 1.0, status="FAILED"),
        run("running", 1.0, status="RUNNING", end_time=None),
        run("incomplete", 1.0, end_time=None),
        run("missing", metrics={"accuracy": 1.0}),
        run("nan", float("nan")),
    ]
    result = MLflowTools(client=client).select_best_run(BestRunQuery(limit=6))
    assert result.best_run.run_id == "good"
    assert len(result.excluded_run_ids) == 5
    assert result.production_ready is False
    assert "production readiness" in " ".join(result.caveats)


def test_loss_is_minimized_and_metric_ties_are_deterministic(client):
    client.search_runs.return_value = [
        run("old", metrics={"loss": 0.1}, end_time=10),
        run("z", metrics={"loss": 0.1}, end_time=20),
        run("a", metrics={"loss": 0.1}, end_time=20),
        run("high", metrics={"loss": 0.5}, end_time=30),
    ]
    result = MLflowTools(client=client).select_best_run(BestRunQuery(metric="loss"))
    assert result.direction == "minimize"
    assert [item.run_id for item in result.candidates] == ["a", "z", "old", "high"]


def test_unknown_metric_requires_explicit_direction(client):
    adapter = MLflowTools(client=client)
    with pytest.raises(ValueError, match="METRIC_DIRECTION_REQUIRED"):
        adapter.select_best_run(BestRunQuery(metric="custom_score"))
    client.search_runs.return_value = [run("good", metrics={"custom_score": 2})]
    assert (
        adapter.select_best_run(BestRunQuery(metric="custom_score", direction="maximize")).best_run.run_id
        == "good"
    )


def test_no_experiment_does_not_invent_runs(client):
    client.get_experiment_by_name.return_value = None
    result = MLflowTools(client=client).select_best_run(BestRunQuery())
    assert result.best_run is None
    assert result.candidates == []
    assert any("does not exist" in caveat for caveat in result.caveats)
    client.search_runs.assert_not_called()


def test_no_completed_runs_is_explicit_uncertainty(client):
    client.search_runs.return_value = [run("failed", status="FAILED")]
    result = MLflowTools(client=client).select_best_run(BestRunQuery())
    assert result.best_run is None
    assert any("No completed run" in caveat for caveat in result.caveats)


def test_run_details_preserve_real_lineage_tags(client):
    client.get_run.return_value = run(
        "real-id",
        tags={
            "dataset.path": "data/dataset.csv",
            "dataset.hash": "abc123",
            "dataset.git_revision": "a" * 40,
        },
    )
    result = MLflowTools(client=client).get_run_details(RunQuery(run_id="real-id"))
    assert result.run.tags["dataset.hash"] == "abc123"
    assert result.run.tags["dataset.git_revision"] == "a" * 40
    assert result.production_ready is False


def test_compare_runs_reports_incompatible_split_caveat(client):
    client.get_run.side_effect = [
        run("one", 0.9, tags={"evaluation.split": "holdout-v1"}),
        run("two", 0.8, tags={"evaluation.split": "holdout-v2"}),
    ]
    result = MLflowTools(client=client).compare_runs(CompareRunsQuery(run_ids=["one", "two"]))
    assert result.best_run.run_id == "one"
    assert any("not be comparable" in item for item in result.caveats)


def test_service_failure_redacts_tracking_credential(client):
    client.get_run.side_effect = RuntimeError("https://secret-user:private-password@example.test/")
    with pytest.raises(MLflowUnavailableError) as captured:
        MLflowTools(client=client).get_run_details(RunQuery(run_id="real-id"))
    assert str(captured.value) == "MLFLOW_UNAVAILABLE_OR_NOT_FOUND"
    assert "private-password" not in str(captured.value)


def test_timeout_has_explicit_sanitized_failure(client):
    client.search_runs.side_effect = TimeoutError("private upstream details")
    with pytest.raises(MLflowUnavailableError, match="MLFLOW_TIMEOUT"):
        MLflowTools(client=client).list_runs(RunsQuery())


def test_registry_unavailable_is_not_reported_as_available(client):
    client.search_registered_models.side_effect = RuntimeError("registry unsupported")
    result = MLflowTools(client=client).get_model_registry_info(RegistryQuery())
    assert result.available is False
    assert result.models == []
    assert result.versions == []
    assert any("unavailable" in item for item in result.caveats)


def test_registry_versions_are_returned_as_recorded(client):
    client.get_registered_model.return_value = SimpleNamespace(
        name="classifier", description="Candidate classifier", aliases={"candidate": 2}, tags={}
    )
    client.search_model_versions.return_value = [
        SimpleNamespace(name="classifier", version=2, run_id="run2", status="READY", current_stage="None")
    ]
    result = MLflowTools(client=client).get_model_registry_info(RegistryQuery(name="classifier"))
    assert result.available is True
    assert result.models[0].aliases["candidate"] == "2"
    assert result.versions[0].run_id == "run2"


@pytest.mark.parametrize("path", ["../secret", "/etc/passwd", "model/../../secret", r"model\secret"])
def test_artifact_path_rejects_traversal(path):
    with pytest.raises(ValidationError):
        ArtifactsQuery(run_id="run1", path=path)


def test_artifact_listing_returns_recorded_metadata(client):
    client.list_artifacts.return_value = [SimpleNamespace(path="model.joblib", is_dir=False, file_size=100)]
    result = MLflowTools(client=client).get_run_artifacts(ArtifactsQuery(run_id="run1"))
    assert result.artifacts[0].path == "model.joblib"
    assert result.artifacts[0].file_size == 100


def test_experiment_listing_empty_is_explicit(client):
    client.search_experiments.return_value = []
    result = MLflowTools(client=client).list_experiments(ExperimentQuery())
    assert result.experiments == []
    assert result.caveats


def test_invalid_comparison_and_extra_model_arguments_are_rejected():
    with pytest.raises(ValidationError):
        CompareRunsQuery(run_ids=["one", "one"])
    with pytest.raises(ValidationError):
        BestRunQuery(shell_command="run arbitrary code")
    with pytest.raises(ValidationError):
        RunsQuery(limit=101)
