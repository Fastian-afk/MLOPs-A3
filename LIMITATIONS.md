# Verification limits and deployment prerequisites

This project distinguishes implemented behavior from executed integrations. The authoritative current-instance records are the timestamped JSON/text files under `evidence/` and [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md). Test fixtures are never substituted for real infrastructure evidence.

## Confirmed environment blockers: Kubernetes

`evidence/kubernetes/current_runtime_cluster.json` records the fresh published-runtime attempt; `runtime_cluster.json` retains the earlier actual attempt. Docker is working, and downloaded kind/kubectl checksums were verified. kind cannot create its rootless cluster because the runtime lacks the required systemd cgroup delegation (`Delegate=yes`). A user systemd scope was also unavailable; repeating the same kind attempt outside the command sandbox did not resolve this host prerequisite.

Consequently, manifests and mocked Kubernetes adapter tests do not prove a real deployment, live Pod health, service routing, or a real cluster fault incident. Actual Docker inference, model readiness failure and recovery are verified separately in `evidence/kubernetes/inference_container.json` and `evidence/failures/inference_readiness_real.json`; container success is not cluster success. Use an existing authorized Kubernetes cluster through secure kubeconfig, or a Linux host with kind's documented cgroup v2/rootless delegation, then run `scripts/kind_demo.sh` and retain the rollout/prediction/API evidence. Do not weaken host isolation or modify cgroup permissions to make this demo pass.

The configured Windows kind API tunnel was also tested with the published credential and exact host allowlist. Both authenticated and unauthenticated requests received HTTP 403, `Server: envoy`, plain text `Your request was blocked.` before any Kubernetes JSON response. `evidence/kubernetes/remote_live.json` records this real upstream access failure. It does not prove the token is invalid, the cluster is empty, or the inference service is healthy/unhealthy. The client does not bypass the route policy, disable TLS or use alternate hostnames/IPs to evade it.

A native Windows helper, `scripts/windows_deploy.ps1 -ConfirmDeploy -InjectSelectorFailure`, prepares the existing local kind cluster and captures in-cluster Service prediction/fault/recovery evidence. Its reviewed, explicit operator path is separate from the read-only agent. Windows execution is still required before marking cluster criteria verified.

## Credentials and external services

The published Groq credential and allowed destination worked: real model discovery and a structured tool call returned HTTP 200, with request IDs and usage in `evidence/groq/provider_probe.json`. The configured `llama-3.3-70b-versatile` was absent from the available models; `openai/gpt-oss-20b` was verified instead. Model availability, rate limits and quotas remain account-specific. Use `--planner groq --groq-model openai/gpt-oss-20b` when launching the local helper to override a stale saved selection. Offline deterministic planning remains available and is never presented as live LLM execution. Configure all keys securely, never through Git or chat.

Airflow needs a running scheduler/API server, authenticated account and shared artifact storage. The adapter deliberately uses Airflow 3 `/api/v2`; an Airflow 2 server is not a substitute. MLflow needs the configured tracking URI and its artifact store. Access failures remain explicit uncertainty rather than invented infrastructure results.

DVC history is reproducible only while the corresponding objects exist in a cache or reachable remote. The deterministic generator reconstructs this sample configuration, but cannot reconstruct arbitrary historical user data. The checked-in metadata records actual content and Git references rather than imaginary labels.

## Development scope

- The HTTP API is a development service. Use loopback unless a secured deployment supplies TLS, authenticated users, identity-backed authorization, rate limits and audit retention.
- Confirmation state is in memory and single-process. A process restart invalidates pending tokens. Multiple API workers require an atomic shared confirmation store.
- Kubernetes tools are read-only and restricted to one approved namespace. Cluster restarts, edits and shell execution are not exposed. Operators perform necessary changes separately with their own authorized tooling.
- MLflow metrics use a deterministic holdout over a small synthetic sample. They demonstrate workflow correctness; they do not establish external validity, drift, fairness or production business quality.
- The joblib model loader trusts only artifacts produced by this pipeline. The committed 2,686-byte demo fixture is an exact recorded pipeline output with a SHA256 manifest; this is intentional small example data, not a large generated model store. Pickle-compatible formats can execute code and must not load untrusted uploads.
- Airflow's local SimpleAuthManager/standalone server and SQLite-backed local services are demonstration choices. Production requires managed authentication, durable databases, executor/storage design and backup/recovery.
- Inference images bundle the quality-gated artifact. A new model requires a new immutable image/build and an explicitly managed rollout; the agent does not auto-promote or deploy experimental winners.
- The service does not invent a retraining freshness threshold. Without an explicit policy, measured degradation or failed gate, it reports insufficient evidence to recommend retraining.

Screenshots are not fabricated. Headless execution may supply API/CLI exports instead. A saved environment configuration does not itself publish a new task snapshot, and hosted GitHub Actions must be checked for the intended commit. A real successful public run for source commit `f5baa78eb26168040107f18f38b383ee59f0ed9e` was observed; that does not automatically certify subsequent changes. The complete Compose stack has not been launched here; configuration validation and individual image/container checks are separate evidence.
