"""Evaluate holdout data and persist actual model and dataset lineage to MLflow."""

import json
import subprocess
import time
from pathlib import Path

import joblib
import yaml
from mlflow.entities import Metric, Param, RunTag
from mlflow.tracking import MlflowClient
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from training.config import TrainingConfig


def git_revision() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10,
    )
    if result.returncode:
        raise ValueError("training_requires_committed_git_revision")
    return result.stdout.strip()


def evaluate_model(
    split_path: str | Path, model_path: str | Path, work_dir: str | Path,
    config: TrainingConfig | None = None, tracking_uri: str = "http://127.0.0.1:5000",
) -> dict:
    config = config or TrainingConfig()
    split = joblib.load(split_path)
    bundle = joblib.load(model_path)
    # Do not mutate an upstream DVC stage output when adding evaluation lineage.
    model_path = Path(work_dir) / "evaluated.joblib"
    predictions = bundle["model"].predict(split["x_test"])
    metrics = {"f1": float(f1_score(split["y_test"], predictions, zero_division=0)),
               "precision": float(precision_score(split["y_test"], predictions, zero_division=0)),
               "recall": float(recall_score(split["y_test"], predictions, zero_division=0)),
               "accuracy": float(accuracy_score(split["y_test"], predictions))}
    root = Path(__file__).resolve().parents[1]
    dataset = Path(split["validation"]["dataset_path"]).resolve()
    dataset_path = dataset.relative_to(root).as_posix() if dataset.is_relative_to(root) else str(dataset)
    revision = git_revision()
    metadata = subprocess.run(
        ["git", "show", f"{revision}:{dataset_path}.dvc"], cwd=root,
        capture_output=True, text=True, timeout=10,
    )
    if metadata.returncode:
        raise ValueError("training_requires_committed_dvc_metadata")
    committed = yaml.safe_load(metadata.stdout)
    actual_hash = split["validation"]["dataset_hash"]
    if not committed.get("outs") or committed["outs"][0].get("md5") != actual_hash:
        raise ValueError("training_dataset_differs_from_committed_dvc_hash")
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "training", "scripts/prepare_data.py",
         "dvc.yaml", ".dvc/config", f"{dataset_path}.dvc"],
        cwd=root, capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
    provenance = {"dataset.path": dataset_path, "dataset.hash": actual_hash,
                  "dataset.git_revision": revision, "git.dirty": str(bool(dirty)).lower()}
    provenance["git.commit"] = provenance["dataset.git_revision"]
    client = MlflowClient(tracking_uri=tracking_uri)
    experiment = client.get_experiment_by_name(config.experiment_name)
    experiment_id = experiment.experiment_id if experiment else client.create_experiment(config.experiment_name)
    run = client.create_run(experiment_id, tags={**provenance,
        "evaluation.split": "stratified_holdout",
        "quality_gate.status": "passed" if metrics["f1"] >= config.f1_threshold else "failed",
        "dataset.validation": "passed"})
    run_id = run.info.run_id
    try:
        now = int(time.time() * 1000)
        client.log_batch(run_id, metrics=[Metric(k, v, now, 0) for k, v in metrics.items()],
                         params=[Param(k, str(v)) for k, v in config.model_dump().items()],
                         tags=[RunTag("model.version", run_id)])
        metadata = {"run_id": run_id, "version": run_id, "dataset_hash": provenance["dataset.hash"],
                    "git_commit": provenance["git.commit"], "provenance": provenance,
                    "metrics": metrics, "config": config.model_dump(), "evaluation_split": "stratified_holdout"}
        bundle["metadata"] = metadata
        output = Path(work_dir)
        output.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, model_path)
        metadata_path = output / "metadata.json"
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        client.log_artifact(run_id, str(model_path), "model")
        client.log_artifact(run_id, str(metadata_path), "model")
        client.set_terminated(run_id, "FINISHED")
    except Exception:
        client.set_terminated(run_id, "FAILED")
        raise
    report = {"run_id": run_id, "metrics": metrics, "provenance": provenance,
              "validation_passed": True, "model_path": str(model_path),
              "quality_gate": "passed" if metrics["f1"] >= config.f1_threshold else "failed"}
    (Path(work_dir) / "evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
