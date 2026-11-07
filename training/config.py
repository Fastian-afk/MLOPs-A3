from pydantic import BaseModel, ConfigDict, Field


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seed: int = Field(default=42, ge=0, le=2**31 - 1)
    c: float = Field(default=1.0, gt=0, le=1000)
    test_size: float = Field(default=0.25, ge=0.1, le=0.5)
    f1_threshold: float = Field(default=0.8, ge=0, le=1)
    experiment_name: str = "mlops-assignment-03"


FEATURE_NAMES = [f"feature_{index}" for index in range(8)]
