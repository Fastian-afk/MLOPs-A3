"""Exercise the real diagnostic adapter against explicitly mocked API responses."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import Mock

from agent.tools.kubernetes_tools import KubernetesTools, ServiceInput


def run_selector_fault() -> dict:
    core, apps = Mock(), Mock()
    adapter = KubernetesTools(core_api=core, apps_api=apps)

    def service(selector):
        return S(
            spec=S(
                type="ClusterIP",
                cluster_ip="10.96.0.10",
                selector=selector,
                ports=[S(port=80, target_port="http", protocol="TCP")],
            )
        )

    pod = S(metadata=S(name="mock-inference-1"))
    healthy_endpoints = S(subsets=[S(addresses=[S(ip="10.244.0.2")], not_ready_addresses=[])])
    core.read_namespaced_service.return_value = service({"app": "inference"})
    core.list_namespaced_pod.return_value = S(items=[pod])
    core.read_namespaced_endpoints.return_value = healthy_endpoints
    baseline = adapter.inspect_service(ServiceInput()).model_dump()

    core.read_namespaced_service.return_value = service({"app": "injected-wrong-selector"})
    core.list_namespaced_pod.return_value = S(items=[])
    core.read_namespaced_endpoints.return_value = S(subsets=[])
    failure = adapter.inspect_service(ServiceInput()).model_dump()
    assert len(failure["diagnoses"]) == 2
    assert failure["ready_addresses"] == []

    core.read_namespaced_service.return_value = service({"app": "inference"})
    core.list_namespaced_pod.return_value = S(items=[pod])
    core.read_namespaced_endpoints.return_value = healthy_endpoints
    recovered = adapter.inspect_service(ServiceInput()).model_dump()
    assert recovered["ready_addresses"] == baseline["ready_addresses"]
    assert recovered["diagnoses"] == []
    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "status": "VERIFIED_MOCKED",
        "environment": "unittest.mock Kubernetes API; no real cluster incident",
        "command": "python -m scripts.kubernetes_fault_demo",
        "injected_failure": "Service selector changed from app=inference to app=injected-wrong-selector",
        "root_cause": "Service selector matches no application Pods, producing no ready backend addresses",
        "corrective_action": "Restore selector app=inference and verify ready addresses return",
        "baseline": baseline,
        "failure": failure,
        "recovered": recovered,
        "checks": {"diagnosis_detected": True, "ready_endpoints_restored": True},
        "limitation": "API transport responses are mocked; real cluster reproduction remains BLOCKED",
    }


if __name__ == "__main__":
    result = run_selector_fault()
    path = Path("evidence/failures/kubernetes_selector_mocked.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"status": result["status"], "evidence": str(path)}))
