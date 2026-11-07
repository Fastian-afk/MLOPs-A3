#!/usr/bin/env bash
# Explicit operator workflow: creates a local cluster and deploys the quality-gated artifact.
set -euo pipefail
cd "$(dirname "$0")/.."
command -v kind >/dev/null || { echo 'Install kind from https://kind.sigs.k8s.io/ with checksum verification' >&2; exit 1; }
command -v kubectl >/dev/null || { echo 'Install kubectl from https://kubernetes.io/docs/tasks/tools/' >&2; exit 1; }
test -f artifacts/model.joblib || { echo 'Run scripts/bootstrap.sh and train a passing model first' >&2; exit 1; }
revision="$(git rev-parse --verify HEAD)"
image="mlops-inference:${revision}"
cluster="${KIND_CLUSTER_NAME:-mlops-assignment}"
docker_build_args=()
if [[ -n "${CODEX_PROXY_CERT:-}" ]]; then
  docker_build_args+=(--secret "id=proxy_ca,src=${CODEX_PROXY_CERT}")
fi
docker build "${docker_build_args[@]}" -f Dockerfile.inference -t "$image" .
if ! kind get clusters | rg -x "$cluster" >/dev/null; then
  kind create cluster --name "$cluster" --wait 120s
fi
kind load docker-image "$image" --name "$cluster"
context="kind-${cluster}"
kubectl --context "$context" apply -f kubernetes/namespace.yaml
kubectl --context "$context" apply -f kubernetes/configmap.yaml -f kubernetes/service.yaml -f kubernetes/rbac.yaml
run_id="$(python -c 'import joblib; print(joblib.load("artifacts/model.joblib")["metadata"]["run_id"])')"
kubectl set image --local -f kubernetes/deployment.yaml "inference=${image}" -o yaml \
  | kubectl annotate --local -f - "mlops.model-run-id=${run_id}" "mlops.git-commit=${revision}" -o yaml \
  | kubectl --context "$context" apply -f -
kubectl --context "$context" -n mlops rollout status deployment/inference --timeout=120s
kubectl --context "$context" -n mlops get pods,deployments,services,endpoints -o wide
echo 'Ready. For local validation: kubectl --context '"$context"' -n mlops port-forward service/inference 8001:80'
