"""FastAPI serving for locally trusted, quality-gated sklearn artifacts."""

from __future__ import annotations

import logging
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)


class PredictionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instances: list[list[float]] = Field(min_length=1, max_length=256)

    @field_validator("instances")
    @classmethod
    def validate_instances(cls, rows: list[list[float]]) -> list[list[float]]:
        for row in rows:
            if len(row) != 8 or not all(math.isfinite(value) for value in row):
                raise ValueError("Each instance must contain exactly eight finite feature values")
        return rows


class PredictionResponse(BaseModel):
    predictions: list[int]
    probabilities: list[list[float]]
    run_id: str | None


class VersionResponse(BaseModel):
    application_version: str
    ready: bool
    run_id: str | None
    git_commit: str | None
    dataset_hash: str | None
    feature_names: list[str]


def create_app(model_path: str | Path | None = None) -> FastAPI:
    path = Path(model_path or os.getenv("MODEL_PATH", "artifacts/model.joblib"))

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.artifact = None
        try:
            # joblib uses pickle: only load an artifact built by this trusted training pipeline.
            artifact = joblib.load(path)
            if (
                not isinstance(artifact, dict)
                or "model" not in artifact
                or len(artifact.get("feature_names", [])) != 8
                or not hasattr(artifact["model"], "predict_proba")
            ):
                raise ValueError("Invalid inference artifact")
            application.state.artifact = artifact
        except (OSError, ValueError, TypeError, KeyError):
            logger.error("Model could not be loaded; readiness remains false")
        yield

    application = FastAPI(title="MLOps inference", version="0.1.0", lifespan=lifespan)
    application.state.artifact = None

    @application.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "live"}

    @application.get("/health/ready")
    def ready() -> dict[str, str]:
        if application.state.artifact is None:
            raise HTTPException(status_code=503, detail="MODEL_NOT_READY")
        return {"status": "ready"}

    @application.get("/version", response_model=VersionResponse)
    def version() -> VersionResponse:
        artifact: dict[str, Any] = application.state.artifact or {}
        metadata = artifact.get("metadata", {})
        return VersionResponse(
            application_version=os.getenv("APP_VERSION", "0.1.0"),
            ready=bool(artifact),
            run_id=metadata.get("run_id"),
            git_commit=metadata.get("git_commit"),
            dataset_hash=metadata.get("dataset_hash"),
            feature_names=artifact.get("feature_names", []),
        )

    @application.post("/predict", response_model=PredictionResponse)
    def predict(payload: PredictionRequest) -> PredictionResponse:
        artifact = application.state.artifact
        if artifact is None:
            raise HTTPException(status_code=503, detail="MODEL_NOT_READY")
        data = np.asarray(payload.instances, dtype=float)
        model = artifact["model"]
        return PredictionResponse(
            predictions=model.predict(data).astype(int).tolist(),
            probabilities=model.predict_proba(data).astype(float).tolist(),
            run_id=artifact.get("metadata", {}).get("run_id"),
        )

    return application


app = create_app()
