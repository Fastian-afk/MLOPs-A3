"""Record a real Groq-planned read-only investigation using configured credentials."""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from agent.config import Settings
from agent.orchestrator import Orchestrator
from agent.registry import build_registry
from agent.schemas import ChatRequest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Explicit available Groq model override; no automatic fallback")
    parser.add_argument("--scenario", choices=["selection", "integrated"], default="selection")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("DVC_SITE_CACHE_DIR", str(root / ".runtime/dvc-site"))
    settings = Settings(planner="groq", **({"groq_model": args.model} if args.model else {}))
    if not settings.groq_api_key:
        parser.error("Supply MLOPS_GROQ_API_KEY securely in environment settings")
    password_file = root / ".runtime/airflow/simple_auth_manager_passwords.json"
    if (
        not settings.airflow_password
        and not settings.airflow_token
        and password_file.exists()
        and settings.airflow_base_url == "http://127.0.0.1:8080"
    ):
        settings.airflow_password = json.loads(password_file.read_text())["admin"]
    question = (
        "Compare the latest five runs by F1 and recommend the best candidate."
        if args.scenario == "selection"
        else "Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary."
    )
    start = time.monotonic()
    result = asyncio.run(
        Orchestrator(settings, build_registry(settings)).chat(
            ChatRequest(message=question, session_id="groq-verification")
        )
    )
    provider_success = bool(
        result.provider_trace and not result.provider_trace.error_code and result.provider_trace.planned_steps
    )
    selected = next((e for e in result.evidence if e.tool == "mlflow.best_run" and e.status == "ok"), None)
    selection_success = bool(
        selected and selected.data.get("best_run") and len(selected.data.get("candidates", [])) >= 5
    )
    required_modules = {e.tool.split(".")[0] for e in result.evidence}
    functional_success = (
        provider_success
        and selection_success
        and (args.scenario == "selection" or required_modules >= {"mlflow", "dvc", "airflow", "kubernetes"})
    )
    all_success = all(e.status == "ok" for e in result.evidence)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "actual Groq provider with actual adapters",
        "status": "VERIFIED_REAL"
        if functional_success and all_success
        else "BLOCKED"
        if functional_success
        else "FAILED",
        "duration_seconds": round(time.monotonic() - start, 3),
        "question": question,
        "provider_success": provider_success,
        "functional_success": functional_success,
        "all_adapters_success": all_success,
        "response": result.model_dump(mode="json"),
    }
    output = args.output or root / "evidence/groq" / f"{args.scenario}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2) + "\n")
    print("Groq provider:", record["status"], "all adapters successful:", record["all_adapters_success"])
    print("Evidence:", str(output))
    if not functional_success or not all_success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
