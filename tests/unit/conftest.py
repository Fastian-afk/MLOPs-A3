"""Unit fixtures must never inherit live provider/cluster credentials or planner mode."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolate_live_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MLOPS_") or name in {
            "OPENAI_API_KEY",
            "OPENAI_BASE_URL",
            "GROQ_API_KEY",
            "MLFLOW_TRACKING_URI",
        }:
            monkeypatch.delenv(name, raising=False)
    # Override a developer's optional .env planner as well. Provider unit tests
    # explicitly construct Settings(planner=...) and inject a mock SDK client.
    monkeypatch.setenv("MLOPS_PLANNER", "offline")
