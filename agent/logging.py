import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger("mlops.tools")
SENSITIVE = re.compile(r"(?i)(token|password|secret|api.?key|authorization|credential)")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): "[REDACTED]" if SENSITIVE.search(str(k)) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+\S+", "Bearer [REDACTED]", value)
        value = re.sub(r"(https?://)[^/@\s]+:[^/@\s]+@", r"\1[REDACTED]@", value)
        value = re.sub(r"(?i)((?:token|password|secret|api[_-]?key)[=: ]+)\S+", r"\1[REDACTED]", value)
    return value


def log_tool(request_id: str, tool: str, duration: float, status: str, error_code: str | None) -> None:
    # Never record tool arguments, operational payloads, exception text or credentials.
    LOGGER.info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "request_id": request_id,
                "tool": tool,
                "duration_ms": round(duration, 3),
                "status": status,
                "error_code": error_code,
            }
        )
    )
