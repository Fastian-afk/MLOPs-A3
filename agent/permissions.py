import json
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PendingAction:
    user_id: str
    session_id: str
    tool: str
    arguments_json: str
    expires_at: float


class ConfirmationStore:
    """Single-process one-use nonces; API authentication supplies the user identity.

    Tokens bind the exact canonical parameters. Restarting the API invalidates
    pending proposals. Multiple workers require an atomic shared store instead.
    """

    def __init__(self, ttl: int = 120):
        self.ttl = ttl
        self._pending: dict[str, PendingAction] = {}
        self._lock = threading.Lock()

    def issue(self, user_id: str, session: str, tool: str, arguments: dict[str, Any]) -> str:
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self._lock:
            self._pending = {k: v for k, v in self._pending.items() if v.expires_at > now}
            if len(self._pending) >= 1000:
                raise PermissionError("Too many pending confirmations")
            self._pending[token] = PendingAction(
                user_id, session, tool, json.dumps(arguments, sort_keys=True), now + self.ttl
            )
        return token

    def consume(self, token: str, user_id: str, session: str) -> tuple[str, dict[str, Any]]:
        with self._lock:
            action = self._pending.get(token)
            if action is None:
                raise PermissionError("Unknown or already used confirmation")
            if action.user_id != user_id or action.session_id != session:
                raise PermissionError("Confirmation belongs to another user/session")
            self._pending.pop(token)
        if action.expires_at <= time.monotonic():
            raise PermissionError("Confirmation expired")
        return action.tool, json.loads(action.arguments_json)
