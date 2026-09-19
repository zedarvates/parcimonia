"""WebBrain MCP adapter for browser agent task delegation.

Converts WebBrain browser agent results (from @webbrain/mcp-server) into
Parcimonia measured resource vectors and verified execution evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from .contracts import Task
from .resources import ResourceVector

__all__ = [
    "WebBrainMode",
    "WebBrainRequest",
    "WebBrainResponse",
    "build_webbrain_request",
    "parse_webbrain_response",
    "WebBrainAction",
    "WebBrainClient",
    "WebBrainCommand",
    "WebBrainResult",
]


class WebBrainMode(str, Enum):
    ASK = "ask"
    ACT = "act"
    DEV = "dev"


@dataclass(frozen=True)
class WebBrainRequest:
    """Validated MCP tool call envelope for WebBrain."""

    tool_name: str
    arguments: dict[str, Any]

    def __post_init__(self) -> None:
        if self.tool_name not in ("webbrain_run", "webbrain_extract"):
            raise ValueError(f"Unsupported WebBrain tool: {self.tool_name}")


@dataclass(frozen=True)
class WebBrainResponse:
    """Parsed and verified result from a WebBrain MCP execution."""

    run_id: str
    status: str
    content: str
    steps_taken: int
    extracted_data: Mapping[str, Any] | None = None
    tokens_used: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("run_id must be a nonempty string.")
        if not isinstance(self.status, str) or not self.status.strip():
            raise ValueError("status must be a nonempty string.")
        if type(self.steps_taken) is not int or self.steps_taken < 0:
            raise ValueError("steps_taken must be a nonnegative integer.")

    def to_resource_vector(self, latency_ms: float | None = None) -> ResourceVector:
        """Convert to a Parcimonia ResourceVector."""
        return ResourceVector(tokens=self.tokens_used, latency_ms=latency_ms)


def build_webbrain_request(
    task: Task,
    *,
    mode: WebBrainMode = WebBrainMode.ASK,
    schema: Mapping[str, Any] | None = None,
) -> WebBrainRequest:
    """Build a validated WebBrain MCP request from a Parcimonia Task."""
    if not isinstance(task, Task):
        raise TypeError("task must be a Task instance.")
    if not isinstance(mode, WebBrainMode):
        raise TypeError("mode must be a WebBrainMode enum.")

    prompt = str(task.inputs.get("prompt") or task.inputs.get("task") or task.kind)
    if not prompt.strip():
        raise ValueError("task must contain a nonempty prompt in inputs.")

    if task.risk_class in ("high", "critical") and mode in (WebBrainMode.ACT, WebBrainMode.DEV):
        raise ValueError(
            f"Mode '{mode.value}' is forbidden on risk class '{task.risk_class}' without prior authorization."
        )

    if schema is not None:
        if not isinstance(schema, Mapping):
            raise TypeError("schema must be a mapping.")
        return WebBrainRequest(
            tool_name="webbrain_extract",
            arguments={"task": prompt, "schema": dict(schema)},
        )

    return WebBrainRequest(
        tool_name="webbrain_run",
        arguments={"task": prompt, "mode": mode.value},
    )


def parse_webbrain_response(payload: object) -> WebBrainResponse:
    """Parse a WebBrain MCP result dictionary into a WebBrainResponse."""
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a mapping.")

    run_id = payload.get("run_id") or payload.get("id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("payload must contain a nonempty string 'run_id'.")

    status = payload.get("status") or "completed"
    if not isinstance(status, str) or not status.strip():
        raise ValueError("status must be a nonempty string.")

    content = payload.get("content") or payload.get("summary") or ""
    if not isinstance(content, str):
        raise ValueError("content must be a string.")

    steps = payload.get("steps_taken") or payload.get("steps") or 0
    if type(steps) is not int or steps < 0:
        raise ValueError("steps_taken must be a nonnegative integer.")

    extracted = payload.get("extracted_data") or payload.get("data")
    if extracted is not None and not isinstance(extracted, Mapping):
        raise ValueError("extracted_data must be a mapping or null.")

    usage = payload.get("usage")
    tokens = None
    if isinstance(usage, Mapping):
        tokens = usage.get("total_tokens")
        if tokens is not None and (type(tokens) is not int or tokens < 0):
            raise ValueError("usage.total_tokens must be a nonnegative integer.")

    return WebBrainResponse(
        run_id=run_id.strip(),
        status=status.strip(),
        content=content,
        steps_taken=steps,
        extracted_data=extracted,
        tokens_used=tokens,
    )


# Aliases and Client Interface
WebBrainAction = WebBrainMode
WebBrainCommand = WebBrainRequest
WebBrainResult = WebBrainResponse


class WebBrainClient:
    """Client for constructing and parsing WebBrain MCP calls."""

    def __init__(self, endpoint_url: str = "ws://127.0.0.1:17374/extension") -> None:
        self.endpoint_url = endpoint_url

    def build_command(
        self,
        task: Task,
        *,
        mode: WebBrainMode = WebBrainMode.ASK,
        schema: Mapping[str, Any] | None = None,
    ) -> WebBrainCommand:
        return build_webbrain_request(task, mode=mode, schema=schema)

    def parse_result(self, payload: object) -> WebBrainResult:
        return parse_webbrain_response(payload)
