# Run the remaining local demonstration

## What is already verified

The repository contains real DVC reproduction, five clean-source MLflow candidates,
Airflow five-stage execution and quality-gate failure/recovery, Docker inference
and readiness failure/recovery, authenticated API checks, and Groq model discovery
plus four real informational planning calls. The current test counts and per-conversation planner
results are recorded in `evidence/validation.json`, `evidence/groq/` and
`evidence/conversations/groq/` (with earlier offline exports retained separately). Hosted Actions has also passed at the source commit
linked in `evidence/runtime/github_actions.json`.

The cluster portion is still incomplete. Cloud kind cannot start because its
rootless host lacks cgroup delegation. The configured Windows cluster tunnel was
allowlisted and had a published credential, but actual requests returned upstream
Envoy/plain-text HTTP 403 before Kubernetes responded. That does not establish a
bad token, an empty cluster or application health. See
`evidence/kubernetes/remote_live.json` and `current_runtime_cluster.json`.

## 1. Native PowerShell: real local inference and Kubernetes

Use your existing Docker Desktop Linux-container engine and local
`mlops-assignment` kind cluster. Have Git, kind and kubectl available. This path
needs no Windows Python, registry account, cloud tunnel or Groq key.

From a reviewed local checkout, run:

```powershell
Set-Location "$env:USERPROFILE\MLOPs-A3"
git pull --ff-only
.\scripts\windows_deploy.ps1 -ConfirmDeploy -InjectSelectorFailure
```

If the repository has not been cloned, first run `git clone
https://github.com/Fastian-afk/MLOPs-A3.git "$env:USERPROFILE\MLOPs-A3"`. If local
changes prevent a fast-forward, preserve them rather than resetting the checkout.
If the local PowerShell execution policy blocks the reviewed script, an approved
process-scoped invocation is:

```powershell
powershell.exe -NoProfile -ExecutionPolicy RemoteSigned -File .\scripts\windows_deploy.ps1 -ConfirmDeploy -InjectSelectorFailure
```

This does not change the saved user/machine execution policy and does not bypass
an organization-enforced policy. Do not use `Bypass` or disable verification.

The deployment flag authorizes changes only to namespace `mlops`; the extra fault
flag authorizes the temporary Service selector mismatch. The helper:

1. Checks the SHA256 of the tiny trusted fixture in `demo_artifacts/` and preserves
   any different existing serving artifact.
2. Builds an image tagged with the actual checkout commit and loads it into kind.
3. Applies the two-replica inference Deployment, ClusterIP Service, ConfigMap,
   probes, resource limits and read-only agent RBAC.
4. Requires two desired/Ready/available replicas, then runs a probe Pod inside the
   cluster to verify ClusterIP/DNS health, version and a real prediction.
5. With the fault flag, records the selector failure and failed Service routing,
   restores the manifest, and verifies prediction recovery.
6. Captures deployment, Pods, Service, endpoints, events, logs and probe results in
   `evidence/kubernetes/windows-<UTC timestamp>/verification.json`, restores any
   temporary Service change and removes its own probe Pods.

The fixture is the exact 2,686-byte artifact from recorded real run
`339b16bb4dc3467aa6004ff170f7f504`, with training source
`5a35d39d1d0e7041ca78a5d0c416f05c9d15d5c8` and F1 0.92. Its original model lineage
is separate from the current image/service source commit. This small example
artifact makes the demonstration self-contained; it is not a retraining claim or
a large model store.

The PowerShell helper has been reviewed and parser/control-flow checked in the
cloud. Real Windows cluster execution is still required. A script-supplied fault
diagnosis is an operator observation; to demonstrate the AI diagnosis criterion,
run the local conversational agent against the same cluster and retain its actual
Kubernetes tool responses as well.

## 2. Linux/WSL2: the full conversational stack

Airflow and the complete Python service stack use Linux/WSL2. From that shell:

```bash
bash scripts/bootstrap.sh
bash scripts/install_airflow.sh
source .venv/bin/activate
python -m scripts.run_local --planner offline
read -r MLOPS_API_TOKEN < .runtime/agent.token
export MLOPS_API_TOKEN
bash scripts/smoke_test.sh
```

For local Kubernetes agent reads, securely select a kubeconfig/context and confirm
`kubectl` can reach the intended API from the same shell as the agent. A Windows
or laptop `127.0.0.1` API address is not automatically reachable from another
container, WSL network or cloud machine. The reader needs only the namespaced
permissions in `kubernetes/rbac.yaml`. Keep administrator credentials separate.

## 3. Live Groq planning

The previously configured `llama-3.3-70b-versatile` was absent from the account's
actual model list. `openai/gpt-oss-20b` returned a real structured tool call with
HTTP 200; request IDs and usage are in `evidence/groq/provider_probe.json`.
Supply `MLOPS_GROQ_API_KEY` securely for HTTPS destination `api.groq.com`, then:

```bash
python -m scripts.run_local --stop
python -m scripts.run_local --planner groq --groq-model openai/gpt-oss-20b
read -r MLOPS_API_TOKEN < .runtime/agent.token
export MLOPS_API_TOKEN
python -m scripts.demo_scenarios --confirm-training --output-dir evidence/conversations/local-groq --provider-interval-seconds 30
```

The command options select non-secret provider/model values for the launched API;
they do not print or modify the key. No OpenAI key is needed for Groq. The
confirmation flag explicitly authorizes one demonstration Airflow trigger. The
informational integrated question must remain read-only.

Use actual provider traces to distinguish live planning from offline routing and
from deterministic coverage guards. Quotas/model availability are account-specific;
record rate limits or provider failures as uncertainty, not fabricated tool success.
A Groq key does not provide Kubernetes connectivity. Even a successful provider
conversation can remain partly blocked by the cloud route policy.

## 4. Retain real evidence before updating assessment status

After the local cluster checks succeed, retain its timestamped exports and actual
agent conversations. Run applicable opt-in tests with the services/configuration
available. Preserve passed, failed, skipped and blocked results separately. Update
the report and rubric only for checks that actually ran. The whole Compose stack
has not been launched here; its configuration and individual image/container
checks are separate evidence.
