import hashlib
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml

from agent.tools.dvc_tools import (
    CompareInput,
    DatasetInput,
    DvcTools,
    EmptyInput,
    ProvenanceInput,
    ReproduceInput,
)


@pytest.fixture
def dvc_repo(tmp_path):
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "Test User")
    git("config", "user.email", "test@example.invalid")
    (tmp_path / "data").mkdir()
    (tmp_path / ".dvc").mkdir()
    (tmp_path / ".dvc/config").write_text('[\'remote "local"\']\n    url = /safe/local/remote\n')
    data = tmp_path / "data/dataset.csv"
    data.write_text("feature,target\n1,0\n")
    first_hash = hashlib.md5(data.read_bytes(), usedforsecurity=False).hexdigest()
    metadata = tmp_path / "data/dataset.csv.dvc"
    metadata.write_text(yaml.safe_dump({"outs": [{"md5": first_hash, "path": "dataset.csv"}]}))
    git("add", ".")
    git("commit", "-m", "first")
    first = git("rev-parse", "HEAD")
    return DvcTools(tmp_path, "http://mlflow.invalid"), data, metadata, first, git


def test_list_reads_actual_metadata_and_remote_names(dvc_repo):
    tools, _, _, sha, _ = dvc_repo
    result = tools.list_datasets(EmptyInput())
    assert result["git_commit"] == sha
    assert result["datasets"][0]["dataset"] == "data/dataset.csv"
    assert result["remotes"] == ["local"]


def test_dirty_data_is_detected_without_trusting_git(dvc_repo):
    tools, data, _, _, _ = dvc_repo
    assert tools.provenance(ProvenanceInput())["dirty"] is False
    data.write_text("feature,target\n2,1\n")
    assert tools.provenance(ProvenanceInput())["dirty"] is True


def test_missing_metadata_is_explicit(dvc_repo):
    tools, _, metadata, _, _ = dvc_repo
    metadata.unlink()
    with pytest.raises(FileNotFoundError, match="metadata_missing"):
        tools.provenance(ProvenanceInput())


@pytest.mark.parametrize("revision", ["--help", "HEAD;echo bad", "../main", "main..HEAD"])
def test_invalid_revision_rejected(revision):
    with pytest.raises(ValueError):
        ProvenanceInput(revision=revision)


@pytest.mark.parametrize("dataset", ["../secret", "/etc/passwd", "data/../../secret", "other/file"])
def test_invalid_dataset_path_rejected(dataset):
    with pytest.raises(ValueError):
        DatasetInput(dataset=dataset)


def test_compare_reads_two_real_git_snapshots(dvc_repo):
    tools, data, metadata, first, git = dvc_repo
    data.write_text("feature,target\n9,1\n")
    metadata.write_text(yaml.safe_dump({"outs": [{"md5": hashlib.md5(data.read_bytes(), usedforsecurity=False).hexdigest(),
                                                "path": "dataset.csv"}]}))
    git("add", ".")
    git("commit", "-m", "second")
    result = tools.compare_versions(CompareInput(old_revision=first))
    assert result["changed"] is True
    assert result["old"]["git_commit"] == first


def test_run_lineage_reads_recorded_tags(dvc_repo):
    tools, _, _, first, _ = dvc_repo
    expected = tools.provenance(ProvenanceInput())["dvc_hash"]
    client = SimpleNamespace(get_run=lambda run_id: SimpleNamespace(data=SimpleNamespace(tags={
        "dataset.path": "data/dataset.csv", "dataset.hash": expected, "dataset.git_revision": first})))
    with patch("mlflow.tracking.MlflowClient", return_value=client):
        result = tools.provenance(ProvenanceInput(run_id="a" * 32))
    assert result["lineage_match"] is True
    assert result["git_commit"] == first


def test_reproduction_plan_does_not_claim_execution(dvc_repo):
    tools, _, _, _, _ = dvc_repo
    result = tools.reproduce_version(ReproduceInput())
    assert result["executed"] is False
    assert result["verified"] is False
    assert result["commands"][-1] == ["dvc", "pull", "data/dataset.csv.dvc"]


def test_reproduction_missing_remote_is_unavailable(dvc_repo):
    tools, _, _, _, _ = dvc_repo
    original = tools.command

    def fail_pull(argv, **kwargs):
        if argv[:2] == ["dvc", "pull"]:
            raise RuntimeError("dvc_pull_failed")
        return original(argv, **kwargs)

    with patch.object(tools, "command", side_effect=fail_pull):
        result = tools.reproduce_version(ReproduceInput(execute=True))
    assert result["verified"] is False
    assert "could not be pulled" in result["limitation"]


def test_command_allowlist_rejects_arbitrary_execution(dvc_repo):
    tools, *_ = dvc_repo
    with pytest.raises(PermissionError):
        tools.command(["git", "push", "origin", "main"])


def test_symlink_escape_rejected(dvc_repo, tmp_path):
    tools, _, _, _, _ = dvc_repo
    outside = tmp_path.parent / "outside.csv"
    outside.write_text("private")
    (tools.root / "data/escape.csv").symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        tools.safe_path("data/escape.csv")
