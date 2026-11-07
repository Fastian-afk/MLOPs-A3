"""Airflow API contracts are mocked here; real-service evidence is separate."""

from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from agent.tools.airflow_tools import (
    AirflowError,
    AirflowTools,
    DiagnosticsInput,
    PageInput,
    RunInput,
    RunsInput,
    TriggerInput,
)


def settings(**overrides):
    fields = dict(airflow_base_url="http://airflow:8080", airflow_token="test-token", airflow_username="admin", airflow_password=None, approved_dag_id="mlops_training", http_timeout=1)
    return SimpleNamespace(**(fields | overrides))


def tools(handler, **overrides):
    return AirflowTools(settings(**overrides), httpx.Client(base_url="http://airflow:8080/", transport=httpx.MockTransport(handler)))


def test_lists_dags_using_v2_bearer_and_pagination():
    def handler(request):
        assert request.url.path == "/api/v2/dags"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(200, json={"dags": [{"dag_id": "mlops_training", "is_paused": False}], "total_entries": 3})
    result = tools(handler).list_dags(PageInput(limit=1))
    assert result.next_offset == 1
    assert result.dags[0].dag_id == "mlops_training"


def test_missing_auth_does_not_make_any_request():
    def handler(request):
        pytest.fail("must not call the service without configured auth")
    with pytest.raises(AirflowError, match="authentication_missing"):
        tools(handler, airflow_token=None).list_dags(PageInput())


def test_auth_error_is_sanitized():
    with pytest.raises(AirflowError, match="authentication_failed") as error:
        tools(lambda _: httpx.Response(401, text="password=private")).list_dags(PageInput())
    assert "private" not in str(error.value)


def test_timeout_is_explicit():
    def timeout(request):
        raise httpx.ReadTimeout("secret detail", request=request)
    with pytest.raises(AirflowError, match="airflow_timeout"):
        tools(timeout).list_runs(RunsInput())


def test_unapproved_dag_rejected_before_mutation():
    def handler(request):
        pytest.fail("unapproved DAG must not be requested")
    with pytest.raises(AirflowError, match="dag_not_approved"):
        tools(handler).trigger_training(TriggerInput(dag_id="arbitrary_dag"))


@pytest.mark.parametrize("conf", [{"c": -1}, {"f1_threshold": 2}, {"dataset": "/etc/passwd"}, {"command": "id"}])
def test_run_configuration_is_bounded(conf):
    with pytest.raises(ValidationError):
        TriggerInput(conf=conf)


def test_trigger_queued_is_not_reported_success():
    calls = []
    run = {"dag_id": "mlops_training", "dag_run_id": "agent__abc", "state": "queued", "logical_date": "2026-11-07T00:00:00Z"}
    def handler(request):
        calls.append(request.method)
        if request.url.path.endswith("taskInstances"):
            return httpx.Response(200, json={"task_instances": [], "total_entries": 0})
        return httpx.Response(200, json=run)
    result = tools(handler).trigger_training(TriggerInput())
    assert calls.count("POST") == 1
    assert result.run.dag_run_id == "agent__abc"
    assert not result.completed and not result.succeeded


def test_failed_task_pagination_and_upstream_failure():
    def handler(request):
        if request.url.params.get("offset") == "0":
            return httpx.Response(200, json={"task_instances": [{"task_id": "validate_dataset", "state": "failed"}], "total_entries": 2})
        return httpx.Response(200, json={"task_instances": [{"task_id": "train_model", "state": "upstream_failed"}], "total_entries": 2})
    result = tools(handler).failed_tasks(RunInput(run_id="agent__abc"))
    assert [task.state for task in result.failed_tasks] == ["failed", "upstream_failed"]


def test_diagnostics_preserves_task_when_log_unavailable():
    def handler(request):
        if "/logs/" in request.url.path:
            return httpx.Response(404, json={"detail": "missing"})
        return httpx.Response(200, json={"task_id": "validate_dataset", "state": "failed", "try_number": 2})
    result = tools(handler).diagnostics(DiagnosticsInput(run_id="agent__abc", task_id="validate_dataset", try_number=2))
    assert result.task.state == "failed"
    assert not result.log_available
    assert result.uncertainty == "airflow_not_found"


def test_simple_auth_token_is_used_for_v2():
    def handler(request):
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "fresh-token"})
        assert request.headers["Authorization"] == "Bearer fresh-token"
        return httpx.Response(200, json={"dags": [], "total_entries": 0})
    assert tools(handler, airflow_token=None, airflow_password="local-password").list_dags(PageInput()).dags == []
