"""Opt-in read-only verification of an existing real five-stage Airflow run."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.tools.airflow_tools import AirflowTools, PageInput, RunInput, RunsInput

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_INTEGRATION") != "1", reason="set RUN_INTEGRATION=1 for real services"),
]


@pytest.fixture
def live_airflow():
    token = os.getenv("MLOPS_AIRFLOW_TOKEN") or os.getenv("AIRFLOW_TOKEN")
    username = os.getenv("MLOPS_AIRFLOW_USERNAME", os.getenv("AIRFLOW_USERNAME", "admin"))
    password = os.getenv("MLOPS_AIRFLOW_PASSWORD") or os.getenv("AIRFLOW_PASSWORD")
    password_file = Path(
        os.getenv("AIRFLOW_PASSWORD_FILE", ".runtime/airflow/simple_auth_manager_passwords.json")
    )
    if not token and not password and password_file.is_file():
        password = json.loads(password_file.read_text()).get(username)
    assert token or password, "configure Airflow authentication or start the documented local Airflow service"
    return AirflowTools(
        SimpleNamespace(
            airflow_base_url=os.getenv(
                "MLOPS_AIRFLOW_BASE_URL", os.getenv("AIRFLOW_BASE_URL", "http://127.0.0.1:8080")
            ),
            airflow_token=token,
            airflow_username=username,
            airflow_password=password,
            approved_dag_id="mlops_training",
            http_timeout=10,
        )
    )


def test_live_dag_is_present(live_airflow):
    listing = live_airflow.list_dags(PageInput(limit=100))
    assert "mlops_training" in {dag.dag_id for dag in listing.dags}


def test_existing_live_success_has_all_five_completed_tasks(live_airflow):
    runs = live_airflow.list_runs(RunsInput(limit=100))
    successful = next((run for run in runs.dag_runs if run.state == "success"), None)
    assert successful is not None, (
        "explicitly execute the documented five-stage DAG before running this check"
    )
    result = live_airflow.run_status(RunInput(run_id=successful.dag_run_id))
    assert result.completed and result.succeeded
    assert result.run.start_date and result.run.end_date
    assert {task.task_id: task.state for task in result.tasks} == {
        "validate_dataset": "success",
        "preprocess_data": "success",
        "train_model": "success",
        "evaluate_and_log": "success",
        "quality_gate": "success",
    }
