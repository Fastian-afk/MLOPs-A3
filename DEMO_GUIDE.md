# Reproducible demonstration and engineering defense

Run from the repository root in an activated Python 3.12 environment. Use [README.md](README.md) for installation and configuration. Preserve timestamps, request IDs and raw evidence; redact credentials before committing outputs.

## Prepare the local data and experiments

```bash
export DVC_SITE_CACHE_DIR="$PWD/.runtime/dvc-site"
python -m scripts.prepare_data --output data/dataset.csv
dvc status
python -m training.train --tracking-uri http://127.0.0.1:5000 --runs 5 --threshold 0.8
```

MLflow must already be running. The CLI records five completed candidates and promotes one only if the explicit F1 threshold passes. The training output supplies real run IDs. Set `MLOPS_MLFLOW_TRACKING_URI` for the agent and `MLFLOW_TRACKING_URI` for the training/DVC process if using a different server.

Start the agent with `uvicorn api.main:app --host 127.0.0.1 --port 8000`. Start inference separately with `uvicorn inference.main:app --host 127.0.0.1 --port 8001` after `artifacts/model.joblib` exists. For a complete infrastructure demonstration, Airflow and a Kubernetes cluster must also be running; their absence is reported, not disguised by mock output.

## Configure Airflow 3 locally

The intended server version is Apache Airflow 3.1.0 on Python 3.12, installed in its own `.venv-airflow` using the matching official constraints. `scripts/start_airflow.sh` initializes the database, configures the repository DAG directory and starts the development standalone server. Keep the agent/training environment separate from Airflow's constrained dependencies.

```bash
uv venv --python 3.12 .venv-airflow
uv pip install --python .venv-airflow/bin/python apache-airflow==3.1.0 \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.1.0/constraints-3.12.txt
uv pip install --python .venv-airflow/bin/python mlflow-skinny==3.5.1 \
  scikit-learn==1.7.2 pandas joblib==1.5.2 \
  --constraint https://raw.githubusercontent.com/apache/airflow/constraints-3.1.0/constraints-3.12.txt
PATH="$PWD/.venv-airflow/bin:$PATH" MLFLOW_TRACKING_URI=http://127.0.0.1:5000 \
  bash scripts/start_airflow.sh
```

The Airflow environment uses the supported `mlflow-skinny` client; the full MLflow server belongs in the primary environment. This avoids overriding Airflow's constrained cryptography dependency. A fresh DAG is unpaused by the startup configuration. For an existing previously paused local DAG, run once:

```bash
AIRFLOW_HOME="$PWD/.runtime/airflow" .venv-airflow/bin/airflow dags unpause mlops_training
```

SimpleAuthManager creates credentials in ignored `.runtime/airflow/simple_auth_manager_passwords.json`. Read/use them locally or through the supported environment binding. The agent accepts `MLOPS_AIRFLOW_TOKEN`, or `MLOPS_AIRFLOW_USERNAME`/`MLOPS_AIRFLOW_PASSWORD`, for authenticated calls. Never copy that file or a token into evidence.

The server uses `MLOPS_SHARED_DIR` for durable run files and `MLOPS_DATASET_PATH` for its configured dataset. Every worker must see the same locations. Allowed DAG configuration contains only validated training parameters: `c`, `seed`, `test_size`, `f1_threshold` and `experiment_name`. Task order and actual retries are visible through the Airflow API; the agent's trigger operation polls boundedly and reports nonterminal/failed states explicitly.

## Five conversations

The examples use one session for clarity. Set the required `MLOPS_API_TOKEN` securely in both server and client shells; every chat request needs bearer authentication. Existing exports under `evidence/conversations/` record the modes and tool outcomes actually exercised in the implementation environment.

### 1. Dataset provenance

Copy a real run ID from the latest training output, then ask:

> Which dataset version was used for experiment RUN_ID, and how can I reproduce it?

Expected trace: MLflow run details → DVC recorded lineage. Inspect the actual dataset hash, Git SHA and metadata. A safe reproduction creates a disposable clone and performs a DVC checkout/pull there, never a destructive reset of the development checkout. If the remote lacks the object, the correct result is unavailable reproduction.

### 2. Model selection

```bash
curl --fail -H "Authorization: Bearer $MLOPS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Compare the latest five runs by F1 and recommend the best candidate.","session_id":"viva","request_id":"viva-selection"}' \
  http://127.0.0.1:8000/agent/chat
```

Show the recorded F1 values for five completed runs, the deterministic ranking and the selected run ID. Explain that the winning experiment still needs a valid gate, lineage and observed deployment. A failed or missing-metric run must not silently win.

### 3. Authorized pipeline execution

Ask:

> Trigger the approved training DAG.

The first response proposes `airflow.trigger_training` and returns a confirmation token. It must not create an Airflow run yet. Submit the same requested action/session with the token. Inspect the actual returned DAG run ID and task states, then query its final state after bounded polling. Show validation → preprocessing → training → evaluation/MLflow → quality gate. A queued response does not prove success.

Check that a token from another session, an expired token or a replay is denied. These checks can be demonstrated with the unit tests without modifying real infrastructure.

### 4. Deployment diagnosis

Ask:

> Why is my prediction API unavailable?

Expected evidence includes Pods, readiness conditions, waiting/termination reasons, restart counts, deployment availability/version, service selector/endpoints, events and relevant logs. The explanation must name the observations supporting its diagnosis. When the cluster is inaccessible, the correct outcome is an access uncertainty, not a claim that the application is unhealthy or healthy.

### 5. Mandatory four-platform reasoning

Ask exactly:

> Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary.

Show the selected MLflow run, its DVC dataset reference, deployment/Pod state and recent Airflow workflow state. Check the trace contains all four systems and no trigger/mutating tool. The answer separates facts and missing evidence. Retraining needs a stated freshness policy, failed quality gate or measured degradation; it is never automatically initiated by this informational question.

## Kubernetes setup and evidence

On a suitable Docker/kind host:

```bash
bash scripts/kind_demo.sh
kubectl -n mlops rollout status deployment/inference --timeout=120s
kubectl -n mlops get deployment,pods,services,endpoints -o wide
kubectl -n mlops get events --sort-by=.lastTimestamp
kubectl -n mlops logs deployment/inference --tail=100
```

The helper builds/loads an immutable image that contains the promoted model. Verify two ready replicas and an actual prediction through the service; an open Pod port alone is not sufficient. The agent should use the namespaced read-only service account rather than cluster-admin credentials. Keep its kubeconfig securely outside the repository.

In the implementation cloud runtime, kind provisioning was blocked by unavailable rootless cgroup delegation. See `evidence/kubernetes/runtime_cluster.json`; these commands require a suitable host or an existing authorized cluster.

## Two deliberate failures

### Failure A: rejected training data or quality gate

Use the fault-injection script's documented mode to run an invalid-data/gate case. For a real Airflow investigation, preserve DAG run ID, failed task, retry attempts, diagnostics and downstream states. Confirm no promotion manifest/new serving artifact appeared. Restore valid input or the documented threshold, rerun the approved DAG with explicit confirmation and retain the successful final task states.

A directly executed validation/gate test proves the Python training safety invariant. It is not a real scheduler incident. The evidence label must identify which operation actually ran.

### Failure B: readiness or service selector failure

On the approved demo cluster, deliberately break only the demonstration namespace's service selector or model readiness configuration using an operator's authorized `kubectl`. Ask the agent to diagnose unavailability from current resources/events/logs. Restore the checked-in manifest, wait for ready endpoints and repeat a prediction. Record before/fault/recovery observations.

The agent itself exposes no Kubernetes mutation endpoint. If no cluster is available, run the mocked diagnosis test and label it `VERIFIED_MOCKED`; do not present it as a live cluster incident.

## Five-minute presentation

| Time | Action | Evidence to show |
| --- | --- | --- |
| 0:00–0:40 | Explain data/control flow and read/write boundary | `architecture.md` diagram, registry schemas and read-only RBAC |
| 0:40–1:25 | Resolve one real run's data and compare five experiments | MLflow metrics, DVC hash, source commit and reproduction export |
| 1:25–2:15 | Show confirmation then actual workflow state | Proposal, actual DAG run ID, five task states, retry/gate behavior |
| 2:15–3:05 | Diagnose deployment using observed resources | Two replicas, probes, service/endpoints, logs and version |
| 3:05–4:10 | Run the exact integrated question | Four-system tool trace, facts/uncertainties, no automatic trigger |
| 4:10–5:00 | Explain two failures and verified limits | Fault/recovery exports, tests summary, `LIMITATIONS.md` |

Start slow services and prepare evidence before the five-minute demonstration. If a required real integration is blocked, disclose that at its scheduled step and show the recorded blocker plus separately labeled mocks; do not substitute the mock silently.

## Engineering defense questions

- **Why both a DVC hash and Git commit?** The hash identifies data content; the commit identifies source and tracked metadata. The two together support run provenance.
- **Why is best F1 not production readiness?** A held-out metric does not establish valid data lineage, a passed gate, deployed version, health, drift or business acceptance.
- **What do retries solve?** Bounded transient failures. Invalid input should still fail deterministically, and retries must not bypass the promotion gate.
- **Why liveness and readiness?** Liveness measures whether the process should restart. Readiness controls routing only after a usable model has loaded. Two desired replicas do not prove two ready replicas.
- **Why a read-only Kubernetes agent?** The assignment permits a safe operations subset. Omitting mutation avoids exposing a restart/edit path while still satisfying inspection and diagnosis; operators retain separate authorized changes.
- **How does confirmation resist injection?** A model/tool response cannot supply authority. The server issues a short-lived action/session-bound nonce and rechecks it before an allowlisted write.
- **What if a tool times out?** The result records a timeout and uncertainty. The agent cannot truthfully report successful infrastructure behavior without a successful tool response.
- **What remains for production?** Identity-backed authorization, TLS, shared confirmation state, managed service backends/storage, artifact integrity policy and observability beyond this CPU demonstration.
