"""Opt-in discussion continuity and portable event exchange.

The caller supplies all records and evidence. No chat interception, network,
source verification, model, daemon or action execution is performed. SQLite
transactions protect one store; distinct stores exchange immutable events.
Hashes detect inconsistency, not authenticity. Only explicitly shared events
can leave the store. Keep the database and exchange files in private directories.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Iterator
from uuid import uuid4

from .knowledge_crosswalk import (
    create_knowledge_index, find_knowledge_candidates, update_knowledge_index,
)

EVENT_SCHEMA = "parcimonia.inception-event/v1"
BATCH_SCHEMA = "parcimonia.inception-batch/v1"
RECEIPT_SCHEMA = "parcimonia.inception-receipt/v1"
STORE_SCHEMA = "parcimonia.inception-store/v1"
MAX_EVENT_BYTES = 32 * 1024
MAX_BATCH_BYTES = 2 * 1024 * 1024
MAX_BATCH_EVENTS = 128
MAX_STORE_EVENTS = 4096
_KINDS = {"checkpoint", "decision", "outcome", "lesson", "link"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}\Z")
_EVENT_FIELDS = {"schema", "id", "project", "node", "kind", "record_key", "parents",
                 "scope", "created_at", "sources", "payload", "event_hash"}
_BATCH_FIELDS = {"schema", "sender", "receiver", "project", "from_cursor",
                 "to_cursor", "events", "batch_hash"}
_RECEIPT_FIELDS = {"schema", "sender", "receiver", "project", "from_cursor",
                   "to_cursor", "batch_hash", "status", "conflicts", "receipt_hash"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _seal(value: dict[str, Any], field: str) -> dict[str, Any]:
    return {**value, field: _hash(value)}


def _shape(value: Any, fields: set[str], name: str) -> None:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{name} must contain exactly {sorted(fields)}.")


def _text(value: Any, name: str, limit: int = 2048) -> None:
    if (type(value) is not str or not value.strip() or value != value.strip()
            or len(value.encode("utf-8")) > limit
            or any(ord(c) < 32 and c not in "\n\t" for c in value)):
        raise ValueError(f"Invalid or oversized {name}.")


def _identifier(value: Any, name: str) -> None:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name} identifier.")


def _choice(value: Any, choices: set[str], name: str) -> None:
    if type(value) is not str or value not in choices:
        raise ValueError(f"Unsupported {name}.")


def _ids(value: Any, name: str, maximum: int = 32) -> None:
    if type(value) is not list or len(value) > maximum:
        raise ValueError(f"{name} must be a bounded list.")
    for item in value:
        _identifier(item, name)
    if len(set(value)) != len(value):
        raise ValueError(f"{name} must not contain duplicates.")


def _texts(value: Any, name: str) -> None:
    if type(value) is not list or len(value) > 16:
        raise ValueError(f"{name} must contain at most 16 texts.")
    for item in value:
        _text(item, name)


def _digest(value: Any) -> None:
    if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected lowercase SHA-256 digest.")


def _check_seal(value: dict[str, Any], field: str, maximum: int) -> None:
    _digest(value[field])
    if len(_canonical(value).encode("utf-8")) > maximum:
        raise ValueError("Object exceeds the serialized byte budget.")
    if value[field] != _hash({k: v for k, v in value.items() if k != field}):
        raise ValueError(f"Mismatched {field}.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_event(event: Any) -> None:
    """Validate the closed extension schema; evidence remains caller-declared."""
    _shape(event, _EVENT_FIELDS, "event")
    if event["schema"] != EVENT_SCHEMA:
        raise ValueError("Unsupported event schema.")
    for field in ("id", "node", "record_key"):
        _identifier(event[field], field)
    _text(event["project"], "project", 256)
    _text(event["created_at"], "created_at", 128)
    _choice(event["kind"], _KINDS, "kind")
    _choice(event["scope"], {"local", "shared"}, "scope")
    _ids(event["parents"], "parents")
    if event["parents"] != sorted(event["parents"]) or event["id"] in event["parents"]:
        raise ValueError("Parents must be sorted and cannot include the event itself.")
    sources = event["sources"]
    if type(sources) is not list or len(sources) > 16:
        raise ValueError("At most 16 source references are accepted.")
    for source in sources:
        _shape(source, {"id", "version", "uri", "sha256", "availability"}, "source")
        for field in ("id", "version", "uri"):
            _text(source[field], "source." + field, 2048 if field == "uri" else 256)
        if source["sha256"] is not None:
            _digest(source["sha256"])
        _choice(source["availability"], {"available", "unavailable", "unknown"}, "availability")
    if len({s["id"] for s in sources}) != len(sources):
        raise ValueError("Source IDs must be unique within an event.")
    payload = event["payload"]
    kind = event["kind"]
    if kind == "checkpoint":
        _shape(payload, {"goal", "state", "next_action", "acceptance", "decision_ids",
                         "outcome_ids", "open_actions"}, "checkpoint")
        for field in ("goal", "state", "next_action", "acceptance"):
            _text(payload[field], field)
        for field in ("decision_ids", "outcome_ids"):
            _ids(payload[field], field)
        _texts(payload["open_actions"], "open_actions")
    elif kind == "outcome":
        _shape(payload, {"summary", "result", "verification", "why", "cause_status"}, "outcome")
        for field in ("summary", "why"):
            _text(payload[field], field)
        _choice(payload["result"], {"success", "failure", "partial", "unknown"}, "result")
        _choice(payload["verification"], {"declared", "verified"}, "verification")
        _choice(payload["cause_status"], {"unknown", "hypothesis", "verified"}, "cause_status")
        if "verified" in (payload["verification"], payload["cause_status"]):
            if not any(s["sha256"] and s["availability"] == "available" for s in sources):
                raise ValueError("A declared verification requires a pinned available evidence reference.")
    elif kind == "decision":
        _shape(payload, {"summary", "rationale", "alternatives"}, "decision")
        _text(payload["summary"], "summary")
        _text(payload["rationale"], "rationale")
        _texts(payload["alternatives"], "alternatives")
    elif kind == "lesson":
        _shape(payload, {"summary", "limits"}, "lesson")
        _text(payload["summary"], "summary")
        _text(payload["limits"], "limits")
    else:
        _shape(payload, {"from_id", "to_id", "relation", "mode", "status", "reason"}, "link")
        for field in ("from_id", "to_id"):
            _identifier(payload[field], field)
        _choice(payload["relation"], {"related_to", "depends_on", "supports", "contradicts", "derived_from"}, "relation")
        _choice(payload["mode"], {"explicit", "semi"}, "link mode")
        _choice(payload["status"], {"proposed", "confirmed", "rejected"}, "link status")
        _text(payload["reason"], "reason")
    _check_seal(event, "event_hash", MAX_EVENT_BYTES)


def _validate_batch(batch: Any) -> None:
    _shape(batch, _BATCH_FIELDS, "batch")
    if batch["schema"] != BATCH_SCHEMA:
        raise ValueError("Unsupported batch schema.")
    for field in ("sender", "receiver"):
        _identifier(batch[field], field)
    if batch["sender"] == batch["receiver"]:
        raise ValueError("A batch requires distinct store identities.")
    _text(batch["project"], "project", 256)
    for field in ("from_cursor", "to_cursor"):
        if type(batch[field]) is not int or not 0 <= batch[field] <= MAX_STORE_EVENTS:
            raise ValueError("Invalid stream cursor.")
    events = batch["events"]
    if type(events) is not list or len(events) > MAX_BATCH_EVENTS:
        raise ValueError("Batch event limit exceeded.")
    if batch["to_cursor"] != batch["from_cursor"] + len(events):
        raise ValueError("Batch cursor does not describe its events.")
    for event in events:
        validate_event(event)
        if event["scope"] != "shared" or event["project"] != batch["project"]:
            raise ValueError("Batch contains an event outside its sharing scope.")
    if len({e["id"] for e in events}) != len(events):
        raise ValueError("Duplicate event identity inside batch.")
    _check_seal(batch, "batch_hash", MAX_BATCH_BYTES)


def _validate_receipt(receipt: Any) -> None:
    _shape(receipt, _RECEIPT_FIELDS, "receipt")
    if receipt["schema"] != RECEIPT_SCHEMA:
        raise ValueError("Unsupported receipt schema.")
    for field in ("sender", "receiver"):
        _identifier(receipt[field], field)
    _text(receipt["project"], "project", 256)
    _digest(receipt["batch_hash"])
    _choice(receipt["status"], {"accepted", "conflict"}, "receipt status")
    _ids(receipt["conflicts"], "receipt conflicts", MAX_BATCH_EVENTS)
    for field in ("from_cursor", "to_cursor"):
        if type(receipt[field]) is not int or not 0 <= receipt[field] <= MAX_STORE_EVENTS:
            raise ValueError("Invalid receipt cursor.")
    _check_seal(receipt, "receipt_hash", MAX_BATCH_BYTES)


def _heads(events: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    removed = {parent for event in events for parent in event["parents"]}
    result: dict[tuple[str, str], list[str]] = {}
    for event in events:
        if event["id"] not in removed:
            result.setdefault((event["kind"], event["record_key"]), []).append(event["id"])
    return {key: sorted(value) for key, value in result.items()}


def _references(event: dict[str, Any]) -> list[str]:
    if event["kind"] == "checkpoint":
        return event["payload"]["decision_ids"] + event["payload"]["outcome_ids"]
    if event["kind"] == "link":
        return [event["payload"]["from_id"], event["payload"]["to_id"]]
    return []


def _knowledge_text(event: dict[str, Any]) -> str:
    """Select whole user text fields; JSON keys must not manufacture overlap."""
    payload = event["payload"]
    fields = {"checkpoint": ("goal", "state", "next_action", "acceptance", "open_actions"),
              "decision": ("summary", "rationale", "alternatives"),
              "outcome": ("summary", "why"), "lesson": ("summary", "limits")}[event["kind"]]
    texts = []
    for field in fields:
        value = payload[field]
        texts.extend(value if type(value) is list else [value])
    return "\n".join(texts)


def _check_context(event: dict[str, Any], known: dict[str, dict[str, Any]]) -> None:
    for parent_id in event["parents"]:
        parent = known.get(parent_id)
        if parent is None:
            raise ValueError("Missing causal parent; retain the batch and obtain the earlier events.")
        if any(event[f] != parent[f] for f in ("project", "kind", "record_key")):
            raise ValueError("Causal parents must belong to the same project and record.")
        if parent["scope"] != event["scope"]:
            raise ValueError("Changing a record's sharing scope requires a separate explicit projection.")
    for reference in _references(event):
        target = known.get(reference)
        if target is not None:
            if target["project"] != event["project"]:
                raise ValueError("Cross-project references require a separately admitted projection.")
            if event["scope"] == "shared" and target["scope"] != "shared":
                raise ValueError("A shared event cannot reveal a local event reference.")
    if event["kind"] == "checkpoint":
        for field, kind in (("decision_ids", "decision"), ("outcome_ids", "outcome")):
            if any(ref in known and known[ref]["kind"] != kind for ref in event["payload"][field]):
                raise ValueError("Checkpoint reference has the wrong event kind.")


def _check_reverse_references(event: dict[str, Any], known: dict[str, dict[str, Any]]) -> None:
    # Missing evidence references are allowed, but later admission cannot turn
    # one into a private, cross-project or wrong-kind reference retroactively.
    enlarged = {**known, event["id"]: event}
    for prior in known.values():
        if event["id"] in _references(prior):
            _check_context(prior, enlarged)


class InceptionStore:
    """A private SQLite journal, explicitly created; connections close per call."""

    def __init__(self, path: str | Path):
        self.path = Path(path).absolute()
        self._regular_file()
        with self._connection() as connection:
            metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            if metadata.get("schema") != STORE_SCHEMA:
                raise ValueError("Unsupported Inception store schema.")
            self.node_id = metadata.get("node_id")
            _identifier(self.node_id, "store node")

    @classmethod
    def create(cls, path: str | Path, node_id: str) -> "InceptionStore":
        _identifier(node_id, "store node")
        target = Path(path).absolute()
        try:
            target.lstat()
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError("Store path already exists, including a dangling link.")
        descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        connection = sqlite3.connect(target, isolation_level=None)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT UNIQUE NOT NULL, project TEXT NOT NULL,
                    scope TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX project_events ON events(project, seq);
                CREATE TABLE cursors (direction TEXT, peer TEXT, project TEXT,
                    cursor INTEGER NOT NULL, confirmed_at TEXT NOT NULL,
                    PRIMARY KEY(direction, peer, project));
                CREATE TABLE outgoing (peer TEXT, project TEXT, batch_hash TEXT UNIQUE,
                    data TEXT NOT NULL, PRIMARY KEY(peer, project));
                CREATE TABLE receipts (batch_hash TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE acknowledgements (batch_hash TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE collisions (collision_hash TEXT PRIMARY KEY, project TEXT,
                    event_id TEXT, sender TEXT, data TEXT NOT NULL);
            """)
            connection.executemany("INSERT INTO metadata VALUES (?, ?)",
                                   [("schema", STORE_SCHEMA), ("node_id", node_id)])
            connection.commit()
        finally:
            connection.close()
        return cls(target)

    def _regular_file(self) -> None:
        info = self.path.lstat()
        if (not stat.S_ISREG(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
            raise ValueError("Store must be a regular non-link file in a trusted private directory.")

    @contextmanager
    def _connection(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._regular_file()
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                     isolation_level=None, timeout=5)
        try:
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _events(connection: sqlite3.Connection, project: str | None = None) -> list[dict[str, Any]]:
        if project is None:
            rows = connection.execute("SELECT data FROM events ORDER BY seq LIMIT ?", (MAX_STORE_EVENTS + 1,))
        else:
            _text(project, "project", 256)
            rows = connection.execute("SELECT data FROM events WHERE project=? ORDER BY seq LIMIT ?",
                                      (project, MAX_STORE_EVENTS + 1))
        events = [json.loads(row[0]) for row in rows]
        if len(events) > MAX_STORE_EVENTS:
            raise ValueError("Store exceeds the pilot event budget.")
        for event in events:
            validate_event(event)
        return events

    @staticmethod
    def _insert(connection: sqlite3.Connection, event: dict[str, Any]) -> None:
        connection.execute("INSERT INTO events(event_id, project, scope, data) VALUES (?, ?, ?, ?)",
                           (event["id"], event["project"], event["scope"], _canonical(event)))

    def append(self, project: str, kind: str, record_key: str, payload: dict[str, Any], *,
               expected_heads: list[str], sources: list[dict[str, Any]] | None = None,
               event_id: str | None = None, scope: str = "local") -> dict[str, Any]:
        _ids(expected_heads, "expected_heads")
        event = _seal({"schema": EVENT_SCHEMA, "id": event_id if event_id is not None else str(uuid4()),
                       "project": project, "node": self.node_id, "kind": kind, "record_key": record_key,
                       "parents": sorted(expected_heads), "scope": scope, "created_at": _now(),
                       "sources": sources if sources is not None else [], "payload": payload}, "event_hash")
        validate_event(event)
        with self._connection(write=True) as connection:
            events = self._events(connection)
            known = {e["id"]: e for e in events}
            previous = known.get(event["id"])
            if previous is not None:
                same = all(previous[f] == event[f] for f in _EVENT_FIELDS - {"event_hash", "created_at"})
                if not same:
                    raise ValueError("Event ID already has different content; it cannot be overwritten.")
                return previous
            if len(events) >= MAX_STORE_EVENTS:
                raise ValueError("Store event budget exceeded; archive explicitly before extending the pilot.")
            current = _heads([e for e in events if e["project"] == project]).get((kind, record_key), [])
            if current != sorted(expected_heads):
                raise ValueError("Stale or incomplete expected_heads; read and reconcile every current head.")
            _check_context(event, known)
            _check_reverse_references(event, known)
            self._insert(connection, event)
        # Detach caller-owned nested payloads from the returned immutable value.
        return json.loads(_canonical(event))

    def projects(self) -> list[str]:
        with self._connection() as connection:
            return [row[0] for row in connection.execute("SELECT DISTINCT project FROM events ORDER BY project")]

    def heads(self, project: str, kind: str, record_key: str) -> list[str]:
        _choice(kind, _KINDS, "kind")
        _identifier(record_key, "record_key")
        with self._connection() as connection:
            return _heads(self._events(connection, project)).get((kind, record_key), [])

    @staticmethod
    def _record_conflicts(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"kind": kind, "record_key": record, "heads": heads}
                for (kind, record), heads in sorted(_heads(events).items()) if len(heads) > 1]

    def status(self, project: str, peer_id: str | None = None) -> dict[str, Any]:
        if peer_id is not None:
            _identifier(peer_id, "peer")
        with self._connection() as connection:
            events = self._events(connection, project)
            return self._status_snapshot(connection, project, peer_id, events)

    def _status_snapshot(self, connection: sqlite3.Connection, project: str,
                         peer_id: str | None, events: list[dict[str, Any]]) -> dict[str, Any]:
        shared = sum(e["scope"] == "shared" for e in events)
        streams = [{"direction": row[0], "peer": row[1], "cursor": row[2], "confirmed_at": row[3]}
                   for row in connection.execute(
                       "SELECT direction,peer,cursor,confirmed_at FROM cursors WHERE project=? ORDER BY direction,peer", (project,))
                   if peer_id is None or row[1] == peer_id]
        pending = [{"peer": row[0], "batch_hash": row[1]}
                   for row in connection.execute("SELECT peer,batch_hash FROM outgoing WHERE project=? ORDER BY peer", (project,))
                   if peer_id is None or row[0] == peer_id]
        collisions = connection.execute("SELECT COUNT(*) FROM collisions WHERE project=?", (project,)).fetchone()[0]
        identity_conflicts = [{"event_id": row[0], "sender": row[1], "collision_hash": row[2]}
                              for row in connection.execute(
                                  "SELECT event_id,sender,collision_hash FROM collisions WHERE project=? ORDER BY collision_hash LIMIT 128", (project,))]
        sent = next((s["cursor"] for s in streams if s["direction"] == "sent" and s["peer"] == peer_id), 0)
        return {"schema": "parcimonia.inception-status/v1", "node": self.node_id, "project": project,
                "event_count": len(events), "shared_event_count": shared, "local_event_count": len(events) - shared,
                "peer": peer_id, "pending_event_count": shared - sent if peer_id else None,
                "streams": streams, "pending_batches": pending,
                "record_conflicts": self._record_conflicts(events), "collision_count": collisions,
                "identity_conflicts": identity_conflicts, "identity_conflicts_omitted": max(0, collisions - len(identity_conflicts)),
                "transport": "explicit_exchange", "connectivity": "not_observed"}

    def resume(self, project: str, record_key: str = "main") -> dict[str, Any]:
        _identifier(record_key, "record_key")
        with self._connection() as connection:
            events = self._events(connection, project)
            sync = self._status_snapshot(connection, project, None, events)
            collision_count = sync["collision_count"]
        known = {e["id"]: e for e in events}
        heads = _heads(events)
        candidates = [known[i] for i in heads.get(("checkpoint", record_key), [])]
        checkpoint = candidates[0] if len(candidates) == 1 else None
        decisions: list[dict[str, Any]] = []
        outcomes: list[dict[str, Any]] = []
        missing: list[str] = []
        stale: list[str] = []
        if checkpoint:
            for field, target, kind in (("decision_ids", decisions, "decision"), ("outcome_ids", outcomes, "outcome")):
                for identifier in checkpoint["payload"][field]:
                    event = known.get(identifier)
                    if event is None or event["kind"] != kind:
                        missing.append(identifier)
                    else:
                        target.append(event)
                        if identifier not in heads.get((kind, event["record_key"]), []):
                            stale.append(identifier)
        sources = [{"event_id": e["id"], **s} for e in candidates + decisions + outcomes for s in e["sources"]]
        conflicts = self._record_conflicts(events)
        needs_review = bool(conflicts or collision_count or missing or stale
                            or any(s["availability"] != "available" for s in sources))
        status = "needs_review" if needs_review else "ready" if checkpoint else "empty"
        return {"schema": "parcimonia.inception-resume/v1", "project": project,
                "status": status, "checkpoint": checkpoint, "checkpoint_candidates": candidates,
                "decisions": decisions, "outcomes": outcomes, "missing_references": missing,
                "superseded_references": stale, "record_conflicts": conflicts, "collision_count": collision_count,
                "sources": sources, "revalidation_required": True,
                "execution_performed": False, "sync": sync}

    def export_batch(self, project: str, peer_id: str, limit: int = 128) -> dict[str, Any]:
        _text(project, "project", 256)
        _identifier(peer_id, "peer")
        if peer_id == self.node_id:
            raise ValueError("Sender and receiver store identities must differ.")
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH_EVENTS:
            raise ValueError("Batch limit must be between 1 and 128.")
        with self._connection(write=True) as connection:
            pending = connection.execute("SELECT data FROM outgoing WHERE peer=? AND project=?", (peer_id, project)).fetchone()
            if pending:
                batch = json.loads(pending[0])
                _validate_batch(batch)
                return batch
            row = connection.execute("SELECT cursor FROM cursors WHERE direction='sent' AND peer=? AND project=?", (peer_id, project)).fetchone()
            cursor = row[0] if row else 0
            shared = [e for e in self._events(connection, project) if e["scope"] == "shared"]
            if cursor > len(shared):
                raise ValueError("Stream cursor is ahead of retained events; do not reset or reuse store identities.")
            selected = shared[cursor:cursor + limit]
            while True:
                batch = _seal({"schema": BATCH_SCHEMA, "sender": self.node_id, "receiver": peer_id,
                               "project": project, "from_cursor": cursor, "to_cursor": cursor + len(selected),
                               "events": selected}, "batch_hash")
                if len(_canonical(batch).encode("utf-8")) <= MAX_BATCH_BYTES:
                    break
                selected.pop()
            _validate_batch(batch)
            connection.execute("INSERT INTO outgoing VALUES (?, ?, ?, ?)", (peer_id, project, batch["batch_hash"], _canonical(batch)))
            return batch

    @staticmethod
    def _receipt(batch: dict[str, Any], status: str, conflicts: list[str]) -> dict[str, Any]:
        return _seal({"schema": RECEIPT_SCHEMA,
                      **{f: batch[f] for f in ("sender", "receiver", "project", "from_cursor", "to_cursor", "batch_hash")},
                      "status": status, "conflicts": conflicts}, "receipt_hash")

    def receive(self, batch: dict[str, Any]) -> dict[str, Any]:
        _validate_batch(batch)
        if batch["receiver"] != self.node_id:
            raise ValueError("Batch is addressed to a different store.")
        with self._connection(write=True) as connection:
            prior = connection.execute("SELECT data FROM receipts WHERE batch_hash=?", (batch["batch_hash"],)).fetchone()
            if prior:
                return json.loads(prior[0])
            row = connection.execute("SELECT cursor FROM cursors WHERE direction='received' AND peer=? AND project=?",
                                     (batch["sender"], batch["project"])).fetchone()
            cursor = row[0] if row else 0
            if batch["from_cursor"] != cursor:
                raise ValueError("Non-contiguous stream; replay the outstanding earlier batch first.")
            events = self._events(connection)
            known = {e["id"]: e for e in events}
            collisions = [e for e in batch["events"] if e["id"] in known and e != known[e["id"]]]
            if collisions:
                for event in collisions:
                    connection.execute("INSERT OR IGNORE INTO collisions VALUES (?, ?, ?, ?, ?)",
                                       (_hash([batch["sender"], event]), batch["project"], event["id"], batch["sender"], _canonical(event)))
                return self._receipt(batch, "conflict", sorted(e["id"] for e in collisions))
            additions = []
            for event in batch["events"]:
                if event["id"] not in known:
                    _check_context(event, known)
                    _check_reverse_references(event, known)
                    known[event["id"]] = event
                    additions.append(event)
            if len(known) > MAX_STORE_EVENTS:
                raise ValueError("Store event budget exceeded; receipt was not committed.")
            for event in additions:
                self._insert(connection, event)
            receipt = self._receipt(batch, "accepted", [])
            connection.execute("INSERT INTO receipts VALUES (?, ?)", (batch["batch_hash"], _canonical(receipt)))
            connection.execute("INSERT OR REPLACE INTO cursors VALUES ('received', ?, ?, ?, ?)",
                               (batch["sender"], batch["project"], batch["to_cursor"], _now()))
            return receipt

    def acknowledge(self, receipt: dict[str, Any]) -> dict[str, Any]:
        _validate_receipt(receipt)
        if receipt["status"] != "accepted" or receipt["conflicts"] != []:
            raise ValueError("Only an accepted durable receipt can advance the stream.")
        if receipt["sender"] != self.node_id:
            raise ValueError("Receipt belongs to a different sender.")
        with self._connection(write=True) as connection:
            prior = connection.execute("SELECT data FROM acknowledgements WHERE batch_hash=?", (receipt["batch_hash"],)).fetchone()
            if prior:
                if json.loads(prior[0]) != receipt:
                    raise ValueError("Receipt changed under its batch identity.")
                # An empty batch at an unchanged cursor has the same identity.
                # Re-acknowledging it must release a newly prepared empty outbox
                # without moving a cursor backwards after subsequent batches.
                connection.execute("DELETE FROM outgoing WHERE batch_hash=?", (receipt["batch_hash"],))
            else:
                row = connection.execute("SELECT data FROM outgoing WHERE batch_hash=?", (receipt["batch_hash"],)).fetchone()
                if row is None:
                    raise ValueError("No outstanding batch matches this receipt.")
                batch = json.loads(row[0])
                if receipt != self._receipt(batch, "accepted", []):
                    raise ValueError("Receipt does not match the outstanding batch, peer and scope.")
                connection.execute("INSERT OR REPLACE INTO cursors VALUES ('sent', ?, ?, ?, ?)",
                                   (batch["receiver"], batch["project"], batch["to_cursor"], _now()))
                connection.execute("INSERT INTO acknowledgements VALUES (?, ?)", (receipt["batch_hash"], _canonical(receipt)))
                connection.execute("DELETE FROM outgoing WHERE batch_hash=?", (receipt["batch_hash"],))
        return {"schema": "parcimonia.inception-ack/v1", "status": "acknowledged",
                "batch_hash": receipt["batch_hash"], "peer": receipt["receiver"], "to_cursor": receipt["to_cursor"]}

    def links(self, project: str, event_id: str, limit: int = 5) -> dict[str, Any]:
        _identifier(event_id, "event")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Link limit must be between 1 and 20.")
        with self._connection() as connection:
            all_events = self._events(connection, project)
        known = {e["id"]: e for e in all_events}
        if event_id not in known:
            raise ValueError("Unknown focus event in this project.")
        active = {i for ids in _heads(all_events).values() for i in ids}
        events = [e for e in all_events if e["id"] in active or e["id"] == event_id]
        focus = known[event_id]
        exact = []
        for event in events:
            if event["id"] == event_id:
                continue
            for left in focus["sources"]:
                for right in event["sources"]:
                    if (left["sha256"] is not None and left["availability"] == right["availability"] == "available"
                            and all(left[f] == right[f] for f in ("id", "version", "sha256"))):
                        exact.append({"from_id": event_id, "to_id": event["id"], "relation": "same_source_revision",
                                      "status": "exact_declared_identity", "source": left})
        fragments = [{"id": e["id"], "version": e["event_hash"], "feed_id": e["id"], "channel": "memory",
                      "project": project, "uri": "inception:event:" + e["id"], "locator": "selected_payload_text",
                      "timestamp": e["created_at"], "state": "active", "text": _knowledge_text(e)}
                     for e in events if e["kind"] != "link"]
        try:
            index = create_knowledge_index("inception-selected-project")
            updated = update_knowledge_index(index, upserts=fragments, removals=[],
                                             coverage=[{"id": f["id"], "status": "partial"} for f in fragments],
                                             expected_head=index["index_hash"])
            proposed = find_knowledge_candidates(updated["index"], fragment_id=event_id, limit=limit)
        except ValueError as exc:
            proposed = {"status": "unavailable", "reason": str(exc), "matches": []}
        explicit = [e for e in events if e["kind"] == "link" and event_id in _references(e)]
        return {"schema": "parcimonia.inception-links/v1", "project": project, "event_id": event_id,
                "automatic": exact[:limit], "automatic_omitted": max(0, len(exact) - limit),
                "proposed": proposed, "explicit": explicit, "proof_of_causality": False,
                "dependency_execution": "not_implemented"}
