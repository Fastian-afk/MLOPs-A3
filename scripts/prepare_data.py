"""Generate the small public synthetic dataset deterministically, without network access."""

import argparse
from pathlib import Path

import pandas as pd
from sklearn.datasets import make_classification

from training.config import FEATURE_NAMES


def prepare(path: Path) -> None:
    x, y = make_classification(
        n_samples=400, n_features=8, n_informative=6, n_redundant=0, random_state=42, class_sep=1.5
    )
    frame = pd.DataFrame(x, columns=FEATURE_NAMES)
    frame["target"] = y
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10f", lineterminator="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/dataset.csv"))
    prepare(parser.parse_args().output)
