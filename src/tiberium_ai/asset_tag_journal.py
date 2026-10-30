"""Pure, append-only review declarations bound to exact inspection reports.

The hash chain detects inconsistent records, not authenticated actors or a
coherent rewrite of history. No decision grants execution authority or proves
that an observed or proposed tag is true.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any

from .asset_catalog import _report
from .verification import hash_input

__all__ = [
    "MAX_TAG_PROPOSALS", "validated_review_report_hash", "create_tag_journal",
    "validate_tag_journal", "append_tag_decision",
]

JOURNAL_SCHEMA = "parcimonia.asset-tag-journal/v1"
DECISION_SCHEMA = "parcimonia.asset-tag-decision/v1"
MAX_EVENTS = 1024
MAX_TAG_PROPOSALS = 256
_ACTIONS = {"accept", "reject", "reset"}
_JOURNAL_FIELDS = {"schema", "events", "head_hash"}
_EVENT_FIELDS = {
    "schema", "event_id", "sequence", "previous_hash", "source",
    "report_hash", "tag", "action", "actor_id", "reason", "event_hash",
}


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _text(value: Any, label: str, maximum: int = 4096) -> None:
    if type(value) is not str or not value or value != value.strip() or len(value) > maximum:
        raise ValueError(f"{label} must be a trimmed string of 1..{maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8 text.") from exc


def _hash(value: Any, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 string.")


def _tag(namespace: Any, value: Any) -> None:
    _text(namespace, "tag.namespace")
    _text(value, "tag.value")
    if ":" in namespace:
        raise ValueError("tag.namespace must not contain ':'.")


def _declaration(action: Any, actor_id: Any, reason: Any, event_id: Any) -> None:
    _text(action, "action", 6)
    if action not in _ACTIONS:
        raise ValueError("action must be accept, reject or reset.")
    _text(actor_id, "actor_id", 256)
    _text(reason, "reason", 2048)
    _text(event_id, "event_id", 128)


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in event.items() if key != "event_hash"}


def _finite_hash(value: Any, label: str) -> str:
    try:
        return hash_input(value)
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"{label} must be finite UTF-8 JSON.") from exc


def _validate_report_json(report: Any) -> None:
    """Reject Python-only values before the canonical JSON encoder can coerce.

    Acyclic shared sub-objects are valid: each occurrence is counted in the
    serialized tree. Active-path identities reject cycles without confusing
    shared values with circular references. Reservations bound the traversal
    queue as well as the number of visited nodes.
    """
    pending = [(report, 0, False)]
    active: set[int] = set()
    reserved = 1
    while pending:
        value, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(value))
            continue
        if depth > 64:
            raise ValueError("Inspection report JSON exceeds depth 64.")
        kind = type(value)
        if kind is dict or kind is list:
            identity = id(value)
            if identity in active:
                raise ValueError("Inspection report JSON must not contain cycles.")
            if reserved + len(value) > 20_000:
                raise ValueError("Inspection report JSON exceeds 20000 nodes.")
            reserved += len(value)
            active.add(identity)
            pending.append((value, depth, True))
            if kind is dict:
                for key, child in value.items():
                    if type(key) is not str:
                        raise ValueError("Inspection report JSON object keys must be strings.")
                    try:
                        key.encode("utf-8")
                    except UnicodeError as exc:
                        raise ValueError("Inspection report must be finite UTF-8 JSON.") from exc
                    pending.append((child, depth + 1, False))
            else:
                pending.extend((child, depth + 1, False) for child in value)
        elif kind is str:
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise ValueError("Inspection report must be finite UTF-8 JSON.") from exc
        elif kind is float:
            if not math.isfinite(value):
                raise ValueError("Inspection report must be finite UTF-8 JSON.")
        elif kind is not int and kind is not bool and kind is not type(None):
            raise ValueError("Inspection report values must use exact JSON types.")


def validated_review_report_hash(report: Any) -> str:
    """Validate a bounded pure-JSON inspection record and return its exact hash.

    This shared producer/consumer boundary does not allow tuple/list or
    non-string/string-key coercions to inherit a review through the same hash.
    It validates declared structure and provenance, not source truth.
    """
    if type(report) is dict and type(report.get("tag_proposals")) is list and len(report["tag_proposals"]) > MAX_TAG_PROPOSALS:
        raise ValueError(f"An inspection report is limited to {MAX_TAG_PROPOSALS} tag proposals.")
    _validate_report_json(report)
    _report(report)
    return _finite_hash(report, "inspection report")


def create_tag_journal() -> dict[str, Any]:
    """Return a fresh empty journal; no event, clock or storage is created."""
    return {"schema": JOURNAL_SCHEMA, "events": [], "head_hash": None}


def validate_tag_journal(journal: Any) -> None:
    """Validate strict records, sequence, IDs, hash links and the final head.

    This establishes internal consistency only. Without an independently kept
    head, coherent replacement or truncation of history is not detectable.
    """
    _object(journal, _JOURNAL_FIELDS, "tag journal")
    if type(journal["schema"]) is not str or journal["schema"] != JOURNAL_SCHEMA:
        raise ValueError("Unsupported tag journal schema.")
    events = journal["events"]
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError(f"events must be an array of at most {MAX_EVENTS} records.")
    _hash(journal["head_hash"], "head_hash", optional=True)
    seen_ids: set[str] = set()
    previous = None
    for position, event in enumerate(events, start=1):
        _object(event, _EVENT_FIELDS, "tag decision")
        if type(event["schema"]) is not str or event["schema"] != DECISION_SCHEMA:
            raise ValueError("Unsupported tag decision schema.")
        _declaration(event["action"], event["actor_id"], event["reason"], event["event_id"])
        if event["event_id"] in seen_ids:
            raise ValueError("event_id must be unique within the journal.")
        seen_ids.add(event["event_id"])
        if type(event["sequence"]) is not int or event["sequence"] != position:
            raise ValueError("Decision sequences must be contiguous integers starting at one.")
        _hash(event["previous_hash"], "previous_hash", optional=True)
        if event["previous_hash"] != previous:
            raise ValueError("Decision previous_hash does not match its predecessor.")
        _object(event["source"], {"id", "revision"}, "decision source")
        for field in ("id", "revision"):
            _text(event["source"][field], f"source.{field}")
        _hash(event["report_hash"], "report_hash")
        _object(event["tag"], {"namespace", "value"}, "decision tag")
        _tag(event["tag"]["namespace"], event["tag"]["value"])
        _hash(event["event_hash"], "event_hash")
        if event["event_hash"] != _finite_hash(_payload(event), "decision"):
            raise ValueError("Decision event_hash does not match its payload.")
        previous = event["event_hash"]
    if journal["head_hash"] != previous:
        raise ValueError("Journal head_hash does not match its final event.")


def append_tag_decision(
    journal: dict[str, Any], report: dict[str, Any], *, namespace: str,
    value: str, action: str, actor_id: str, reason: str, event_id: str,
    expected_head: str | None,
) -> dict[str, Any]:
    """Return a new journal with one explicit review declaration.

    New events require the expected current head. An exact retry of an existing
    event also requires its original previous_hash and returns a deep copy of
    the *current* journal, preserving any later decisions. Event IDs cannot be
    reused with a different payload. This is not a lock on external storage.
    """
    validate_tag_journal(journal)
    _tag(namespace, value)
    _declaration(action, actor_id, reason, event_id)
    _hash(expected_head, "expected_head", optional=True)
    report_hash = validated_review_report_hash(report)
    if not any(tag["namespace"] == namespace and tag["value"] == value for tag in report["tag_proposals"]):
        raise ValueError("A decision must reference an existing proposed tag in this report.")
    requested = {
        "schema": DECISION_SCHEMA,
        "event_id": event_id,
        "source": {"id": report["source"]["id"], "revision": report["source"]["revision"]},
        "report_hash": report_hash,
        "tag": {"namespace": namespace, "value": value},
        "action": action,
        "actor_id": actor_id,
        "reason": reason,
    }
    for event in journal["events"]:
        if event["event_id"] == event_id:
            original = {key: event[key] for key in requested}
            if original != requested or event["previous_hash"] != expected_head:
                raise ValueError("event_id was already used for a different declaration or expected head.")
            return deepcopy(journal)
    if expected_head != journal["head_hash"]:
        raise ValueError("expected_head is stale; re-read the journal before a new decision.")
    if len(journal["events"]) == MAX_EVENTS:
        raise ValueError(f"The journal is limited to {MAX_EVENTS} events.")
    event = {
        **requested,
        "sequence": len(journal["events"]) + 1,
        "previous_hash": journal["head_hash"],
    }
    event["event_hash"] = _finite_hash(event, "decision")
    result = deepcopy(journal)
    result["events"].append(event)
    result["head_hash"] = event["event_hash"]
    return result
