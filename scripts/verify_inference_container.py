"""Build and verify a real Docker inference image, then inject a readiness fault.

This checks Docker containers, not Kubernetes. It removes every container it starts.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCKER = ["docker", "--host=unix:///var/run/docker.sock"]


def verify(image: str, build: bool = False) -> None:
    environment = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(key, None)
    commands: list[dict[str, Any]] = []
    containers: list[str] = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    timestamp = dt.datetime.now(dt.UTC).isoformat()
    record: dict[str, Any] = {
        "status": "FAILED",
        "timestamp": timestamp,
        "scope": "real Docker inference container",
        "image": image,
    }
    fault: dict[str, Any] = {
        "status": "FAILED",
        "timestamp": timestamp,
        "scope": "real Docker container; NOT a Kubernetes incident",
    }

    def docker(*arguments: str, timeout: int = 120) -> str:
        command = DOCKER + list(arguments)
        started = time.monotonic()
        process = subprocess.run(
            command, cwd=ROOT, env=environment, text=True, capture_output=True, timeout=timeout
        )
        commands.append(
            {
                "command": command,
                "exit_code": process.returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "stdout": process.stdout[-12000:],
                "stderr": process.stderr[-12000:],
            }
        )
        if process.returncode:
            raise RuntimeError(f"Docker command failed with exit code {process.returncode}")
        return process.stdout.strip()

    def request(port: int, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with opener.open(req, timeout=3) as response:
                return {"http_status": response.status, "body": json.load(response)}
        except urllib.error.HTTPError as error:
            return {"http_status": error.code, "body": json.load(error)}

    def start(name: str, bad_model: bool = False) -> int:
        arguments = [
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "-p",
            "127.0.0.1::8001",
        ]
        if bad_model:
            arguments += ["-e", "MODEL_PATH=/app/artifacts/deliberately-missing.joblib"]
        arguments.append(image)
        docker(*arguments)
        containers.append(name)
        binding = docker("port", name, "8001/tcp")
        port = int(binding.rsplit(":", 1)[1])
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            try:
                if request(port, "/health/live")["http_status"] == 200:
                    return port
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                pass
            time.sleep(0.25)
        raise RuntimeError("Inference container did not start within 40 seconds")

    try:
        if build:
            docker(
                "build",
                "--secret",
                "id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt",
                "-f",
                "Dockerfile.inference",
                "-t",
                image,
                ".",
                timeout=600,
            )
        record.update(
            image_id=docker("image", "inspect", "--format", "{{.Id}}", image),
            configured_user=docker("image", "inspect", "--format", "{{.Config.User}}", image),
            repository_digests=json.loads(
                docker("image", "inspect", "--format", "{{json .RepoDigests}}", image)
            ),
        )
        artifact_details = json.loads(
            docker(
                "run",
                "--rm",
                "--read-only",
                "--entrypoint",
                "python",
                image,
                "-c",
                "import hashlib,json,joblib; from pathlib import Path; p=Path('/app/artifacts/model.joblib'); "
                "print(json.dumps({'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'metadata':joblib.load(p)['metadata']}))",
            )
        )
        record["artifact_sha256"] = artifact_details["sha256"]
        record["artifact_metadata"] = artifact_details["metadata"]
        assert (
            record["artifact_sha256"]
            == hashlib.sha256((ROOT / "artifacts/model.joblib").read_bytes()).hexdigest()
        )
        record["provenance_note"] = (
            "The model preserves its actual training Git SHA and git.dirty tag. Later repository commits do not change that recorded training source state."
        )
        assert record["configured_user"] == "10001:10001", "Image must run as a non-root user"
        with (ROOT / "data/dataset.csv").open() as handle:
            row = next(csv.DictReader(handle))
        payload = {"instances": [[float(row[f"feature_{index}"]) for index in range(8)]]}
        suffix = str(time.time_ns())
        name = "mlops-inference-verify-" + suffix
        port = start(name)
        record["checks"] = {
            "live": request(port, "/health/live"),
            "ready": request(port, "/health/ready"),
            "version": request(port, "/version"),
            "predict": request(port, "/predict", payload),
            "invalid_payload": request(port, "/predict", {"instances": [[1.0, 2.0]]}),
        }
        for key in ("live", "ready", "version", "predict"):
            assert record["checks"][key]["http_status"] == 200
        assert record["checks"]["invalid_payload"]["http_status"] == 422
        version = record["checks"]["version"]["body"]
        prediction = record["checks"]["predict"]["body"]
        assert version["ready"] and version["run_id"] and version["git_commit"] and version["dataset_hash"]
        assert prediction["run_id"] == version["run_id"]
        assert len(prediction["predictions"]) == 1 and len(prediction["probabilities"][0]) == 2
        assert abs(sum(prediction["probabilities"][0]) - 1.0) < 1e-8
        docker("rm", "-f", name)
        containers.remove(name)

        bad_name = "mlops-inference-fault-" + suffix
        bad_port = start(bad_name, bad_model=True)
        fault["injected_fault"] = (
            "MODEL_PATH points to an absent artifact in a real read-only Docker container"
        )
        fault["failed_checks"] = {
            "live": request(bad_port, "/health/live"),
            "ready": request(bad_port, "/health/ready"),
            "predict": request(bad_port, "/predict", payload),
            "version": request(bad_port, "/version"),
        }
        assert fault["failed_checks"]["live"]["http_status"] == 200
        assert fault["failed_checks"]["ready"]["http_status"] == 503
        assert fault["failed_checks"]["predict"]["http_status"] == 503
        assert fault["failed_checks"]["version"]["body"]["ready"] is False
        docker("logs", bad_name)
        fault["logs"] = commands[-1]["stdout"] + commands[-1]["stderr"]
        fault["diagnosis"] = (
            "The process remains live, but the model artifact cannot be loaded. Readiness and prediction return MODEL_NOT_READY instead of serving invalid predictions."
        )
        docker("rm", "-f", bad_name)
        containers.remove(bad_name)
        recovered_name = "mlops-inference-recovery-" + suffix
        recovered_port = start(recovered_name)
        fault["corrective_action"] = (
            "Recreate the container from the same immutable image without overriding the bundled valid model path"
        )
        fault["recovery_checks"] = {
            "ready": request(recovered_port, "/health/ready"),
            "predict": request(recovered_port, "/predict", payload),
            "version": request(recovered_port, "/version"),
        }
        assert all(value["http_status"] == 200 for value in fault["recovery_checks"].values())
        assert fault["recovery_checks"]["version"]["body"]["run_id"] == version["run_id"]
        record["status"] = "VERIFIED_REAL"
        fault["status"] = "VERIFIED_REAL"
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)
        fault["error"] = record["error"]
        raise
    finally:
        for name in containers:
            try:
                docker("rm", "-f", name)
            except Exception:
                pass
        record["commands"] = commands
        record["containers_cleaned"] = all(
            command["exit_code"] == 0 for command in commands if command["command"][2:4] == ["rm", "-f"]
        )
        fault["image"] = image
        fault["image_id"] = record.get("image_id")
        fault["containers_cleaned"] = record["containers_cleaned"]
        for path, content in [
            (ROOT / "evidence/kubernetes/inference_container.json", record),
            (ROOT / "evidence/failures/inference_readiness_real.json", fault),
        ]:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--build", action="store_true")
    arguments = parser.parse_args()
    verify(arguments.image, arguments.build)
