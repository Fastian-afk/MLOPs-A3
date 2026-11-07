"""Explicit operator-run Airflow verification; never called by an informational chat.

Run: python -m scripts.verify_airflow --confirm-trigger --output evidence/airflow/run.json
The password file is local runtime state, never part of the exported evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from agent.tools.airflow_tools import (
    AirflowTools,
    DiagnosticsInput,
    RunInput,
    TrainingConf,
    TriggerInput,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-trigger", action="store_true", required=True)
    parser.add_argument("--base-url", default=os.getenv("AIRFLOW_BASE_URL", "http://127.0.0.1:8080"))
    parser.add_argument(
        "--password-file", type=Path, default=Path(".runtime/airflow/simple_auth_manager_passwords.json")
    )
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--expect-state", choices=["success", "failed"], default="success")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    password = os.getenv("AIRFLOW_PASSWORD")
    username = os.getenv("AIRFLOW_USERNAME", "admin")
    if not os.getenv("AIRFLOW_TOKEN") and not password and args.password_file.is_file():
        password = json.loads(args.password_file.read_text())[username]
    adapter = AirflowTools(
        SimpleNamespace(
            airflow_base_url=args.base_url,
            airflow_token=os.getenv("AIRFLOW_TOKEN"),
            airflow_username=username,
            airflow_password=password,
            approved_dag_id="mlops_training",
            http_timeout=10,
        )
    )
    started = time.monotonic()
    result = adapter.trigger_training(TriggerInput(conf=TrainingConf(f1_threshold=args.threshold)))
    run_args = RunInput(run_id=result.run.dag_run_id)
    while not result.completed and time.monotonic() - started < args.timeout:
        time.sleep(2)
        result = adapter.run_status(run_args)
    diagnostics = []
    for task in result.tasks:
        if task.state in ("failed", "upstream_failed"):
            diagnostics.append(
                adapter.diagnostics(
                    DiagnosticsInput(
                        run_id=result.run.dag_run_id,
                        task_id=task.task_id,
                        try_number=max(task.try_number or 1, 1),
                    )
                ).model_dump()
            )
    run_directory = hashlib.sha256(result.run.dag_run_id.encode()).hexdigest()[:24]
    shared = Path(os.getenv("MLOPS_SHARED_DIR", ".runtime/training")) / run_directory
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "label": "VERIFIED_REAL",
        "command": "python -m scripts.verify_airflow --confirm-trigger",
        "explicit_operator_confirmation": True,
        "threshold": args.threshold,
        "duration_seconds": round(time.monotonic() - started, 3),
        "result": result.model_dump(),
        "diagnostics": diagnostics,
        "promotion_manifest_present": (shared / "promotion.json").is_file(),
        "expected_state": args.expect_state,
    }
    evaluation = shared / "evaluation.json"
    if evaluation.is_file():
        record["evaluation"] = json.loads(evaluation.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + "\n")
    print(
        json.dumps(
            {
                "run_id": result.run.dag_run_id,
                "state": result.run.state,
                "tasks": {task.task_id: task.state for task in result.tasks},
                "promotion_manifest_present": record["promotion_manifest_present"],
            },
            indent=2,
        )
    )
    if result.run.state != args.expect_state:
        raise SystemExit("airflow_run_did_not_reach_expected_state")
    if args.expect_state == "failed" and record["promotion_manifest_present"]:
        raise SystemExit("failed_run_created_promotion_manifest")


if __name__ == "__main__":
    main()
