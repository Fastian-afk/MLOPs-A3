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
| Agent container | `evidence/runtime/final_app_image_build.json`, `final_app_container_smoke.json` (earlier build also retained) | Current source content-tagged image built; non-root read-only container health/authenticated 25-tool registry verified; per-file hashes record the uncommitted build snapshot honestly |
| MLflow service | `evidence/mlflow/server_health.json` | Real server health record; training/run exports supply metrics separately |
| Kubernetes provisioning | `evidence/kubernetes/current_runtime_cluster.json`, `runtime_cluster.json` | Fresh and historical real kind attempts blocked by host cgroup delegation; no cluster deployment claim |
| Remote Kubernetes route | `evidence/kubernetes/remote_live.json` | Actual authenticated request received upstream Envoy/plain-text HTTP 403 before Kubernetes; token/resource state remains unknown |
| Groq provider | `evidence/groq/provider_probe.json` | Real account model discovery and structured tool call returned HTTP 200 on `openai/gpt-oss-20b`, with request IDs and usage |
| Hosted CI | `evidence/runtime/github_actions.json`, [run 42398167839](https://github.com/Fastian-afk/MLOPs-A3/actions/runs/42398167839) | Public workflow completed successfully for source commit `f5baa78eb26168040107f18f38b383ee59f0ed9e`; later commits require separate verification |
| Inference image and serving | `evidence/kubernetes/inference_container.json`, `inference_clean_source_build.json` | Real non-root read-only Docker image; live/ready/version/predict HTTP 200, invalid payload 422; actual model lineage returned |
| DVC provenance/reproduction | `evidence/dvc/current_provenance.json`, `historical_reproduction.json`, `dirty_detection.json`, `mlflow_run_lineage.json`, `compare_changed_clone.json` | Real hash `3eacf7ec7241e7f914d7a1aca0346328`, clean→dirty→restored detection, changed-version comparison and actual run lineage; disposable clone at `a73a43ac9bc5a2adc25cd4b2ab8f8586c5480f3a` pulled and verified the dataset |
| Actual experiment runs | `evidence/mlflow/clean_source_runs.json`, `real_runs.json` | Five clean-source candidates plus historical setup runs and a live client integration test; best F1 0.92; registry available but empty |
| Workflow execution | `evidence/airflow/final_run.json`, `run_success.json` | Fresh published-runtime run `agent__a96b2260dc0c483e8d047eda0d4d706a` completed all five tasks successfully and produced its promotion manifest; earlier run retained |
| Conversations | `evidence/conversations/` | Per-conversation planner mode and per-tool result; mixed available/unavailable services remain visible |
| Failure investigations | `evidence/failures/` | Each record states actual execution versus simulation and recovery outcome |

The final command/test exports under `evidence/` establish executed commands, exit codes, durations and pass/fail counts. This report does not turn a planned command into verification merely by listing it.

## Commands and test outcomes

`evidence/validation.json` records the local CI-equivalent checks and opt-in live checks, including timestamps, durations and command exit status. The current recorded run completed:

| Command | Exit | Recorded outcome | Verification |
| --- | ---: | --- | --- |
| `.venv/bin/ruff check .` | 0 | All checks passed | Real static check |
| `.venv/bin/mypy` | 0 | No issues in the configured 3-file schema/configuration/permissions scope | Real static check; not a claim of whole-repository type checking |
| `.venv/bin/python -m pytest -q tests/unit` | 0 | **132 passed**, 81 dependency deprecation warnings | CI-safe local/fixture tests; external services mocked |
| `.venv/bin/python scripts/verify_submission.py` | 0 | Required files present; configured secret scan had no findings | Real repository check at recorded revision |
| `RUN_INTEGRATION=1 .venv/bin/python -m pytest -q tests/integration` | 0 | **3 passed, 1 skipped** | Real MLflow/Airflow; the additional remote-cluster target needs its own explicit opt-in |
| `RUN_INTEGRATION=1 .venv/bin/python -m pytest -q tests/e2e` | 0 | **2 passed** | Real authenticated local agent and inference; does not prove Kubernetes health |
| `RUN_INTEGRATION=1 RUN_REMOTE_KUBERNETES=1 .venv/bin/python -m pytest -q tests/integration/test_kubernetes_remote_live.py` | 1 | **1 failed**, classified `BLOCKED` | Actual upstream policy denial; no cluster result, `evidence/kubernetes/remote_live_test.json` |
| `bash scripts/bootstrap.sh` | 0 | Repeated frozen sync, matching data hash, DVC cache/remote preparation | Real idempotence check, `evidence/runtime/setup.json` |
| `docker compose config --quiet` | 0 | Syntax and variable interpolation accepted | Real configuration check only, `evidence/runtime/compose_config.json` |

`tests/conftest.py` skips integration/e2e targets unless `RUN_INTEGRATION=1`; the remote workload target additionally requires `RUN_REMOTE_KUBERNETES=1`. Standard CI selects only `tests/unit`. The separate explicit remote test was run and failed on the diagnosed upstream denial; it is not counted as a passing or silently disabled cluster check. A successful hosted GitHub Actions run was also observed for the source commit linked above; this is separate from the local results and does not automatically cover later commits. The Compose configuration check does not establish that the complete Compose stack was started successfully.

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

The current five exports under `evidence/conversations/groq/` were executed against the actual authenticated local API. Four informational requests made real Groq structured-planning calls using `openai/gpt-oss-20b`. The write proposal/confirmation path intentionally used no provider call: model output is not write authority. Earlier explicitly labeled offline exports remain in `evidence/conversations/` as historical evidence.

| Scenario | Actual result | Provider request / evidence |
| --- | --- | --- |
| Dataset provenance | `VERIFIED_REAL`: actual run lineage/hash and safe reproduction-plan tool succeeded. The returned reproduction commands are explicitly a plan; separate DVC exports verify actual historical retrieval. | `req_01m6vn5q1veeeadxrvt9gdvwzg`, 1,987 tokens; `groq/01_dataset_provenance.json` |
| Model selection | `VERIFIED_REAL`: completed-run F1 ranking returned five recorded candidates and the best run, with a production-readiness caveat. | `req_01m6vn6my9ex0ra3znj75bvxxh`, 1,500 tokens; `groq/02_model_selection.json` |
| Pipeline execution | `VERIFIED_REAL`: proposal made no write; confirmed trigger created actual run `agent__de2ee8afc6354414b6d9d0d673f77205`; authenticated polling reached `success` with all five tasks successful. No provider request was needed for this explicit safety flow. | `groq/03_pipeline_execution.json` |
| Deployment diagnosis | `BLOCKED` operationally: the real provider selected Kubernetes reads, but they received `NETWORK_POLICY_DENIED`; a dependent Pod lookup returned `REFERENCE_UNAVAILABLE` rather than inventing a Pod name. | `req_01m6vn7jtyedhsafkzbh26b6a6`, 1,747 tokens; `groq/04_deployment_diagnosis.json` |
| Mandatory integrated request | `BLOCKED` for complete infrastructure verification: actual MLflow/DVC/Airflow results and Kubernetes route failures were correlated, without a trigger or proposed action. | `req_01m6vn8hveenrs23xycmsyy7gt`, 3,541 tokens; `groq/05_integrated.json` |

The integrated investigation covers all four adapters while preserving Kubernetes failures. Its actual provider plan selected model ranking, dependent DVC provenance and Kubernetes reads. The trace separately identifies server coverage additions (`dvc.provenance`, `kubernetes.deployment_version`, `airflow.list_runs`); those reads are not misrepresented as provider-selected actions. No freshness policy or measured degradation establishes a retraining requirement, and the informational scenario performed no mutation. A successful provider request does not turn blocked infrastructure checks into successful deployment evidence.

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

This is actual application-container behavior and recovery, not a real Kubernetes probe/rollout incident. The cluster portion remains blocked by the cloud host prerequisite and the separate remote upstream route denial.

### Additional Kubernetes service-selector mismatch (`VERIFIED_MOCKED`)

`evidence/failures/kubernetes_selector_mocked.json` injects a Service selector changing `app=inference` to `app=injected-wrong-selector` in controlled Kubernetes API fixtures. The adapter observes zero matching Pods and no ready endpoints, diagnoses the selector/routing failure, then confirms that restoring the selector restores the ready address. This verifies diagnosis and correction logic against mocked transport responses. It is not a real cluster incident; the host blocker above prevents that claim.

## Limitations and engineering judgment

The cloud kind host prerequisite and remote upstream policy denial limit live Kubernetes and cluster fault evidence. Groq authentication/tool calling has real evidence, while each higher-level conversation still requires its own provider/tool trace and can remain partly blocked by Kubernetes. In-memory confirmations suit the documented single-process demo; production requires an atomic shared store and identity-backed authorization. Small synthetic holdout metrics do not prove external model quality or drift. Joblib artifacts are trusted pipeline outputs, never arbitrary uploads.

[README.md](README.md) supplies startup/authentication, DVC remote and cleanup instructions. [LIMITATIONS.md](LIMITATIONS.md) records prerequisites and production gaps. [RUBRIC_CHECKLIST.md](RUBRIC_CHECKLIST.md) maps all 100 rubric marks to source/tests/evidence without guaranteeing a score. A fully complete service criterion still needs its actual real-service evidence.

## Groq provider extension

The `groq` planner uses the fixed Groq OpenAI-compatible endpoint and its own `MLOPS_GROQ_API_KEY`. Current-runtime model discovery returned HTTP 200, request `req_01m6vmc5jpex2884c09es370n4`. The configured `llama-3.3-70b-versatile` was absent from the available model list. A real structured read-tool call using `openai/gpt-oss-20b` returned HTTP 200, request `req_01m6vmc5pveqj8pxtawhf68ymx`, completion `chatcmpl-1d1af902-f6dc-4d18-937d-3693ad77c36a`, and 209 total tokens. The recorded account advertised 8,000 tokens/minute and 1,000 requests/day; these are timestamped observations, not guarantees for other accounts. Groq uses one bounded `plan_read_tools` structured call to select ordered reads, reducing repeated schema/token overhead; the OpenAI route retains iterative calls. The server validates the advertised tool catalog, denies writes before execution, validates each typed argument, and resolves only fixed references such as `$best_run.run_id` from actual previous results. Responses include provider/model/request/completion IDs, token usage, planned/executed steps and any separately labeled coverage-guard reads. A model-generated plan never supplies confirmation authority or operational facts.

An initial real provider plan (`evidence/groq/selection_initial_invalid_arguments.json`, request `req_01m6vmsk2teqzas51mgvc141hr`) requested an uppercase `F1` comparison with an empty run-ID array. MLflow listing succeeded, but server validation rejected the comparison as `INVALID_REQUEST`; no winning metric was invented. The catalog guidance was corrected to use recorded lowercase `f1` and the existing best-run ranking tool for this prompt. The actual corrective rerun (`evidence/groq/selection.json`, request `req_01m6vmzn8ceettxfm8gcqjzf7w`) selected `mlflow.best_run`, returned the recorded run339/F1 0.92 and used 1,412 total tokens. The failed attempt is preserved as failed rather than replaced with mocked success. Mocked provider tests independently cover malformed plans, credential separation, budget and mutation denial. See `evidence/groq/` and [NEXT_STEPS.md](NEXT_STEPS.md).

## Remote Kubernetes connection preparation

The optional HTTPS API-origin mode uses an isolated Kubernetes client with verified TLS, inherited proxy/CA settings and a separate namespaced read-only token. Fifteen additional tests cover origin validation, missing credentials, credential redaction, proxy/TLS configuration and the unchanged kubeconfig route. The endpoint and read-only credential were configured and observed ready in the published runtime. Nevertheless, actual requests received an upstream Envoy HTTP 403/plain-text policy denial before any Kubernetes JSON response. Authenticated read access, deployment state and cluster faults therefore remain unverified. This is not evidence of an invalid token. `WINDOWS_KUBERNETES.md` records the connection procedure; the native `scripts/windows_deploy.ps1` supplies a separate operator-authorized local verification path. Windows execution remains the responsibility of that host, not a claimed cloud result.

## Self-contained Windows inference fixture

`demo_artifacts/model.joblib` is the exact 2,686-byte trusted model from real clean-source run `339b16bb4dc3467aa6004ff170f7f504`. Its manifest records SHA256 `4958e4b3b1765d5aca1d4e4f7f14df4b0335d8f0a8cb75dee79326223231f271`, F1 0.92, the passed 0.8 gate, dataset hash and training commit `5a35d39d1d0e7041ca78a5d0c416f05c9d15d5c8`. It is deliberately tiny example data, not a large model/artifact store. The Windows helper checks the hash before copying it into an image, requires committed deployment source for the immutable image tag, and preserves any differing existing serving artifact. Its image tag identifies the checkout used to build the service; the model's training source remains separately recorded. No new training run or provenance label is invented.

The explicit `-ConfirmDeploy` helper path checks two ready replicas and runs a probe Pod against ClusterIP/DNS, with an optional separately authorized selector failure and recovery. This prepares real local verification without giving the conversational agent write permissions. PowerShell 7.5.4 parser validation and three native-command mocked control-flow cases passed: confirmation denial with no writes, deployment/selector-fault/recovery, and error-path cleanup. `evidence/runtime/windows_helper_validation.json` is explicitly `VERIFIED_MOCKED` on Linux, not a real Windows/cluster run. This is distinct from executing it against a real Windows cluster.

The final app-image check built the actual in-progress source snapshot, tagged by its content hash, in 44.437 seconds. `evidence/runtime/final_app_image_build.json` records `source_dirty=true` because the final submission commit had not yet been made, plus file hashes that identify the build inputs. Its actual image `sha256:02c81f95f93658acb60e91fd6ef9767d34c0ed6641f9841cec62552b70d11497` passed health HTTP 200, unauthenticated inventory HTTP 401 and authenticated 25-tool inventory HTTP 200 in a non-root read-only container, then was removed (`final_app_container_smoke.json`). No provider or Kubernetes credential was passed to that container, so this container smoke is not live-provider or cluster verification. Later commits do not rewrite the recorded build provenance.
