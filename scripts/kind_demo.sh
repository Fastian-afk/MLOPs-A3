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
if ! kind get clusters | grep -Fxq -- "$cluster"; then
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
port="${INFERENCE_LOCAL_PORT:-8001}"
kubectl --context "$context" -n mlops port-forward service/inference "${port}:80" >/tmp/mlops-kind-port-forward.log 2>&1 &
forward_pid=$!
trap 'kill "$forward_pid" 2>/dev/null || true' EXIT
INFERENCE_LOCAL_PORT="$port" python - <<'PY'
import csv, json, os, time, urllib.request
base = 'http://127.0.0.1:' + os.environ['INFERENCE_LOCAL_PORT']
for attempt in range(30):
    try:
        with urllib.request.urlopen(base + '/health/ready', timeout=2) as response:
            assert response.status == 200
        break
    except (OSError, AssertionError):
        if attempt == 29:
            raise
        time.sleep(1)
with open('data/dataset.csv') as stream:
    row = next(csv.DictReader(stream))
features = [float(row[f'feature_{i}']) for i in range(8)]
request = urllib.request.Request(base + '/predict', data=json.dumps({'instances': [features]}).encode(),
                                 headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=10) as response:
    result = json.load(response)
assert len(result['predictions']) == 1
assert result['run_id']
print(json.dumps({'status': 'VERIFIED_REAL', 'prediction': result}, indent=2))
PY
echo 'Inference rollout and representative prediction passed.'
