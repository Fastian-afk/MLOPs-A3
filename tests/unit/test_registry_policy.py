import asyncio

from pydantic import BaseModel

from agent.registry import ToolRegistry


class Empty(BaseModel):
    pass


class NetworkDenied(RuntimeError):
    code = "kubernetes_network_policy_denied"


def test_policy_denial_is_distinct_from_cluster_or_credential_failure():
    def denied(args):
        raise NetworkDenied("Authorization: Bearer do-not-expose")

    registry = ToolRegistry()
    registry.add("kubernetes.list_pods", "Read Pods", Empty, denied, output_model=Empty)
    result = asyncio.run(registry.execute("kubernetes.list_pods", {}, "policy-test"))
    assert result.status == "error"
    assert result.error_code == "NETWORK_POLICY_DENIED"
    assert "unknown" in result.uncertainty
    assert "do-not-expose" not in result.model_dump_json()
