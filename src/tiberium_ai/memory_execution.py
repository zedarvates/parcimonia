"""Attach the existing capture_run result to an explicit memory episode.

This adapter accepts results, never callables or transports. It cannot launch,
retry or reroute an execution. The raw output remains in the caller's memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .capture import CapturedRun
from .memory_capture import MemorySequenceCapture, _clone, _usage
from .verification import hash_input


@dataclass(frozen=True)
class MemoryRunAttachment:
    execution_recorded: bool
    usage_recorded: bool
    detail_code: str


def attach_memory_run(
    capture: MemorySequenceCapture, captured: CapturedRun, *, execution_id: str,
    request_hash: str, usage_receipt: Mapping[str, Any] | None = None,
) -> MemoryRunAttachment:
    """Record one completed attempt without manufacturing usage or labels.

    Rejected/oversized usage preserves the execution record. A recording error
    is distinct from a failed route: callers must not retry a performed call
    to repair its logging. Partial/failed-call usage may be supplied explicitly.
    """
    if not isinstance(capture, MemorySequenceCapture) or not isinstance(captured, CapturedRun):
        raise TypeError("expected MemorySequenceCapture and CapturedRun instances.")
    try:
        payload_hash = request_hash
        measured = _clone(captured.measurement)
        verification = None if captured.verification is None else captured.verification.to_record()
        if verification is not None and verification["input_hash"] != hash_input(captured.output):
            raise ValueError("captured output no longer matches its verification.")
        capture.record_execution(measured["task_id"], {
            "execution_id": execution_id, "route_id": measured["route_id"],
            "payload_hash": payload_hash, "measurement": measured, "verification": verification,
        })
    except (ValueError, TypeError, KeyError):
        return MemoryRunAttachment(False, False, "execution_record_rejected")
    if usage_receipt is None:
        return MemoryRunAttachment(True, False, "usage_not_supplied")
    try:
        usage = _usage(usage_receipt)
        if usage["receipt_id"] != execution_id or usage["payload_hash"] != payload_hash or usage["variant"] != "current":
            raise ValueError("usage scope does not match the existing run.")
        # The measured execution of a fixture cannot upgrade its source origin.
        if capture.origin == "authored":
            usage["origin"] = "authored"
        capture.record_usage(measured["task_id"], usage)
    except (ValueError, TypeError, KeyError):
        return MemoryRunAttachment(True, False, "usage_record_rejected")
    return MemoryRunAttachment(True, True, "recorded")
