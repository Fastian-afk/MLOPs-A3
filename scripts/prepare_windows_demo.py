"""Package the tiny, trusted quality-gated demo artifact with its real lineage.

This does not train a replacement model or rewrite its recorded source commit.
Never use this command on untrusted pickle/joblib uploads.
"""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

import joblib


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("artifacts/model.joblib"))
    parser.add_argument("--output", type=Path, default=Path("demo_artifacts"))
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    data = args.model.read_bytes()
    if len(data) > 1024 * 1024:
        raise SystemExit("Refusing to commit a large model; distribute it through DVC instead")
    bundle = joblib.load(args.model)
    metadata = bundle["metadata"]
    threshold = float(metadata["config"]["f1_threshold"])
    if float(metadata["metrics"]["f1"]) < threshold:
        raise SystemExit("Demo artifact does not pass its recorded quality threshold")
    args.output.mkdir(parents=True, exist_ok=True)
    destination = args.output / "model.joblib"
    if destination.exists() and destination.read_bytes() != data and not args.replace:
        raise SystemExit("Existing fixture differs; use --replace after reviewing the new artifact")
    if args.model.resolve() != destination.resolve():
        shutil.copyfile(args.model, destination)
    manifest = {
        "schema_version": 1,
        "artifact": "model.joblib",
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "run_id": metadata["run_id"],
        "training_git_commit": metadata["git_commit"],
        "dataset_hash": metadata["dataset_hash"],
        "feature_names": bundle["feature_names"],
        "metrics": metadata["metrics"],
        "quality_gate": {"threshold": threshold, "passed": True},
        "provenance": metadata["provenance"],
        "source": "Exact trusted artifacts/model.joblib produced by the recorded real training run",
    }
    (args.output / "metadata.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(
        json.dumps(
            {
                "fixture": str(destination),
                "size_bytes": len(data),
                "sha256": manifest["sha256"],
                "run_id": manifest["run_id"],
            }
        )
    )


if __name__ == "__main__":
    main()
