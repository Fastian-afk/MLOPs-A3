#!/usr/bin/env bash
# Separate environment preserves Apache's tested dependency constraints.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_root/.runtime/uv-cache}"
mkdir -p .runtime/airflow
curl -fsS --max-time 60 \
  https://raw.githubusercontent.com/apache/airflow/constraints-3.1.0/constraints-3.12.txt \
  -o .runtime/airflow/constraints-3.12.txt
if [[ ! -x .venv-airflow/bin/python ]]; then
  uv venv .venv-airflow --python 3.12
fi
uv pip install --python .venv-airflow/bin/python \
  'apache-airflow==3.1.0' --constraint .runtime/airflow/constraints-3.12.txt
uv pip install --python .venv-airflow/bin/python \
  'mlflow-skinny==3.5.1' 'scikit-learn==1.7.2' pandas 'joblib==1.5.2' \
  --constraint .runtime/airflow/constraints-3.12.txt
uv pip check --python .venv-airflow/bin/python
