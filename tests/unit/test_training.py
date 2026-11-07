import json

import joblib
import pandas as pd
import pytest
from sklearn.metrics import f1_score

from scripts.prepare_data import prepare
from training.config import TrainingConfig
from training.preprocess import preprocess_dataset
from training.quality_gate import apply_quality_gate
from training.train import train_model
from training.validate import dataset_hash, validate_dataset


@pytest.fixture
def dataset(tmp_path):
    path = tmp_path / "dataset.csv"
    prepare(path)
    return path


def test_dataset_generation_is_reproducible(dataset, tmp_path):
    second = tmp_path / "second.csv"
    prepare(second)
    assert dataset.read_bytes() == second.read_bytes()
    assert validate_dataset(dataset)["rows"] == 400


def test_validation_rejects_missing_values(dataset):
    frame = pd.read_csv(dataset)
    frame.loc[0, "feature_0"] = float("nan")
    frame.to_csv(dataset, index=False)
    with pytest.raises(ValueError, match="missing_values"):
        validate_dataset(dataset)


def test_validation_rejects_wrong_target(dataset):
    frame = pd.read_csv(dataset)
    frame["target"] = 1
    frame.to_csv(dataset, index=False)
    with pytest.raises(ValueError, match="binary_classes"):
        validate_dataset(dataset)


def test_validation_rejects_wrong_schema(dataset):
    frame = pd.read_csv(dataset).drop(columns=["feature_0"])
    frame.to_csv(dataset, index=False)
    with pytest.raises(ValueError, match="schema_invalid"):
        validate_dataset(dataset)


def test_split_is_stratified_deterministic_and_training_serializes(dataset, tmp_path):
    one = joblib.load(preprocess_dataset(dataset, tmp_path / "one"))
    two_path = preprocess_dataset(dataset, tmp_path / "two")
    two = joblib.load(two_path)
    assert one["x_train"].equals(two["x_train"])
    assert set(one["x_train"].index).isdisjoint(one["x_test"].index)
    assert len(one["x_train"]) == 300
    artifact = joblib.load(train_model(two_path, tmp_path / "model"))
    predictions = artifact["model"].predict(two["x_test"])
    assert f1_score(two["y_test"], predictions) >= 0.8
    assert artifact["metadata"]["dataset_hash"] == dataset_hash(dataset)


def test_quality_gate_failure_cannot_promote(tmp_path):
    report = {"validation_passed": True, "metrics": {"f1": 0.2}, "model_path": "nonexistent"}
    with pytest.raises(ValueError, match="promotion blocked"):
        apply_quality_gate(report, tmp_path / "artifacts", 0.8)
    assert not (tmp_path / "artifacts/promotion.json").exists()


def test_quality_gate_validation_failure_cannot_promote(tmp_path):
    report = {"validation_passed": False, "metrics": {"f1": 1.0}, "model_path": "nonexistent"}
    with pytest.raises(ValueError, match="promotion blocked"):
        apply_quality_gate(report, tmp_path, 0.8)


def test_quality_gate_atomically_copies_passed_artifact(tmp_path):
    model = tmp_path / "candidate.joblib"
    model.write_bytes(b"a-real-artifact-test-double")
    report = {"validation_passed": True, "metrics": {"f1": 0.9}, "model_path": str(model)}
    result = apply_quality_gate(report, tmp_path / "artifacts", 0.8)
    assert (tmp_path / "artifacts/model.joblib").read_bytes() == model.read_bytes()
    assert result["quality_gate"] == "passed"
    assert json.loads((tmp_path / "artifacts/promotion.json").read_text())["f1_threshold"] == 0.8


def test_training_config_rejects_arbitrary_parameters():
    with pytest.raises(ValueError):
        TrainingConfig.model_validate({"shell": "arbitrary"})
