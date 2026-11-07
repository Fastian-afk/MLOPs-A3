"""Verify agent image startup, bearer authentication and typed tool registration.

This smoke test uses no external infrastructure credentials and removes its container.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def verify(image: str, docker_host: str = "unix:///var/run/docker.sock") -> None:
    environment = os.environ.copy()
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
        environment.pop(key, None)
    ephemeral_token = secrets.token_hex(32)
    environment["MLOPS_API_TOKEN"] = ephemeral_token
    commands: list[dict[str, Any]] = []
    container = "mlops-agent-smoke-" + str(time.time_ns())
    started_container = False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    record: dict[str, Any] = {
        "timestamp": dt.datetime.now(dt.UTC).isoformat(),
        "status": "FAILED",
        "scope": "real Docker agent startup/authentication/tool-registration smoke; external services unconfigured",
        "image": image,
    }

    def docker(*arguments: str) -> str:
        command = ["docker", "--host=" + docker_host, *arguments]
        started = time.monotonic()
        process = subprocess.run(
            command, cwd=ROOT, env=environment, text=True, capture_output=True, timeout=120
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

    def request(port: int, path: str, *, authenticated: bool = False) -> dict[str, Any]:
        headers = {"Authorization": "Bearer " + ephemeral_token} if authenticated else {}
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", headers=headers)
        try:
            with opener.open(req, timeout=3) as response:
                return {"http_status": response.status, "body": json.load(response)}
        except urllib.error.HTTPError as error:
            return {"http_status": error.code, "body": json.load(error)}

    try:
        identity = docker("image", "inspect", "--format", "{{.Id}} {{.Config.User}}", image)
        image_id, user = identity.split()
        assert user and user not in ("0", "root", "0:0"), "Agent image must run as a non-root user"
        record.update(image_id=image_id, configured_user=user)
        docker(
            "run",
            "-d",
            "--name",
            container,
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=32m",
            "--security-opt",
            "no-new-privileges",
            "--cap-drop",
            "ALL",
            "--env",
            "MLOPS_API_TOKEN",
            "-p",
            "127.0.0.1::8000",
            image,
        )
        started_container = True
        port = int(docker("port", container, "8000/tcp").rsplit(":", 1)[1])
        deadline = time.monotonic() + 45
        while True:
            try:
                health = request(port, "/health")
                if health["http_status"] == 200:
                    break
            except (urllib.error.URLError, ConnectionError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("Agent container did not become healthy within 45 seconds") from None
            time.sleep(0.25)
        denied = request(port, "/agent/tools")
        authorized = request(port, "/agent/tools", authenticated=True)
        assert health["body"]["status"] == "ok"
        assert health["body"]["authentication_configured"] is True
        assert denied["http_status"] == 401
        assert authorized["http_status"] == 200
        tools = authorized["body"]
        assert len(tools) >= 12
        assert {tool["name"].split(".")[0] for tool in tools} == {"dvc", "mlflow", "airflow", "kubernetes"}
        assert all(tool["input_schema"] and tool["output_schema"] and tool["timeout"] > 0 for tool in tools)
        assert all(tool["permission"] == "read" for tool in tools if tool["name"].startswith("kubernetes."))
        record.update(
            status="VERIFIED_REAL",
            health=health,
            unauthenticated_tools=denied,
            registered_tool_count=len(tools),
            registered_tools=tools,
            external_service_claims="None: service startup and schema registration only",
        )
    except Exception as error:
        record["error"] = type(error).__name__ + ": " + str(error)
        if started_container:
            try:
                docker("logs", container)
            except Exception:
                pass
        raise
    finally:
        if started_container:
            docker("rm", "-f", container)
        record["container_cleaned"] = started_container and commands[-1]["exit_code"] == 0
        record["commands"] = commands
        path = ROOT / "evidence/runtime/app_container_smoke.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(record, indent=2) + "\n"
        assert ephemeral_token not in text, "Ephemeral authentication token must never be written to evidence"
        path.write_text(text)
    print(
        json.dumps(
            {
                "status": record["status"],
                "registered_tools": record["registered_tool_count"],
                "image_id": record["image_id"],
            }
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="mlops-agent:dev")
    parser.add_argument("--docker-host", default="unix:///var/run/docker.sock")
    args = parser.parse_args()
    verify(args.image, args.docker_host)
