from types import SimpleNamespace as S
from unittest.mock import Mock

import pytest

from agent.tools.kubernetes_tools import (
    DeploymentInput,
    KubernetesTools,
    ListInput,
    LogInput,
    PodInput,
    ServiceInput,
    register,
)


def pod(*, ready=True, phase="Running", restarts=0, reason=None):
    return S(
        metadata=S(name="inference-abc", namespace="mlops"),
        spec=S(node_name="node-1"),
        status=S(
            phase=phase,
            conditions=[S(type="Ready", status="True" if ready else "False")],
            container_statuses=[
                S(
                    name="inference",
                    ready=ready,
                    restart_count=restarts,
                    state=S(waiting=S(reason=reason) if reason else None),
                    last_state=S(terminated=None),
                )
            ],
        ),
    )


@pytest.fixture
def clients():
    core, apps = Mock(), Mock()
    return core, apps, KubernetesTools(core_api=core, apps_api=apps)


def test_forbidden_namespace_is_rejected_before_any_api_request(clients):
    core, _, tools = clients
    with pytest.raises(PermissionError, match="NAMESPACE_FORBIDDEN"):
        tools.list_pods(ListInput(namespace="kube-system"))
    core.list_namespaced_pod.assert_not_called()


def test_empty_pod_response_is_not_reported_as_healthy(clients):
    core, _, tools = clients
    core.list_namespaced_pod.return_value = S(items=[], metadata=S(_continue=None))
    result = tools.list_pods(ListInput())
    assert result.pods == []
    assert result.namespace == "mlops"


def test_pod_health_reports_restart_and_image_pull_diagnoses(clients):
    core, _, tools = clients
    core.read_namespaced_pod.return_value = pod(
        ready=False, phase="Pending", restarts=4, reason="ImagePullBackOff"
    )
    result = tools.pod_health(PodInput(pod="inference-abc"))
    assert not result.ready
    assert result.restart_count == 4
    assert any("ImagePullBackOff" in d for d in result.diagnoses)
    assert any("Pending" in d for d in result.diagnoses)


def test_service_selector_mismatch_and_empty_endpoints_diagnosed(clients):
    core, _, tools = clients
    core.read_namespaced_service.return_value = S(
        spec=S(
            type="ClusterIP",
            cluster_ip="10.96.0.3",
            selector={"app": "wrong"},
            ports=[S(port=80, target_port="http", protocol="TCP")],
        )
    )
    core.list_namespaced_pod.return_value = S(items=[])
    core.read_namespaced_endpoints.return_value = S(subsets=[])
    result = tools.inspect_service(ServiceInput())
    assert result.matching_pods == []
    assert len(result.diagnoses) == 2
    assert "selector mismatch" in result.diagnoses[0]
    core.list_namespaced_pod.assert_called_once_with(
        "mlops", label_selector="app=wrong", limit=200, _request_timeout=10
    )


def test_kubernetes_auth_error_is_sanitized(clients):
    core, _, tools = clients
    failure = RuntimeError("Authorization: Bearer sensitive-value")
    failure.status = 403
    core.read_namespaced_pod.side_effect = failure
    with pytest.raises(RuntimeError, match="FORBIDDEN") as error:
        tools.pod_health(PodInput(pod="inference-abc"))
    assert "sensitive-value" not in str(error.value)


def test_pod_logs_are_bounded_and_redacted(clients):
    core, _, tools = clients
    core.read_namespaced_pod_log.return_value = (
        "startup token=supersecret password=hunter2\nAuthorization: Bearer confidential-token\nready"
    )
    result = tools.pod_logs(LogInput(pod="inference-abc", tail_lines=20))
    assert result.redacted
    assert "supersecret" not in result.logs
    assert "hunter2" not in result.logs
    assert "confidential-token" not in result.logs
    assert core.read_namespaced_pod_log.call_args.kwargs["limit_bytes"] == 30000


def test_deployment_version_does_not_overstate_partial_rollout(clients):
    _, apps, tools = clients
    apps.read_namespaced_deployment.return_value = S(
        metadata=S(name="inference", namespace="mlops", generation=2),
        spec=S(
            replicas=2,
            template=S(
                metadata=S(labels={"app": "inference"}, annotations={"mlops.model-run-id": "run-123"}),
                spec=S(containers=[S(image="inference:sha", env=[])]),
            ),
        ),
        status=S(
            ready_replicas=1,
            available_replicas=1,
            updated_replicas=2,
            observed_generation=2,
            conditions=[S(type="Available", status="False")],
        ),
    )
    result = tools.deployment_version(DeploymentInput())
    assert result.model_run_id == "run-123"
    assert not result.rollout_complete
    assert result.deployment.images == ["inference:sha"]


def test_registry_exposes_only_read_permissions_and_no_mutation():
    registry = Mock()
    settings = S(namespace="mlops", kubeconfig=None, kube_context=None, http_timeout=10)
    register(registry, settings)
    assert registry.add.call_count == 7
    assert all(c.kwargs["permission"] == "read" for c in registry.add.call_args_list)
    assert not any("restart" in c.args[0] for c in registry.add.call_args_list)


def test_invalid_pod_cannot_inject_field_selectors():
    with pytest.raises(ValueError):
        PodInput(pod="pod-1,involvedObject.namespace=other")
