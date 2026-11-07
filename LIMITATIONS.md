# Verification limits and deployment prerequisites

This project distinguishes implemented behavior from executed integrations. The authoritative current-instance records are the timestamped JSON/text files under `evidence/` and [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md). Test fixtures are never substituted for real infrastructure evidence.

## Confirmed environment blocker: Kubernetes

`evidence/kubernetes/runtime_cluster.json` records an actual cluster-provisioning attempt. Docker is working, and downloaded kind/kubectl checksums were verified. kind cannot create its rootless cluster because the runtime lacks the required systemd cgroup delegation (`Delegate=yes`). A user systemd scope was also unavailable; repeating the same kind attempt outside the command sandbox did not resolve this host prerequisite.

Consequently, manifests and mocked Kubernetes adapter tests do not prove a real deployment, live Pod health, service routing, or a real cluster fault incident. Use an existing authorized Kubernetes cluster through secure kubeconfig, or a Linux host with kind's documented cgroup v2/rootless delegation, then run `scripts/kind_demo.sh` and retain the rollout/prediction/API evidence. Do not weaken host isolation or modify cgroup permissions to make this demo pass.

## Credentials and external services

The LLM provider requires a valid key and permitted HTTPS destination. Offline deterministic planning is provided for local tests; those transcripts are not real LLM-provider verification. Configure supported credentials securely through environment settings or an ignored local file, never through Git.

Airflow needs a running scheduler/API server, authenticated account and shared artifact storage. The adapter deliberately uses Airflow 3 `/api/v2`; an Airflow 2 server is not a substitute. MLflow needs the configured tracking URI and its artifact store. Access failures remain explicit uncertainty rather than invented infrastructure results.

DVC history is reproducible only while the corresponding objects exist in a cache or reachable remote. The deterministic generator reconstructs this sample configuration, but cannot reconstruct arbitrary historical user data. The checked-in metadata records actual content and Git references rather than imaginary labels.

## Development scope

- The HTTP API is a development service. Use loopback unless a secured deployment supplies TLS, authenticated users, identity-backed authorization, rate limits and audit retention.
- Confirmation state is in memory and single-process. A process restart invalidates pending tokens. Multiple API workers require an atomic shared confirmation store.
- Kubernetes tools are read-only and restricted to one approved namespace. Cluster restarts, edits and shell execution are not exposed. Operators perform necessary changes separately with their own authorized tooling.
- MLflow metrics use a deterministic holdout over a small synthetic sample. They demonstrate workflow correctness; they do not establish external validity, drift, fairness or production business quality.
- The joblib model loader trusts only artifacts produced by this pipeline. Pickle-compatible formats can execute code and must not load untrusted uploads.
- Airflow's local SimpleAuthManager/standalone server and SQLite-backed local services are demonstration choices. Production requires managed authentication, durable databases, executor/storage design and backup/recovery.
- Inference images bundle the quality-gated artifact. A new model requires a new immutable image/build and an explicitly managed rollout; the agent does not auto-promote or deploy experimental winners.
- The service does not invent a retraining freshness threshold. Without an explicit policy, measured degradation or failed gate, it reports insufficient evidence to recommend retraining.

Screenshots are not fabricated. Headless execution may supply API/CLI exports instead. A saved environment configuration does not itself publish a new task snapshot, and a local workflow definition does not prove that hosted GitHub Actions has run.
