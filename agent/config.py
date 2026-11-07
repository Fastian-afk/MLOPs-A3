from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MLOPS_", env_file=".env", extra="ignore")
    root: Path = Path.cwd()
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    experiment_name: str = "mlops-assignment-03"
    artifact_dir: Path = Path("artifacts")
    data_path: Path = Path("data/dataset.csv")
    airflow_base_url: str = "http://127.0.0.1:8080"
    airflow_token: str | None = None
    airflow_username: str = "admin"
    airflow_password: str | None = None
    approved_dag_id: str = "mlops_training"
    namespace: str = "mlops"
    kubeconfig: str | None = None
    kube_context: str | None = None
    http_timeout: float = Field(default=10, gt=0, le=60)
    planner: Literal["offline", "openai"] = "offline"
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: SecretStr | None = None
    api_token: SecretStr | None = None
    max_tool_calls: int = Field(default=12, ge=1, le=20)
    request_timeout: float = Field(default=90, gt=0, le=300)
    freshness_days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def paths(self) -> "Settings":
        self.root = self.root.resolve()
        for field in ("artifact_dir", "data_path"):
            value = getattr(self, field)
            if not value.is_absolute():
                setattr(self, field, self.root / value)
        return self
