"""Airflow 3 SDK DAG; every worker mounts the same durable artifact volume."""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.sdk import dag, get_current_context, task

from agent.tools.airflow_tools import TrainingConf
from training.config import TrainingConfig
from training.evaluate import evaluate_model
from training.preprocess import preprocess_dataset
from training.quality_gate import apply_quality_gate
from training.train import train_model
from training.validate import validate_dataset

LOGGER = logging.getLogger(__name__)


def _context() -> tuple[Path, Path, TrainingConfig]:
    context = get_current_context()
    conf = TrainingConf.model_validate(context["dag_run"].conf or {})
    run_id = context["run_id"]
    # Airflow IDs contain colons and '+'. Hashing gives a portable, bounded path.
    import hashlib
    directory = hashlib.sha256(run_id.encode()).hexdigest()[:24]
    root = Path(os.environ.get("MLOPS_SHARED_DIR", "/workspace/shared/training")).resolve()
    work_dir = root / directory
    work_dir.mkdir(parents=True, exist_ok=True)
    dataset = Path(os.environ.get("MLOPS_DATASET_PATH", "/workspace/MLOPs-A3/data/dataset.csv"))
    return dataset, work_dir, TrainingConfig.model_validate(conf.model_dump())


@dag(
    dag_id="mlops_training",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(seconds=5)},
    tags=["mlops", "assignment-03"],
    description="Validate → preprocess → train → evaluate/MLflow → quality gate",
)
def training_pipeline():
    @task(task_id="validate_dataset")
    def validate():
        dataset, _, _ = _context()
        LOGGER.info("Validating configured dataset before any training")
        validate_dataset(dataset)

    @task(task_id="preprocess_data")
    def preprocess():
        dataset, work_dir, config = _context()
        LOGGER.info("Persisting deterministic split on the shared artifact volume")
        return preprocess_dataset(dataset, work_dir, config)

    @task(task_id="train_model")
    def train(split_path: str):
        _, work_dir, config = _context()
        LOGGER.info("Training model in durable run directory")
        return train_model(split_path, work_dir, config)

    @task(task_id="evaluate_and_log")
    def evaluate(split_path: str, model_path: str):
        _, work_dir, config = _context()
        LOGGER.info("Evaluating held-out split and recording MLflow lineage")
        return evaluate_model(
            split_path, model_path, work_dir,
            config, os.environ.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        )

    @task(task_id="quality_gate")
    def gate(report: dict):
        _, work_dir, config = _context()
        LOGGER.info("Checking quality gate; failure never creates a promotion manifest")
        return apply_quality_gate(report, work_dir, config.f1_threshold)

    validation = validate()
    preprocessing = preprocess()
    training = train(preprocessing)
    evaluation = evaluate(preprocessing, training)
    quality = gate(evaluation)
    validation >> preprocessing >> training >> evaluation >> quality


training_dag = training_pipeline()
