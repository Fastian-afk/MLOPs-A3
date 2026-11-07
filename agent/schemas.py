from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=6000)
    session_id: str = Field(default="default", min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    request_id: str | None = Field(default=None, max_length=128, pattern=r"^[\w.-]+$")
    confirmation_token: str | None = Field(default=None, max_length=256)


class ToolResult(StrictModel):
    tool: str
    status: Literal["ok", "error", "confirmation_required"]
    data: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    uncertainty: str | None = None
    duration_ms: float = 0
    source: str = "live_adapter"


class ProposedAction(StrictModel):
    tool: str
    arguments: dict[str, Any]
    confirmation_token: str
    expires_in_seconds: int = 120


class PlannedRead(StrictModel):
    tool: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_.]+$")
    arguments: dict[str, Any] = Field(default_factory=dict, max_length=30)


class ProviderTrace(StrictModel):
    provider: Literal["openai", "groq"]
    model: str
    strategy: Literal["iterative_tools", "bounded_read_plan"]
    request_ids: list[str] = Field(default_factory=list)
    completion_ids: list[str] = Field(default_factory=list)
    usage: dict[str, int] = Field(default_factory=dict)
    planned_steps: list[PlannedRead] = Field(default_factory=list)
    executed_steps: list[PlannedRead] = Field(default_factory=list)
    coverage_guard_tools: list[str] = Field(default_factory=list)
    error_code: str | None = None
    retry_after_seconds: float | None = None


class ChatResponse(StrictModel):
    answer: str
    selected_tools: list[str]
    evidence: list[ToolResult]
    uncertainties: list[str]
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    trace_id: str
    planner: Literal["offline", "openai", "groq"]
    provider_trace: ProviderTrace | None = None
