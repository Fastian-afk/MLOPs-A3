# Tiny trusted inference fixture

`model.joblib` is the exact small quality-gated model from the real training run
identified in `metadata.json`. Its bytes, SHA256, original training Git commit,
dataset hash and recorded metrics are preserved. Later packaging/documentation
commits do not relabel the model as freshly trained. This tiny fixture makes the
Windows Kubernetes demonstration self-contained without a registry credential or
Python installation on Windows; large datasets/models and runtime stores remain
excluded from Git.

`scripts/windows_deploy.ps1` verifies its checksum before copying it into the
ignored Docker build artifact directory. A changed fixture requires a new
reviewed manifest and image. The joblib format is pickle-compatible: load only
this trusted pipeline-produced artifact, never arbitrary uploaded models.

To refresh after a separately verified real training/promotion run:

```bash
python -m scripts.prepare_windows_demo --replace
```

Review both the model hash and original training lineage before committing.
