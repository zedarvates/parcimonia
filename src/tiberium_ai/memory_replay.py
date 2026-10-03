"""Offline sequential memory replay over explicit local source/trace/label files.

No source discovery, transport or route execution. Source integrity is not fact
truth; labels remain separate, attributed, and bound to an exact sequence hash.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Sequence

from .benchmark import BenchmarkCase, BenchmarkRoute
from .compact_memory import CompactMemory, MemoryContext, MemoryFact, MemoryLimits, SCHEMA, _identity
from .context_router import ContextShadowRouter
from .contracts import CandidateRoute, Decision, Task
from .router import ShadowRouter
from .verification import VerifierRegistry, hash_input

VARIANTS = ("full_history", "compact", "compact_persistent")
SOURCE_VERIFIER = "memory.archive_integrity"
VERIFIER_VERSION = "1"
MAX_FILE_BYTES = 32 * 1024 * 1024
_TASK_FIELDS = frozenset({"task_id", "kind", "inputs", "risk_class", "evidence_level", "locality"})
_ROUTE_FIELDS = frozenset({"route_id", "capability_ids", "estimated_cost", "estimated_latency_ms",
                           "confidence", "known_failure_modes"})


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _closed(record: Any, required: set[str], optional: set[str] | frozenset[str] = frozenset()) -> None:
    if not isinstance(record, dict) or not required <= set(record) or set(record) - required - optional:
        raise ValueError("record has missing or unexpected fields.")


def _strings(values: Any, *, unique: bool = True) -> None:
    if not isinstance(values, list):
        raise ValueError("expected a list of identifiers.")
    for value in values:
        _identity(value, "identifier")
    if unique and len(values) != len(set(values)):
        raise ValueError("duplicate identifier.")


def _safe_id(value: Any) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value):
        raise ValueError("sequence_id must be a filename-safe identifier of at most 64 characters.")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field.")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("non-finite JSON number.")


def read_jsonl(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Read one explicit file, with no private data copied into error messages."""
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("JSONL input exceeds the 32 MiB file limit.")
    rows = []
    for number, line in enumerate(data.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=_object, parse_constant=_nonfinite)
            if not isinstance(row, dict):
                raise ValueError("row must be an object")
            _encode(row)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid JSON object at line {number}.") from exc
        rows.append(row)
    if not rows:
        raise ValueError("at least one JSONL row is required.")
    return tuple(rows)


class VersionedFactArchive:
    """Caller-owned external archive; immutable pins survive working-state eviction.

    Each value is encoded on insertion and decoded on lookup. The built-in
    verifier proves exact membership of that supplied snapshot, not its truth.
    """

    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self._facts: dict[tuple[str, str, str], str] = {}
        for row in rows:
            _closed(row, {"entity_id", "source_version", "key", "value"})
            for name in ("entity_id", "source_version", "key"):
                _identity(row[name], name)
            scope = (row["entity_id"], row["key"], row["source_version"])
            encoded = _encode(row)
            if scope in self._facts and self._facts[scope] != encoded:
                raise ValueError("immutable source-version conflict.")
            self._facts[scope] = encoded
        if not self._facts:
            raise ValueError("at least one archived fact is required.")
        self._encoded = _encode([json.loads(v) for _, v in sorted(self._facts.items())])
        self.revision = hash_input(json.loads(self._encoded))
        self.registry = VerifierRegistry()
        accepted = {hash_input(json.loads(value)) for value in self._facts.values()}
        self.registry.register(SOURCE_VERIFIER, VERIFIER_VERSION, lambda p: hash_input(p) in accepted)

    @property
    def utf8_bytes(self) -> int:
        return len(self._encoded.encode("utf-8"))

    def source(self, entity: str, key: str, version: str) -> MemoryFact | None:
        encoded = self._facts.get((entity, key, version))
        if encoded is None:
            return None
        row = json.loads(encoded)
        return MemoryFact(entity, key, version, row["value"], SOURCE_VERIFIER, VERIFIER_VERSION)


def validate_sequence(row: dict[str, Any]) -> None:
    _closed(row, {"schema", "sequence_id", "origin", "source_ref", "producer_id", "turns"}, {"initial_history"})
    if row["schema"] != "memory-sequence/1" or row["origin"] not in {"authored", "captured", "public"}:
        raise ValueError("unsupported sequence schema or declared origin.")
    _safe_id(row["sequence_id"])
    for name in ("source_ref", "producer_id"):
        _identity(row[name], name)
    if not isinstance(row.get("initial_history", []), list):
        raise ValueError("initial_history must be a list.")
    if not isinstance(row["turns"], list) or not row["turns"]:
        raise ValueError("a sequence requires a nonempty turns list.")
    task_ids = set()
    for turn in row["turns"]:
        _closed(turn, {"task", "required_keys", "candidates", "routing_epoch"},
                {"critical_change", "restart", "history_events", "required_capabilities"})
        _identity(turn["routing_epoch"], "routing_epoch")
        for flag in ("critical_change", "restart"):
            if type(turn.get(flag, False)) is not bool:
                raise ValueError("turn flags must be booleans.")
        if not isinstance(turn.get("history_events", []), list):
            raise ValueError("history_events must be a list.")
        _strings(turn["required_keys"])
        _strings(turn.get("required_capabilities", []))
        task = turn["task"]
        _closed(task, {"task_id", "kind", "inputs"}, _TASK_FIELDS)
        for name in _TASK_FIELDS - {"inputs"}:
            if name in task:
                _identity(task[name], name)
        if task["task_id"] in task_ids:
            raise ValueError("duplicate task_id inside a sequence.")
        task_ids.add(task["task_id"])
        if not isinstance(task["inputs"], dict):
            raise ValueError("task inputs must be a JSON object.")
        for name in ("entity_id", "source_version"):
            _identity(task["inputs"].get(name), name)
        if not isinstance(turn["candidates"], list):
            raise ValueError("candidates must be a list.")
        for candidate in turn["candidates"]:
            _closed(candidate, {"route_id", "capability_ids"}, _ROUTE_FIELDS)
            _identity(candidate["route_id"], "route_id")
            _strings(candidate["capability_ids"])
            _strings(candidate.get("known_failure_modes", []))
    _encode(row)


def validate_outcomes(label: dict[str, Any], sequence: dict[str, Any], archive_revision: str) -> str | None:
    """Validate exact linkage; return why a label cannot supply a verdict."""
    _closed(label, {"schema", "sequence_id", "sequence_hash", "archive_revision", "origin", "labeller_id", "source_ref", "turns"})
    if label["schema"] != "memory-outcomes/1" or label["origin"] not in {"authored", "outcomes"}:
        raise ValueError("unsupported outcomes schema or declared origin.")
    if label["sequence_id"] != sequence["sequence_id"] or label["sequence_hash"] != hash_input(sequence):
        raise ValueError("outcomes do not match the exact sequence revision.")
    if label["archive_revision"] != archive_revision:
        raise ValueError("outcomes do not match the exact archive revision.")
    for name in ("labeller_id", "source_ref"):
        _identity(label[name], name)
    if not isinstance(label["turns"], list) or len(label["turns"]) != len(sequence["turns"]):
        raise ValueError("outcomes must cover every turn in sequence order.")
    for expected, turn in zip(label["turns"], sequence["turns"]):
        _closed(expected, {"task_id", "facts", "missing", "allowed_routes"})
        if expected["task_id"] != turn["task"]["task_id"] or not isinstance(expected["facts"], dict):
            raise ValueError("outcome task or facts mismatch.")
        _strings(expected["missing"])
        keys = set(expected["facts"])
        if keys & set(expected["missing"]) or keys | set(expected["missing"]) != set(turn["required_keys"]):
            raise ValueError("outcome facts and missing must partition the requested keys.")
        allowed = expected["allowed_routes"]
        if not isinstance(allowed, list) or not allowed:
            raise ValueError("allowed_routes must be a nonempty list.")
        candidate_ids = {c["route_id"] for c in turn["candidates"]}
        if any(route is not None and route not in candidate_ids for route in allowed):
            raise ValueError("outcome names an unavailable route.")
    _encode(label)
    if label["origin"] == "outcomes" and label["labeller_id"] == sequence["producer_id"]:
        return "dependent_labels"
    return None


def _full_context(archive: VersionedFactArchive, entity: str, version: str, keys: Sequence[str]) -> MemoryContext:
    facts, missing = [], []
    for key in keys:
        fact = archive.source(entity, key, version)
        if fact is None:
            missing.append({"key": key, "reason": "source_missing"})
            continue
        proof = archive.registry.verify(fact.verifier_id, fact.verifier_version, fact.payload())
        if proof.verdict is True:
            facts.append({"key": key, "value": fact.value, "verification": proof.to_record()})
        else:
            missing.append({"key": key, "reason": proof.detail_code or "verification_rejected"})
    return MemoryContext(_encode({"schema": SCHEMA, "entity_id": entity, "source_version": version,
                                  "facts": facts, "missing": missing}))


def _replay(sequence, archive, variant, limits, margin, max_holds):
    memory = CompactMemory(archive.source, archive.registry, limits=limits)
    persistent = ContextShadowRouter(max_holds=max_holds, relative_cost_margin=margin, max_entities=limits.max_entities)
    base = ShadowRouter()
    history = list(sequence.get("initial_history", []))
    turns, sizes, previous = [], [], {}
    switches = 0
    for turn in sequence["turns"]:
        if turn.get("restart", False):
            checkpoint = memory.checkpoint()
            memory = CompactMemory(archive.source, archive.registry, limits=limits)
            memory.restore(checkpoint)
            persistent = ContextShadowRouter(max_holds=max_holds, relative_cost_margin=margin, max_entities=limits.max_entities)
        task = Task(**turn["task"])
        entity, version = task.inputs["entity_id"], task.inputs["source_version"]
        context = (_full_context(archive, entity, version, turn["required_keys"]) if variant == "full_history"
                   else memory.context(entity, version, turn["required_keys"]))
        record = context.to_record()
        facts = {f["key"]: f["value"] for f in record["facts"]}
        missing = [m["key"] for m in record["missing"]]
        history.extend(turn.get("history_events", []))
        history.append({"task": asdict(task), "facts": facts, "missing": missing})
        payload = {"task": asdict(task), "candidates": turn["candidates"]}
        payload["history" if variant == "full_history" else "memory"] = history if variant == "full_history" else record
        sizes.append(len(_encode(payload).encode("utf-8")))
        candidates = [CandidateRoute(**c) for c in turn["candidates"]]
        required = tuple(turn.get("required_capabilities", []))
        if variant == "compact_persistent":
            decision = persistent.propose(task, candidates, context=context, routing_epoch=turn["routing_epoch"],
                                          critical_change=turn.get("critical_change", False), required_capabilities=required)
        elif not context.complete:
            decision = Decision(task.task_id, None, abstained=True, rationale="Unresolved source fact.")
        else:
            # Keep explicit-candidate capability checks equivalent across arms.
            decision = base.propose(task, candidates)
            if not decision.abstained:
                decision = base.propose(task, [c for c in candidates if set(required) <= set(c.capability_ids)])
        if entity in previous and previous[entity] != decision.selected_route_id:
            switches += 1
        previous[entity] = decision.selected_route_id
        turns.append({"task_id": task.task_id, "entity_id": entity, "source_version": version,
                      "facts": facts, "missing": missing, "selected_route_id": decision.selected_route_id,
                      "abstained": decision.abstained, "mode": decision.mode})
    return {"turns": turns, "metrics": {"prepared_context_utf8_bytes": sum(sizes),
            "peak_context_utf8_bytes": max(sizes), "route_switches_including_abstentions": switches,
            "external_archive_utf8_bytes": archive.utf8_bytes, "tokens": None, "provider_cost": None}}


def _oracle(label, sequence):
    def verify(output):
        actual = output.get("turns", [])
        if len(actual) != len(label["turns"]):
            return False
        for result, expected, turn in zip(actual, label["turns"], sequence["turns"]):
            inputs = turn["task"]["inputs"]
            if (result.get("task_id") != expected["task_id"] or result.get("entity_id") != inputs["entity_id"]
                    or result.get("source_version") != inputs["source_version"]
                    or hash_input(result.get("facts")) != hash_input(expected["facts"])
                    or sorted(result.get("missing", [])) != sorted(expected["missing"])
                    or result.get("selected_route_id") not in expected["allowed_routes"]
                    or result.get("abstained") != (result.get("selected_route_id") is None)
                    or result.get("mode") != "shadow"):
                return False
        return True
    return verify


def build_memory_replay_cases(
    sequences: Sequence[dict[str, Any]], archive: VersionedFactArchive, *,
    outcomes: Sequence[dict[str, Any]] = (), limits: MemoryLimits | None = None,
    relative_cost_margin: float = 0.0, max_holds: int = 3,
    outputs: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[BenchmarkCase], dict[str, Any]]:
    """Create normal benchmark cases; never manufacture a missing quality label."""
    sequences = json.loads(_encode(list(sequences)))
    outcomes = json.loads(_encode(list(outcomes)))
    active_limits = limits or MemoryLimits()
    ContextShadowRouter(max_holds=max_holds, relative_cost_margin=relative_cost_margin)
    if not sequences:
        raise ValueError("at least one sequence is required.")
    labels, seen, statuses = {}, set(), {}
    for label in outcomes:
        if label.get("sequence_id") in labels:
            raise ValueError("duplicate outcome sequence.")
        labels[label.get("sequence_id")] = label
    cases = []
    for sequence in sequences:
        validate_sequence(sequence)
        case_id = sequence["sequence_id"]
        if case_id in seen:
            raise ValueError("duplicate sequence_id.")
        seen.add(case_id)
        if any(len(t["required_keys"]) > active_limits.max_refs_per_entity for t in sequence["turns"]):
            raise ValueError("requested keys exceed the declared working-reference budget.")
        label = labels.get(case_id)
        reason = "missing_outcomes" if label is None else validate_outcomes(label, sequence, archive.revision)
        statuses[case_id] = reason or ("declared_outcomes" if label["origin"] == "outcomes" else "authored_labels")
        verifier = None if reason else _oracle(label, sequence)
        version = VERIFIER_VERSION if label is None else VERIFIER_VERSION + ":" + hash_input(label)
        def run(variant, sequence=sequence):
            result = _replay(sequence, archive, variant, active_limits, relative_cost_margin, max_holds)
            if outputs is not None:
                outputs.setdefault(sequence["sequence_id"], {})[variant] = result
            return result
        routes = tuple(BenchmarkRoute(v, lambda v=v, run=run: run(v), confidence=0.95) for v in VARIANTS)
        cases.append(BenchmarkCase(Task(case_id, "memory-sequence-replay", {}), routes,
                                    "memory.sequence_exact:" + case_id, version, verifier, "full_history"))
    if set(labels) - seen:
        raise ValueError("outcomes reference a sequence outside this corpus.")
    provenance = {"schema": "memory-replay-provenance/1", "sequence_revision": hash_input(sequences),
                  "archive_revision": archive.revision, "outcomes_revision": hash_input(outcomes),
                  "origins": {s["sequence_id"]: s["origin"] for s in sequences}, "label_status": statuses,
                  "source_attribution": {s["sequence_id"]: {
                      "source_ref": s["source_ref"], "producer_id": s["producer_id"], "origin": s["origin"]
                  } for s in sequences},
                  "outcome_attribution": {case_id: {
                      "source_ref": label["source_ref"], "labeller_id": label["labeller_id"],
                      "origin": label["origin"], "revision": hash_input(label)
                  } for case_id, label in labels.items()},
                  "policy": {"relative_cost_margin": relative_cost_margin, "max_holds": max_holds,
                             "limits": asdict(active_limits)},
                  "claim_scope": "Offline retrieval/route contract replay; source origins are caller-declared.",
                  "production_saving_claim": {"status": "refused", "reason": "no model or provider usage measurement"}}
    return cases, provenance
