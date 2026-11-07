"""Dataset validation fails before preprocessing or model production."""

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from training.config import FEATURE_NAMES


def dataset_hash(path: str | Path) -> str:
    return hashlib.md5(Path(path).read_bytes(), usedforsecurity=False).hexdigest()


def validate_dataset(path: str | Path) -> dict:
    path = Path(path)
    frame = pd.read_csv(path)
    if list(frame.columns) != [*FEATURE_NAMES, "target"]:
        raise ValueError("dataset_schema_invalid")
    if len(frame) < 40 or frame.isna().any().any():
        raise ValueError("dataset_rows_or_missing_values_invalid")
    if not np.isfinite(frame.to_numpy(dtype=float)).all():
        raise ValueError("dataset_nonfinite_values")
    if set(frame["target"].unique()) != {0, 1}:
        raise ValueError("dataset_target_must_contain_two_binary_classes")
    if frame["target"].value_counts().min() < 10:
        raise ValueError("dataset_insufficient_class_samples")
    return {
        "validated": True,
        "rows": len(frame),
        "features": FEATURE_NAMES,
        "dataset_path": str(path),
        "dataset_hash": dataset_hash(path),
    }
