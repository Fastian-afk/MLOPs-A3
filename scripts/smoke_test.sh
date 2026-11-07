#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="$PWD/.venv/bin:$PATH"
python - <<'PY'
import os
import httpx
token = os.environ.get('MLOPS_API_TOKEN')
if not token:
    raise SystemExit('Set MLOPS_API_TOKEN before smoke testing the protected agent')
agent = os.environ.get('AGENT_URL', 'http://127.0.0.1:8000')
inference = os.environ.get('INFERENCE_URL', 'http://127.0.0.1:8001')
for url in [agent+'/health', inference+'/health/live', inference+'/health/ready']:
    response = httpx.get(url, timeout=10); response.raise_for_status()
    print(url, response.status_code, response.json())
response = httpx.post(inference+'/predict', json={'instances': [[0.0]*8]}, timeout=10)
response.raise_for_status()
assert len(response.json()['predictions']) == 1
response = httpx.post(agent+'/agent/chat', headers={'Authorization': 'Bearer '+token},
                      json={'message':'Compare the latest five runs by F1', 'session_id':'smoke'}, timeout=90)
response.raise_for_status()
assert any(e['status']=='ok' and e['tool']=='mlflow.best_run' for e in response.json()['evidence'])
print('Inference and real MLflow-backed agent functional requests passed')
PY
