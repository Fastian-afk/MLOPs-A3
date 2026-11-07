"""Train real deterministic classifiers; CLI records five runs and promotes the best."""

import argparse
import json
import os
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from training.config import FEATURE_NAMES, TrainingConfig


def train_model(
    split_path: str | Path, work_dir: str | Path, config: TrainingConfig | None = None
) -> str:
    config = config or TrainingConfig()
    split = joblib.load(split_path)
    model = Pipeline([("scale", StandardScaler()), ("classifier", LogisticRegression(
        C=config.c, random_state=config.seed, max_iter=1000,
    ))])
    model.fit(split["x_train"], split["y_train"])
    output = Path(work_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "candidate.joblib"
    joblib.dump({"model": model, "feature_names": FEATURE_NAMES,
                 "metadata": {"config": config.model_dump(),
                              "dataset_hash": split["validation"]["dataset_hash"]}}, path)
    return str(path)


def main() -> None:
    from training.evaluate import evaluate_model
    from training.preprocess import preprocess_dataset
    from training.quality_gate import apply_quality_gate

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/dataset.csv"))
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--work-dir", type=Path, default=Path(".runtime/training"))
    parser.add_argument("--tracking-uri", default=os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000"))
    parser.add_argument("--runs", type=int, choices=range(1, 6), default=5)
    parser.add_argument("--threshold", type=float, default=0.8)
    args = parser.parse_args()
    reports = []
    for index, c in enumerate([0.01, 0.1, 1.0, 10.0, 100.0][:args.runs]):
        config = TrainingConfig(c=c, f1_threshold=args.threshold)
        run_dir = args.work_dir / f"candidate-{index}"
        split = preprocess_dataset(args.dataset, run_dir, config)
        model = train_model(split, run_dir, config)
        reports.append(evaluate_model(split, model, run_dir, config, args.tracking_uri))
    best = sorted(reports, key=lambda report: (-report["metrics"]["f1"], report["run_id"]))[0]
    promoted = apply_quality_gate(best, args.artifact_dir, args.threshold)
    print(json.dumps({"runs": reports, "promoted": promoted}, indent=2))


if __name__ == "__main__":
    main()
