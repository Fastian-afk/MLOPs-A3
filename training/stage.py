"""Small stage CLI used by the real DVC pipeline."""

import argparse
import json
import os
from pathlib import Path

from training.config import TrainingConfig
from training.evaluate import evaluate_model
from training.preprocess import preprocess_dataset
from training.quality_gate import apply_quality_gate
from training.train import train_model
from training.validate import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["validate", "preprocess", "train", "evaluate", "gate"])
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.csv"))
    parser.add_argument("--work-dir", type=Path, default=Path(".runtime/dvc"))
    parser.add_argument("--config", type=Path, default=Path("training/config.json"))
    args = parser.parse_args()
    config = TrainingConfig.model_validate_json(args.config.read_text())
    work = args.work_dir
    work.mkdir(parents=True, exist_ok=True)
    if args.stage == "validate":
        (work / "validation.json").write_text(json.dumps(validate_dataset(args.dataset), indent=2) + "\n")
    elif args.stage == "preprocess":
        preprocess_dataset(args.dataset, work, config)
    elif args.stage == "train":
        train_model(work / "split.joblib", work, config)
    elif args.stage == "evaluate":
        evaluate_model(work / "split.joblib", work / "candidate.joblib", work, config,
                       os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    else:
        apply_quality_gate(json.loads((work / "evaluation.json").read_text()), "artifacts", config.f1_threshold)


if __name__ == "__main__":
    main()
