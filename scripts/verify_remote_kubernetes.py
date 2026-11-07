"""Export real, read-only remote Kubernetes evidence without exposing credentials.

Use --expect-deployed only when the inference workload has been deployed. This
command never applies manifests, changes RBAC, restarts workloads or injects a
failure. A reachable empty cluster is reported separately from a ready model.
"""

import argparse
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from agent.config import Settings
from agent.logging import redact
from agent.tools.kubernetes_tools import (
    DeploymentInput,
    KubernetesTools,
    ListInput,
    LogInput,
    PodInput,
    ServiceInput,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("evidence/kubernetes/remote_live.json"))
    parser.add_argument("--expect-deployed", action="store_true")
    args = parser.parse_args()
    settings = Settings()
    token = settings.kube_api_token.get_secret_value() if settings.kube_api_token else ""
    if not settings.kube_api_url or not token:
        parser.error("Configure MLOPS_KUBE_API_URL and the separate secure MLOPS_KUBE_API_TOKEN")
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("httpx").setLevel(logging.ERROR)
    adapter = KubernetesTools(
        namespace=settings.namespace,
        kube_api_url=settings.kube_api_url,
        kube_api_token=settings.kube_api_token,
        kube_ca_cert=settings.kube_ca_cert,
        http_timeout=settings.http_timeout,
    )
    evidence = {
        "timestamp": datetime.now(UTC).isoformat(),
        "scope": "Actual remote namespaced Kubernetes reads through verified HTTPS",
        "status": "BLOCKED",
        "api_host": urlsplit(settings.kube_api_url).hostname,
        "namespace": settings.namespace,
        "mutations_performed": False,
        "read_access_verified": False,
        "deployment_verified": False,
        "checks": [],
    }

    def export():
        clean = redact(evidence)
        # Defense in depth if an unexpected service reflects the request secret.
        serialized = json.dumps(clean, indent=2).replace(token, "[REDACTED]")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized + "\n")
        print("Evidence:", args.output, "status:", evidence["status"])

    # Inspect the actual HTTPS response before the SDK normalizes every upstream
    # HTTP 403 into an authorization exception. A policy denial is not a claim
    # about the token or Kubernetes state.
    try:
        start = time.monotonic()
        response = httpx.get(
            settings.kube_api_url + f"/api/v1/namespaces/{settings.namespace}/pods",
            headers={"Authorization": "Bearer " + token},
            timeout=settings.http_timeout,
        )
        evidence["preflight"] = {
            "authenticated": True,
            "method": "GET",
            "path": f"/api/v1/namespaces/{settings.namespace}/pods",
            "http_status": response.status_code,
            "server": response.headers.get("server"),
            "content_type": response.headers.get("content-type"),
            "duration_seconds": round(time.monotonic() - start, 3),
        }
        if (
            response.status_code == 403
            and response.headers.get("server", "").lower() == "envoy"
            and response.headers.get("content-type", "").startswith("text/plain")
            and response.text.strip() == "Your request was blocked."
        ):
            evidence["preflight"]["error_code"] = "KUBERNETES_NETWORK_POLICY_DENIED"
            evidence["preflight"]["sanitized_message"] = "Your request was blocked."
            evidence["limitation"] = (
                "An upstream HTTP policy denial prevented a Kubernetes response; "
                "token validity, resource state and deployment readiness remain unknown."
            )
            export()
            raise SystemExit(1)
    except httpx.HTTPError as exc:
        evidence["preflight"] = {"error_class": type(exc).__name__}
        evidence["limitation"] = "Remote HTTPS transport failed before a Kubernetes response was obtained."
        export()
        raise SystemExit(1) from None

    def call(name, handler, payload):
        start = time.monotonic()
        try:
            output = handler(payload)
            record = {"tool": "kubernetes." + name, "status": "ok", "data": output.model_dump(mode="json")}
        except Exception as exc:
            # No raw exception text, request headers, token or service body.
            code = str(exc).split(":", 1)[0]
            if code not in {"KUBERNETES_UNAVAILABLE", "AUTHENTICATION_FAILED", "FORBIDDEN", "NOT_FOUND"}:
                code = "REQUEST_FAILED"
            record = {
                "tool": "kubernetes." + name,
                "status": "error",
                "error_code": code,
                "http_status": getattr(exc.__cause__, "status", None),
                "error_class": type(exc).__name__,
            }
        record["duration_seconds"] = round(time.monotonic() - start, 3)
        evidence["checks"].append(record)
        print(record["tool"], record["status"], record.get("error_code", ""))
        return record

    pods = call("list_pods", adapter.list_pods, ListInput())
    if pods["status"] == "ok":
        deployments = call("list_deployments", adapter.list_deployments, ListInput())
        evidence["read_access_verified"] = deployments["status"] == "ok"
        if evidence["read_access_verified"]:
            evidence["status"] = "VERIFIED_REAL"
        if deployments.get("data", {}).get("deployments"):
            service = call("inspect_service", adapter.inspect_service, ServiceInput())
            version = call("deployment_version", adapter.deployment_version, DeploymentInput())
            evidence["deployment_verified"] = bool(
                version.get("data", {}).get("rollout_complete")
                and version.get("data", {}).get("deployment", {}).get("ready_replicas", 0) >= 2
                and len(service.get("data", {}).get("ready_addresses", [])) >= 2
            )
            for item in pods["data"]["pods"][:2]:
                name = item["name"]
                call("pod_health", adapter.pod_health, PodInput(pod=name))
                call("pod_events", adapter.pod_events, PodInput(pod=name))
                call("pod_logs", adapter.pod_logs, LogInput(pod=name, tail_lines=30))
        else:
            evidence["limitation"] = (
                "Authenticated cluster reads succeeded, but no inference Deployment was present."
            )
    else:
        # One independent no-credential request distinguishes a Kubernetes JSON
        # denial from an upstream policy/error page without dumping its contents.
        try:
            response = httpx.get(settings.kube_api_url + "/version", timeout=settings.http_timeout)
            diagnosis = {
                "authenticated": False,
                "path": "/version",
                "http_status": response.status_code,
                "server": response.headers.get("server"),
                "content_type": response.headers.get("content-type"),
            }
            if response.status_code == 403 and response.headers.get("content-type", "").startswith(
                "text/plain"
            ):
                diagnosis["classification"] = "NON_KUBERNETES_HTTP_DENIAL"
            evidence["transport_diagnosis"] = diagnosis
        except httpx.HTTPError as exc:
            evidence["transport_diagnosis"] = {"error_class": type(exc).__name__}
        evidence["limitation"] = (
            "No authenticated cluster result was obtained; token validity and cluster state remain unknown."
        )
    if args.expect_deployed and not evidence["deployment_verified"]:
        evidence["status"] = "BLOCKED"
    export()
    if not evidence["read_access_verified"] or (args.expect_deployed and not evidence["deployment_verified"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
