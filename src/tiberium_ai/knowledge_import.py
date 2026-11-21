"""Pure preparation of explicit, source-bound knowledge import batches.

Connector responses are bounded summaries/projections, never whole discussions
or authenticated source truth. URLs are opaque identifiers and are not opened.
No input text is executed. Prepared batches still require an explicit caller
write; this module performs no I/O, synchronization, model call or activation.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any

from .knowledge_crosswalk import (
    MAX_FRAGMENTS, MAX_INDEX_BYTES, UPDATE_SCHEMA, update_knowledge_index,
    validate_knowledge_index,
)
from .verification import hash_input

__all__ = ["IMPORT_SCHEMA", "prepare_knowledge_import", "prepare_unavailable_import"]

IMPORT_SCHEMA = "parcimonia.knowledge-import/v1"
_SOURCE_KINDS = frozenset({"second_brain", "knowledge_inbox", "documents"})
_CHANNELS = frozenset({"cloud", "local", "memory", "wiki"})
_STATES = frozenset({"active", "superseded", "rejected", "paused"})
_REASONS = frozenset({"unavailable", "read_failed", "not_connected", "invalid_response"})
_SEARCH_FIELDS = {"detail", "id", "kind", "project", "status", "tags", "title", "url"}
_INBOX_FIELDS = {
    "confidence", "createdAt", "id", "project", "sourceKind", "sourceUrl",
    "status", "summary", "title",
}
_DOCUMENT_FIELDS = {"id", "version", "project", "uri", "timestamp", "state", "text"}
_CHUNK_CHARACTERS = 512


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _text(value: Any, label: str, *, maximum: int = 4096, content: bool = False,
          identity: bool = False) -> None:
    if type(value) is not str:
        raise ValueError(f"{label} must be text.")
    if identity and (not value or value != value.strip()):
        raise ValueError(f"{label} must be nonempty trimmed text.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError(f"{label} must be UTF-8.") from exc
    allowed = "\r\n\t" if content else ""
    if size > maximum or any((ord(char) < 32 and char not in allowed)
                              or 127 <= ord(char) <= 159 for char in value):
        raise ValueError(f"{label} exceeds its byte budget or contains unsupported controls.")


def _json_budget(value: Any, *, maximum: int, label: str, depth_limit: int = 16,
                 node_limit: int = 10000) -> None:
    """Reject foreign Python types/cycles before bounded JSON serialization."""
    pending = [(value, 0, False)]
    active: set[int] = set()
    reserved = 1
    while pending:
        current, depth, leaving = pending.pop()
        if leaving:
            active.remove(id(current))
            continue
        if depth > depth_limit:
            raise ValueError(f"{label} exceeds its nesting budget.")
        kind = type(current)
        if kind is dict or kind is list:
            if id(current) in active:
                raise ValueError(f"{label} must not contain cycles.")
            if reserved + len(current) > node_limit:
                raise ValueError(f"{label} exceeds its node budget.")
            reserved += len(current)
            active.add(id(current))
            pending.append((current, depth, True))
            if kind is dict:
                for key, item in current.items():
                    _text(key, label + " key", maximum=256)
                    pending.append((item, depth + 1, False))
            else:
                pending.extend((item, depth + 1, False) for item in current)
        elif kind is str:
            _text(current, label + " text", maximum=65536, content=True)
        elif kind is float:
            if not math.isfinite(current):
                raise ValueError(f"{label} must contain finite numbers.")
        elif kind is int:
            if current.bit_length() > 12000:
                raise ValueError(f"{label} contains an oversized integer.")
        elif kind is not bool and kind is not type(None):
            raise ValueError(f"{label} must use exact JSON types.")
    size = 0
    try:
        encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
        for chunk in encoder.iterencode(value):
            size += len(chunk.encode("utf-8"))
            if size > maximum:
                raise ValueError(f"{label} exceeds {maximum} canonical UTF-8 bytes.")
    except (TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        raise ValueError(f"{label} must be bounded UTF-8 JSON.") from exc


def _number_id(value: Any, label: str) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer, not a boolean.")


def _optional_url(value: Any, label: str) -> None:
    if value is not None:
        _text(value, label)


def _record_kind(record: dict[str, Any], source_kind: str) -> str:
    if source_kind == "second_brain":
        return record["kind"]
    if source_kind == "knowledge_inbox":
        return record["sourceKind"]
    return "document"


def _identity_kind(record: dict[str, Any], source_kind: str) -> str:
    # Inbox IDs identify native inbox rows. sourceKind describes their origin
    # and can be corrected without creating a second identity. Search results
    # instead combine several collections whose numerical IDs may overlap.
    return "inbox" if source_kind == "knowledge_inbox" else _record_kind(record, source_kind)


def _records(response: Any, source_kind: str) -> list[dict[str, Any]]:
    if source_kind == "second_brain":
        _object(response, {"results"}, "second-brain response")
        values = response["results"]
    elif source_kind == "knowledge_inbox":
        _object(response, {"items", "syncAgeSeconds", "syncStatus"}, "knowledge-inbox response")
        age = response["syncAgeSeconds"]
        if age is not None:
            _number_id(age, "syncAgeSeconds")
        _text(response["syncStatus"], "syncStatus")
        values = response["items"]
    else:
        _object(response, {"documents"}, "document response")
        values = response["documents"]
    if type(values) is not list or len(values) > MAX_FRAGMENTS:
        raise ValueError("A response must contain at most 256 records.")
    seen: set[tuple[str, Any]] = set()
    for record in values:
        fields = (_SEARCH_FIELDS if source_kind == "second_brain" else
                  _INBOX_FIELDS if source_kind == "knowledge_inbox" else _DOCUMENT_FIELDS)
        _object(record, fields, "source record")
        if source_kind == "documents":
            for name in ("id", "version", "project", "uri", "timestamp"):
                _text(record[name], "document." + name, identity=True)
            if type(record["state"]) is not str or record["state"] not in _STATES:
                raise ValueError("Unsupported document state.")
            _text(record["text"], "document.text", maximum=65536, content=True)
        else:
            _number_id(record["id"], "record.id")
            for name in ("kind", "project", "status") if source_kind == "second_brain" else ("project", "sourceKind", "status", "createdAt"):
                _text(record[name], "record." + name, identity=name in {"kind", "project", "sourceKind"})
            for name in (("title", "detail", "tags") if source_kind == "second_brain" else ("title", "summary")):
                _text(record[name], "record." + name, maximum=65536, content=True)
            _optional_url(record["url" if source_kind == "second_brain" else "sourceUrl"], "record URL")
            if source_kind == "knowledge_inbox":
                confidence = record["confidence"]
                if (type(confidence) not in (int, float)
                        or (type(confidence) is float and not math.isfinite(confidence))):
                    raise ValueError("confidence must be a finite number, not a boolean.")
        identity = (_identity_kind(record, source_kind), record["id"])
        if identity in seen:
            raise ValueError("Duplicate stable record identity in one response.")
        seen.add(identity)
    return values


def _metadata(snapshot: Any, *, feed_id: str, observed_at: str, source_kind: str,
              channel: str, parameters: Any) -> dict[str, Any]:
    validate_knowledge_index(snapshot)
    _text(feed_id, "feed_id", maximum=256, identity=True)
    _text(observed_at, "observed_at", maximum=128, identity=True)
    if type(channel) is not str or channel not in _CHANNELS:
        raise ValueError("Unsupported knowledge channel.")
    if source_kind != "documents" and channel != "cloud":
        raise ValueError("Connector projections must retain the cloud channel.")
    parameters = {} if parameters is None else parameters
    if type(parameters) is not dict:
        raise ValueError("parameters must be a JSON object.")
    _json_budget(parameters, maximum=8192, label="parameters", depth_limit=8, node_limit=2048)
    return {
        "expected_head": snapshot["index_hash"], "observed_at": observed_at,
        "source_kind": source_kind, "feed_id": feed_id, "channel": channel,
        "parameters": deepcopy(parameters), "source_summary_only": source_kind != "documents",
        "freshness": "not_established",
    }


def prepare_knowledge_import(
    snapshot: Any, response: Any, *, source_kind: str, feed_id: str,
    observed_at: str, channel: str = "cloud", parameters: Any = None,
) -> dict[str, Any]:
    """Prepare a partial import; only present records replace their own chunks.

    Record identity is stable across response reordering. Record content hashes
    govern versions independently of collection time. Missing records, empty
    responses and omitted feeds never imply a deletion. ``active`` on connector
    projections means search eligibility, not a validated or current decision.
    Chunks are exact Unicode-character windows, not complete semantic context.
    Read the complete source field before interpreting constraints or negations
    that may span a boundary; chunks do not replace the original source.
    """
    if type(source_kind) is not str or source_kind not in _SOURCE_KINDS:
        raise ValueError("Unsupported import source_kind.")
    manifest = _metadata(snapshot, feed_id=feed_id, observed_at=observed_at,
                         source_kind=source_kind, channel=channel, parameters=parameters)
    _json_budget(response, maximum=MAX_INDEX_BYTES, label="response")
    records = _records(response, source_kind)
    response_hash = hash_input(response)
    upserts: list[dict[str, Any]] = []
    removals: set[str] = set()
    declarations: list[dict[str, Any]] = []
    for record in records:
        kind = _record_kind(record, source_kind)
        stable_hash = hash_input({"feed_id": feed_id, "source_kind": source_kind,
                                  "recordkind": _identity_kind(record, source_kind), "id": record["id"]})
        prefix = "import:" + stable_hash + ":"
        record_hash = hash_input(record)
        if source_kind == "documents":
            version = "declared:" + hash_input({"declared_version": record["version"], "record_hash": record_hash})
            uri, timestamp, state = record["uri"], record["timestamp"], record["state"]
            fields = ("text",)
            raw_status = record["state"]
            extra = {"declared_version": record["version"]}
        else:
            version = "projection:" + record_hash
            url_field = "url" if source_kind == "second_brain" else "sourceUrl"
            uri = record[url_field] or "projection:" + source_kind + ":" + stable_hash
            timestamp = "not_provided" if source_kind == "second_brain" else record["createdAt"]
            state, raw_status = "active", record["status"]
            fields = ("title", "detail", "tags") if source_kind == "second_brain" else ("title", "summary")
            extra = {"declared_version": None}
            if source_kind == "knowledge_inbox":
                extra["confidence"] = record["confidence"]
        fragment_ids: list[str] = []
        for field in fields:
            text = record[field]
            for start in range(0, len(text), _CHUNK_CHARACTERS):
                content = text[start:start + _CHUNK_CHARACTERS]
                if not content.strip():
                    continue
                fragment_id = prefix + field + ":" + str(start)
                if source_kind == "documents":
                    locator = "documents:" + stable_hash + ":" + field
                else:
                    locator = "projection:" + source_kind + ":" + stable_hash + ":" + field
                upserts.append({
                    "id": fragment_id, "version": version, "feed_id": feed_id,
                    "channel": channel, "project": record["project"], "uri": uri,
                    "locator": locator + f"[{start}:{start + len(content)}]",
                    "timestamp": timestamp, "state": state, "text": content,
                })
                if len(upserts) > MAX_FRAGMENTS:
                    raise ValueError("Import exceeds 256 fragments; select a smaller response.")
                fragment_ids.append(fragment_id)
        incoming = set(fragment_ids)
        removals.update(
            old["id"] for old in snapshot["fragments"]
            if old["feed_id"] == feed_id and old["id"].startswith(prefix)
            and old["id"] not in incoming
        )
        declarations.append({
            "id": record["id"], "kind": kind, "record_hash": record_hash,
            "source_version": version, "timestamp": timestamp, "raw_status": raw_status,
            "project": record["project"], "uri": uri, "fragment_ids": fragment_ids,
            **extra,
        })
    batch = {
        "schema": UPDATE_SCHEMA, "upserts": sorted(upserts, key=lambda item: item["id"]),
        "removals": sorted(removals), "coverage": [{"id": feed_id, "status": "partial"}],
    }
    # This is a pure feasibility check against the supplied snapshot, not a
    # write, reservation or acknowledgement that the shared head remains current.
    update_knowledge_index(snapshot, upserts=batch["upserts"], removals=batch["removals"],
                           coverage=batch["coverage"], expected_head=manifest["expected_head"])
    manifest.update({
        "response_hash": response_hash,
        "records": sorted(declarations, key=lambda item: (item["kind"], str(item["id"]))),
        "upsert_count": len(upserts), "removal_count": len(removals),
        "chunking": {"unit": "unicode_characters", "max_characters": _CHUNK_CHARACTERS,
                     "context_complete": False},
    })
    if source_kind == "knowledge_inbox":
        manifest.update(syncStatus=response["syncStatus"], syncAgeSeconds=response["syncAgeSeconds"])
    result = {"schema": IMPORT_SCHEMA, "batch": batch, "manifest": manifest}
    _json_budget(result, maximum=MAX_INDEX_BYTES, label="import result", node_limit=20000)
    return deepcopy(result)


def prepare_unavailable_import(
    snapshot: Any, *, feed_id: str, observed_at: str, reason_code: str,
) -> dict[str, Any]:
    """Declare a failed read without clearing, replacing or executing content."""
    validate_knowledge_index(snapshot)
    _text(feed_id, "feed_id", maximum=256, identity=True)
    _text(observed_at, "observed_at", maximum=128, identity=True)
    if type(reason_code) is not str or reason_code not in _REASONS:
        raise ValueError("Unsupported unavailable reason_code.")
    batch = {"schema": UPDATE_SCHEMA, "upserts": [], "removals": [],
             "coverage": [{"id": feed_id, "status": "unavailable"}]}
    update_knowledge_index(snapshot, upserts=[], removals=[], coverage=batch["coverage"],
                           expected_head=snapshot["index_hash"])
    channels = {fragment["channel"] for fragment in snapshot["fragments"]
                if fragment["feed_id"] == feed_id}
    channel = next(iter(channels)) if len(channels) == 1 else None
    return {
        "schema": IMPORT_SCHEMA, "batch": batch,
        "manifest": {
            "expected_head": snapshot["index_hash"], "response_hash": None,
            "observed_at": observed_at, "source_kind": "unavailable", "feed_id": feed_id,
            "channel": channel, "parameters": {}, "source_summary_only": None,
            "freshness": "not_established", "reason_code": reason_code,
            "records": [], "upsert_count": 0, "removal_count": 0,
        },
    }
