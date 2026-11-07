# Finish live Kubernetes and Groq verification

## Groq provider

Groq's OpenAI-compatible structured tool-calling endpoint is supported directly.
The agent keeps its credential separate from the OpenAI credential and fixes the
endpoint to `https://api.groq.com/openai/v1`.

In the cloud environment settings, securely supply **MLOPS_GROQ_API_KEY**, limited
to HTTPS destination **api.groq.com**. Do not paste the key in a conversation,
commit it, or put it in a command argument. The saved requirement declares a
credential name/destination, not an actual key. Review/save the settings and
publish the updated environment as required by the product.

Configure these non-secret variables for live provider testing:

```text
MLOPS_PLANNER=groq
MLOPS_GROQ_MODEL=llama-3.3-70b-versatile
```

The selected model must be available to the account and support function calling.
Availability, quotas and rate limits must be verified with the actual account.
Live Groq execution remains **BLOCKED** until the credential and network settings
are available in the running environment. Provider routing and tool-call safety
have mocked unit tests; these do not establish live provider success. No OpenAI
key is needed when Groq is selected. The `offline` mode remains available without
a provider key.

After configuring the key, restart the helper-owned API so it loads the variables:

```bash
source .venv/bin/activate
python -m scripts.run_local --stop
python -m scripts.run_local
read -r MLOPS_API_TOKEN < .runtime/agent.token
export MLOPS_API_TOKEN
python -m scripts.demo_scenarios --confirm-training
```

The confirmation flag explicitly authorizes the one demonstration training run.
Each conversation records its actual planner and tool status; unavailable
Kubernetes remains unavailable even when Groq works. Use a separate evidence copy
if retaining the earlier offline transcripts. Groq supplies reasoning/tool
selection; it does not supply a Kubernetes cluster or infrastructure credentials.

## Option A: local kind on Docker Desktop/WSL2

This is the simplest route if you do not already have a cluster. On Windows,
install Docker Desktop with its WSL2 engine and enable WSL integration for your
Ubuntu distribution. Use Linux containers and work inside WSL. The Docker Desktop
Kubernetes toggle is not required: the script creates a kind cluster itself.
Have roughly 4 CPUs and 8 GB RAM available for the combined demonstration stack.

Install Git, Python 3.12, uv, kind and kubectl from their official distributions.
Verify downloaded kind/kubectl checksums. Confirm `docker info` works inside the
same shell where the repository will run.

From a fresh checkout:

```bash
git clone https://github.com/Fastian-afk/MLOPs-A3.git
cd MLOPs-A3
bash scripts/bootstrap.sh
bash scripts/install_airflow.sh
source .venv/bin/activate
export MLOPS_KUBECONFIG="$HOME/.kube/config"
export MLOPS_KUBE_CONTEXT=kind-mlops-assignment
python -m scripts.run_local
INFERENCE_LOCAL_PORT=18001 bash scripts/kind_demo.sh
kubectl --context kind-mlops-assignment -n mlops get deployments,pods,services,endpoints -o wide
```

The startup helper trains the artifact if missing. The kind script builds the
inference image, loads it into its cluster, applies manifests, waits for rollout,
and verifies readiness and a real prediction. Port 18001 avoids conflicting with
the helper's standalone inference server on 8001. The script's temporary
port-forward stops when it exits. The supplied agent RBAC is namespaced and
read-only; the operator running deployment setup needs separate create/update
permissions. All writes must remain explicit operator actions in this demo
namespace.

Run the agent on this same local machine to query the kind API. A laptop kind
kubeconfig normally points at `127.0.0.1`; copying it into Codex Cloud does not make
the laptop's API reachable from the cloud. Supply only redacted exports if sharing
the local verification results through chat. Never share the kubeconfig, tokens,
client private keys or the complete shell environment.

## Option B: an existing cluster reachable from the cloud

To let the cloud agent perform reads directly, configure an authorized cluster
whose API is reachable from this execution environment. Provide its kubeconfig
through an approved secure file/credential mechanism, set `MLOPS_KUBECONFIG` to
that file and `MLOPS_KUBE_CONTEXT` to the intended context, and configure required
API network/VPN access and TLS trust. A path variable alone does not supply the
credential or connectivity. Do not send kubeconfig contents in chat or Git.

The deployment operator applies `kubernetes/` in namespace `mlops` and installs an
immutable inference image in a registry accessible to the cluster nodes. The
local `kind load docker-image` command is not a remote-cluster image distribution
method. The agent needs only the get/list permissions declared in
`kubernetes/rbac.yaml`, including Pod logs/events, Services/endpoints and
Deployments. Namespace creation and deployment changes remain operator actions.

The managed runtime currently cannot create kind because the rootless Docker host
lacks cgroup delegation. A Groq key cannot fix that host prerequisite; use one of
the two routes above instead of weakening host isolation.

## Checks still required with a real cluster

1. Confirm the Deployment has **2 ready/available replicas**, expected image,
   ConfigMap, resource requests/limits and readiness/liveness probes.
2. Export actual Pod state, restart counts, logs, events, Service selector and
   ready endpoints. Verify live/ready/version and a prediction through the Service;
   separately test ClusterIP routing from a cluster client when validating the
   service data path, since port-forward traffic alone does not prove that path.
3. Rerun deployment diagnosis and the mandatory four-system conversation with
   live Kubernetes responses. Confirm the informational request makes no write.
4. Explicitly inject a temporary Service selector mismatch in the **demo namespace**,
   collect the agent's diagnosis of zero matching Pods/endpoints, restore
   `kubernetes/service.yaml`, and verify endpoints and prediction recovery. A
   missing-model Docker fault is not a substitute for this real cluster incident.
5. Save redacted, timestamped API/CLI exports and conversations under
   `evidence/kubernetes/`, `evidence/failures/` and `evidence/conversations/`;
   rerun applicable live tests and update verification statuses only after success.

All earlier DVC, MLflow and Airflow real checks remain recorded. The provider and
cluster checks above are separate prerequisites. Hosted GitHub Actions results
and a complete Compose-stack launch also require their own verification; local
CI-equivalent checks and Compose configuration validation are already recorded.
