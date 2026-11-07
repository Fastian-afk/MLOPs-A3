import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from inference.main import create_app


def test_committed_demo_fixture_integrity_and_actual_serving_lineage():
    """The distributable fixture must serve the exact model promised by its manifest."""
    directory = Path(__file__).resolve().parents[2] / "demo_artifacts"
    manifest = json.loads((directory / "metadata.json").read_text())
    artifact = directory / manifest["artifact"]
    data = artifact.read_bytes()
    assert len(data) == manifest["size_bytes"] < 1024 * 1024
    assert hashlib.sha256(data).hexdigest() == manifest["sha256"]
    assert manifest["quality_gate"]["passed"] is True
    assert manifest["metrics"]["f1"] >= manifest["quality_gate"]["threshold"]
    assert manifest["provenance"]["git.commit"] == manifest["training_git_commit"]
    assert manifest["provenance"]["dataset.hash"] == manifest["dataset_hash"]
    # Loading is limited to this checksum-verified, trusted repository fixture.
    with TestClient(create_app(artifact)) as client:
        assert client.get("/health/ready").status_code == 200
        version = client.get("/version").json()
        prediction = client.post("/predict", json={"instances": [[0.0] * 8]})
        assert prediction.status_code == 200
        assert prediction.json()["run_id"] == version["run_id"] == manifest["run_id"]
        assert version["git_commit"] == manifest["training_git_commit"]
        assert version["dataset_hash"] == manifest["dataset_hash"]
        assert version["feature_names"] == manifest["feature_names"]
        assert len(prediction.json()["predictions"]) == 1
        assert abs(sum(prediction.json()["probabilities"][0]) - 1.0) < 1e-9
