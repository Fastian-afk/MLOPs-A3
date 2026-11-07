import os

import httpx
import pytest

pytestmark = pytest.mark.e2e


def test_real_agent_model_dataset_chain_does_not_mutate():
    token = os.environ.get("MLOPS_API_TOKEN")
    if not token:
        pytest.skip("Set MLOPS_API_TOKEN for authenticated live API")
    response = httpx.post(
        "http://127.0.0.1:8000/agent/chat",
        timeout=90,
        headers={"Authorization": "Bearer " + token},
        json={
            "session_id": "e2e",
            "message": "Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary.",
        },
    )
    response.raise_for_status()
    result = response.json()
    assert {name.split(".")[0] for name in result["selected_tools"]} >= {
        "mlflow",
        "dvc",
        "airflow",
        "kubernetes",
    }
    assert "airflow.trigger_training" not in result["selected_tools"]
    assert not result["proposed_actions"]
    provenance = next(e for e in result["evidence"] if e["tool"] == "dvc.provenance")
    assert provenance["status"] == "ok"
    assert provenance["data"]["lineage_match"] is True
    assert any(e["tool"] == "airflow.list_runs" and e["status"] == "ok" for e in result["evidence"])


def test_real_inference_prediction_and_version():
    version = httpx.get("http://127.0.0.1:8001/version", timeout=10)
    version.raise_for_status()
    prediction = httpx.post("http://127.0.0.1:8001/predict", timeout=10, json={"instances": [[0.0] * 8]})
    prediction.raise_for_status()
    assert len(prediction.json()["predictions"]) == 1
    assert prediction.json()["run_id"] == version.json()["run_id"]
