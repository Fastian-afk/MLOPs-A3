"""Start the local development stack and reuse already healthy services.

Run bootstrap.sh and install_airflow.sh first. Credentials stay in .runtime.
This single-user helper uses the Airflow SimpleAuthManager development password.
--stop terminates only processes launched by this helper with matching start IDs.
"""

import argparse
import json
import os
import secrets
import signal
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"


def alive(pid: int, started: str) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[21] == started
    except (OSError, IndexError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    RUNTIME.mkdir(exist_ok=True)
    state_file = RUNTIME / "local-services.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    if args.stop:
        for name, item in state.items():
            if alive(item["pid"], item["started"]):
                os.killpg(item["pid"], signal.SIGTERM)
                print("Stopped", name)
        state_file.write_text("{}\n")
        return
    python = ROOT / ".venv/bin/python"
    if not python.exists():
        raise SystemExit("Run bash scripts/bootstrap.sh first")
    environment = os.environ.copy()
    environment["PATH"] = str(ROOT / ".venv/bin") + os.pathsep + environment.get("PATH", "")
    environment["DVC_SITE_CACHE_DIR"] = str(RUNTIME / "dvc-site")
    environment["DVC_NO_ANALYTICS"] = "1"
    environment["MLFLOW_TRACKING_URI"] = "http://127.0.0.1:5000"
    environment["MLOPS_MLFLOW_TRACKING_URI"] = environment["MLFLOW_TRACKING_URI"]
    environment["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "10"
    environment["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    environment["MLOPS_ROOT"] = str(ROOT)

    def healthy(url):
        try:
            return httpx.get(url, timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def start(name, command, env, url, wait=60):
        if healthy(url):
            print("Reusing healthy", name)
            return
        if name in state and alive(state[name]["pid"], state[name]["started"]):
            raise SystemExit(f"{name} is running but unhealthy; inspect .runtime/{name}.log")
        with (RUNTIME / f"{name}.log").open("a") as log:
            process = subprocess.Popen(
                command, cwd=ROOT, env=env, stdout=log, stderr=log, start_new_session=True
            )
        state[name] = {
            "pid": process.pid,
            "started": Path(f"/proc/{process.pid}/stat").read_text().split()[21],
        }
        state_file.write_text(json.dumps(state, indent=2) + "\n")
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            if healthy(url):
                print("Ready", name)
                return
            if process.poll() is not None:
                break
            time.sleep(1)
        raise SystemExit(
            f"{name} failed readiness; inspect .runtime/{name}.log (may contain local credentials)"
        )

    start(
        "mlflow",
        [
            str(ROOT / ".venv/bin/mlflow"),
            "server",
            "--host",
            "127.0.0.1",
            "--port",
            "5000",
            "--workers",
            "1",
            "--backend-store-uri",
            f"sqlite:///{RUNTIME}/mlflow.db",
            "--artifacts-destination",
            str(RUNTIME / "mlflow-store"),
        ],
        environment,
        "http://127.0.0.1:5000/health",
    )
    airflow_env = environment.copy()
    airflow_env["PATH"] = str(ROOT / ".venv-airflow/bin") + os.pathsep + environment["PATH"]
    if not (ROOT / ".venv-airflow/bin/airflow").is_file():
        raise SystemExit("Run bash scripts/install_airflow.sh before starting Airflow")
    start(
        "airflow",
        ["bash", "scripts/start_airflow.sh"],
        airflow_env,
        "http://127.0.0.1:8080/api/v2/monitor/health",
        120,
    )
    password_file = RUNTIME / "airflow/simple_auth_manager_passwords.json"
    if (
        password_file.is_file()
        and not environment.get("MLOPS_AIRFLOW_TOKEN")
        and not environment.get("MLOPS_AIRFLOW_PASSWORD")
    ):
        environment["MLOPS_AIRFLOW_PASSWORD"] = json.loads(password_file.read_text())["admin"]
    if not (ROOT / "artifacts/model.joblib").is_file():
        with (RUNTIME / "initial-training.log").open("w") as log:
            subprocess.run(
                [str(python), "-m", "training.train", "--runs", "5"],
                env=environment,
                cwd=ROOT,
                stdout=log,
                stderr=log,
                check=True,
                timeout=180,
            )
    token_file = RUNTIME / "agent.token"
    token = environment.get("MLOPS_API_TOKEN") or (
        token_file.read_text().strip() if token_file.exists() else secrets.token_urlsafe(32)
    )
    token_file.write_text(token + "\n")
    token_file.chmod(0o600)
    environment["MLOPS_API_TOKEN"] = token
    start(
        "agent",
        [str(python), "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"],
        environment,
        "http://127.0.0.1:8000/health",
    )
    start(
        "inference",
        [str(python), "-m", "uvicorn", "inference.main:app", "--host", "127.0.0.1", "--port", "8001"],
        environment,
        "http://127.0.0.1:8001/health/ready",
    )
    print(
        "Local services ready. Load MLOPS_API_TOKEN securely from .runtime/agent.token for smoke/demo commands."
    )
    print(
        "Kubernetes remains separately configured; this helper does not create a cluster or use an LLM key."
    )


if __name__ == "__main__":
    main()
