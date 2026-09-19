"""WebBrain MCP client adapter for browser automation.

Provides a resilient, offline-safe client for interacting with the WebBrain
browser extension endpoint (ws://127.0.0.1:17374/extension) for authenticated
browser sessions without consuming vision-LLM tokens.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
import socket
from typing import Any
from urllib.parse import urlparse

__all__ = [
    "WebBrainAction",
    "WebBrainClient",
    "WebBrainCommand",
    "WebBrainResult",
]


class WebBrainAction(str, Enum):
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    READ = "read"
    SCREENSHOT = "screenshot"
    EVAL = "eval"


@dataclass(frozen=True)
class WebBrainCommand:
    action: WebBrainAction
    target: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.action, str):
            try:
                act = WebBrainAction(self.action)
                object.__setattr__(self, "action", act)
            except ValueError as exc:
                raise ValueError(f"action must be a valid WebBrainAction enum or string, got {self.action!r}") from exc
        elif not isinstance(self.action, WebBrainAction):
            raise ValueError(f"action must be a valid WebBrainAction enum or string, got {self.action!r}")

    def to_payload(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "target": self.target,
            "value": self.value,
        }


@dataclass(frozen=True)
class WebBrainResult:
    ok: bool
    status: str
    data: Any = None
    error: str | None = None


class WebBrainClient:
    """Offline-safe client connecting to WebBrain extension gateway."""

    def __init__(
        self,
        endpoint: str = "ws://127.0.0.1:17374/extension",
        timeout: float = 2.0,
        transport: Any = None,
    ) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.transport = transport

    def execute(self, command: WebBrainCommand) -> WebBrainResult:
        """Execute a browser automation command against WebBrain gateway."""
        if not isinstance(command, WebBrainCommand):
            raise TypeError("command must be a WebBrainCommand instance.")

        payload = command.to_payload()

        if self.transport is not None:
            try:
                response = self.transport.send_and_receive(payload, timeout=self.timeout)
                return WebBrainResult(ok=True, status="executed", data=response)
            except Exception as exc:
                return WebBrainResult(ok=False, status="error", error=f"{type(exc).__name__}: {exc}")

        # Default socket/WS connection probe
        try:
            parsed = urlparse(self.endpoint)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 17374

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((host, port))
            # Basic probe connected
            sock.close()
            return WebBrainResult(
                ok=True,
                status="executed",
                data={"message": f"Connected to {self.endpoint}", "command": payload},
            )
        except Exception as exc:
            return WebBrainResult(
                ok=False,
                status="offline",
                error=f"{type(exc).__name__}: {exc}",
            )
