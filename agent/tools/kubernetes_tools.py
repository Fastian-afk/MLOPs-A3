"""Read-only, namespace-scoped Kubernetes diagnostics using the supported client."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScopedInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str | None = Field(default=None, pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class ListInput(ScopedInput):
    app: str = Field(default="inference", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")
    limit: int = Field(default=100, ge=1, le=200)


class PodInput(ScopedInput):
    pod: str = Field(pattern=r"^[a-z0-9]([-a-z0-9.]*[a-z0-9])?$", max_length=253)


class LogInput(PodInput):
    tail_lines: int = Field(default=100, ge=1, le=500)


class ServiceInput(ScopedInput):
    service: str = Field(default="inference", pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class DeploymentInput(ScopedInput):
    deployment: str = Field(default="inference", pattern=r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class ContainerHealth(BaseModel):
    name: str
    ready: bool
    restart_count: int
    waiting_reason: str | None = None
    termination_reason: str | None = None


class PodHealth(BaseModel):
    name: str
    namespace: str
    phase: str
    ready: bool
    restart_count: int
    conditions: dict[str, str]
    containers: list[ContainerHealth]
    diagnoses: list[str]
    node: str | None = None


class PodList(BaseModel):
    namespace: str
    pods: list[PodHealth]
    continuation: str | None = None


class DeploymentState(BaseModel):
    name: str
    namespace: str
    desired_replicas: int
    ready_replicas: int
    available_replicas: int
    updated_replicas: int
    generation: int | None
    observed_generation: int | None
    images: list[str]
    conditions: dict[str, str]


class DeploymentList(BaseModel):
    namespace: str
    deployments: list[DeploymentState]
    continuation: str | None = None


class ServiceState(BaseModel):
    name: str
    namespace: str
    service_type: str
    cluster_ip: str | None
    selector: dict[str, str]
    ports: list[dict[str, Any]]
    matching_pods: list[str]
    ready_addresses: list[str]
    not_ready_addresses: list[str]
    diagnoses: list[str]


class PodLogs(BaseModel):
    pod: str
    namespace: str
    logs: str
    tail_lines: int
    redacted: bool


class PodEvent(BaseModel):
    reason: str | None
    message: str | None
    event_type: str | None
    count: int
    last_timestamp: str | None


class PodEvents(BaseModel):
    pod: str
    namespace: str
    events: list[PodEvent]


class DeploymentVersion(BaseModel):
    deployment: DeploymentState
    labels: dict[str, str]
    annotations: dict[str, str]
    model_run_id: str | None
    rollout_complete: bool
    caveats: list[str]


def _get(obj: Any, name: str, default: Any = None) -> Any:
    value = obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)
    return default if value is None else value


def _redact(value: str) -> str:
    value = re.sub(
        r"(?i)((?:authorization|password|api[_-]?key|token|secret)\s*[:=]\s*)([^\s,;]+)",
        r"\1[REDACTED]",
        value,
    )
    return re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[REDACTED]", value)


class KubernetesTools:
    """Only reads are exposed; an injected client makes ordinary CI fully offline."""

    def __init__(
        self,
        *,
        core_api: Any = None,
        apps_api: Any = None,
        namespace: str = "mlops",
        kubeconfig: str | None = None,
        kube_context: str | None = None,
        http_timeout: float = 10,
    ):
        self.core = core_api
        self.apps = apps_api
        self.namespace = namespace
        self.kubeconfig = kubeconfig
        self.kube_context = kube_context
        self.http_timeout = http_timeout

    def _namespace(self, requested: str | None) -> str:
        if requested is not None and requested != self.namespace:
            raise PermissionError("NAMESPACE_FORBIDDEN: only the configured namespace is allowed")
        return self.namespace

    def _clients(self) -> None:
        if self.core is not None and self.apps is not None:
            return
        from kubernetes.config.config_exception import ConfigException

        from kubernetes import client, config

        try:
            if self.kubeconfig or self.kube_context:
                config.load_kube_config(config_file=self.kubeconfig, context=self.kube_context)
            else:
                try:
                    config.load_incluster_config()
                except ConfigException:
                    config.load_kube_config()
        except ConfigException as exc:
            raise RuntimeError(
                "KUBERNETES_UNAVAILABLE: configure a cluster and read-only credentials"
            ) from exc
        self.core = self.core or client.CoreV1Api()
        self.apps = self.apps or client.AppsV1Api()

    def _call(self, api: Any, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return getattr(api, method)(*args, _request_timeout=self.http_timeout, **kwargs)
        except Exception as exc:
            status = getattr(exc, "status", None)
            code = {401: "AUTHENTICATION_FAILED", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(
                status, "KUBERNETES_UNAVAILABLE"
            )
            raise RuntimeError(f"{code}: Kubernetes request failed; inspect cluster access") from exc

    def _health(self, pod: Any) -> PodHealth:
        metadata, status, spec = _get(pod, "metadata"), _get(pod, "status"), _get(pod, "spec")
        conditions = {_get(c, "type"): str(_get(c, "status")) for c in _get(status, "conditions", [])}
        containers = []
        diagnoses = []
        for item in _get(status, "container_statuses", []):
            waiting = _get(_get(item, "state"), "waiting")
            terminated = _get(_get(item, "last_state"), "terminated")
            reason = _get(waiting, "reason")
            if reason:
                diagnoses.append(f"Container {_get(item, 'name')}: {reason}")
            restarts = _get(item, "restart_count", 0)
            if restarts:
                diagnoses.append(f"Container {_get(item, 'name')} has restarted {restarts} times")
            containers.append(
                ContainerHealth(
                    name=_get(item, "name", "unknown"),
                    ready=_get(item, "ready", False),
                    restart_count=restarts,
                    waiting_reason=reason,
                    termination_reason=_get(terminated, "reason"),
                )
            )
        phase = _get(status, "phase", "Unknown")
        ready = conditions.get("Ready") == "True" and bool(containers) and all(c.ready for c in containers)
        if phase == "Pending":
            diagnoses.append("Pod is Pending; inspect scheduling and image-pull events")
        if not ready:
            diagnoses.append("Pod is not Ready; Service traffic excludes unready endpoints")
        return PodHealth(
            name=_get(metadata, "name", "unknown"),
            namespace=_get(metadata, "namespace", self.namespace),
            phase=phase,
            ready=ready,
            restart_count=sum(c.restart_count for c in containers),
            conditions=conditions,
            containers=containers,
            diagnoses=diagnoses,
            node=_get(spec, "node_name"),
        )

    def _deployment(self, deployment: Any) -> DeploymentState:
        metadata, status, spec = (_get(deployment, k) for k in ("metadata", "status", "spec"))
        return DeploymentState(
            name=_get(metadata, "name", "unknown"),
            namespace=_get(metadata, "namespace", self.namespace),
            desired_replicas=_get(spec, "replicas", 0),
            ready_replicas=_get(status, "ready_replicas", 0),
            available_replicas=_get(status, "available_replicas", 0),
            updated_replicas=_get(status, "updated_replicas", 0),
            generation=_get(metadata, "generation"),
            observed_generation=_get(status, "observed_generation"),
            images=[
                _get(c, "image", "unknown")
                for c in _get(_get(_get(spec, "template"), "spec"), "containers", [])
            ],
            conditions={_get(c, "type"): str(_get(c, "status")) for c in _get(status, "conditions", [])},
        )

    def list_pods(self, args: ListInput) -> PodList:
        namespace = self._namespace(args.namespace)
        self._clients()
        result = self._call(
            self.core, "list_namespaced_pod", namespace, label_selector=f"app={args.app}", limit=args.limit
        )
        return PodList(
            namespace=namespace,
            pods=[self._health(p) for p in _get(result, "items", [])],
            continuation=_get(_get(result, "metadata"), "_continue"),
        )

    def list_deployments(self, args: ListInput) -> DeploymentList:
        namespace = self._namespace(args.namespace)
        self._clients()
        result = self._call(
            self.apps,
            "list_namespaced_deployment",
            namespace,
            label_selector=f"app={args.app}",
            limit=args.limit,
        )
        return DeploymentList(
            namespace=namespace,
            deployments=[self._deployment(d) for d in _get(result, "items", [])],
            continuation=_get(_get(result, "metadata"), "_continue"),
        )

    def inspect_service(self, args: ServiceInput) -> ServiceState:
        namespace = self._namespace(args.namespace)
        self._clients()
        service = self._call(self.core, "read_namespaced_service", args.service, namespace)
        spec = _get(service, "spec")
        selector = _get(spec, "selector", {})
        pods = self._call(
            self.core,
            "list_namespaced_pod",
            namespace,
            label_selector=",".join(f"{k}={v}" for k, v in sorted(selector.items())),
            limit=200,
        )
        endpoints = self._call(self.core, "read_namespaced_endpoints", args.service, namespace)
        ready, unready = [], []
        for subset in _get(endpoints, "subsets", []):
            ready.extend(_get(a, "ip", "unknown") for a in _get(subset, "addresses", []))
            unready.extend(_get(a, "ip", "unknown") for a in _get(subset, "not_ready_addresses", []))
        matching = [_get(_get(p, "metadata"), "name", "unknown") for p in _get(pods, "items", [])]
        diagnoses = []
        if not selector:
            diagnoses.append("Service has no selector; endpoints require explicit management")
        if selector and not matching:
            diagnoses.append(
                "Service selector matches no Pods; selector mismatch can make the API unavailable"
            )
        if not ready:
            diagnoses.append("Service has no ready endpoint addresses; requests cannot reach a ready backend")
        return ServiceState(
            name=args.service,
            namespace=namespace,
            service_type=_get(spec, "type", "Unknown"),
            cluster_ip=_get(spec, "cluster_ip"),
            selector=selector,
            matching_pods=matching,
            ports=[
                {
                    "port": _get(p, "port"),
                    "target_port": _get(p, "target_port"),
                    "protocol": _get(p, "protocol", "TCP"),
                }
                for p in _get(spec, "ports", [])
            ],
            ready_addresses=ready,
            not_ready_addresses=unready,
            diagnoses=diagnoses,
        )

    def pod_health(self, args: PodInput) -> PodHealth:
        namespace = self._namespace(args.namespace)
        self._clients()
        return self._health(self._call(self.core, "read_namespaced_pod", args.pod, namespace))

    def pod_logs(self, args: LogInput) -> PodLogs:
        namespace = self._namespace(args.namespace)
        self._clients()
        raw = str(
            self._call(
                self.core,
                "read_namespaced_pod_log",
                args.pod,
                namespace,
                tail_lines=args.tail_lines,
                limit_bytes=30000,
                timestamps=True,
            )
        )
        clean = _redact(raw)[:30000]
        return PodLogs(
            pod=args.pod, namespace=namespace, logs=clean, tail_lines=args.tail_lines, redacted=clean != raw
        )

    def pod_events(self, args: PodInput) -> PodEvents:
        namespace = self._namespace(args.namespace)
        self._clients()
        response = self._call(
            self.core,
            "list_namespaced_event",
            namespace,
            field_selector=f"involvedObject.kind=Pod,involvedObject.name={args.pod}",
            limit=100,
        )
        return PodEvents(
            pod=args.pod,
            namespace=namespace,
            events=[
                PodEvent(
                    reason=_get(e, "reason"),
                    message=_redact(str(_get(e, "message", ""))),
                    event_type=_get(e, "type"),
                    count=_get(e, "count", 1),
                    last_timestamp=str(_get(e, "last_timestamp")) if _get(e, "last_timestamp") else None,
                )
                for e in _get(response, "items", [])
            ],
        )

    def deployment_version(self, args: DeploymentInput) -> DeploymentVersion:
        namespace = self._namespace(args.namespace)
        self._clients()
        deployment = self._call(self.apps, "read_namespaced_deployment", args.deployment, namespace)
        state = self._deployment(deployment)
        template = _get(_get(deployment, "spec"), "template")
        metadata = _get(template, "metadata")
        annotations = _get(metadata, "annotations", {})
        model_run_id = annotations.get("mlops.model-run-id")
        for container in _get(_get(template, "spec"), "containers", []):
            for env in _get(container, "env", []):
                if _get(env, "name") == "MODEL_RUN_ID" and _get(env, "value"):
                    model_run_id = _get(env, "value")
        complete = (
            state.desired_replicas > 0
            and state.ready_replicas == state.desired_replicas
            and state.available_replicas == state.desired_replicas
            and state.updated_replicas == state.desired_replicas
            and state.generation == state.observed_generation
        )
        return DeploymentVersion(
            deployment=state,
            labels=_get(metadata, "labels", {}),
            annotations=annotations,
            model_run_id=model_run_id,
            rollout_complete=complete,
            caveats=[]
            if model_run_id
            else ["Deployment does not record a model run ID; candidate equality is unknown"],
        )


def register(registry: Any, settings: Any) -> None:
    tools = KubernetesTools(
        namespace=settings.namespace,
        kubeconfig=settings.kubeconfig,
        kube_context=settings.kube_context,
        http_timeout=settings.http_timeout,
    )
    definitions = [
        (
            "list_pods",
            "List approved-namespace application Pods and health",
            ListInput,
            tools.list_pods,
            PodList,
        ),
        (
            "list_deployments",
            "List application Deployments and rollout state",
            ListInput,
            tools.list_deployments,
            DeploymentList,
        ),
        (
            "inspect_service",
            "Inspect Service selector and ready endpoint addresses",
            ServiceInput,
            tools.inspect_service,
            ServiceState,
        ),
        (
            "pod_health",
            "Inspect Pod readiness, restarts and waiting reasons",
            PodInput,
            tools.pod_health,
            PodHealth,
        ),
        ("pod_logs", "Read bounded sanitized Pod logs", LogInput, tools.pod_logs, PodLogs),
        (
            "pod_events",
            "Read relevant Pod warning and scheduling events",
            PodInput,
            tools.pod_events,
            PodEvents,
        ),
        (
            "deployment_version",
            "Read deployment image versions and model identity",
            DeploymentInput,
            tools.deployment_version,
            DeploymentVersion,
        ),
    ]
    for name, description, inputs, handler, output in definitions:
        registry.add(
            f"kubernetes.{name}",
            description,
            inputs,
            handler,
            output_model=output,
            permission="read",
            timeout=30,
        )
