# Evidence-backed MLOps AI Agent

A Python conversational operations interface for DVC, MLflow, Airflow 3 and Kubernetes, built for MLOps Assignment 03. It trains a small deterministic binary classifier, records experiment provenance, exposes model inference and answers operational questions through validated tools.

The repository began empty. The uploaded assignment defines the requirements; the master execution brief adds implementation and evidence requirements. Neither an attractive report nor passing mocks establish a working deployment. [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md), [RUBRIC_CHECKLIST.md](RUBRIC_CHECKLIST.md) and [LIMITATIONS.md](LIMITATIONS.md) distinguish actual execution, mocked tests and unavailable infrastructure.

## Components

| Component | Entry point | Responsibility |
| --- | --- | --- |
| Agent/API | `api/main.py`, `agent/orchestrator.py` | Structured tool calls, confirmation, evidence-backed responses |
| Data provenance | `agent/tools/dvc_tools.py`, `data/`, `dvc.yaml` | Dataset hash, Git source reference, comparison and safe reproduction |
| Experiments | `agent/tools/mlflow_tools.py`, `training/evaluate.py` | MLflow client queries, metrics, artifacts and ranking |
| Workflow | `dags/training_pipeline.py`, `agent/tools/airflow_tools.py` | Five ordered tasks, authenticated Airflow 3 API and failure diagnosis |
| Deployment/inference | `kubernetes/`, `inference/main.py` | Two inference replicas and namespaced read-only inspection |
| Validation | `tests/`, `.github/workflows/ci.yml`, `scripts/` | Mock-isolated CI plus separately recorded real integrations |

See [architecture.md](architecture.md) for data flow, trust boundaries and the confirmation lifecycle.

Recorded local verification: 124 unit tests, 3 live integration tests and 2 local API end-to-end tests passed. DVC reproduction, five-run MLflow training from committed clean operational source, five-stage Airflow execution and Docker inference have real exports. Live Kubernetes deployment is blocked by unavailable cgroup delegation; live LLM-provider calls need a credential. See `evidence/validation.json` for exact commands/outcomes.


## Prerequisites

- Python 3.12, `uv`, Git and a POSIX shell. Linux or WSL2 is the simplest development path. On Windows, clone inside WSL2 and run these commands there; Docker Desktop must enable WSL integration for container workflows.
- Sufficient disk space for Python dependencies and runtime artifacts. The training demo runs on CPU.
- Docker Engine with a working daemon and Compose v2 for the full container stack. A Docker executable alone is insufficient.
- For real deployment: `kubectl`, a current kubeconfig and kind/minikube or an authorized cluster. Local kind also requires a working container daemon.
- Optional LLM-provider credentials for actual structured model tool calling. Offline deterministic mode requires no provider secret and is clearly labeled.

Cloud tasks already have an isolated checkout. Work in the existing repository; do not create another Git worktree for normal development.

## Install and test

From the repository root:

```bash
bash scripts/bootstrap.sh
. .venv/bin/activate
export DVC_SITE_CACHE_DIR="$PWD/.runtime/dvc-site"
ruff check .
mypy
pytest -q tests/unit
```

The bootstrap uses `uv sync --frozen --extra dev` and `uv.lock`, regenerates/verifies the deterministic sample, and seeds an ignored local DVC remote. Dependency versions are declared in `pyproject.toml`. The environment also pins `pathspec==0.12.1` for DVC compatibility and `SQLAlchemy==2.0.44` for MLflow compatibility; unconstrained newer transitive versions caused import/runtime failures during setup. Ordinary CI mocks external infrastructure and does not need a cluster, Airflow or an LLM key. Real integration/e2e checks are separate, opt-in targets; their prerequisites must be running before invoking them:

```bash
RUN_INTEGRATION=1 pytest -q tests/integration
RUN_INTEGRATION=1 pytest -q tests/e2e
```

The end-to-end agent request additionally needs the securely configured `MLOPS_API_TOKEN`.

Key configuration names (the agent uses the `MLOPS_` prefix):

| Variable | Default/purpose |
| --- | --- |
| `MLOPS_API_TOKEN` | Required bearer authentication for chat/tool inventory; no default credential |
| `MLOPS_PLANNER` | `offline`, `openai` or `groq`; offline is deterministic routing |
| `MLOPS_GROQ_API_KEY` | Separate secure Groq credential, sent only to `api.groq.com` |
| `MLOPS_GROQ_MODEL` | Function-calling model; default `llama-3.3-70b-versatile` |
| `MLOPS_LLM_API_KEY`, `MLOPS_LLM_MODEL` | Secure provider credential binding and model for actual structured LLM calls; standard `OPENAI_API_KEY` is also supported locally |
| `MLOPS_MLFLOW_TRACKING_URI` | Agent tracking server, default `http://127.0.0.1:5000` |
| `MLFLOW_TRACKING_URI` | Training/DVC tracking server; set consistently with the agent |
| `MLOPS_AIRFLOW_BASE_URL` | Airflow origin, default `http://127.0.0.1:8080` |
| `MLOPS_AIRFLOW_TOKEN` | Existing bearer token for Airflow 3 |
| `MLOPS_AIRFLOW_USERNAME`, `MLOPS_AIRFLOW_PASSWORD` | Supported `/auth/token` login when no bearer token supplied |
| `MLOPS_APPROVED_DAG_ID` | Allowlisted DAG, default `mlops_training` |
| `MLOPS_NAMESPACE` | Approved namespace, default `mlops` |
| `MLOPS_KUBECONFIG`, `MLOPS_KUBE_CONTEXT` | Optional secure Kubernetes configuration selectors |
| `MLOPS_FRESHNESS_DAYS` | Optional explicit retraining freshness policy; absent by default |
| `MODEL_PATH`, `APP_VERSION` | Inference artifact path and application version |

Use `.env.example` as the configuration reference. A local `.env` is ignored by Git. Do not paste secrets into source, reports or issue comments. When using managed cloud bindings, inspect variable presence and permitted destinations rather than printing values.

## One-command local startup

After bootstrap, install the separately constrained Airflow runtime once, then use the helper:

```bash
bash scripts/install_airflow.sh
. .venv/bin/activate
python -m scripts.run_local
read -r MLOPS_API_TOKEN < .runtime/agent.token
export MLOPS_API_TOKEN
bash scripts/smoke_test.sh
```

The helper starts or reuses real MLflow, Airflow, the agent and inference; it trains a model if the serving artifact is absent. It waits for readiness and stores development credentials only in ignored `.runtime`. The smoke test makes a real prediction and an authenticated MLflow-backed agent request. Kubernetes and LLM credentials remain separately configured. Repeating startup reuses healthy local services.

```bash
python -m scripts.run_local --stop
```

Stop terminates only helper-owned processes whose recorded process start identity still matches. Services started separately remain your terminal's responsibility. The sections below document individual components for troubleshooting and independent startup.

## Dataset and DVC

The sample generator uses a fixed seed, eight numeric features and a binary target:

```bash
export DVC_SITE_CACHE_DIR="$PWD/.runtime/dvc-site"
python scripts/prepare_data.py
```

The initial repository setup records dataset metadata with DVC. To inspect an existing initialized checkout:

```bash
dvc status
dvc remote list
git rev-parse HEAD
cat data/dataset.csv.dvc
```

A DVC hash identifies content. A Git commit identifies the tracked code and dataset metadata. Training records both; no invented human-readable dataset version is used.

For a private local demo remote, use the ignored `.dvc-remote` directory and an absolute URL so disposable-clone reproduction can find it:

```bash
mkdir -p .dvc-remote
dvc remote add --local -f -d demo "$PWD/.dvc-remote"
dvc push
```

`--local` keeps machine-specific configuration in ignored `.dvc/config.local`. `DVC_SITE_CACHE_DIR` selects a writable cache in managed environments where the default `/var/tmp` path is read-only. Other machines need a reachable remote or the deterministic generator. For a team/object-store remote, install the corresponding DVC backend extra and configure its URL and credentials securely before `dvc pull`.

The agent's reproduction tool validates a Git revision, creates a disposable clone and runs approved DVC operations there. It leaves the development checkout untouched. If the requested content is absent from both cache and remote, reproduction is unavailable; generating today's sample is not proof of restoring arbitrary historical data.

## MLflow and five real experiments

Start a local tracking server in one terminal, using ignored runtime state:

```bash
mkdir -p .runtime
mlflow server --host 127.0.0.1 --port 5000 \
  --workers 1 --backend-store-uri "sqlite:///$PWD/.runtime/mlflow.db" \
  --artifacts-destination "$PWD/.runtime/mlflow-store"
```

In another activated terminal, train five configurations and promote the highest F1 candidate only after the threshold passes:

```bash
python -m training.train --tracking-uri http://127.0.0.1:5000 --runs 5 --threshold 0.8
```

The deterministic held-out split is shared across configurations. Reports contain accuracy, precision, recall and F1 plus the run ID, parameters, dataset hash and source commit. Artifacts and databases are ignored by Git. Model selection maximizes F1, while loss metrics use minimization; missing/incomplete runs are excluded and ties are deterministic. A winning experimental score does not certify deployment health or production readiness.

## Agent API and conversations

The chat/tools endpoints require a bearer token; `/health` is public. Supply the token securely to both the server and client. For a temporary local session, generate a random value without printing it:

```bash
export MLOPS_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Run the development API bound to loopback in a shell inheriting that variable:

```bash
uvicorn api.main:app --host 127.0.0.1 --port 8000
```

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail -H "Authorization: Bearer $MLOPS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Compare the latest five runs by F1 and recommend the best candidate.","session_id":"demo","request_id":"demo-selection"}' \
  http://127.0.0.1:8000/agent/chat
```

The typed response identifies planner mode, selected tools, evidence, uncertainties, proposed actions and a trace ID. The registry validates tool arguments and output models, applies timeouts and enforces read/write permissions. Tool failures remain visible.

For the mandatory read-only scenario:

```bash
curl --fail -H "Authorization: Bearer $MLOPS_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary.","session_id":"demo","request_id":"demo-integrated"}' \
  http://127.0.0.1:8000/agent/chat
```

This request queries all four platforms and never automatically triggers training. Missing Airflow/Kubernetes access becomes uncertainty, not a healthy deployment claim or a reason to retrain. The optional LLM planner needs provider configuration documented in `.env.example`; offline mode uses deterministic routing and is not represented as full LLM reasoning.

A training request first proposes an action. Resubmit the same action in the same session with the returned `confirmation_token` before it expires. The server binds confirmation to the exact action/arguments/session and rejects replay or mismatch. It returns actual run state; an accepted trigger is not proof of workflow completion.

## Airflow 3

Airflow has its own virtual environment because its constrained dependency set differs from the agent environment. Use the tested version and installation/startup commands in [DEMO_GUIDE.md](DEMO_GUIDE.md) and `scripts/start_airflow.sh`. The DAG uses `airflow.sdk` and the adapter uses `/api/v2`, not Airflow 2's `/api/v1`.

The development script initializes the metadata database and starts Airflow with SimpleAuthManager. Passwords are generated into the ignored Airflow home directory. Configure `AIRFLOW_TOKEN`, or the matching username/password for `/auth/token`, through environment variables. Do not commit the password file. This development auth scheme is not a production identity system.

The DAG stages are:

```text
validate_dataset → preprocess_data → train_model → evaluate_and_log → quality_gate
```

Each stage has bounded retries. Dataset validation fails before training. A failed F1 gate does not produce a promoted artifact. All tasks must share `MLOPS_SHARED_DIR` and the same configured `MLOPS_DATASET_PATH`; a distributed executor needs durable shared storage mounted at identical paths. Run configuration permits bounded training parameters, not arbitrary filesystem paths, commands or Python.

## Container stack

`compose.yaml` provides the repeatable service topology: MLflow on port 5000, Airflow on 8080 and the protected agent on 8000, each published to loopback. Set `MLOPS_API_TOKEN` before Compose interpolation. The optional `BUILD_CA_BUNDLE` points at a trusted CA bundle for verified package downloads during builds; verification stays enabled. The local Python and Compose variants use the same ports, so stop the local variants before starting containers. Airflow's generated password/token must also be supplied securely to the agent after initialization. Start it only after confirming a working Docker daemon:

```bash
docker info
export AIRFLOW_UID="$(id -u)"
docker compose config
docker compose up --build -d
```

Inspect logs and the local readiness endpoints; container creation alone is not readiness. The exact current-instance validation and any unavailable Docker capability are recorded in [LIMITATIONS.md](LIMITATIONS.md). The local Python path above remains useful when containers cannot run.

## Inference and Kubernetes

After successful training creates `artifacts/model.joblib`, launch the inference app locally:

```bash
uvicorn inference.main:app --host 127.0.0.1 --port 8001
curl --fail http://127.0.0.1:8001/health/live
curl --fail http://127.0.0.1:8001/health/ready
curl --fail http://127.0.0.1:8001/version
```

Liveness proves that the process responds; readiness also requires a loaded model. `/predict` validates feature count, numeric values and batch bounds. It rejects malformed input rather than silently changing feature order.

Build/load the immutable image and apply namespaced resources using `scripts/kind_demo.sh`. The manifests specify at least two desired replicas, ClusterIP service, liveness/readiness probes, resource requests/limits, a non-secret ConfigMap and read-only RBAC. Keep kubeconfig outside Git. The adapter restricts requests to the approved namespace and exposes no cluster mutation tool.

A deployment is verified only after rollout succeeds and a representative prediction passes through the service. See [DEMO_GUIDE.md](DEMO_GUIDE.md) for the real cluster diagnosis and recovery sequence.

## Evidence, demonstration and troubleshooting

[DEMO_GUIDE.md](DEMO_GUIDE.md) covers the five conversations, two fault investigations, a five-minute presentation and engineering defense questions. Evidence is exported as timestamped JSON/CLI output under `evidence/`; screenshots are not fabricated when a GUI is unavailable.

| Symptom | First check | Meaning/action |
| --- | --- | --- |
| DVC reproduction unavailable | Remote configuration and requested hash | Supply the actual cache/remote; do not claim an unavailable revision was reproduced |
| No MLflow best run | Tracking URI, completed runs and requested metric | Train/log runs or correct the service; a missing F1 cannot be ranked |
| Airflow 401/403 | Auth manager, token expiry and account | Refresh supported authentication; never disable auth to make a check pass |
| Airflow queued indefinitely | Scheduler, DAG parsing and shared paths | Inspect actual run/task states; trigger acceptance alone is insufficient |
| Inference live but unready | Artifact path, model compatibility and logs | Train/pass gate and mount the artifact before expecting predictions |
| Kubernetes unavailable | kubeconfig context, namespace and RBAC | Report access failure separately from application health |
| Service has no endpoints | Service selectors, Pod labels and readiness | Match selectors and recover ready replicas, then repeat the prediction |
| Docker daemon unavailable | `docker info` | Use an authorized host/daemon; manifests alone do not establish deployment |

Stop services you launched and retain only required evidence:

```bash
docker compose down
```

Do not use `down -v` unless you intend to delete service state. Local Python processes should be stopped in their own terminals. Preserve DVC remote data and MLflow evidence needed for assessment.

Groq and remaining live-cluster setup: [NEXT_STEPS.md](NEXT_STEPS.md). Provider routing is unit-tested; live Groq requires securely configured credentials and permitted access.

Windows-to-cloud Kubernetes connection: [WINDOWS_KUBERNETES.md](WINDOWS_KUBERNETES.md). The HTTPS reader supports a separately scoped bearer token and inherited proxy/CA trust. Live connectivity is unverified until a real endpoint/token is configured.
