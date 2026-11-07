"""Record five conversations against the real API; a blocked tool stays blocked.

Use --confirm-training to explicitly authorize the demonstration trigger. No
Kubernetes state is changed. Credentials/tokens are removed from saved transcripts.
"""

import argparse
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from agent.config import Settings
from agent.logging import redact
from agent.tools.airflow_tools import AirflowTools, RunInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--confirm-training", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("MLOPS_API_TOKEN")
    if not token:
        parser.error("Set MLOPS_API_TOKEN securely")
    client = httpx.Client(base_url=args.url, headers={"Authorization": "Bearer " + token}, timeout=120)
    settings = Settings()
    local_password = Path(".runtime/airflow/simple_auth_manager_passwords.json")
    if (
        not settings.airflow_token
        and not settings.airflow_password
        and local_password.is_file()
        and settings.airflow_base_url in {"http://127.0.0.1:8080", "http://localhost:8080"}
    ):
        settings.airflow_password = json.loads(local_password.read_text())["admin"]
    from mlflow.tracking import MlflowClient

    tracking = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    experiment = tracking.get_experiment_by_name(settings.experiment_name)
    runs = (
        tracking.search_runs([experiment.experiment_id], order_by=["start_time DESC"], max_results=100)
        if experiment
        else []
    )
    run = next((r for r in runs if r.info.status == "FINISHED" and "f1" in r.data.metrics), None)
    if not run:
        raise SystemExit("Record real training runs first; no invented run ID is substituted")
    scenarios = [
        (
            "dataset_provenance",
            f"Which dataset version was used for experiment {run.info.run_id}, and how can I reproduce it?",
        ),
        ("model_selection", "Compare the latest five runs by F1 and recommend the best candidate."),
        ("pipeline_execution", "Trigger the approved training DAG"),
        ("deployment_diagnosis", "Why is my prediction API unavailable?"),
        (
            "integrated",
            "Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary.",
        ),
    ]
    directory = Path("evidence/conversations")
    directory.mkdir(parents=True, exist_ok=True)
    for index, (name, question) in enumerate(scenarios, 1):
        response = client.post("/agent/chat", json={"message": question, "session_id": f"demo-{index}"})
        response.raise_for_status()
        result = response.json()
        turns = [{"user": question, "agent": result}]
        if index == 3 and args.confirm_training and result["proposed_actions"]:
            confirmation = result["proposed_actions"][0]["confirmation_token"]
            reply = client.post(
                "/agent/chat",
                json={
                    "message": "Confirm training",
                    "session_id": f"demo-{index}",
                    "confirmation_token": confirmation,
                },
            )
            reply.raise_for_status()
            confirmed = reply.json()
            turns.append({"user": "Confirm exact proposed training action", "agent": confirmed})
            evidence = confirmed.get("evidence", [])
            if evidence and evidence[0]["status"] == "ok":
                run_id = evidence[0]["data"]["run"]["dag_run_id"]
                airflow = AirflowTools(settings)
                status = None
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    status = airflow.run_status(RunInput(run_id=run_id))
                    if status.completed:
                        break
                    time.sleep(2)
                turns.append(
                    {
                        "source": "authenticated Airflow3 /api/v2 polling",
                        "actual_status": status.model_dump(mode="json") if status else None,
                    }
                )
        if index == 5:
            assert "airflow.trigger_training" not in result["selected_tools"]
            assert not result["proposed_actions"]
            assert {name.split(".")[0] for name in result["selected_tools"]} >= {
                "mlflow",
                "dvc",
                "kubernetes",
                "airflow",
            }
        errors = [e for t in turns for e in t.get("agent", {}).get("evidence", []) if e["status"] != "ok"]
        label = "BLOCKED" if errors else "VERIFIED_REAL"
        if index == 3:
            polled = next((t["actual_status"] for t in turns if "actual_status" in t), None)
            if not polled or not polled.get("completed"):
                label = "BLOCKED"
            elif not polled.get("succeeded"):
                label = "FAILED"
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "environment": "actual local services; Kubernetes may be blocked",
            "status": label,
            "planner": settings.planner,
            "turns": redact(turns),
        }
        (directory / f"{index:02d}_{name}.json").write_text(json.dumps(record, indent=2) + "\n")
        print(name, record["status"])


if __name__ == "__main__":
    main()
