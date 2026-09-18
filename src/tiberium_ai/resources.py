"""Measured resource vectors, kept apart from constraints and policy.

A vector carries only resources. Hard constraints such as risk class or
locality never enter it, and no weighted scalar combines the dimensions, so a
trade-off stays visible instead of being averaged away.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .router import is_nonnegative_number

__all__ = ["DIMENSIONS", "ResourceVector", "pareto_front"]

DIMENSIONS = ("tokens", "latency_ms", "vram_mb", "energy_joules")


@dataclass(frozen=True)
class ResourceVector:
    """Resources consumed by one route. `None` means not measured."""

    tokens: int | None = None
    latency_ms: float | None = None
    vram_mb: float | None = None
    energy_joules: float | None = None

    def __post_init__(self) -> None:
        if self.tokens is not None and (
            type(self.tokens) is not int or self.tokens < 0
        ):
            raise ValueError("tokens must be null or a nonnegative integer.")
        for name in DIMENSIONS[1:]:
            value = getattr(self, name)
            if value is not None and not is_nonnegative_number(value):
                raise ValueError(f"{name} must be null or a finite nonnegative number.")

    def dominates(self, other: "ResourceVector") -> bool:
        """Return whether this vector is better on a shared dimension only.

        Unknown dimensions are ignored rather than assumed equal, and at least
        one strictly better dimension is required, so ties never dominate.
        """
        if not isinstance(other, ResourceVector):
            raise TypeError("other must be a ResourceVector.")
        strictly_better = False
        for name in DIMENSIONS:
            mine = getattr(self, name)
            theirs = getattr(other, name)
            if mine is None or theirs is None:
                continue
            if mine > theirs:
                return False
            if mine < theirs:
                strictly_better = True
        return strictly_better

    def to_record(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in DIMENSIONS}

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "ResourceVector":
        if not isinstance(record, Mapping) or set(record) != set(DIMENSIONS):
            raise ValueError(f"a resource vector record must contain exactly {list(DIMENSIONS)}.")
        return cls(**{name: record[name] for name in DIMENSIONS})

    @classmethod
    def from_measurement(cls, record: Mapping[str, Any]) -> "ResourceVector":
        """Build a vector from a measured run.

        Latency always comes from the record; tokens, VRAM and energy come from
        the version 2 resources block and stay unknown for version 1 records.
        """
        if not isinstance(record, Mapping) or not is_nonnegative_number(
            record.get("latency_ms")
        ):
            raise ValueError(
                "a measurement record must carry a finite nonnegative latency_ms."
            )
        resources = record.get("resources")
        if resources is None:
            return cls(latency_ms=record["latency_ms"])
        if not isinstance(resources, Mapping) or set(resources) != {
            "tokens",
            "vram_mb",
            "energy_joules",
        }:
            raise ValueError(
                "a resources block must contain exactly tokens, vram_mb and energy_joules."
            )
        return cls(
            tokens=resources["tokens"],
            latency_ms=record["latency_ms"],
            vram_mb=resources["vram_mb"],
            energy_joules=resources["energy_joules"],
        )


def pareto_front(vectors: Mapping[str, ResourceVector]) -> tuple[str, ...]:
    """Return the non-dominated route ids, sorted for determinism."""
    front = []
    for name, vector in vectors.items():
        if not isinstance(vector, ResourceVector):
            raise TypeError("vectors values must be ResourceVector instances.")
        if not any(
            other.dominates(vector)
            for other_name, other in vectors.items()
            if other_name != name
        ):
            front.append(name)
    return tuple(sorted(front))
