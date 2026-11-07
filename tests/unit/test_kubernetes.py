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


def test_remote_https_uses_isolated_verified_client_and_inherited_proxy(monkeypatch, tmp_path, caplog):
    from kubernetes import client, config

    certificate = tmp_path / "combined-public-ca.pem"
    certificate.write_text("public CA fixture")
    monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    monkeypatch.setenv("HTTPS_PROXY", "http://managed-proxy:8080")
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
    monkeypatch.delenv("no_proxy", raising=False)
    api_client = Mock()
    constructor = Mock(return_value=api_client)
    core_constructor, apps_constructor = Mock(), Mock()
    monkeypatch.setattr(client, "ApiClient", constructor)
    monkeypatch.setattr(client, "CoreV1Api", core_constructor)
    monkeypatch.setattr(client, "AppsV1Api", apps_constructor)
    global_config = Mock()
    monkeypatch.setattr(config, "load_kube_config", global_config)
    tools = KubernetesTools(kube_api_url="https://demo.example.test/", kube_api_token="read-only-test-token")
    tools._clients()
    configuration = constructor.call_args.kwargs["configuration"]
    assert configuration.host == "https://demo.example.test"
    assert configuration.verify_ssl is True
    assert configuration.debug is False
    assert configuration.ssl_ca_cert == str(certificate)
    assert configuration.proxy == "http://managed-proxy:8080"
    assert configuration.no_proxy == "localhost,127.0.0.1"
    assert configuration.auth_settings()["BearerToken"]["value"] == "Bearer read-only-test-token"
    core_constructor.assert_called_once_with(api_client=api_client)
    apps_constructor.assert_called_once_with(api_client=api_client)
    global_config.assert_not_called()
    assert "read-only-test-token" not in caplog.text


def test_remote_token_is_required_before_client_creation(monkeypatch):
    from kubernetes import client

    constructor = Mock()
    monkeypatch.setattr(client, "ApiClient", constructor)
    with pytest.raises(RuntimeError, match="AUTHENTICATION_MISSING"):
        KubernetesTools(kube_api_url="https://demo.example.test")._clients()
    constructor.assert_not_called()


def test_remote_explicit_ca_must_exist(monkeypatch):
    from kubernetes import client

    constructor = Mock()
    monkeypatch.setattr(client, "ApiClient", constructor)
    with pytest.raises(RuntimeError, match="CA_UNAVAILABLE"):
        KubernetesTools(
            kube_api_url="https://demo.example.test",
            kube_api_token="fixture-token",
            kube_ca_cert="/missing/public-ca.pem",
        )._clients()
    constructor.assert_not_called()


@pytest.mark.parametrize(
    "url",
    [
        "http://demo.example.test",
        "https://user:secret@demo.example.test",
        "https://demo.example.test/api",
        "https://demo.example.test?token=secret",
        "https://demo.example.test#fragment",
        "https://demo.example.test:99999",
        "https://demo.example.test:0",
        "https://*.example.test",
        "https://demo.example.test/\\elsewhere",
        "https://demo.example.test\n",
    ],
)
def test_remote_api_rejects_invalid_origins(url):
    from agent.config import Settings

    with pytest.raises(ValueError):
        Settings(kube_api_url=url)
    with pytest.raises(ValueError):
        KubernetesTools(kube_api_url=url)


def test_remote_settings_keep_token_secret_and_private_https_origins_supported():
    from agent.config import Settings

    settings = Settings(kube_api_url="https://100.100.100.1:6443/", kube_api_token="fixture-private-token")
    assert settings.kube_api_url == "https://100.100.100.1:6443"
    assert "fixture-private-token" not in repr(settings)
    with pytest.raises(ValueError) as error:
        Settings(kube_api_url="https://user:fixture-private-token@example.test")
    assert "fixture-private-token" not in str(error.value)


def test_existing_kubeconfig_route_remains_supported(monkeypatch):
    from kubernetes import client, config

    loader = Mock()
    monkeypatch.setattr(config, "load_kube_config", loader)
    monkeypatch.setattr(client, "CoreV1Api", Mock())
    monkeypatch.setattr(client, "AppsV1Api", Mock())
    KubernetesTools(kubeconfig="/safe/config", kube_context="approved-context")._clients()
    loader.assert_called_once_with(config_file="/safe/config", context="approved-context")
