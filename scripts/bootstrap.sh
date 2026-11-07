#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_root/.runtime/uv-cache}"
export DVC_SITE_CACHE_DIR="${DVC_SITE_CACHE_DIR:-$repo_root/.runtime/dvc-site}"
export DVC_NO_ANALYTICS=1
mkdir -p .runtime
uv sync --frozen --extra dev
export PATH="$repo_root/.venv/bin:$PATH"
if [[ ! -f data/dataset.csv ]]; then python -m scripts.prepare_data; fi
if [[ ! -d .dvc ]]; then dvc init; fi
python - <<'PY'
import hashlib
from pathlib import Path
import yaml
metadata = yaml.safe_load(Path('data/dataset.csv.dvc').read_text())
actual = hashlib.md5(Path('data/dataset.csv').read_bytes(), usedforsecurity=False).hexdigest()
if actual != metadata['outs'][0]['md5']:
    raise SystemExit('Generated dataset differs from committed DVC reference; refusing to rewrite metadata')
print('Dataset matches committed DVC reference:', actual)
PY
if ! dvc remote list | awk '{print $1}' | grep -qx local; then
  dvc remote add --local --default local "$repo_root/.dvc-remote"
fi
# Seed the deterministic demo cache without changing committed metadata.
dvc commit data/dataset.csv.dvc
dvc push -r local data/dataset.csv.dvc
echo 'Base dependencies and deterministic DVC data are prepared.'
echo 'Run bash scripts/install_airflow.sh to prepare the separately constrained Airflow runtime.'
