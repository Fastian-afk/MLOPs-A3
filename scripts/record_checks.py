"""Run CI-equivalent checks and record exact commands, exits and durations."""

import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    commands = [
        [".venv/bin/ruff", "check", "."],
        [".venv/bin/mypy"],
        [".venv/bin/python", "-m", "pytest", "-q", "tests/unit"],
        [".venv/bin/python", "scripts/verify_submission.py"],
        [".venv/bin/python", "-m", "pytest", "-q", "tests/integration"],
        [".venv/bin/python", "-m", "pytest", "-q", "tests/e2e"],
    ]
    environment = os.environ.copy()
    environment["RUN_INTEGRATION"] = "1"
    password = root / ".runtime/airflow/simple_auth_manager_passwords.json"
    if password.exists():
        environment["MLOPS_AIRFLOW_PASSWORD"] = json.loads(password.read_text())["admin"]
    token_file = root / ".runtime/agent.token"
    if token_file.exists():
        environment["MLOPS_API_TOKEN"] = token_file.read_text().strip()
    records = []
    for command in commands:
        start = time.monotonic()
        result = subprocess.run(command, capture_output=True, text=True, env=environment, timeout=180)
        record = {
            "command": command,
            "timestamp": datetime.now(UTC).isoformat(),
            "exit_code": result.returncode,
            "duration_seconds": round(time.monotonic() - start, 3),
            "output": result.stdout + result.stderr,
            "status": "VERIFIED_MOCKED" if "tests/unit" in command else "VERIFIED_REAL",
        }
        if result.returncode:
            record["status"] = "FAILED"
        records.append(record)
        print(" ".join(command), "->", result.returncode)
    path = root / "evidence/validation.json"
    path.write_text(json.dumps(records, indent=2) + "\n")
    if any(record["exit_code"] for record in records):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
