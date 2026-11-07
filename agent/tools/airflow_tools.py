"""Typed, authenticated Airflow 3 REST API operations.

The sole write is an allowlisted DAG trigger. The registry must authorize its
confirmation before calling it; this adapter additionally validates DAG and conf.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from agent.logging import redact


class AirflowError(RuntimeError):
    """A stable, sanitized error suitable for an agent response."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PageInput(Input):
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=10000)


class RunsInput(PageInput):
    dag_id: str = Field(default="mlops_training", pattern=r"^[A-Za-z0-9_.-]{1,150}$")


class RunInput(Input):
    dag_id: str = Field(default="mlops_training", pattern=r"^[A-Za-z0-9_.-]{1,150}$")
    run_id: str = Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9_.:+@-]+$")


class DiagnosticsInput(RunInput):
    task_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,250}$")
    try_number: int = Field(default=1, ge=1, le=100)


class TrainingConf(Input):
    c: float = Field(default=1.0, gt=0, le=1000)
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    test_size: float = Field(default=0.25, ge=0.1, le=0.5)
    f1_threshold: float = Field(default=0.85, ge=0, le=1)
    experiment_name: str = Field(default="mlops-assignment-03", pattern=r"^[A-Za-z0-9_.-]{1,100}$")


class TriggerInput(Input):
    dag_id: str = Field(default="mlops_training", pattern=r"^[A-Za-z0-9_.-]{1,150}$")
    conf: TrainingConf = Field(default_factory=TrainingConf)
    poll_seconds: int = Field(default=0, ge=0, le=20)


class DAGSummary(BaseModel):
    dag_id: str
    is_paused: bool | None = None
    is_active: bool | None = None
    description: str | None = None


class DAGsOutput(BaseModel):
    dags: list[DAGSummary]
    total_entries: int
    next_offset: int | None


class RunSummary(BaseModel):
    dag_id: str
    dag_run_id: str
    state: str | None = None
    logical_date: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    conf: dict[str, Any] = Field(default_factory=dict)


class RunsOutput(BaseModel):
    dag_runs: list[RunSummary]
    total_entries: int
    next_offset: int | None


class TaskSummary(BaseModel):
    task_id: str
    state: str | None = None
    try_number: int | None = None
    start_date: str | None = None
    end_date: str | None = None
    duration: float | None = None


class RunOutput(BaseModel):
    run: RunSummary
    tasks: list[TaskSummary]
    completed: bool
    succeeded: bool


class FailedTasksOutput(BaseModel):
    dag_id: str
    run_id: str
    failed_tasks: list[TaskSummary]


class DiagnosticsOutput(BaseModel):
    dag_id: str
    run_id: str
    task: TaskSummary
    log: str
    log_available: bool
    log_truncated: bool = False
    uncertainty: str | None = None


class AirflowTools:
    def __init__(self, settings: Any, client: httpx.Client | None = None):
        self.settings = settings
        self.client = client or httpx.Client(
            base_url=settings.airflow_base_url.rstrip("/") + "/",
            timeout=settings.http_timeout,
        )
        self.token: str | None = settings.airflow_token

    def _headers(self) -> dict[str, str]:
        if not self.token:
            if not self.settings.airflow_password:
                raise AirflowError("airflow_authentication_missing")
            try:
                response = self.client.post(
                    "auth/token",
                    json={
                        "username": self.settings.airflow_username,
                        "password": self.settings.airflow_password,
                    },
                )
                if response.status_code in (401, 403):
                    raise AirflowError("airflow_authentication_failed")
                response.raise_for_status()
                token = response.json().get("access_token")
                if not isinstance(token, str) or not token:
                    raise AirflowError("airflow_invalid_auth_response")
                self.token = token
            except httpx.TimeoutException as exc:
                raise AirflowError("airflow_timeout") from exc
            except (httpx.HTTPError, ValueError) as exc:
                raise AirflowError("airflow_authentication_unavailable") from exc
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self.client.request(method, "api/v2/" + path, headers=self._headers(), **kwargs)
            if response.status_code in (401, 403):
                raise AirflowError("airflow_authentication_failed")
            if response.status_code == 404:
                raise AirflowError("airflow_not_found")
            if response.status_code == 409:
                raise AirflowError("airflow_conflict")
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise AirflowError("airflow_invalid_response")
            return body
        except httpx.TimeoutException as exc:
            raise AirflowError("airflow_timeout") from exc
        except httpx.HTTPError as exc:
            raise AirflowError("airflow_service_unavailable") from exc
        except ValueError as exc:
            raise AirflowError("airflow_invalid_response") from exc

    def _dag(self, dag_id: str) -> str:
        if dag_id != self.settings.approved_dag_id:
            raise AirflowError("airflow_dag_not_approved")
        return "dags/" + quote(dag_id, safe="")

    def _run_path(self, args: RunInput) -> str:
        return self._dag(args.dag_id) + "/dagRuns/" + quote(args.run_id, safe="")

    @staticmethod
    def _next(offset: int, returned: int, total: int) -> int | None:
        return offset + returned if returned and offset + returned < total else None

    def list_dags(self, args: PageInput) -> DAGsOutput:
        body = self._request("GET", "dags", params=args.model_dump())
        dags = [DAGSummary.model_validate(item) for item in body.get("dags", [])]
        total = int(body.get("total_entries", len(dags)))
        return DAGsOutput(
            dags=dags, total_entries=total, next_offset=self._next(args.offset, len(dags), total)
        )

    def list_runs(self, args: RunsInput) -> RunsOutput:
        body = self._request(
            "GET",
            self._dag(args.dag_id) + "/dagRuns",
            params={"limit": args.limit, "offset": args.offset, "order_by": "-start_date"},
        )
        runs = [RunSummary.model_validate(item) for item in body.get("dag_runs", [])]
        total = int(body.get("total_entries", len(runs)))
        return RunsOutput(
            dag_runs=runs, total_entries=total, next_offset=self._next(args.offset, len(runs), total)
        )

    def _tasks(self, args: RunInput) -> list[TaskSummary]:
        tasks: list[TaskSummary] = []
        offset = 0
        for _ in range(10):
            body = self._request(
                "GET", self._run_path(args) + "/taskInstances", params={"limit": 100, "offset": offset}
            )
            batch = body.get("task_instances", [])
            tasks.extend(TaskSummary.model_validate(item) for item in batch)
            offset += len(batch)
            if not batch or offset >= int(body.get("total_entries", offset)):
                return tasks
        raise AirflowError("airflow_task_pagination_limit")

    def run_status(self, args: RunInput) -> RunOutput:
        run = RunSummary.model_validate(self._request("GET", self._run_path(args)))
        return RunOutput(
            run=run,
            tasks=self._tasks(args),
            completed=run.state in ("success", "failed"),
            succeeded=run.state == "success",
        )

    def trigger_training(self, args: TriggerInput) -> RunOutput:
        path = self._dag(args.dag_id) + "/dagRuns"
        body = self._request(
            "POST",
            path,
            json={
                "dag_run_id": "agent__" + uuid4().hex,
                "logical_date": datetime.now(UTC).isoformat(),
                "conf": args.conf.model_dump(),
            },
        )
        run = RunSummary.model_validate(body)
        run_args = RunInput(dag_id=args.dag_id, run_id=run.dag_run_id)
        deadline = time.monotonic() + args.poll_seconds
        result = self.run_status(run_args)
        while not result.completed and time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline - time.monotonic())))
            result = self.run_status(run_args)
        return result

    def failed_tasks(self, args: RunInput) -> FailedTasksOutput:
        return FailedTasksOutput(
            dag_id=args.dag_id,
            run_id=args.run_id,
            failed_tasks=[task for task in self._tasks(args) if task.state in ("failed", "upstream_failed")],
        )

    def diagnostics(self, args: DiagnosticsInput) -> DiagnosticsOutput:
        path = self._run_path(args) + "/taskInstances/" + quote(args.task_id, safe="")
        task = TaskSummary.model_validate(self._request("GET", path))
        try:
            logs = self._request("GET", path + f"/logs/{args.try_number}")
            content = logs.get("content", "")
            if not isinstance(content, str):
                import json

                content = json.dumps(content)
            return DiagnosticsOutput(
                dag_id=args.dag_id,
                run_id=args.run_id,
                task=task,
                log=redact(content[:16000]),
                log_available=True,
                log_truncated=len(content) > 16000,
            )
        except AirflowError as exc:
            return DiagnosticsOutput(
                dag_id=args.dag_id,
                run_id=args.run_id,
                task=task,
                log="",
                log_available=False,
                uncertainty=exc.code,
            )


def register(registry: Any, settings: Any) -> None:
    tools = AirflowTools(settings)
    for name, description, args, handler, output, permission in [
        ("list_dags", "List Airflow 3 DAGs with pagination.", PageInput, tools.list_dags, DAGsOutput, "read"),
        (
            "list_runs",
            "List recent runs of the approved training DAG.",
            RunsInput,
            tools.list_runs,
            RunsOutput,
            "read",
        ),
        (
            "run_status",
            "Inspect actual run and task states; queued does not mean success.",
            RunInput,
            tools.run_status,
            RunOutput,
            "read",
        ),
        (
            "trigger_training",
            "Trigger the approved DAG only after explicit action-bound confirmation.",
            TriggerInput,
            tools.trigger_training,
            RunOutput,
            "write",
        ),
        (
            "failed_tasks",
            "List failed and upstream-failed tasks for an approved DAG run.",
            RunInput,
            tools.failed_tasks,
            FailedTasksOutput,
            "read",
        ),
        (
            "diagnostics",
            "Read task state and available bounded logs.",
            DiagnosticsInput,
            tools.diagnostics,
            DiagnosticsOutput,
            "read",
        ),
    ]:
        registry.add(
            "airflow." + name,
            description,
            args,
            handler,
            output_model=output,
            permission=permission,
            timeout=30,
        )
