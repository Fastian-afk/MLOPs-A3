# Real Airflow quality gate failure and recovery

Status: **VERIFIED_REAL**, Airflow 3.1.0 with authenticated API v2 and actual
LocalExecutor task processes. These are not mocked incidents.

- Baseline run `agent__73187a545f374db085252d1a314eea8b` completed all five
  tasks successfully: [run_success.json](../airflow/run_success.json).
- Injection: operator explicitly triggered `mlops_training` with
  `f1_threshold=1`. The held-out F1 was `0.9019607843137255`, so the quality
  gate raised `quality_gate_failed: promotion blocked`.
- Failed run `agent__9d6153721b8248038695a2561e15065b` passed validation,
  preprocessing, training and evaluation, then failed its quality gate after
  **two attempts** (one configured retry). No promotion manifest exists in its
  isolated run directory. The authenticated task diagnostics include the actual
  failure log: [airflow_gate_failure.json](airflow_gate_failure.json).
- Correction: reset the operator-supplied threshold to the documented `0.8`;
  no source code or test assertions were changed.
- Recovery run `agent__62dcf42e5efd4fb48bc95cc0cdd45782` completed all five
  tasks successfully and produced its own promotion manifest:
  [airflow_gate_recovery.json](airflow_gate_recovery.json).

Reproduce from the repository root while the documented MLflow and Airflow
services run:

```bash
.venv/bin/python -m scripts.verify_airflow --confirm-trigger --threshold 1 \
  --expect-state failed --output evidence/failures/airflow_gate_failure.json
.venv/bin/python -m scripts.verify_airflow --confirm-trigger --threshold .8 \
  --expect-state success --output evidence/failures/airflow_gate_recovery.json
```

Run IDs and timestamps will differ. `--confirm-trigger` records deliberate
operator authorization; an informational agent request does not call this script.
Models and generated authentication files remain in ignored runtime directories.
