"""Versioned route manifests: candidates come from a registry, not from callers.

A manifest declares, per route, the capabilities it provides, the estimates it
carries, the task constraints it accepts and the verifier that must judge its
output. Registry routes are filtered by constraints and by required
capabilities, and the registry version is part of the router policy version, so
a registry change is visible in every observation it produced.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import CandidateRoute, Task
from .router import is_nonnegative_number
from .verification import VerifierRegistry

MANIFEST_SCHEMA_VERSION = 1

_MANIFEST_FIELDS = frozenset({"schema_version", "registry_version", "routes"})
_ROUTE_FIELDS = frozenset(
    {
        "route_id",
        "capability_ids",
        "estimated_cost",
        "estimated_latency_ms",
        "confidence",
        "constraints",
        "verifier",
    }
)
_CONSTRAINT_FIELDS = frozenset({"risk_classes", "evidence_levels", "localities"})
_VERIFIER_FIELDS = frozenset({"verifier_id", "verifier_version"})


def _is_trimmed_nonempty(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value == value.strip()


def _require_exact_keys(value: object, expected: frozenset[str], label: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    if set(value) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}.")


def _check_string_list(value: object, label: str, *, minimum: int = 1) -> None:
    if not isinstance(value, list) or len(value) < minimum:
        raise ValueError(f"{label} must be a list of at least {minimum} string(s).")
    seen: set[str] = set()
    for item in value:
        if not _is_trimmed_nonempty(item):
            raise ValueError(f"{label} entries must be nonempty, trimmed strings.")
        if item in seen:
            raise ValueError(f"{label} must not repeat {item!r}.")
        seen.add(item)


def _check_optional_number(value: object, label: str) -> None:
    if value is not None and not is_nonnegative_number(value):
        raise ValueError(f"{label} must be null or a finite nonnegative number.")


@dataclass(frozen=True)
class RouteManifest:
    """One declared route, with its estimates, constraints and verifier."""

    route_id: str
    capability_ids: tuple[str, ...]
    estimated_cost: float | None
    estimated_latency_ms: float | None
    confidence: float | None
    risk_classes: tuple[str, ...]
    evidence_levels: tuple[str, ...]
    localities: tuple[str, ...]
    verifier_id: str
    verifier_version: str

    def __post_init__(self) -> None:
        if not _is_trimmed_nonempty(self.route_id):
            raise ValueError("route_id must be a nonempty, trimmed string.")
        _check_string_list(list(self.capability_ids), "capability_ids")
        _check_optional_number(self.estimated_cost, "estimated_cost")
        _check_optional_number(self.estimated_latency_ms, "estimated_latency_ms")
        if self.confidence is not None and (
            not is_nonnegative_number(self.confidence) or self.confidence > 1
        ):
            raise ValueError("confidence must be null or in [0, 1].")
        _check_string_list(list(self.risk_classes), "risk_classes")
        _check_string_list(list(self.evidence_levels), "evidence_levels")
        _check_string_list(list(self.localities), "localities")
        if not _is_trimmed_nonempty(self.verifier_id):
            raise ValueError("verifier_id must be a nonempty, trimmed string.")
        if not _is_trimmed_nonempty(self.verifier_version):
            raise ValueError("verifier_version must be a nonempty, trimmed string.")

    def accepts(self, task: Task) -> bool:
        """Return whether this route accepts the task constraints."""
        return (
            task.risk_class in self.risk_classes
            and task.evidence_level in self.evidence_levels
            and task.locality in self.localities
        )

    def to_candidate(self) -> CandidateRoute:
        return CandidateRoute(
            self.route_id,
            list(self.capability_ids),
            self.estimated_cost,
            self.estimated_latency_ms,
            self.confidence,
        )


class RouteRegistry:
    """Validated, versioned set of routes."""

    def __init__(self, version: str, routes: Sequence[RouteManifest]) -> None:
        if not _is_trimmed_nonempty(version):
            raise ValueError("registry version must be a nonempty, trimmed string.")
        routes = tuple(routes)
        if not routes:
            raise ValueError("a registry needs at least one route.")
        if not all(isinstance(route, RouteManifest) for route in routes):
            raise TypeError("routes must contain RouteManifest instances.")
        identifiers = [route.route_id for route in routes]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("duplicate route ids are not allowed.")
        self._version = version
        self._routes = routes
        self._by_id = {route.route_id: route for route in routes}

    @property
    def version(self) -> str:
        return self._version

    @property
    def routes(self) -> tuple[RouteManifest, ...]:
        return self._routes

    def policy_version(self, base: str) -> str:
        if not _is_trimmed_nonempty(base):
            raise ValueError("base must be a nonempty, trimmed string.")
        return f"{base}+registry:{self._version}"

    def route(self, route_id: str) -> RouteManifest:
        try:
            return self._by_id[route_id]
        except KeyError as exc:
            raise ValueError(f"unknown route_id {route_id!r}.") from exc

    def verifier_for(self, route_id: str) -> tuple[str, str]:
        route = self.route(route_id)
        return (route.verifier_id, route.verifier_version)

    def candidates_for(
        self, task: Task, *, required_capabilities: Sequence[str] = ()
    ) -> list[CandidateRoute]:
        """Return eligible candidates in manifest order.

        A task whose constraints or required capabilities match no route yields
        an empty list, which makes the router abstain instead of guessing.
        """
        for capability in required_capabilities:
            if not _is_trimmed_nonempty(capability):
                raise ValueError(
                    "required capability ids must be nonempty, trimmed strings."
                )
        return [
            route.to_candidate()
            for route in self._routes
            if route.accepts(task)
            and all(
                capability in route.capability_ids
                for capability in required_capabilities
            )
        ]

    @classmethod
    def from_manifest(
        cls,
        manifest: Mapping[str, Any],
        *,
        known_capabilities: Sequence[str] | None = None,
        verifiers: VerifierRegistry | None = None,
    ) -> "RouteRegistry":
        _require_exact_keys(manifest, _MANIFEST_FIELDS, "manifest")
        schema_version = manifest["schema_version"]
        if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported manifest schema_version; expected {MANIFEST_SCHEMA_VERSION}."
            )
        if not _is_trimmed_nonempty(manifest["registry_version"]):
            raise ValueError("registry_version must be a nonempty, trimmed string.")
        raw_routes = manifest["routes"]
        if not isinstance(raw_routes, list) or not raw_routes:
            raise ValueError("routes must be a nonempty list.")
        known = set(known_capabilities) if known_capabilities is not None else None

        routes: list[RouteManifest] = []
        identifiers: set[str] = set()
        for index, raw in enumerate(raw_routes):
            label = f"routes[{index}]"
            _require_exact_keys(raw, _ROUTE_FIELDS, label)
            _check_string_list(raw["capability_ids"], f"{label}.capability_ids")
            constraints = raw["constraints"]
            _require_exact_keys(constraints, _CONSTRAINT_FIELDS, f"{label}.constraints")
            for field in sorted(_CONSTRAINT_FIELDS):
                _check_string_list(constraints[field], f"{label}.constraints.{field}")
            verifier = raw["verifier"]
            _require_exact_keys(verifier, _VERIFIER_FIELDS, f"{label}.verifier")
            if not _is_trimmed_nonempty(verifier["verifier_id"]) or not _is_trimmed_nonempty(
                verifier["verifier_version"]
            ):
                raise ValueError(f"{label}.verifier must name an id and a version.")
            if known is not None:
                unknown = sorted(
                    capability
                    for capability in raw["capability_ids"]
                    if capability not in known
                )
                if unknown:
                    raise ValueError(f"{label} references unknown capabilities {unknown}.")
            if verifiers is not None and not verifiers.is_registered(
                verifier["verifier_id"], verifier["verifier_version"]
            ):
                raise ValueError(
                    f"{label} references an unregistered verifier "
                    f"{verifier['verifier_id']!r} version {verifier['verifier_version']!r}."
                )
            route = RouteManifest(
                route_id=raw["route_id"],
                capability_ids=tuple(raw["capability_ids"]),
                estimated_cost=raw["estimated_cost"],
                estimated_latency_ms=raw["estimated_latency_ms"],
                confidence=raw["confidence"],
                risk_classes=tuple(constraints["risk_classes"]),
                evidence_levels=tuple(constraints["evidence_levels"]),
                localities=tuple(constraints["localities"]),
                verifier_id=verifier["verifier_id"],
                verifier_version=verifier["verifier_version"],
            )
            if route.route_id in identifiers:
                raise ValueError(f"duplicate route_id {route.route_id!r}.")
            identifiers.add(route.route_id)
            routes.append(route)
        return cls(manifest["registry_version"], routes)


def load_route_registry(
    path: str | Path,
    *,
    known_capabilities: Sequence[str] | None = None,
    verifiers: VerifierRegistry | None = None,
) -> RouteRegistry:
    """Read a route manifest, rejecting malformed or ambiguous JSON."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        manifest = json.loads(
            text,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
    except ValueError as exc:
        raise ValueError(f"Route manifest is not valid JSON: {exc}") from exc
    return RouteRegistry.from_manifest(
        manifest, known_capabilities=known_capabilities, verifiers=verifiers
    )


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite number {value!r} is not supported")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key!r} is not allowed")
        result[key] = value
    return result
