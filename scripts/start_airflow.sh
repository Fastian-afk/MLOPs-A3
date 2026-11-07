#!/usr/bin/env bash
# Airflow 3 standalone is development-only; run inside the dedicated Airflow venv.
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export AIRFLOW_HOME="${AIRFLOW_HOME:-$repo_root/.runtime/airflow}"
export AIRFLOW__CORE__DAGS_FOLDER="$repo_root/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False
export AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION=False
export AIRFLOW__CORE__AUTH_MANAGER=airflow.api_fastapi.auth.managers.simple.simple_auth_manager.SimpleAuthManager
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS="${AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS:-admin:admin}"
export AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_PASSWORDS_FILE="$AIRFLOW_HOME/simple_auth_manager_passwords.json"
export AIRFLOW__CORE__EXECUTION_API_SERVER_URL="${AIRFLOW__CORE__EXECUTION_API_SERVER_URL:-http://127.0.0.1:8080/execution/}"
export MLOPS_SHARED_DIR="${MLOPS_SHARED_DIR:-$repo_root/.runtime/training}"
export MLOPS_DATASET_PATH="${MLOPS_DATASET_PATH:-$repo_root/data/dataset.csv}"
export PYTHONPATH="$repo_root${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p "$AIRFLOW_HOME" "$MLOPS_SHARED_DIR"
if ! command -v airflow >/dev/null; then
  echo 'Airflow is missing. Activate .venv-airflow and install apache-airflow==3.1.0 using official Python-version constraints.' >&2
  exit 1
fi
airflow db migrate
exec airflow standalone
