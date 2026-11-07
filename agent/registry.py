import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, ValidationError

from agent.logging import log_tool, redact
from agent.schemas import ToolResult


@dataclass
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    handler: Callable
    output_model: type[BaseModel]
    permission: Literal["read", "write"]
    timeout: float


class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, ToolSpec] = {}

    def add(self, name, description, input_model, handler, *, output_model, permission="read", timeout=30):
        if name in self.tools:
            raise ValueError("Duplicate tool")
        self.tools[name] = ToolSpec(name, description, input_model, handler, output_model, permission, timeout)

    def schemas(self, *, allow_writes: bool = False) -> list[dict]:
        return [
            {"type": "function", "function": {"name": spec.name.replace(".", "__"),
             "description": spec.description,
             "parameters": spec.input_model.model_json_schema()}}
            for spec in self.tools.values() if allow_writes or spec.permission == "read"
        ]

    async def execute(self, name: str, arguments: dict[str, Any], request_id: str,
                      *, authorized_write: bool = False) -> ToolResult:
        start = time.monotonic()
        try:
            spec = self.tools.get(name)
            if spec is None:
                raise KeyError("Unknown tool")
            if spec.permission == "write" and not authorized_write:
                raise PermissionError("Explicit confirmation required")
            if set(arguments) - set(spec.input_model.model_fields):
                raise ValueError("Unknown arguments")
            args = spec.input_model.model_validate(arguments)
            if inspect.iscoroutinefunction(spec.handler):
                output = await asyncio.wait_for(spec.handler(args), timeout=spec.timeout)
            else:
                output = await asyncio.wait_for(asyncio.to_thread(spec.handler, args), timeout=spec.timeout)
            if isinstance(output, BaseModel):
                output = output.model_dump(mode="json")
            validated = spec.output_model.model_validate(output).model_dump(mode="json")
            result = ToolResult(tool=name, status="ok", data=redact(validated))
        except (TimeoutError, asyncio.TimeoutError):
            result = ToolResult(tool=name, status="error", error_code="TIMEOUT",
                                uncertainty="The service did not respond within the tool deadline.")
        except PermissionError:
            result = ToolResult(tool=name, status="error", error_code="FORBIDDEN",
                                uncertainty="Operation denied by permissions or service authorization.")
        except (ValueError, ValidationError, KeyError):
            result = ToolResult(tool=name, status="error", error_code="INVALID_REQUEST",
                                uncertainty="Invalid tool name, arguments or service response schema.")
        except Exception:
            # Exception strings can contain remote URLs, tokens and service payloads.
            result = ToolResult(tool=name, status="error", error_code="SERVICE_UNAVAILABLE",
                                uncertainty="Adapter failed; no operational result can be established.")
        result.duration_ms = round((time.monotonic() - start) * 1000, 3)
        log_tool(request_id, name, result.duration_ms, result.status, result.error_code)
        return result


def build_registry(settings) -> ToolRegistry:
    from agent.tools import airflow_tools, dvc_tools, kubernetes_tools, mlflow_tools

    registry = ToolRegistry()
    for module in (dvc_tools, mlflow_tools, airflow_tools, kubernetes_tools):
        module.register(registry, settings)
    return registry
