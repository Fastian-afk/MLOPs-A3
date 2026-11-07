"""Read real DVC metadata and reproduce snapshots in disposable clones."""

import hashlib
import re
import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmptyInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetInput(EmptyInput):
    dataset: str = "data/dataset.csv"

    @field_validator("dataset")
    @classmethod
    def safe_dataset(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            raise ValueError("dataset_path_invalid")
        if value.startswith("-") or not value.startswith("data/"):
            raise ValueError("dataset_path_must_be_under_data")
        return value


class ProvenanceInput(DatasetInput):
    revision: str = "HEAD"
    run_id: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{32}$")
    expected_hash: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{32}$")

    @field_validator("revision")
    @classmethod
    def safe_revision(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,127}", value) or ".." in value:
            raise ValueError("git_revision_invalid")
        return value


class CompareInput(DatasetInput):
    old_revision: str
    new_revision: str = "HEAD"

    @field_validator("old_revision", "new_revision")
    @classmethod
    def safe_revision(cls, value: str) -> str:
        return ProvenanceInput.safe_revision(value)


class ReproduceInput(ProvenanceInput):
    execute: bool = False


class DatasetRecord(BaseModel):
    dataset: str
    metadata_path: str
    dvc_hash: str | None = None
    source: str


class DatasetList(BaseModel):
    datasets: list[DatasetRecord]
    git_commit: str
    remotes: list[str]


class ProvenanceOutput(BaseModel):
    dataset: str
    git_commit: str
    dvc_hash: str
    actual_hash: str | None
    dirty: bool | None
    metadata_dirty: bool
    metadata_path: str
    run_id: str | None
    lineage_match: bool | None
    remotes: list[str]


class CompareOutput(BaseModel):
    dataset: str
    old: ProvenanceOutput
    new: ProvenanceOutput
    changed: bool


class ChangesOutput(BaseModel):
    datasets: list[ProvenanceOutput]
    changed: bool
    dvc_status: dict


class ReproduceOutput(BaseModel):
    git_commit: str
    dataset: str
    dvc_hash: str
    executed: bool
    verified: bool
    commands: list[list[str]]
    limitation: str | None = None


class DvcTools:
    def __init__(self, root: Path, tracking_uri: str):
        self.root = Path(root).resolve()
        self.tracking_uri = tracking_uri

    def command(self, argv: list[str], cwd: Path | None = None, timeout: int = 30) -> str:
        allowed = {"git": {"rev-parse", "show", "status", "clone", "checkout"},
                   "dvc": {"status", "pull"}}
        if len(argv) < 2 or argv[0] not in allowed or argv[1] not in allowed[argv[0]]:
            raise PermissionError("command_not_allowlisted")
        result = subprocess.run(argv, cwd=cwd or self.root, capture_output=True,
                                text=True, timeout=timeout, check=False)
        if result.returncode:
            # Raw stderr can contain remote credentials; return a fixed error only.
            raise RuntimeError(f"{argv[0]}_{argv[1]}_failed")
        return result.stdout.strip()

    def commit(self, revision: str = "HEAD") -> str:
        ProvenanceInput.safe_revision(revision)
        return self.command(["git", "rev-parse", "--verify", f"{revision}^{{commit}}"])

    def remotes(self) -> list[str]:
        config = self.root / ".dvc/config"
        if not config.exists():
            return []
        return re.findall(r"\[\s*'remote\s+\"([^\"]+)\"'\s*\]", config.read_text())

    def safe_path(self, dataset: str) -> Path:
        DatasetInput.safe_dataset(dataset)
        path = (self.root / dataset).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("dataset_path_escapes_repository")
        return path

    def metadata(self, dataset: str, revision: str = "HEAD") -> tuple[str, dict]:
        path = f"{dataset}.dvc"
        if revision == "HEAD":
            file = self.safe_path(path)
            if not file.is_file():
                raise FileNotFoundError("dvc_metadata_missing")
            contents = file.read_text()
        else:
            sha = self.commit(revision)
            contents = self.command(["git", "show", f"{sha}:{path}"])
        value = yaml.safe_load(contents)
        if not isinstance(value, dict) or not value.get("outs"):
            raise ValueError("dvc_metadata_invalid")
        return path, value

    def list_datasets(self, _: EmptyInput) -> dict:
        records = []
        for metadata in sorted((self.root / "data").rglob("*.dvc")):
            if not metadata.resolve().is_relative_to(self.root):
                raise ValueError("metadata_path_escapes_repository")
            document = yaml.safe_load(metadata.read_text()) or {}
            for out in document.get("outs", []):
                target = metadata.parent / out["path"]
                records.append({"dataset": target.relative_to(self.root).as_posix(),
                                "metadata_path": metadata.relative_to(self.root).as_posix(),
                                "dvc_hash": out.get("md5"), "source": "dvc_metadata"})
        lock = self.root / "dvc.lock"
        if lock.exists():
            document = yaml.safe_load(lock.read_text()) or {}
            for stage in document.get("stages", {}).values():
                for out in stage.get("outs", []):
                    if out.get("path", "").startswith("data/"):
                        records.append({"dataset": out["path"], "metadata_path": "dvc.lock",
                                        "dvc_hash": out.get("md5"), "source": "dvc_lock"})
        return {"datasets": records, "git_commit": self.commit(), "remotes": self.remotes()}

    def provenance(self, args: ProvenanceInput) -> dict:
        dataset, revision, expected_hash = args.dataset, args.revision, args.expected_hash
        if args.run_id:
            from mlflow.tracking import MlflowClient

            tags = MlflowClient(tracking_uri=self.tracking_uri).get_run(args.run_id).data.tags
            required = ["dataset.path", "dataset.hash", "dataset.git_revision"]
            if not all(tags.get(key) for key in required):
                raise ValueError("mlflow_dataset_lineage_missing")
            dataset = tags["dataset.path"]
            revision = tags["dataset.git_revision"]
            expected_hash = tags["dataset.hash"]
            DatasetInput.safe_dataset(dataset)
            ProvenanceInput.safe_revision(revision)
        sha = self.commit(revision)
        path, document = self.metadata(dataset, revision)
        out = document["outs"][0]
        recorded_hash = out.get("md5")
        if not recorded_hash or recorded_hash.endswith(".dir"):
            raise ValueError("only_single_file_md5_dataset_supported")
        actual_hash = None
        dirty = None
        if revision == "HEAD":
            actual_path = self.safe_path(dataset)
            if actual_path.is_file():
                actual_hash = hashlib.md5(actual_path.read_bytes(), usedforsecurity=False).hexdigest()
            dirty = actual_hash != recorded_hash
        metadata_dirty = bool(self.command(["git", "status", "--porcelain", "--", path, "dvc.lock"]))
        return {"dataset": dataset, "git_commit": sha, "dvc_hash": recorded_hash,
                "actual_hash": actual_hash, "dirty": dirty, "metadata_dirty": metadata_dirty,
                "metadata_path": path, "run_id": args.run_id,
                "lineage_match": expected_hash == recorded_hash if expected_hash else None,
                "remotes": self.remotes()}

    def compare_versions(self, args: CompareInput) -> dict:
        old = self.provenance(ProvenanceInput(dataset=args.dataset, revision=args.old_revision))
        new = self.provenance(ProvenanceInput(dataset=args.dataset, revision=args.new_revision))
        return {"dataset": args.dataset, "old": old, "new": new,
                "changed": old["dvc_hash"] != new["dvc_hash"]}

    def detect_changes(self, _: EmptyInput) -> dict:
        listed = self.list_datasets(EmptyInput())
        provenance = [self.provenance(ProvenanceInput(dataset=item["dataset"]))
                      for item in listed["datasets"]]
        status = self.command(["dvc", "status", "--json"])
        import json

        parsed = json.loads(status or "{}")
        return {"datasets": provenance, "changed": any(item["dirty"] for item in provenance),
                "dvc_status": parsed}

    def reproduce_version(self, args: ReproduceInput) -> dict:
        provenance = self.provenance(args)
        sha = provenance["git_commit"]
        commands = [["git", "clone", "--no-hardlinks", str(self.root), "reproduction"],
                    ["git", "checkout", "--detach", sha],
                    ["dvc", "pull", provenance["metadata_path"]]]
        result = {"git_commit": sha, "dataset": provenance["dataset"],
                  "dvc_hash": provenance["dvc_hash"], "executed": args.execute,
                  "verified": False, "commands": commands, "limitation": None}
        if not args.execute:
            result["limitation"] = "Commands are a plan; no historical data was retrieved."
            return result
        with tempfile.TemporaryDirectory(prefix="mlops-dvc-reproduction-") as temporary:
            clone = Path(temporary) / "reproduction"
            self.command(["git", "clone", "--no-hardlinks", str(self.root), str(clone)], timeout=30)
            self.command(["git", "checkout", "--detach", sha], cwd=clone)
            try:
                self.command(["dvc", "pull", provenance["metadata_path"]], cwd=clone, timeout=60)
            except (RuntimeError, subprocess.TimeoutExpired):
                result["limitation"] = "Historical DVC data could not be pulled from the configured remote."
                return result
            data = (clone / provenance["dataset"]).read_bytes()
            result["verified"] = hashlib.md5(data, usedforsecurity=False).hexdigest() == provenance["dvc_hash"]
            if not result["verified"]:
                result["limitation"] = "Retrieved bytes failed the recorded MD5 comparison."
        return result


def register(registry, settings) -> None:
    tools = DvcTools(settings.root, settings.mlflow_tracking_uri)
    definitions = [
        ("dvc.list_datasets", "List actual DVC-tracked dataset metadata and Git commit", EmptyInput, tools.list_datasets, DatasetList),
        ("dvc.provenance", "Read dataset hash, Git revision and optional MLflow run lineage", ProvenanceInput, tools.provenance, ProvenanceOutput),
        ("dvc.compare_versions", "Compare dataset hashes at two validated Git revisions", CompareInput, tools.compare_versions, CompareOutput),
        ("dvc.detect_changes", "Compare workspace data to DVC hashes and actual DVC status", EmptyInput, tools.detect_changes, ChangesOutput),
        ("dvc.reproduce_version", "Plan or verify historical reproduction in a disposable clone", ReproduceInput, tools.reproduce_version, ReproduceOutput),
    ]
    for name, description, input_model, handler, output_model in definitions:
        registry.add(name, description, input_model, handler, output_model=output_model,
                     permission="read", timeout=120 if name == "dvc.reproduce_version" else 30)
