"""Inventory, secret-pattern and safety checks; does not replace pytest/live tests."""

import json
import re
import subprocess
from pathlib import Path

REQUIRED = [
    "agent/main.py",
    "agent/orchestrator.py",
    "agent/schemas.py",
    "agent/permissions.py",
    "agent/logging.py",
    "agent/tools/dvc_tools.py",
    "agent/tools/mlflow_tools.py",
    "agent/tools/airflow_tools.py",
    "agent/tools/kubernetes_tools.py",
    "api/main.py",
    "inference/main.py",
    "dags/training_pipeline.py",
    "training/train.py",
    "training/preprocess.py",
    "training/evaluate.py",
    "training/validate.py",
    "training/quality_gate.py",
    "kubernetes/deployment.yaml",
    "kubernetes/service.yaml",
    "kubernetes/configmap.yaml",
    "kubernetes/namespace.yaml",
    ".github/workflows/ci.yml",
    "Dockerfile",
    "Dockerfile.inference",
    "compose.yaml",
    "dvc.yaml",
    "pyproject.toml",
    "uv.lock",
    ".env.example",
    "README.md",
    "architecture.md",
    "TECHNICAL_REPORT.md",
    "DEMO_GUIDE.md",
    "RUBRIC_CHECKLIST.md",
    "LIMITATIONS.md",
    "scripts/bootstrap.sh",
    "scripts/smoke_test.sh",
    "scripts/demo_scenarios.py",
    "scripts/inject_failures.py",
]


def main():
    root = Path(__file__).resolve().parents[1]
    missing = [path for path in REQUIRED if not (root / path).is_file()]
    tracked = (
        subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
        .stdout.decode()
        .split("\0")
    )
    findings = []
    for name in filter(None, tracked):
        path = root / name
        if name == ".env" or name.startswith((".venv/", ".runtime/", "artifacts/", ".dvc/cache/")):
            findings.append(name + ": forbidden generated/secret path")
        if not path.is_file() or path.suffix in {".pdf", ".png"}:
            continue
        content = path.read_text(errors="replace")
        if re.search(
            r"(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{25,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
            content,
        ):
            findings.append(name + ": credential/private key pattern")
    result = {
        "missing_files": missing,
        "secret_scan_findings": findings,
        "tracked_file_count": len(list(filter(None, tracked))),
    }
    print(json.dumps(result, indent=2))
    if missing or findings:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
