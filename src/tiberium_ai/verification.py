"""Deterministic verification: accept or reject without asking a model.

Every verdict is bound to a named and versioned verifier plus a hash of the
exact input, so the same input and version always produce the same verdict and
an unknown identity abstains instead of guessing.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping

from .contracts import Evidence, Verification, validate_verification_record

__all__ = [
    "VerifierRegistry",
    "attributed_evidence",
    "exact_match_verifier",
    "hash_input",
    "shape_verifier",
    "runner_result_verifier",
    "validate_verification_record",
]

_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "str": lambda value: isinstance(value, str),
    "int": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "float": lambda value: isinstance(value, (int, float))
    and not isinstance(value, bool),
    "number": lambda value: isinstance(value, (int, float))
    and not isinstance(value, bool),
    "bool": lambda value: isinstance(value, bool),
    "list": lambda value: isinstance(value, list),
    "dict": lambda value: isinstance(value, dict),
}


def hash_input(value: Any) -> str:
    """Return the sha256 of the canonical JSON form of `value`."""
    canonical = _canonical(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class VerifierRegistry:
    """Registry of named, versioned, deterministic verifiers."""

    def __init__(self) -> None:
        self._verifiers: dict[tuple[str, str], Callable[[Any], bool]] = {}

    def register(
        self, verifier_id: str, version: str, verifier: Callable[[Any], bool]
    ) -> None:
        _check_identity(verifier_id, "verifier_id")
        _check_identity(version, "verifier_version")
        if not callable(verifier):
            raise TypeError("verifier must be callable.")
        key = (verifier_id, version)
        if key in self._verifiers:
            raise ValueError(
                f"verifier {verifier_id!r} version {version!r} is already registered."
            )
        self._verifiers[key] = verifier

    def is_registered(self, verifier_id: str, version: str) -> bool:
        """Return whether exactly this identity and version is registered."""
        _check_identity(verifier_id, "verifier_id")
        _check_identity(version, "verifier_version")
        return (verifier_id, version) in self._verifiers

    def verify(self, verifier_id: str, version: str, value: Any) -> Verification:
        """Verify `value`, abstaining when the identity is unknown."""
        _check_identity(verifier_id, "verifier_id")
        _check_identity(version, "verifier_version")
        input_hash = hash_input(value)
        verifier = self._verifiers.get((verifier_id, version))
        if verifier is None:
            return Verification(
                verifier_id, version, None, input_hash, "unregistered_verifier"
            )
        try:
            verdict = verifier(value)
        except Exception as exc:  # noqa: BLE001 - reported as an abstention
            return Verification(
                verifier_id, version, None, input_hash, f"verifier_error:{type(exc).__name__}"
            )
        if not isinstance(verdict, bool):
            raise TypeError("verifier must return a boolean verdict.")
        return Verification(verifier_id, version, verdict, input_hash, None)


def shape_verifier(required: Mapping[str, str]) -> Callable[[Any], bool]:
    """Reject a mapping that misses a required field or gives it a wrong type."""
    if not isinstance(required, Mapping):
        raise TypeError("required must be a mapping of field names to type names.")
    checks: dict[str, Callable[[Any], bool]] = {}
    for field, type_name in required.items():
        if not isinstance(field, str) or not field or field != field.strip():
            raise ValueError("required field names must be nonempty, trimmed strings.")
        if type_name not in _TYPE_CHECKS:
            raise ValueError(
                f"unsupported type name {type_name!r}; expected one of "
                f"{sorted(_TYPE_CHECKS)}."
            )
        checks[field] = _TYPE_CHECKS[type_name]

    def verify_shape(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        return all(
            field in value and check(value[field]) for field, check in checks.items()
        )

    return verify_shape


def exact_match_verifier(expected: Any) -> Callable[[Any], bool]:
    """Accept a value only when its canonical JSON form equals `expected`."""
    expected_canonical = _canonical(expected)

    def verify_exact(value: Any) -> bool:
        try:
            return _canonical(value) == expected_canonical
        except ValueError:
            return False

    return verify_exact


def runner_result_verifier() -> Callable[[Any], bool]:
    """Accept a test-runner summary that exited cleanly with no failures."""

    def verify_test_result(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        exit_code = value.get("exit_code")
        if not isinstance(exit_code, int) or isinstance(exit_code, bool):
            return False
        if exit_code != 0:
            return False
        failed = value.get("failed")
        if failed is None:
            return True
        return isinstance(failed, int) and not isinstance(failed, bool) and failed == 0

    return verify_test_result


def attributed_evidence(
    verification: Verification,
    *,
    task_id: str,
    route_id: str,
    measured_latency_ms: float | None = None,
    measured_cost: float | None = None,
) -> Evidence:
    """Bind one verifier run and its measurements to a task and route.

    An abstained verification is not a success: `verifier_ok` is then False.
    """
    if not isinstance(verification, Verification):
        raise TypeError("verification must be a Verification instance.")
    return Evidence(
        task_id=task_id,
        route_id=route_id,
        verifier_ok=verification.verdict is True,
        measured_latency_ms=measured_latency_ms,
        measured_cost=measured_cost,
        verification=verification,
    )


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "input must be JSON-serialisable with finite numbers."
        ) from exc


def _check_identity(value: object, label: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} must be a nonempty, trimmed string.")
