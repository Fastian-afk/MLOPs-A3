"""Exercise real native argument boundaries, not string-splitting command mocks."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_powershell_native_argument_boundaries(tmp_path):
    executable = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
    if not executable:
        pytest.skip("PowerShell unavailable locally; actual Desktop 5.1 regression runs in windows-helper CI")
    root = Path(__file__).resolve().parents[2]
    output = tmp_path / "native-arguments.json"
    environment = os.environ.copy()
    for category in ("CACHE", "CONFIG", "DATA"):
        environment["XDG_" + category + "_HOME"] = str(tmp_path / category.lower())
    result = subprocess.run(
        [
            executable,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(root / "scripts/test_windows_arguments.ps1"),
            "-OutputPath",
            str(output),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=root,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    record = json.loads(output.read_text())
    assert record["status"] == "VERIFIED_REAL"
    assert {
        "docker_info_three_native_arguments",
        "paths_spaces_and_jsonpath_preserved",
        "kubectl_context_namespace_and_arguments_separate",
        "native_nonzero_exit_rejected",
        "successful_stderr_does_not_corrupt_stdout",
    } <= set(record["checks"])
