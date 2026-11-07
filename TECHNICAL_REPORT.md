# Technical report: production-oriented MLOps agent

## Scope and architecture

The system implements the assignment's four operational modules behind one typed conversational API. A deterministic CPU classification pipeline provides real data, models and metrics. FastAPI accepts requests; an orchestration layer selects registry tools; validated adapters query DVC/Git, MLflow, Airflow 3 and Kubernetes. Every operational answer includes tool evidence and uncertainty. [architecture.md](architecture.md) contains the control/data-flow diagram, sequence and trust boundaries.

The repository was intentionally empty at the start. The implementation follows the original assignment and the supplied master brief; it does not assume the illustrative dataset version, experiment ID or Git SHA in the assignment are real.

## Implementation inventory and permissions

| Module | Implemented tool responsibilities | Permission |
| --- | --- | --- |
| DVC | List datasets, retrieve recorded provenance, compare revisions, detect changes, explain/verify historical reproduction | Read repository/data; bounded disposable-clone reproduction |
| MLflow | List experiments/runs, details/artifacts, metric-specific best run, compare runs, registry metadata | Read tracking/registry API |
| Airflow 3 | List DAGs/runs, status, approved training trigger, failed tasks, task diagnostics | Reads; trigger requires explicit bound confirmation |
| Kubernetes | Pods/deployments, service/endpoints, Pod health/logs/events, deployed version | Read-only approved namespace |
| Agent | Structured natural-language tools, offline test planner, evidence renderer, action proposal/confirmation | Validates all arguments and output contracts |
| Inference | Liveness/readiness, feature-validated prediction, actual model/version metadata | Serves a trusted quality-gated artifact |

Model-generated tool calls never grant write authority. The server binds a single-use, expiring confirmation to the authenticated user/session and exact action parameters; the adapter rechecks the approved DAG. Kubernetes mutations are deliberately absent. Least-privilege namespaced RBAC accompanies the deployment manifests.

## Reproducibility and selection policy

The sample is generated deterministically with eight numeric features, a binary target and fixed seed. A fixed stratified holdout is used across five logistic-regression regularization configurations. Training records parameters, accuracy, precision, recall, F1, source commit, dataset content hash, evaluation split and MLflow run ID. The serialized joblib artifact contains feature order and lineage metadata. An explicit F1 threshold controls promotion.

DVC content identity and the Git source/metadata reference are both retained. Historical reproduction operates in a disposable clone and requires actual cached/remote objects. The tracking-client selection excludes unsuccessful/incomplete or missing-metric runs; F1 is maximized and loss metrics minimized with deterministic ties. The highest experimental metric is only a candidate, not automatic production approval.

## Evidence record

Evidence labels distinguish `VERIFIED_REAL`, `VERIFIED_MOCKED`, `BLOCKED` and `FAILED`. Raw per-system evidence and conversation exports are the authority for concrete run IDs, commit hashes, metrics and timestamps. Screenshots were not fabricated; headless API/CLI exports are used.

| Capability | Evidence location | Verified interpretation |
| --- | --- | --- |
| Airflow 3 DAG import | `evidence/airflow/dag_import.json` | Real Airflow 3.1.0 import, no import errors, required five tasks and bounded retries |
| Airflow authenticated API | `evidence/airflow/api_dags.json` | Real SimpleAuthManager login and `/api/v2` DAG response; listing alone does not prove a completed run |
| Agent container | `evidence/runtime/app_image_build.json`, `app_container_smoke.json` | Real frozen-lock image build; non-root read-only container health and authenticated 25-tool registry verified |
| MLflow service | `evidence/mlflow/server_health.json` | Real server health record; training/run exports supply metrics separately |
| Kubernetes provisioning | `evidence/kubernetes/runtime_cluster.json` | Real attempt blocked by host cgroup delegation; no cluster deployment claim |
| Inference image and serving | `evidence/kubernetes/inference_container.json`, `inference_clean_source_build.json` | Real non-root read-only Docker image; live/ready/version/predict HTTP 200, invalid payload 422; actual model lineage returned |
| DVC provenance/reproduction | `evidence/dvc/current_provenance.json`, `historical_reproduction.json`, `dirty_detection.json`, `mlflow_run_lineage.json`, `compare_changed_clone.json` | Real hash `3eacf7ec7241e7f914d7a1aca0346328`, clean→dirty→restored detection, changed-version comparison and actual run lineage; disposable clone at `a73a43ac9bc5a2adc25cd4b2ab8f8586c5480f3a` pulled and verified the dataset |
| Actual experiment runs | `evidence/mlflow/clean_source_runs.json`, `real_runs.json` | Five clean-source candidates plus historical setup runs and a live client integration test; best F1 0.92; registry available but empty |
| Workflow execution | `evidence/airflow/run_success.json` | Real run `agent__73187a545f374db085252d1a314eea8b`: all five tasks succeeded, F1 0.9019607843 and promotion manifest present |
| Conversations | `evidence/conversations/` | Per-conversation planner mode and per-tool result; mixed available/unavailable services remain visible |
| Failure investigations | `evidence/failures/` | Each record states actual execution versus simulation and recovery outcome |

The final command/test exports under `evidence/` establish executed commands, exit codes, durations and pass/fail counts. This report does not turn a planned command into verification merely by listing it.

## Commands and test outcomes

`evidence/validation.json` records the local CI-equivalent checks and opt-in live checks, including timestamps, durations and command exit status. The current recorded run completed:

| Command | Exit | Recorded outcome | Verification |
| --- | ---: | --- | --- |
| `.venv/bin/ruff check .` | 0 | All checks passed | Real static check |
| `.venv/bin/mypy` | 0 | No issues in the configured 3-file schema/configuration/permissions scope | Real static check; not a claim of whole-repository type checking |
| `.venv/bin/python -m pytest -q tests/unit` | 0 | **109 passed**, 72 dependency deprecation warnings | CI-safe local/fixture tests; external services mocked |
| `.venv/bin/python scripts/verify_submission.py` | 0 | Required files present; configured secret scan had no findings | Real repository check at recorded revision |
| `RUN_INTEGRATION=1 .venv/bin/python -m pytest -q tests/integration` | 0 | **3 passed** | Real MLflow and Airflow services |
| `RUN_INTEGRATION=1 .venv/bin/python -m pytest -q tests/e2e` | 0 | **2 passed** | Real authenticated local agent and inference; does not prove Kubernetes health |
| `bash scripts/bootstrap.sh` | 0 | Repeated frozen sync, matching data hash, DVC cache/remote preparation | Real idempotence check, `evidence/runtime/setup.json` |
| `docker compose config --quiet` | 0 | Syntax and variable interpolation accepted | Real configuration check only, `evidence/runtime/compose_config.json` |

`tests/conftest.py` skips integration/e2e targets unless `RUN_INTEGRATION=1`; standard CI selects only `tests/unit`. Actual hosted GitHub Actions execution is separate from these local results. The Compose configuration check does not establish that the complete Compose stack was started successfully.

## Actual five-run experiment comparison

After committing the operational source, `evidence/mlflow/clean_source_runs.json` records five completed HTTP-backed MLflow runs against commit `5a35d39d1d0e7041ca78a5d0c416f05c9d15d5c8`. All five record `git.dirty=false`, the same verified dataset hash and fixed holdout:

| Regularization C | Run ID | F1 |
| ---: | --- | ---: |
| 0.01 | `7f9d279eb0fd4972bb71ac01487622af` | 0.8431372549 |
| 0.1 | `591d770491ed49a6b3cb9a0ea893702f` | 0.8823529412 |
| 1.0 | `163628ee0dea430d805ab965cd98e4f1` | 0.9019607843 |
| 10.0 | `50098d1677434c79b901658b9edeb74b` | 0.92 |
| 100.0 | `339b16bb4dc3467aa6004ff170f7f504` | 0.92 |

The clean-source comparison selected `339b16bb4dc3467aa6004ff170f7f504` deterministically, passed the 0.8 gate and logged the real model plus metadata artifacts. Documentation/evidence added afterward do not change that recorded training-source identity. The registry endpoint works but contains no registered models. The live MLflow integration check passed one test as part of the three-test integration suite.

The earlier `evidence/mlflow/real_runs.json` remains historical evidence: it records the initial commit `a73a43ac9bc5a2adc25cd4b2ab8f8586c5480f3a`, explicitly `git.dirty=true` during implementation fixes, and selected run `00f3a8f527ca4c4bbee3fc421d6780cf` with the same F1 0.92. The current container, readiness-fault and conversation exports were independently rerun against the clean-source model. Historical exports in Git history retain their original run/source references; no old result is relabeled as a new execution.

## Five demonstration conversations

All five were executed against the actual authenticated local API in labeled `offline` deterministic-planner mode. The API calls themselves are real; no LLM-provider execution is claimed.

| Scenario | Actual result | Evidence |
| --- | --- | --- |
| Dataset provenance | `VERIFIED_REAL`: run lineage/hash and dirty-state query succeeded; returned historical reproduction commands are explicitly a plan, while separate DVC evidence verifies actual reproduction | `evidence/conversations/01_dataset_provenance.json` |
| Model selection | `VERIFIED_REAL`: completed-run F1 ranking with production-readiness caveat | `evidence/conversations/02_model_selection.json` |
| Pipeline execution | `VERIFIED_REAL`: proposal made no write; confirmed trigger produced actual run `agent__a1056bcc558740cd859ee9eb41e5d540`, authenticated polling reached `success` | `evidence/conversations/03_pipeline_execution.json` |
| Deployment diagnosis | `BLOCKED`: Kubernetes calls returned service unavailable; answer correctly states operational status is unknown | `evidence/conversations/04_deployment_diagnosis.json` |
| Mandatory integrated request | `BLOCKED` for complete infrastructure verification: actual MLflow/DVC/Airflow data collected, Kubernetes unavailable, no trigger or proposed action | `evidence/conversations/05_integrated.json` |

The integrated trace covers all four adapters and preserves Kubernetes failures rather than inventing deployment health. No configured freshness threshold or measured degradation establishes a retraining requirement. Actual provider-based structured LLM calling remains blocked by missing credentials and is tested separately with mocked provider responses.

The exact prompts, repeatable recording command and five-minute defense procedure are in [DEMO_GUIDE.md](DEMO_GUIDE.md). Local startup via `python -m scripts.run_local` was tested with real services; the helper stores credentials in ignored runtime files, reuses healthy services, and stops only processes it owns. Bootstrap was executed twice to verify the frozen dependency/DVC setup is idempotent.

## Failure investigations and corrections

### Environment discovery: rootless cluster creation

The Docker daemon is functional, and kind/kubectl downloads were checksum-verified. Actual kind cluster creation failed because rootless operation requires the host systemd property `Delegate=yes`. A user systemd scope was unavailable, and the same kind command outside the sandbox failed for the same reason. The root cause is a host capability prerequisite, not invalid application YAML. The safe next action is a suitable delegated host or an existing authorized cluster; no host isolation was weakened. See `evidence/kubernetes/runtime_cluster.json`.

### Dependency compatibility discovered during setup

Unconstrained DVC transitive `pathspec` 1.1.1 caused an internal `_DIR_MARK` import failure. MLflow was incompatible with SQLAlchemy 2.1 in this environment. Setup pins `pathspec==0.12.1` and `SQLAlchemy==2.0.44`, reruns the affected operations and retains the constraints in the reproducible dependency configuration. The Airflow environment separately follows official 3.1.0/Python 3.12 constraints and uses the official `mlflow-skinny` client to avoid overriding its cryptography requirement. Its idempotent install and dependency compatibility check passed for 141 installed packages (`evidence/airflow/commands.json`).

A further actual MLflow run (`a967c64ac9e542f8ba83ae6a78f7ef3d`) failed during artifact upload because the SDK artifact resolver consulted the process-default file URI even though `MlflowClient` used HTTP. Evaluation and adapter initialization now call the supported `mlflow.set_tracking_uri(tracking_uri)` before artifact operations. The five completed candidates in the historical `real_runs.json` are the successful corrective rerun; `clean_source_runs.json` records the later committed-source validation. The failed run remains marked failed in evidence.

### Deliberate fault A: Airflow quality-gate rejection (`VERIFIED_REAL`)

The actual DAG run `agent__9d6153721b8248038695a2561e15065b` used an injected F1 threshold of 1.0. Validation, preprocessing, training and evaluation succeeded; measured F1 was 0.9019607843. The `quality_gate` task retried once (`try_number: 2`) and then failed with `quality_gate_failed: promotion blocked`. The run ended `failed`, and no promotion manifest existed for that run. This is the intended safety outcome, not a passing deployment. `evidence/failures/airflow_gate_failure.json` contains task timing, diagnostics and recorded MLflow lineage. The corrective action restored the stated 0.8 demonstration threshold and reran with explicit authorization. Recovery run `agent__62dcf42e5efd4fb48bc95cc0cdd45782` completed all five tasks successfully and created a promotion manifest (`evidence/failures/airflow_gate_recovery.json`). The recovery records `git.dirty=true` while implementation files were being edited; that provenance is preserved rather than presented as an immutable clean-source release.

### Deliberate fault B: model readiness failure (`VERIFIED_REAL` container)

`evidence/failures/inference_readiness_real.json` records a real read-only Docker container launched with `MODEL_PATH` deliberately pointing to an absent artifact. Liveness remained HTTP 200, while readiness and prediction returned HTTP 503 `MODEL_NOT_READY`; version correctly reported no loaded model. Recreating the container from the same immutable image without the bad path restored readiness/prediction to HTTP 200 and the same actual run ID `339b16bb4dc3467aa6004ff170f7f504`. The image ID was `sha256:30facc2dc0323805beece7232b61bd21149be0914ff64a1a9cff38bfdc9afba2`, running as user `10001:10001` with a read-only filesystem and dropped capabilities. All test containers were removed.

This is actual application-container behavior and recovery, not a real Kubernetes probe/rollout incident. That infrastructure portion remains blocked by the host prerequisite.

### Additional Kubernetes service-selector mismatch (`VERIFIED_MOCKED`)

`evidence/failures/kubernetes_selector_mocked.json` injects a Service selector changing `app=inference` to `app=injected-wrong-selector` in controlled Kubernetes API fixtures. The adapter observes zero matching Pods and no ready endpoints, diagnoses the selector/routing failure, then confirms that restoring the selector restores the ready address. This verifies diagnosis and correction logic against mocked transport responses. It is not a real cluster incident; the host blocker above prevents that claim.

## Limitations and engineering judgment

The known cluster-provisioning blocker limits live Kubernetes and cluster fault evidence. Provider credentials and reachable destinations are required before claiming real LLM integration. In-memory confirmations suit the documented single-process demo; production requires an atomic shared store and identity-backed authorization. Small synthetic holdout metrics do not prove external model quality or drift. Joblib artifacts are trusted pipeline outputs, never arbitrary uploads.

[README.md](README.md) supplies startup/authentication, DVC remote and cleanup instructions. [LIMITATIONS.md](LIMITATIONS.md) records prerequisites and production gaps. [RUBRIC_CHECKLIST.md](RUBRIC_CHECKLIST.md) maps all 100 rubric marks to source/tests/evidence without guaranteeing a score. A fully complete service criterion still needs its actual real-service evidence.

## Groq provider extension

The `groq` planner uses the fixed Groq OpenAI-compatible endpoint and its own `MLOPS_GROQ_API_KEY`. Three additional mocked tests verify endpoint/model selection, credential separation, missing-key handling and read-only integrated coverage. The current unit total is 109. Live Groq calls remain blocked until a key and applied network access are available; no provider success is claimed. See [NEXT_STEPS.md](NEXT_STEPS.md).
