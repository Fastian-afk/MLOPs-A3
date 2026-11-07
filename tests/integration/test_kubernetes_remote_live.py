"""Opt-in real workload verification; an upstream denial must fail, never pass."""

import os

import httpx
import pytest

from agent.config import Settings
from agent.tools.kubernetes_tools import DeploymentInput, KubernetesTools, ListInput, ServiceInput

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_REMOTE_KUBERNETES") != "1",
        reason="Set RUN_INTEGRATION=1 and RUN_REMOTE_KUBERNETES=1 for the real configured remote cluster",
    ),
]


def test_real_remote_inference_has_two_ready_replicas_and_service_backends():
    settings = Settings()
    if not settings.kube_api_url or not settings.kube_api_token:
        pytest.skip("Remote Kubernetes URL/token are not configured")
    response = httpx.get(
        settings.kube_api_url + f"/api/v1/namespaces/{settings.namespace}/pods",
        headers={"Authorization": "Bearer " + settings.kube_api_token.get_secret_value()},
        timeout=settings.http_timeout,
    )
    if (
        response.status_code == 403
        and response.headers.get("server", "").lower() == "envoy"
        and response.headers.get("content-type", "").startswith("text/plain")
        and response.text.strip() == "Your request was blocked."
    ):
        pytest.fail("KUBERNETES_NETWORK_POLICY_DENIED: upstream transport blocked; no cluster result")
    assert response.status_code == 200, "Authenticated Kubernetes Pod read did not succeed"
    adapter = KubernetesTools(
        namespace=settings.namespace,
        kube_api_url=settings.kube_api_url,
        kube_api_token=settings.kube_api_token,
        kube_ca_cert=settings.kube_ca_cert,
        http_timeout=settings.http_timeout,
    )
    version = adapter.deployment_version(DeploymentInput())
    assert version.rollout_complete
    assert version.deployment.ready_replicas >= 2
    service = adapter.inspect_service(ServiceInput())
    assert len(service.ready_addresses) >= 2
    assert not service.diagnoses
    assert len([pod for pod in adapter.list_pods(ListInput()).pods if pod.ready]) >= 2
