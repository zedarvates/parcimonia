"""Bounded working references with exact, versioned fact retrieval.

The caller owns the source and its verifiers. This module retains no history or
fact values, executes no route, and never treats a checkpoint as verified data.
"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

from .contracts import validate_verification_record
from .verification import VerifierRegistry, hash_input

SCHEMA = "compact-memory/1"
_REFERENCE_FIELDS = frozenset({"key", "input_hash", "verifier_id", "verifier_version"})


def _identity(value: object, name: str) -> None:
    if (not isinstance(value, str) or not value or value != value.strip()
            or len(value.encode("utf-8")) > 128):
        raise ValueError(f"{name} must be a trimmed identifier of at most 128 UTF-8 bytes.")


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class MemoryLimits:
    max_entities: int = 8
    max_refs_per_entity: int = 16
    max_context_bytes: int = 8192
    max_fact_bytes: int = 4096

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer.")


@dataclass(frozen=True)
class MemoryFact:
    entity_id: str
    key: str
    source_version: str
    value: Any
    verifier_id: str
    verifier_version: str

    def __post_init__(self) -> None:
        for name in ("entity_id", "key", "source_version", "verifier_id", "verifier_version"):
            _identity(getattr(self, name), name)

    def payload(self) -> dict[str, Any]:
        # Detach nested mutable values before a caller-supplied verifier sees them.
        return json.loads(_encode({
            "entity_id": self.entity_id, "key": self.key,
            "source_version": self.source_version, "value": self.value,
        }))


@dataclass(frozen=True)
class MemoryContext:
    """An immutable encoded context; structural validation is not source trust.

    Callers must obtain fresh contexts through CompactMemory. An exported JSON
    record is evidence to inspect, not an authenticated context to import.
    """

    encoded: str

    def __post_init__(self) -> None:
        record = self.to_record()
        if not isinstance(record, dict) or set(record) != {
            "schema", "entity_id", "source_version", "facts", "missing"
        } or record["schema"] != SCHEMA:
            raise ValueError("invalid memory context fields or schema.")
        for name in ("entity_id", "source_version"):
            _identity(record[name], name)
        if not isinstance(record["facts"], list) or not isinstance(record["missing"], list):
            raise ValueError("context facts and missing must be lists.")
        keys: set[str] = set()
        for fact in record["facts"]:
            if not isinstance(fact, dict) or set(fact) != {"key", "value", "verification"}:
                raise ValueError("invalid context fact fields.")
            _identity(fact["key"], "key")
            validate_verification_record(fact["verification"])
            payload = {"entity_id": record["entity_id"], "source_version": record["source_version"],
                       "key": fact["key"], "value": fact["value"]}
            if (fact["verification"]["verdict"] is not True
                    or fact["verification"]["input_hash"] != hash_input(payload)):
                raise ValueError("context fact lacks an accepted, matching verification.")
            if fact["key"] in keys:
                raise ValueError("duplicate context key.")
            keys.add(fact["key"])
        for missing in record["missing"]:
            if not isinstance(missing, dict) or set(missing) != {"key", "reason"}:
                raise ValueError("invalid missing fact fields.")
            _identity(missing["key"], "key")
            _identity(missing["reason"], "reason")
            if missing["key"] in keys:
                raise ValueError("duplicate context key.")
            keys.add(missing["key"])
        _encode(record)  # reject non-finite JSON, including manually supplied NaN

    @property
    def complete(self) -> bool:
        return not self.to_record()["missing"]

    @property
    def fingerprint(self) -> str:
        return hash_input(self.to_record())

    @property
    def utf8_bytes(self) -> int:
        return len(self.encoded.encode("utf-8"))

    def to_record(self) -> dict[str, Any]:
        return json.loads(self.encoded)


@dataclass
class _EntityState:
    source_version: str
    references: OrderedDict[str, dict[str, str]] = field(default_factory=OrderedDict)


class CompactMemory:
    """Revalidate explicitly requested facts through the existing registry.

    source(entity_id, key, source_version) returns a MemoryFact or None. A source
    version must be immutable: a changed payload under the same version is
    rejected while its reference is retained. Eviction forgets that local pin;
    the caller's versioned source remains responsible for immutability.
    """

    def __init__(self, source: Callable[[str, str, str], MemoryFact | None],
                 registry: VerifierRegistry, *, limits: MemoryLimits | None = None) -> None:
        if not callable(source):
            raise TypeError("source must be callable.")
        if not isinstance(registry, VerifierRegistry):
            raise TypeError("registry must be a VerifierRegistry.")
        if limits is not None and not isinstance(limits, MemoryLimits):
            raise TypeError("limits must be MemoryLimits.")
        self._source = source
        self._registry = registry
        self.limits = limits or MemoryLimits()
        self._entities: OrderedDict[str, _EntityState] = OrderedDict()

    def context(self, entity_id: str, source_version: str,
                required_keys: Sequence[str]) -> MemoryContext:
        _identity(entity_id, "entity_id")
        _identity(source_version, "source_version")
        if isinstance(required_keys, (str, bytes)):
            raise ValueError("required_keys must be a sequence of unique identifiers.")
        keys = tuple(required_keys)
        for key in keys:
            _identity(key, "key")
        if len(keys) != len(set(keys)) or len(keys) > self.limits.max_refs_per_entity:
            raise ValueError("required_keys must be unique and fit the reference budget.")
        previous = self._entities.get(entity_id)
        references = OrderedDict(
            previous.references if previous and previous.source_version == source_version else ()
        )
        facts, missing = [], []
        for key in keys:
            try:
                fact = self._source(entity_id, key, source_version)
            except Exception as exc:  # source failure is an abstention, never guessed content
                missing.append({"key": key, "reason": f"source_error:{type(exc).__name__}"})
                continue
            if fact is None:
                missing.append({"key": key, "reason": "source_missing"})
                continue
            if not isinstance(fact, MemoryFact) or (
                fact.entity_id, fact.key, fact.source_version
            ) != (entity_id, key, source_version):
                missing.append({"key": key, "reason": "scope_or_version_mismatch"})
                continue
            try:
                payload = fact.payload()
                if len(_encode(payload).encode("utf-8")) > self.limits.max_fact_bytes:
                    missing.append({"key": key, "reason": "fact_budget_exceeded"})
                    continue
                verification = self._registry.verify(
                    fact.verifier_id, fact.verifier_version, payload
                )
                if verification.input_hash != hash_input(payload):
                    missing.append({"key": key, "reason": "verifier_mutated_input"})
                    continue
            except Exception as exc:
                missing.append({"key": key, "reason": f"verification_error:{type(exc).__name__}"})
                continue
            if verification.verdict is not True:
                missing.append({"key": key, "reason": verification.detail_code or "verification_rejected"})
                continue
            reference = {
                "key": key, "input_hash": verification.input_hash,
                "verifier_id": fact.verifier_id, "verifier_version": fact.verifier_version,
            }
            if key in references and references[key] != reference:
                missing.append({"key": key, "reason": "reference_changed_without_version"})
                continue
            references[key] = reference
            references.move_to_end(key)
            facts.append({"key": key, "value": payload["value"],
                          "verification": verification.to_record()})
        record = {"schema": SCHEMA, "entity_id": entity_id,
                  "source_version": source_version, "facts": facts, "missing": missing}
        encoded = _encode(record)
        if len(encoded.encode("utf-8")) > self.limits.max_context_bytes:
            # Do not truncate a requested constraint or replace it with a summary.
            raise ValueError("context exceeds max_context_bytes; use a smaller request or abstain.")
        while len(references) > self.limits.max_refs_per_entity:
            references.popitem(last=False)
        self._entities[entity_id] = _EntityState(source_version, references)
        self._entities.move_to_end(entity_id)
        while len(self._entities) > self.limits.max_entities:
            self._entities.popitem(last=False)
        return MemoryContext(encoded)

    def checkpoint(self) -> dict[str, Any]:
        """Return bounded references only, not archived facts or an execution log."""
        body = {"schema": SCHEMA, "limits": asdict(self.limits), "entities": [
            {"entity_id": entity_id, "source_version": state.source_version,
             "references": list(state.references.values())}
            for entity_id, state in self._entities.items()
        ]}
        return {**json.loads(_encode(body)), "input_hash": hash_input(body)}

    def restore(self, checkpoint: dict[str, Any]) -> None:
        """Validate a checkpoint atomically; facts are reverified on retrieval."""
        if not isinstance(checkpoint, dict) or set(checkpoint) != {
            "schema", "limits", "entities", "input_hash"
        }:
            raise ValueError("invalid checkpoint fields.")
        body = {key: value for key, value in checkpoint.items() if key != "input_hash"}
        expected_limits = asdict(self.limits)
        if (not isinstance(checkpoint["limits"], dict)
                or set(checkpoint["limits"]) != set(expected_limits)
                or any(type(v) is not int for v in checkpoint["limits"].values())):
            raise ValueError("invalid checkpoint limits.")
        if (checkpoint["schema"] != SCHEMA or checkpoint["limits"] != expected_limits
                or checkpoint["input_hash"] != hash_input(body)):
            raise ValueError("checkpoint schema, limits or hash mismatch.")
        entries = checkpoint["entities"]
        if not isinstance(entries, list) or len(entries) > self.limits.max_entities:
            raise ValueError("checkpoint exceeds the entity budget.")
        restored: OrderedDict[str, _EntityState] = OrderedDict()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {
                "entity_id", "source_version", "references"
            }:
                raise ValueError("invalid checkpoint entity fields.")
            entity_id, version = entry["entity_id"], entry["source_version"]
            _identity(entity_id, "entity_id")
            _identity(version, "source_version")
            if entity_id in restored:
                raise ValueError("duplicate checkpoint entity.")
            refs = entry["references"]
            if not isinstance(refs, list) or len(refs) > self.limits.max_refs_per_entity:
                raise ValueError("checkpoint exceeds the reference budget.")
            state = _EntityState(version)
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != _REFERENCE_FIELDS:
                    raise ValueError("invalid checkpoint reference fields.")
                for name in ("key", "verifier_id", "verifier_version"):
                    _identity(ref[name], name)
                digest = ref["input_hash"]
                if (not isinstance(digest, str) or len(digest) != 64
                        or any(c not in "0123456789abcdef" for c in digest)):
                    raise ValueError("invalid reference input_hash.")
                if ref["key"] in state.references:
                    raise ValueError("duplicate checkpoint reference.")
                state.references[ref["key"]] = dict(ref)
            restored[entity_id] = state
        self._entities = restored
