"""Only passing evaluated artifacts are promoted to the inference path."""

import json
import os
import shutil
from pathlib import Path


def apply_quality_gate(report: dict, work_dir: str | Path, threshold: float = 0.8) -> dict:
    if not 0 <= threshold <= 1:
        raise ValueError("quality_gate_threshold_invalid")
    passed = report.get("validation_passed") is True and report["metrics"]["f1"] >= threshold
    if not passed:
        raise ValueError("quality_gate_failed: promotion blocked")
    destination = Path(work_dir)
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(report["model_path"])
    model_path = destination / "model.joblib"
    temporary = destination / "model.joblib.tmp"
    if source.resolve() != model_path.resolve():
        shutil.copyfile(source, temporary)
        os.replace(temporary, model_path)
    manifest = {**report, "quality_gate": "passed", "f1_threshold": threshold,
                "model_path": str(model_path)}
    (destination / "promotion.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
