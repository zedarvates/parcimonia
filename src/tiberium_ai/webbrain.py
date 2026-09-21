"""WebBrain MCP adapter for browser agent task delegation.

Converts WebBrain browser agent results (from @webbrain/mcp-server) into
Parcimonia measured resource vectors and verified execution evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

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
    "WebBrainRoundTrip",
    "is_loopback_endpoint",
]

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def is_loopback_endpoint(endpoint_url: object) -> bool:
    """Return whether a WebSocket endpoint targets this machine.

    A round-trip never leaves the loopback interface, so a non-loopback host is
    refused instead of contacted.
    """
    if not isinstance(endpoint_url, str) or not endpoint_url.strip():
        raise ValueError("endpoint_url must be a nonempty string.")
    parsed = urlparse(endpoint_url.strip())
    if parsed.scheme not in ("ws", "wss"):
        raise ValueError("endpoint_url must use the ws or wss scheme.")
    return (parsed.hostname or "").lower() in _LOOPBACK_HOSTS


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


@dataclass(frozen=True)
class WebBrainRoundTrip:
    """Result of one observation-only ASK round-trip.

    `status` is `ok`, `unavailable` or `error`. Nothing here proves the answer
    is true, and no action is ever performed on the page.
    """

    status: str
    mode: WebBrainMode
    request: WebBrainRequest
    response: WebBrainResponse | None
    detail_code: str

    def __post_init__(self) -> None:
        if self.status not in ("ok", "unavailable", "error"):
            raise ValueError("status must be ok, unavailable or error.")
        if self.status == "ok" and self.response is None:
            raise ValueError("an ok round-trip must carry a parsed response.")
        if self.status != "ok" and self.response is not None:
            raise ValueError("only an ok round-trip may carry a response.")
        if not isinstance(self.detail_code, str) or not self.detail_code.strip():
            raise ValueError("detail_code must be a nonempty string.")

    @property
    def performed(self) -> bool:
        return self.status == "ok"

    def to_resource_vector(self, latency_ms: float | None = None) -> ResourceVector:
        """Measure the round-trip. An absent response has nothing to measure."""
        if self.response is None:
            raise ValueError("no response was received, so there is no vector.")
        return self.response.to_resource_vector(latency_ms=latency_ms)


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

    def round_trip(
        self,
        task: Task,
        *,
        mode: WebBrainMode = WebBrainMode.ASK,
        transport: Callable[[str, Mapping[str, Any]], object] | None = None,
        schema: Mapping[str, Any] | None = None,
    ) -> WebBrainRoundTrip:
        """Perform one ASK-only, loopback-only, observation-only round-trip.

        The transport is injected, so the library performs no network I/O: a
        caller supplies the WebSocket or MCP transport, and its absence is a
        typed `unavailable` result rather than an exception.
        """
        if mode is not WebBrainMode.ASK:
            raise ValueError(
                "WebBrain round_trip is ASK only; ACT and DEV require prior "
                "authorization."
            )
        if not is_loopback_endpoint(self.endpoint_url):
            raise ValueError("WebBrain round_trip requires a loopback endpoint.")
        command = self.build_command(task, mode=mode, schema=schema)
        if transport is None:
            return WebBrainRoundTrip(
                "unavailable", mode, command, None, "no_transport_configured"
            )
        if not callable(transport):
            raise TypeError("transport must be callable.")
        envelope = {
            "tool_name": command.tool_name,
            "arguments": dict(command.arguments),
        }
        try:
            payload = transport(self.endpoint_url, envelope)
        except OSError as exc:
            return WebBrainRoundTrip(
                "unavailable",
                mode,
                command,
                None,
                f"transport_unavailable:{type(exc).__name__}",
            )
        except Exception as exc:  # noqa: BLE001 - reported as a typed error
            return WebBrainRoundTrip(
                "error", mode, command, None, f"transport_error:{type(exc).__name__}"
            )
        try:
            response = self.parse_result(payload)
        except (TypeError, ValueError):
            return WebBrainRoundTrip("error", mode, command, None, "invalid_response")
        return WebBrainRoundTrip("ok", mode, command, response, response.status)
