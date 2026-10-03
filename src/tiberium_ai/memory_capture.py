"""Explicit bounded capture for the existing offline memory replay contract.

The caller supplies observed turns, exact source facts and optional usage.
Nothing intercepts an agent, executes a route, supplies labels or calls a model.
Raw capture files are private inputs, unlike the payload-free replay reports.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .compact_memory import _identity
from .memory_replay import (
    MAX_FILE_BYTES, VARIANTS, VersionedFactArchive, _closed, _encode,
    _safe_id, _strings, validate_sequence,
)
from .router import is_nonnegative_number
from .verification import hash_input

_USAGE_REQUIRED = {"receipt_id", "origin", "source_ref", "variant", "backend_id",
                   "backend_version", "payload_hash"}
_USAGE_METRICS = {"input_tokens", "output_tokens", "tokens_total", "n_retries",
                  "latency_ms", "cost", "cost_unit"}
_USAGE_ORIGINS = {"authored", "provider_reported", "local_measured", "caller_reported"}


def _clone(value: Any) -> Any:
    return json.loads(_encode(value))


def _usage(record: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise ValueError("usage must be a mapping.")
    item = _clone(dict(record))
    _closed(item, _USAGE_REQUIRED, _USAGE_METRICS)
    for name in ("receipt_id", "source_ref", "backend_id", "backend_version"):
        _identity(item[name], name)
    if item["origin"] not in _USAGE_ORIGINS or item["variant"] not in (*VARIANTS, "current"):
        raise ValueError("unsupported usage origin or variant.")
    payload_hash = item["payload_hash"]
    if payload_hash is not None and (not isinstance(payload_hash, str)
                                    or not re.fullmatch(r"[0-9a-f]{64}", payload_hash)):
        raise ValueError("payload_hash must be a canonical input hash or null.")
    for name in _USAGE_METRICS:
        item.setdefault(name, None)
    for name in ("input_tokens", "output_tokens", "tokens_total", "n_retries"):
        if item[name] is not None and (type(item[name]) is not int or item[name] < 0):
            raise ValueError("usage counts must be nonnegative integers or null.")
    for name in ("latency_ms", "cost"):
        if item[name] is not None and not is_nonnegative_number(item[name]):
            raise ValueError("usage measurements must be finite nonnegative numbers or null.")
    if item["cost_unit"] is not None:
        _identity(item["cost_unit"], "cost_unit")
    if item["cost"] is not None and item["cost_unit"] is None:
        raise ValueError("a recorded cost needs an explicit unit.")
    if item["input_tokens"] is not None and item["output_tokens"] is not None:
        total = item["input_tokens"] + item["output_tokens"]
        if item["tokens_total"] is not None and item["tokens_total"] != total:
            raise ValueError("token total contradicts the recorded input/output counts.")
        item["tokens_total"] = total
    return item


class MemorySequenceCapture:
    """One caller-declared episode; source absence is immutable within a version.

    Append and usage validation commit together with their respective bounded
    state checks. Capture failures are raised to the caller, never hidden as
    successful logging. Usage is a sidecar, never an offline measurement.
    """

    def __init__(self, *, sequence_id: str, origin: str, source_ref: str,
                 producer_id: str, initial_history: Sequence[Any] = (),
                 max_turns: int = 256, max_capture_bytes: int = MAX_FILE_BYTES) -> None:
        _safe_id(sequence_id)
        for name, value in (("source_ref", source_ref), ("producer_id", producer_id)):
            _identity(value, name)
        if origin not in {"authored", "captured", "public"}:
            raise ValueError("unsupported declared capture origin.")
        if not isinstance(initial_history, (list, tuple)):
            raise ValueError("initial_history must be a list or tuple.")
        for limit in (max_turns, max_capture_bytes):
            if type(limit) is not int or limit < 1:
                raise ValueError("capture limits must be positive integers.")
        if max_capture_bytes > MAX_FILE_BYTES:
            raise ValueError("capture byte limit must fit the 32 MiB replay input limit.")
        self._sequence = _clone({"schema": "memory-sequence/1", "sequence_id": sequence_id,
                                 "origin": origin, "source_ref": source_ref,
                                 "producer_id": producer_id, "initial_history": list(initial_history),
                                 "turns": []})
        self._pins: dict[tuple[str, str, str], str | None] = {}
        self._receipts: list[dict[str, Any]] = []
        self._max_turns, self._max_bytes = max_turns, max_capture_bytes
        self._package(self._sequence, self._pins, self._receipts)

    def append_turn(self, turn: Mapping[str, Any], *, facts: Mapping[str, Any],
                    missing: Sequence[str]) -> None:
        if len(self._sequence["turns"]) >= self._max_turns:
            raise ValueError("capture turn limit exceeded.")
        if not isinstance(turn, Mapping):
            raise ValueError("turn must be a mapping.")
        sequence = _clone(self._sequence)
        sequence["turns"].append(_clone(dict(turn)))
        validate_sequence(sequence)
        turn = sequence["turns"][-1]
        if not isinstance(facts, Mapping) or not isinstance(missing, (list, tuple)):
            raise ValueError("facts must be a mapping and missing must be a list or tuple.")
        facts, missing = _clone(dict(facts)), list(missing)
        _strings(missing)
        requested = set(turn["required_keys"])
        if set(facts) & set(missing) or set(facts) | set(missing) != requested:
            raise ValueError("observed facts and missing keys must partition the requested keys.")
        inputs = turn["task"]["inputs"]
        pins = dict(self._pins)
        for key in turn["required_keys"]:
            scope = (inputs["entity_id"], key, inputs["source_version"])
            value = _encode({"entity_id": scope[0], "key": key, "source_version": scope[2],
                             "value": facts[key]}) if key in facts else None
            if scope in pins and pins[scope] != value:
                raise ValueError("immutable source-version conflict, including observed absence.")
            pins[scope] = value
        self._package(sequence, pins, self._receipts)
        self._sequence, self._pins = sequence, pins

    def record_usage(self, task_id: str, receipt: Mapping[str, Any]) -> None:
        turn = next((t for t in self._sequence["turns"] if t["task"]["task_id"] == task_id), None)
        if turn is None:
            raise ValueError("usage must reference an already captured task.")
        item = _usage(receipt)
        if any(r["receipt_id"] == item["receipt_id"] for r in self._receipts):
            raise ValueError("duplicate usage receipt identity.")
        item.update(task_id=task_id, turn_hash=hash_input(turn))
        receipts = [*self._receipts, item]
        self._package(self._sequence, self._pins, receipts)
        self._receipts = receipts

    def _package(self, sequence, pins, receipts):
        facts = [json.loads(value) for _, value in sorted(pins.items()) if value is not None]
        archive = VersionedFactArchive(facts)
        sequence_hash = hash_input(sequence)
        usage = [{"schema": "memory-usage/1", **r, "sequence_id": sequence["sequence_id"],
                  "sequence_hash": sequence_hash, "archive_revision": archive.revision} for r in receipts]
        manifest = {"schema": "memory-capture/1", "sequence_id": sequence["sequence_id"],
                    "sequence_hash": sequence_hash, "archive_revision": archive.revision,
                    "usage_revision": hash_input(usage), "origin": sequence["origin"],
                    "turns": len(sequence["turns"]), "facts": len(facts), "usage_receipts": len(usage),
                    "outcomes": "not_collected", "raw_inputs_present": True,
                    "production_saving_claim": {"status": "refused", "reason": "capture is not a comparison"}}
        package = {"sequence": sequence, "facts": facts, "usage": usage, "manifest": manifest}
        payloads = self._payloads(package)
        if sum(len(v.encode("utf-8")) for v in payloads.values()) > self._max_bytes:
            raise ValueError("capture byte limit exceeded.")
        return package

    @staticmethod
    def _payloads(package):
        def lines(rows):
            return "".join(_encode(r) + "\n" for r in rows)
        return {"sequences.jsonl": lines([package["sequence"]]), "facts.jsonl": lines(package["facts"]),
                "usage.jsonl": lines(package["usage"]), "manifest.json": _encode(package["manifest"]) + "\n"}

    def snapshot(self) -> dict[str, Any]:
        if not self._sequence["turns"]:
            raise ValueError("capture requires at least one observed turn.")
        return _clone(self._package(self._sequence, self._pins, self._receipts))

    def write(self, directory: str | Path) -> dict[str, Any]:
        """Write explicit private inputs to a fresh directory; never overwrite."""
        package = self.snapshot()
        payloads = self._payloads(package)
        directory = Path(directory)
        directory.mkdir(mode=0o700, parents=False, exist_ok=False)
        created = []
        try:
            for name, payload in payloads.items():
                path = directory / name
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                created.append(path)
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
                    stream.write(payload)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            directory.rmdir()
            raise
        return _clone(package["manifest"])


def capture_rows(rows: Sequence[Mapping[str, Any]], **metadata) -> MemorySequenceCapture:
    """Convert an explicit export; no heuristics or invented observations."""
    capture = MemorySequenceCapture(**metadata)
    for row in rows:
        row = _clone(row)
        _closed(row, {"schema", "turn", "facts", "missing"}, {"usage"})
        if row["schema"] != "memory-capture-turn/1" or not isinstance(row.get("usage", []), list):
            raise ValueError("unsupported capture turn schema or usage list.")
        capture.append_turn(row["turn"], facts=row["facts"], missing=row["missing"])
        for receipt in row.get("usage", []):
            capture.record_usage(row["turn"]["task"]["task_id"], receipt)
    capture.snapshot()
    return capture
