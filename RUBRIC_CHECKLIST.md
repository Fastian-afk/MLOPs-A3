# Rubric coverage and evidence checklist

The original assignment totals 100 marks. This table maps requirements to implementation and intended checks; it does not predict a grade. A requirement without corresponding execution evidence remains incomplete even if code exists. Read [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md) and the timestamped files under `evidence/` for the actual execution record.

| Original rubric component | Marks | Source and configuration | Tests and evidence | Assessment state |
| --- | ---: | --- | --- | --- |
| DVC integration and data provenance | 15 | `agent/tools/dvc_tools.py`, `data/dataset.csv.dvc`, `dvc.yaml`, `training/` | `tests/unit/test_dvc.py`, `tests/unit/test_training.py`, `evidence/dvc/`, `evidence/mlflow/` | `VERIFIED_REAL`: clean/dirty/restored data, version comparison, actual run lineage and disposable-clone reproduction |
| MLflow experiment intelligence | 15 | `agent/tools/mlflow_tools.py`, `training/evaluate.py` | `tests/unit/test_mlflow.py`, `evidence/mlflow/`, model-selection conversation | `VERIFIED_REAL`: five clean-source candidates, artifacts/client query; historical dirty-source runs retained; registry available and empty |
| Airflow DAG and workflow operations | 15 | `agent/tools/airflow_tools.py`, `dags/training_pipeline.py`, `compose.yaml` | `tests/unit/test_airflow.py`, `evidence/airflow/` | `VERIFIED_REAL`: all five stages, failed gate with retry/no promotion, successful corrective run |
| Kubernetes deployment and diagnostics | 15 | `agent/tools/kubernetes_tools.py`, `inference/main.py`, `kubernetes/`, `Dockerfile.inference` | `tests/unit/test_kubernetes.py`, `tests/unit/test_inference.py`, `evidence/kubernetes/` | Cluster `BLOCKED`: cloud cgroup delegation and remote upstream HTTP 403; real Docker prediction/readiness fault `VERIFIED_REAL`; adapter/selector diagnosis `VERIFIED_MOCKED`; explicit Windows helper supplied |
| Multi-tool AI agent reasoning | 15 | `agent/orchestrator.py`, `agent/schemas.py`, `api/main.py`, tool registry | Agent/API unit tests, `evidence/conversations/` | Real Groq request/plan traces in four informational conversations; actual four-adapter investigation with separately labeled coverage reads; full cluster verification remains `BLOCKED` |
| Testing, reliability, and safety | 10 | `agent/permissions.py`, `agent/logging.py`, `scripts/inject_failures.py` | `tests/unit/`, `evidence/failures/` | 132 unit passed; 3 live integration passed/1 remote target skipped by default; 2 local e2e passed; separate explicit remote test1 failed/BLOCKED on upstream denial; real Airflow/container faults recovered, mocked Kubernetes selector separately labeled |
| GitHub repository and CI | 5 | `pyproject.toml`, `.github/workflows/ci.yml`, setup scripts | Local CI-equivalent record, GitHub Actions after push | Local checks recorded in `evidence/validation.json`; hosted Actions run42403361140 passed for source commit f5baa78; later commits require separate verification |
| Demonstration and architecture defense | 10 | `architecture.md`, `DEMO_GUIDE.md`, `TECHNICAL_REPORT.md`, `LIMITATIONS.md` | Five conversations, two investigations, per-system exports | Five current API conversations under `evidence/conversations/groq/`: 3 verified, 2 blocked operationally by upstream Kube denial; 4 real provider calls, explicit confirmation flow, 2 real local-service fault recoveries plus mocked selector case |
| **TOTAL** | **100** | | | **No guaranteed mark claim** |

## Detailed acceptance map

| Criterion | Implementation | Required check/evidence |
| --- | --- | --- |
| List DVC datasets and current Git/content references | `dvc_tools.py`: list and provenance tools | Actual `.dvc`/lock metadata and current commit export |
| Compare versions and detect changed data | `dvc_tools.py`: comparison and dirty-state tools | Tests for clean/dirty data, different metadata and invalid revisions |
| Reproduce a historical dataset safely | `dvc_tools.py`: disposable clone reproduction | Verified checkout/hash with available cache/remote; unavailable data reported |
| Link a training run to its dataset | Training lineage tags and DVC provenance inputs | Real selected MLflow run ID resolves recorded dataset hash/Git reference |
| List MLflow experiments, runs, details, artifacts | `mlflow_tools.py` | Client-based tests and actual tracking-server exports |
| Rank and compare at least five runs by requested metric | `mlflow_tools.py`, training CLI | Actual five-run table; direction, missing metric and tie handling tests |
| Registry metadata when supported | `mlflow_tools.py` | Registry result or explicit unsupported/unavailable uncertainty |
| Five ordered Airflow stages | `dags/training_pipeline.py` | DAG import, task dependency export, real task states |
| Retries, validation and quality gate | DAG plus `training/validate.py`, `quality_gate.py` | Failed validation/gate blocks promotion; corrective run evidence |
| Airflow authenticated v3 API and pagination | `airflow_tools.py` | Auth/pagination/timeout tests and real authenticated `/api/v2` response |
| Approved DAG trigger with confirmation | Registry permissions and Airflow adapter | Denial, confirmation binding/expiry/replay tests; actual run final state |
| Inspect failed Airflow tasks and diagnostics | `airflow_tools.py` | Failed-task fixture tests and real failure diagnostics if available |
| Containerized real inference | `inference/main.py`, `Dockerfile.inference` | Ready/liveness distinction and valid prediction against trained artifact |
| Two inference replicas, ClusterIP, probes, requests/limits, ConfigMap | `kubernetes/` | Manifest validation plus actual rollout/API output when cluster available |
| Inspect Pods, deployments, services, logs/events/restarts/version | `kubernetes_tools.py` | Adapter tests and actual namespaced resource exports |
| Namespace restriction and no unauthorized mutation | Adapter, registry, namespaced read-only RBAC | Wrong-namespace and mutation denial tests |
| Structured natural-language API | `/agent/chat`, typed schemas, provider planner | Invalid request, tool selection and structured response tests |
| Mandatory four-system read-only reasoning | Orchestrator and adapters | MLflow → DVC lineage plus Kubernetes and Airflow trace; no trigger call |
| Evidence-grounded uncertainty and retraining recommendation | Orchestrator | Unavailable service test; explicit policy/gate/degradation support only |
| Actual LLM structured calls and labeled offline mode | Provider planner | Real Groq request/tool/usage evidence under `evidence/groq/`; per-conversation provider trace; offline labeled separately |
| At least 8 assignment tests and 20 master-prompt tests | `tests/unit/` | Actual current pytest summary, with skips and opt-in tests separated |
| Sanitized structured logs | `agent/logging.py` | Secret redaction and correlation tests |
| Two deliberately injected failures | `scripts/inject_failures.py` | Label simulations separately; preserve root cause, correction and rerun |
| PR lint/test CI and reproducible dependencies | Workflow, `pyproject.toml`, dependency lock if present | `ruff`, static checks and pytest locally; hosted Actions run/commit status separately recorded |
| Five conversations and report | Demo script and documentation | Timestamped transcripts and exact tool status for all five scenarios |
| No secrets or large runtime state | `.gitignore`, `.env.example`, source review | Tracked-file and secret scan before commit |

Screenshots are optional when the environment is headless; timestamped API/CLI exports provide auditable evidence. Fabricated images and synthetic transcripts are never labeled as real service verification.
