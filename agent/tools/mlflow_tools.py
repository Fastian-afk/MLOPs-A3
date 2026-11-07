"""Read-only, schema-validated MLflow intelligence backed by ``MlflowClient``.

Scores are evidence about an evaluation split, never proof of production readiness.
Service exception details deliberately stay out of tool responses: tracking URIs and
upstream exception strings can contain credentials.
"""

from __future__ import annotations

import math
from pathlib import PurePosixPath
from typing import Any, Literal

from mlflow import MlflowClient
from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExperimentQuery(InputModel):
    limit: int = Field(default=100, ge=1, le=100)


class RunsQuery(InputModel):
    experiment_ids: list[str] | None = Field(default=None, max_length=10)
    limit: int = Field(default=5, ge=1, le=100)

    @field_validator("experiment_ids")
    @classmethod
    def validate_experiment_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (
            not value or any(not item or len(item) > 128 for item in value)
        ):
            raise ValueError("Provide one to ten nonempty experiment identifiers")
        return value


class RunQuery(InputModel):
    run_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ArtifactsQuery(RunQuery):
    path: str = Field(default="", max_length=256)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("Artifact paths must be relative without parent traversal")
        return value


class BestRunQuery(RunsQuery):
    metric: str = Field(default="f1", min_length=1, max_length=128, pattern=r"^[\w./:-]+$")
    direction: Literal["maximize", "minimize"] | None = None


class CompareRunsQuery(InputModel):
    run_ids: list[str] = Field(min_length=2, max_length=20)
    metric: str = Field(default="f1", min_length=1, max_length=128, pattern=r"^[\w./:-]+$")
    direction: Literal["maximize", "minimize"] | None = None

    @field_validator("run_ids")
    @classmethod
    def validate_ids(cls, value: list[str]) -> list[str]:
        for run_id in value:
            RunQuery(run_id=run_id)
        if len(set(value)) != len(value):
            raise ValueError("Comparison run identifiers must be distinct")
        return value


class RegistryQuery(InputModel):
    name: str | None = Field(default=None, max_length=200, pattern=r"^[A-Za-z0-9_.-]+$")
    limit: int = Field(default=20, ge=1, le=100)


class ExperimentRecord(BaseModel):
    experiment_id: str
    name: str
    lifecycle_stage: str
    tags: dict[str, str] = Field(default_factory=dict)


class ExperimentsOutput(BaseModel):
    experiments: list[ExperimentRecord]
    next_page_token: str | None = None
    caveats: list[str] = Field(default_factory=list)


class RunRecord(BaseModel):
    run_id: str
    experiment_id: str
    status: str
    start_time: int | None = None
    end_time: int | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)


class RunsOutput(BaseModel):
    runs: list[RunRecord]
    next_page_token: str | None = None
    caveats: list[str] = Field(default_factory=list)


class RunDetailsOutput(BaseModel):
    run: RunRecord
    production_ready: bool = False
    caveats: list[str]


class ArtifactRecord(BaseModel):
    path: str
    is_dir: bool
    file_size: int | None = None


class ArtifactsOutput(BaseModel):
    run_id: str
    path: str
    artifacts: list[ArtifactRecord]


class BestRunOutput(BaseModel):
    best_run: RunRecord | None
    candidates: list[RunRecord]
    metric: str
    direction: Literal["maximize", "minimize"]
    excluded_run_ids: list[str]
    evaluation_split: str | None = None
    production_ready: bool = False
    caveats: list[str]


class RegistryVersion(BaseModel):
    name: str
    version: str
    run_id: str | None = None
    status: str | None = None
    current_stage: str | None = None


class RegisteredModel(BaseModel):
    name: str
    description: str | None = None
    aliases: dict[str, str] = Field(default_factory=dict)
    tags: dict[str, str] = Field(default_factory=dict)


class RegistryOutput(BaseModel):
    available: bool
    models: list[RegisteredModel]
    versions: list[RegistryVersion]
    caveats: list[str]


class MLflowUnavailableError(RuntimeError):
    """A sanitized failure safe for an agent response or structured log."""


_DIRECTIONS: dict[str, Literal["maximize", "minimize"]] = {
    "f1": "maximize",
    "accuracy": "maximize",
    "precision": "maximize",
    "recall": "maximize",
    "auc": "maximize",
    "roc_auc": "maximize",
    "r2": "maximize",
    "loss": "minimize",
    "log_loss": "minimize",
    "mae": "minimize",
    "mse": "minimize",
    "rmse": "minimize",
    "error": "minimize",
}

_READINESS_CAVEAT = (
    "An experimental metric alone does not establish production readiness: verify "
    "dataset provenance, validation, quality gate, deployment health and freshness policy."
)


def _direction(metric: str, direction: str | None) -> Literal["maximize", "minimize"]:
    if direction in ("maximize", "minimize"):
        return direction
    inferred = _DIRECTIONS.get(metric.lower())
    if inferred is None:
        raise ValueError("METRIC_DIRECTION_REQUIRED: specify maximize or minimize")
    return inferred


def _run_record(run: Any) -> RunRecord:
    # Drop non-finite metrics: JSON cannot represent NaN/Infinity reliably.
    metrics = {
        str(name): float(value)
        for name, value in run.data.metrics.items()
        if math.isfinite(float(value))
    }
    return RunRecord(
        run_id=run.info.run_id,
        experiment_id=run.info.experiment_id,
        status=run.info.status,
        start_time=run.info.start_time,
        end_time=run.info.end_time,
        metrics=metrics,
        params=dict(run.data.params),
        tags=dict(run.data.tags),
    )


class MLflowTools:
    """Adapters have an injectable client for isolated CI, not fake production data."""

    def __init__(
        self,
        tracking_uri: str | None = None,
        experiment_name: str = "mlops-assignment",
        *,
        client: Any = None,
    ) -> None:
        self._client = client
        self.tracking_uri = tracking_uri
        self.experiment_name = experiment_name

    @property
    def client(self) -> Any:
        # A tracking outage must not stop the agent's health endpoint or other tools.
        if self._client is None:
            self._client = MlflowClient(tracking_uri=self.tracking_uri)
        return self._client

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(self.client, method)(*args, **kwargs)
        except TimeoutError as exc:
            raise MLflowUnavailableError("MLFLOW_TIMEOUT") from exc
        except Exception as exc:
            raise MLflowUnavailableError("MLFLOW_UNAVAILABLE_OR_NOT_FOUND") from exc

    def list_experiments(self, query: ExperimentQuery) -> ExperimentsOutput:
        page = self._call("search_experiments", max_results=query.limit)
        records = [
            ExperimentRecord(
                experiment_id=item.experiment_id,
                name=item.name,
                lifecycle_stage=item.lifecycle_stage,
                tags=dict(item.tags),
            )
            for item in page
        ]
        return ExperimentsOutput(
            experiments=records,
            next_page_token=getattr(page, "token", None),
            caveats=[] if records else ["No active experiments were returned."],
        )

    def _experiment_ids(self, query: RunsQuery) -> list[str]:
        if query.experiment_ids is not None:
            return query.experiment_ids
        experiment = self._call("get_experiment_by_name", self.experiment_name)
        return [experiment.experiment_id] if experiment is not None else []

    def list_runs(self, query: RunsQuery) -> RunsOutput:
        ids = self._experiment_ids(query)
        if not ids:
            return RunsOutput(runs=[], caveats=["The configured experiment does not exist."])
        page = self._call(
            "search_runs",
            experiment_ids=ids,
            order_by=["attributes.start_time DESC", "attributes.run_id ASC"],
            max_results=query.limit,
        )
        runs = [_run_record(run) for run in page]
        return RunsOutput(
            runs=runs,
            next_page_token=getattr(page, "token", None),
            caveats=[] if runs else ["No runs were returned for the selected experiments."],
        )

    def get_run_details(self, query: RunQuery) -> RunDetailsOutput:
        return RunDetailsOutput(
            run=_run_record(self._call("get_run", query.run_id)),
            caveats=[_READINESS_CAVEAT],
        )

    def get_run_artifacts(self, query: ArtifactsQuery) -> ArtifactsOutput:
        records = self._call("list_artifacts", query.run_id, path=query.path)
        return ArtifactsOutput(
            run_id=query.run_id,
            path=query.path,
            artifacts=[
                ArtifactRecord(path=item.path, is_dir=item.is_dir, file_size=item.file_size)
                for item in records
            ],
        )

    def _rank(
        self, runs: list[RunRecord], metric: str, direction: Literal["maximize", "minimize"]
    ) -> BestRunOutput:
        candidates = [
            run
            for run in runs
            if run.status == "FINISHED" and run.end_time is not None and metric in run.metrics
        ]
        # Metric ties prefer the most recently completed run, then lexical run ID.
        candidates.sort(
            key=lambda run: (
                run.metrics[metric] * (-1 if direction == "maximize" else 1),
                -(run.end_time or 0),
                run.run_id,
            )
        )
        selected = candidates[0] if candidates else None
        excluded = sorted(set(run.run_id for run in runs) - {run.run_id for run in candidates})
        splits = {run.tags.get("evaluation.split", "unknown") for run in candidates}
        caveats = [_READINESS_CAVEAT]
        if not selected:
            caveats.append("No completed run has a finite value for the requested metric.")
        if excluded:
            caveats.append("Failed, incomplete and missing/non-finite metric runs were excluded.")
        if len(splits) > 1 or "unknown" in splits:
            caveats.append("Evaluation splits differ or are unrecorded; scores may not be comparable.")
        return BestRunOutput(
            best_run=selected,
            candidates=candidates,
            metric=metric,
            direction=direction,
            excluded_run_ids=excluded,
            evaluation_split=selected.tags.get("evaluation.split") if selected else None,
            caveats=caveats,
        )

    def select_best_run(self, query: BestRunQuery) -> BestRunOutput:
        direction = _direction(query.metric, query.direction)
        runs = self.list_runs(RunsQuery(experiment_ids=query.experiment_ids, limit=query.limit))
        result = self._rank(runs.runs, query.metric, direction)
        result.caveats.extend(runs.caveats)
        return result

    def compare_runs(self, query: CompareRunsQuery) -> BestRunOutput:
        direction = _direction(query.metric, query.direction)
        runs = [_run_record(self._call("get_run", run_id)) for run_id in query.run_ids]
        return self._rank(runs, query.metric, direction)

    def get_model_registry_info(self, query: RegistryQuery) -> RegistryOutput:
        try:
            if query.name is None:
                models = self._call("search_registered_models", max_results=query.limit)
                versions = []
            else:
                models = [self._call("get_registered_model", query.name)]
                versions = self._call(
                    "search_model_versions",
                    filter_string=f"name = '{query.name}'",
                    max_results=query.limit,
                )
        except MLflowUnavailableError:
            return RegistryOutput(
                available=False,
                models=[],
                versions=[],
                caveats=["Registry is unavailable or the requested model was not found; no deployment is inferred."],
            )
        return RegistryOutput(
            available=True,
            models=[
                RegisteredModel(
                    name=model.name,
                    description=model.description,
                    aliases={str(key): str(value) for key, value in (getattr(model, "aliases", {}) or {}).items()},
                    tags=dict(getattr(model, "tags", {}) or {}),
                )
                for model in models
            ],
            versions=[
                RegistryVersion(
                    name=version.name,
                    version=str(version.version),
                    run_id=version.run_id,
                    status=str(version.status),
                    current_stage=getattr(version, "current_stage", None),
                )
                for version in versions
            ],
            caveats=[] if models else ["No registered models exist."],
        )


def register(registry: Any, settings: Any) -> None:
    adapter = MLflowTools(settings.mlflow_tracking_uri, settings.experiment_name)
    definitions = [
        ("mlflow.list_experiments", "List recorded MLflow experiments", ExperimentQuery, adapter.list_experiments, ExperimentsOutput),
        ("mlflow.list_runs", "List the most recent recorded runs", RunsQuery, adapter.list_runs, RunsOutput),
        ("mlflow.run_details", "Retrieve one run's metrics, parameters and lineage tags", RunQuery, adapter.get_run_details, RunDetailsOutput),
        ("mlflow.artifacts", "List artifact metadata without downloading or executing artifacts", ArtifactsQuery, adapter.get_run_artifacts, ArtifactsOutput),
        ("mlflow.best_run", "Rank recent completed runs by a metric and explicit direction", BestRunQuery, adapter.select_best_run, BestRunOutput),
        ("mlflow.compare_runs", "Compare specific completed runs across experiments", CompareRunsQuery, adapter.compare_runs, BestRunOutput),
        ("mlflow.registry_info", "Read registered-model metadata where supported", RegistryQuery, adapter.get_model_registry_info, RegistryOutput),
    ]
    for name, description, input_model, handler, output_model in definitions:
        registry.add(
            name,
            description,
            input_model,
            handler,
            output_model=output_model,
            permission="read",
            timeout=30,
        )
