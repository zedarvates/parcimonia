"""Baseline measurement with explicit provenance.

Nothing here executes a route on Parcimonia's behalf. The caller supplies the
callable, the clock and the environment label; this module only records what
happened, how it was measured and where, without task payloads, outputs or
exception messages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .router import is_nonnegative_number

MEASUREMENT_SCHEMA_VERSION = 1
MEASUREMENT_KIND = "measurement"
MEASURED_DATA_ORIGIN = "measured"
WALL_CLOCK_METHOD = "wall_clock/monotonic"

_ENVIRONMENT_FIELDS = frozenset({"machine_id", "runtime_versions"})
_OUTCOME_FIELDS = frozenset({"ok", "error_type"})
_RECORD_FIELDS = frozenset(
    {
        "schema_version",
        "kind",
        "task_id",
        "route_id",
        "method",
        "environment",
        "measured_at",
        "outcome",
        "latency_ms",
        "cost",
        "cost_unit",
        "data_origin",
    }
)


@dataclass(frozen=True)
class Environment:
    """Caller-declared execution environment.

    `machine_id` is a label chosen by the caller, never a hardware or hostname
    fingerprint, and runtime_versions maps a component name to its version.
    """

    machine_id: str
    runtime_versions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.machine_id):
            raise ValueError("machine_id must be a nonempty, trimmed string.")
        if not isinstance(self.runtime_versions, Mapping):
            raise TypeError("runtime_versions must be a mapping of names to versions.")
        for name, version in self.runtime_versions.items():
            if not _is_trimmed_nonempty(name) or not _is_trimmed_nonempty(version):
                raise ValueError(
                    "runtime_versions keys and values must be nonempty, trimmed strings."
                )


@dataclass(frozen=True)
class BaselineRun:
    """One measured execution of a baseline callable."""

    task_id: str
    route_id: str
    ok: bool
    error_type: str | None
    latency_ms: float
    cost: float | None
    cost_unit: str
    measured_at: str
    method: str
    environment: Environment

    def to_record(self) -> dict[str, Any]:
        record = {
            "schema_version": MEASUREMENT_SCHEMA_VERSION,
            "kind": MEASUREMENT_KIND,
            "task_id": self.task_id,
            "route_id": self.route_id,
            "method": self.method,
            "environment": {
                "machine_id": self.environment.machine_id,
                "runtime_versions": dict(self.environment.runtime_versions),
            },
            "measured_at": self.measured_at,
            "outcome": {"ok": self.ok, "error_type": self.error_type},
            "latency_ms": self.latency_ms,
            "cost": self.cost,
            "cost_unit": self.cost_unit,
            "data_origin": MEASURED_DATA_ORIGIN,
        }
        _validate_measurement_record(record)
        return record


def run_baseline(
    task_id: str,
    route_id: str,
    run: Callable[[], Any],
    *,
    cost_unit: str,
    environment: Environment,
    clock: Callable[[], float],
    now: Callable[[], str] | None = None,
    cost: float | None = None,
) -> BaselineRun:
    """Execute `run` once and record what happened.

    The callable is executed exactly once and never retried. An exception is
    recorded as a failed outcome with its type only; the message, the inputs and
    the output stay outside the record. BaseException (for example
    KeyboardInterrupt) is not swallowed.
    """
    if not _is_trimmed_nonempty(task_id):
        raise ValueError("task_id must be a nonempty, trimmed string.")
    if not _is_trimmed_nonempty(route_id):
        raise ValueError("route_id must be a nonempty, trimmed string.")
    if not _is_trimmed_nonempty(cost_unit):
        raise ValueError("cost_unit must be a nonempty, trimmed string.")
    if not isinstance(environment, Environment):
        raise TypeError("environment must be an Environment instance.")
    if not callable(run):
        raise TypeError("run must be callable.")
    if not callable(clock):
        raise TypeError("clock must be callable.")
    if cost is not None and not is_nonnegative_number(cost):
        raise ValueError("cost must be null or a finite nonnegative number.")

    started = clock()
    ok = True
    error_type: str | None = None
    try:
        run()
    except Exception as exc:  # noqa: BLE001 - recorded, not swallowed
        ok = False
        error_type = type(exc).__name__
    finished = clock()

    if not isinstance(started, (int, float)) or not isinstance(finished, (int, float)):
        raise TypeError("clock must return a number.")
    if finished < started:
        raise ValueError("clock must not go backwards between the two readings.")

    return BaselineRun(
        task_id=task_id,
        route_id=route_id,
        ok=ok,
        error_type=error_type,
        latency_ms=(finished - started) * 1000.0,
        cost=cost,
        cost_unit=cost_unit,
        measured_at=_normalise_timestamp((now or _utc_now)()),
        method=WALL_CLOCK_METHOD,
        environment=environment,
    )


def write_measurement(path: str | Path, record: Mapping[str, Any]) -> None:
    """Write a validated measurement without overwriting an existing file."""
    _validate_measurement_record(record)
    payload = json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    with open(path, "x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload)


def read_measurement(path: str | Path) -> dict[str, Any]:
    """Read one measurement, rejecting malformed or ambiguous JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        record = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError as exc:
        raise ValueError(f"Measurement file is not valid JSON: {exc}") from exc
    _validate_measurement_record(record)
    return record


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _normalise_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("measured_at must be a nonempty ISO 8601 string.")
    candidate = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(
            "measured_at must be an ISO 8601 timestamp with a timezone offset."
        ) from exc
    if parsed.tzinfo is None:
        raise ValueError(
            "measured_at must be an ISO 8601 timestamp with a timezone offset."
        )
    return parsed.isoformat()


def _require_exact_keys(value: object, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    if set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}.")


def _validate_measurement_record(record: object) -> None:
    _require_exact_keys(record, _RECORD_FIELDS, "measurement")
    schema_version = record["schema_version"]
    if type(schema_version) is not int or schema_version != MEASUREMENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema_version; expected {MEASUREMENT_SCHEMA_VERSION}."
        )
    if record["kind"] != MEASUREMENT_KIND:
        raise ValueError(f"kind must be {MEASUREMENT_KIND!r}.")
    if record["data_origin"] != MEASURED_DATA_ORIGIN:
        raise ValueError(
            f"data_origin must be {MEASURED_DATA_ORIGIN!r}; this record type is "
            "reserved for runs that actually happened."
        )
    if not _is_trimmed_nonempty(record["task_id"]):
        raise ValueError("task_id must be a nonempty, trimmed string.")
    if not _is_trimmed_nonempty(record["route_id"]):
        raise ValueError("route_id must be a nonempty, trimmed string.")
    if not _is_trimmed_nonempty(record["method"]):
        raise ValueError("method must be a nonempty, trimmed string.")

    environment = record["environment"]
    _require_exact_keys(environment, _ENVIRONMENT_FIELDS, "environment")
    if not _is_trimmed_nonempty(environment["machine_id"]):
        raise ValueError("environment.machine_id must be a nonempty, trimmed string.")
    runtime_versions = environment["runtime_versions"]
    if not isinstance(runtime_versions, dict) or not all(
        _is_trimmed_nonempty(name) and _is_trimmed_nonempty(version)
        for name, version in runtime_versions.items()
    ):
        raise ValueError(
            "environment.runtime_versions must map nonempty names to nonempty versions."
        )

    if not isinstance(record["measured_at"], str):
        raise ValueError("measured_at must be an ISO 8601 string.")
    _normalise_timestamp(record["measured_at"])

    outcome = record["outcome"]
    _require_exact_keys(outcome, _OUTCOME_FIELDS, "outcome")
    if not isinstance(outcome["ok"], bool):
        raise ValueError("outcome.ok must be a boolean.")
    if outcome["ok"] is True and outcome["error_type"] is not None:
        raise ValueError("outcome.error_type must be null when outcome.ok is true.")
    if outcome["ok"] is False and not _is_trimmed_nonempty(outcome["error_type"]):
        raise ValueError(
            "outcome.error_type must name the exception when outcome.ok is false."
        )

    if not is_nonnegative_number(record["latency_ms"]):
        raise ValueError("latency_ms must be a finite nonnegative number.")
    cost = record["cost"]
    if cost is not None and not is_nonnegative_number(cost):
        raise ValueError("cost must be null or a finite nonnegative number.")
    if not _is_trimmed_nonempty(record["cost_unit"]):
        raise ValueError("cost_unit must be a nonempty, trimmed string.")


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value!r} is not supported")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} is not allowed")
        result[key] = value
    return result
