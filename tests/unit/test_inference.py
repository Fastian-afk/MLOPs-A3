import joblib
import numpy as np
import pytest
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from inference.main import create_app


@pytest.fixture
def trained_artifact(tmp_path):
    model = LogisticRegression(random_state=42).fit(
        np.array([[0] * 8, [1] * 8, [2] * 8, [3] * 8]), [0, 0, 1, 1]
    )
    path = tmp_path / "model.joblib"
    joblib.dump(
        {
            "model": model,
            "feature_names": [f"feature_{i}" for i in range(8)],
            "metadata": {"run_id": "real-test-run", "dataset_hash": "abc123", "git_commit": "a" * 40},
        },
        path,
    )
    return path


def test_missing_model_keeps_process_live_but_not_ready(tmp_path):
    with TestClient(create_app(tmp_path / "missing.joblib")) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
        assert client.post("/predict", json={"instances": [[0] * 8]}).status_code == 503
        assert client.get("/version").json()["ready"] is False


def test_actual_serialized_model_predicts_and_reports_provenance(trained_artifact):
    with TestClient(create_app(trained_artifact)) as client:
        assert client.get("/health/ready").status_code == 200
        response = client.post("/predict", json={"instances": [[0] * 8, [3] * 8]})
        assert response.status_code == 200
        assert response.json()["predictions"] == [0, 1]
        assert response.json()["run_id"] == "real-test-run"
        assert all(abs(sum(row) - 1) < 1e-9 for row in response.json()["probabilities"])
        version = client.get("/version").json()
        assert version["git_commit"] == "a" * 40
        assert version["dataset_hash"] == "abc123"


@pytest.mark.parametrize(
    "instances", [[], [[0] * 7], [[0] * 9], [["NaN"] * 8], [["Infinity"] * 8], [[0] * 8] * 257]
)
def test_invalid_prediction_inputs_rejected(trained_artifact, instances):
    with TestClient(create_app(trained_artifact)) as client:
        assert client.post("/predict", json={"instances": instances}).status_code == 422


def test_wrong_artifact_structure_is_unready(tmp_path):
    path = tmp_path / "bad.joblib"
    joblib.dump({"unrelated": "data"}, path)
    with TestClient(create_app(path)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 503
