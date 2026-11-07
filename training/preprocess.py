"""Prepare a deterministic stratified split without fitting on test data."""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.model_selection import train_test_split

from training.config import FEATURE_NAMES, TrainingConfig
from training.validate import validate_dataset


def preprocess_dataset(path: str | Path, work_dir: str | Path, config: TrainingConfig | None = None) -> str:
    config = config or TrainingConfig()
    validation = validate_dataset(path)
    frame = pd.read_csv(path)
    x_train, x_test, y_train, y_test = train_test_split(
        frame[FEATURE_NAMES],
        frame["target"],
        test_size=config.test_size,
        random_state=config.seed,
        stratify=frame["target"],
    )
    output = Path(work_dir)
    output.mkdir(parents=True, exist_ok=True)
    split_path = output / "split.joblib"
    joblib.dump(
        {
            "x_train": x_train,
            "x_test": x_test,
            "y_train": y_train,
            "y_test": y_test,
            "validation": validation,
            "config": config.model_dump(),
        },
        split_path,
    )
    return str(split_path)
