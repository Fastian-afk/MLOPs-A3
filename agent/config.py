from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def validate_kube_api_url(value: str | None) -> str | None:
    """Accept a user-configured HTTPS API origin, never a URL with credentials."""
    if value is None:
        return None
    try:
        if any(character.isspace() or ord(character) < 32 for character in value):
            raise ValueError
        if any(character in value for character in ("\\", "?", "#")):
            raise ValueError
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.netloc.endswith(":")
        ):
            raise ValueError
        # Accessing .port validates syntax/range; reject a wildcard host explicitly.
        if parsed.port == 0 or "*" in parsed.hostname:
            raise ValueError
    except ValueError:
        # Never include the original URL: an invalid value may contain credentials.
        raise ValueError("Kubernetes API URL must be an HTTPS origin without credentials or path") from None
    return value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MLOPS_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )
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
    kube_api_url: str | None = None
    kube_api_token: SecretStr | None = None
    kube_ca_cert: str | None = None
    http_timeout: float = Field(default=10, gt=0, le=60)
    planner: Literal["offline", "openai", "groq"] = "offline"
    llm_model: str = "gpt-4.1-mini"
    llm_api_key: SecretStr | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_api_key: SecretStr | None = None
    api_token: SecretStr | None = None
    max_tool_calls: int = Field(default=12, ge=1, le=20)
    request_timeout: float = Field(default=90, gt=0, le=300)
    freshness_days: int | None = Field(default=None, ge=1)

    @field_validator("kube_api_url")
    @classmethod
    def secure_kubernetes_origin(cls, value: str | None) -> str | None:
        return validate_kube_api_url(value)

    @model_validator(mode="after")
    def paths(self) -> "Settings":
        self.root = self.root.resolve()
        for field in ("artifact_dir", "data_path"):
            value = getattr(self, field)
            if not value.is_absolute():
                setattr(self, field, self.root / value)
        return self
