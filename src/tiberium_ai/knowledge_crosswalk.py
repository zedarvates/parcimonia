"""Bounded lexical candidates between caller-selected cloud/local knowledge.

No source is fetched, no model runs and no remembered instruction is executed.
Coverage and lifecycle states are declarations. Similar words do not establish
complementarity, compatibility, a current decision or an unevaluated opportunity.
Snapshots retain raw fragments; keep private inputs and resulting files private.
Hashes establish internal consistency, not authenticity or source truth.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import re
import unicodedata
from typing import Any

from .verification import hash_input

__all__ = [
    "INDEX_SCHEMA", "CANDIDATES_SCHEMA", "UPDATE_SCHEMA", "MAX_INDEX_BYTES",
    "MAX_FRAGMENTS", "create_knowledge_index", "validate_knowledge_index",
    "update_knowledge_index", "find_knowledge_candidates",
]

INDEX_SCHEMA = "parcimonia.knowledge-index/v1"
CANDIDATES_SCHEMA = "parcimonia.knowledge-candidates/v1"
UPDATE_SCHEMA = "parcimonia.knowledge-update/v1"
MAX_INDEX_BYTES = 2 * 1024 * 1024
MAX_FRAGMENTS = 256
MAX_TEXT_BYTES = 8192
MAX_TERMS = 256
_MAX_GENERATION = 2**63 - 1
_INDEX_FIELDS = {
    "schema", "index_id", "generation", "parent_hash", "fragments", "coverage",
    "postings", "index_hash",
}
_FRAGMENT_FIELDS = {
    "id", "version", "feed_id", "channel", "project", "uri", "locator",
    "timestamp", "state", "text",
}
_CHANNELS = frozenset({"cloud", "local", "memory", "wiki"})
_STATES = frozenset({"active", "superseded", "rejected", "paused"})
_COVERAGE = frozenset({"complete", "partial", "unavailable"})
_STOPWORDS = frozenset("""
a afin ai ainsi alors apres are as at au aucun aussi aux avec avoir avant be been
but by ca car ce ceci cela ces cet cette ceux chaque chez comme comment dans de
des depuis doit donc dont du elle elles en encore entre est et etre eux faire
fait for from had has have ici il ils in into is it its je la le les leur leurs
mais me meme mes moi mon ne ni nos notre nous of on ont or ou par pas plus pour
pourquoi puis que quel quelle quelles quels qui sa sans se ses si son sont sous
sur ta tes the their them there these they this those to tous tout toute toutes
tu un une vos votre vous was were what when where which who will with yes your
peut peuvent exemple exemples demander demande voir
""".split())
_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


def _object(value: Any, fields: set[str], label: str) -> None:
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != fields:
        raise ValueError(f"{label} must contain exactly {sorted(fields)}.")


def _text(value: Any, label: str, maximum: int = 1024) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{label} must be nonempty trimmed text.")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8.") from exc
    if size > maximum or any(ord(char) < 32 for char in value):
        raise ValueError(f"{label} exceeds its text budget or contains controls.")


def _digest(value: Any, label: str) -> None:
    if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest.")


def _size(value: Any, label: str) -> None:
    # Call only after strict shape and scalar checks; do not stringify foreign
    # objects, cycles or unbounded nested values supplied through the Python API.
    size = 0
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > MAX_INDEX_BYTES:
            raise ValueError(f"{label} exceeds the 2 MiB canonical UTF-8 budget.")


def _terms(text: str) -> frozenset[str]:
    normalized = "".join(
        char for char in unicodedata.normalize("NFKD", text.casefold())
        if not unicodedata.combining(char)
    )
    result = frozenset(
        word for word in _WORDS.findall(normalized)
        if 3 <= len(word) <= 64 and word not in _STOPWORDS
    )
    if len(result) > MAX_TERMS:
        raise ValueError("Fragment exceeds 256 lexical terms; split it explicitly.")
    return result


def _fragment(value: Any) -> None:
    _object(value, _FRAGMENT_FIELDS, "fragment")
    for field in ("id", "version", "feed_id", "project"):
        _text(value[field], "fragment." + field, 256)
    for field in ("uri", "locator", "timestamp"):
        _text(value[field], "fragment." + field, 2048 if field == "uri" else 1024)
    for field, allowed in (("channel", _CHANNELS), ("state", _STATES)):
        if type(value[field]) is not str or value[field] not in allowed:
            raise ValueError(f"Unsupported fragment {field}.")
    content = value["text"]
    if type(content) is not str or not content.strip():
        raise ValueError("Fragment text must be nonempty text.")
    try:
        size = len(content.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError("Fragment text must be UTF-8.") from exc
    if size > MAX_TEXT_BYTES or any(ord(c) < 32 and c not in "\n\r\t" for c in content):
        raise ValueError("Fragment text exceeds 8 KiB or contains unsupported controls.")


def _feed(value: Any) -> None:
    _object(value, {"id", "status"}, "coverage entry")
    _text(value["id"], "coverage.id", 256)
    if type(value["status"]) is not str or value["status"] not in _COVERAGE:
        raise ValueError("Unsupported coverage status.")


def _postings(fragments: list[dict[str, Any]]) -> dict[str, list[str]]:
    postings: dict[str, list[str]] = defaultdict(list)
    for fragment in fragments:
        for term in sorted(_terms(fragment["text"])):
            postings[term].append(fragment["id"])
    return dict(sorted(postings.items()))


def _payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if key != "index_hash"}


def _seal(payload: dict[str, Any]) -> dict[str, Any]:
    result = {**payload, "index_hash": "0" * 64}
    _size(result, "Index")
    result["index_hash"] = hash_input(payload)
    return result


def create_knowledge_index(index_id: str) -> dict[str, Any]:
    """Create an empty value; no directory, index service or source is opened."""
    _text(index_id, "index_id", 256)
    return _seal({
        "schema": INDEX_SCHEMA, "index_id": index_id, "generation": 0,
        "parent_hash": None, "fragments": [], "coverage": [], "postings": {},
    })


def validate_knowledge_index(snapshot: Any) -> None:
    """Check shape, exact derived postings and hashes; no external trust check."""
    _object(snapshot, _INDEX_FIELDS, "knowledge index")
    if type(snapshot["schema"]) is not str or snapshot["schema"] != INDEX_SCHEMA:
        raise ValueError("Unsupported knowledge index schema.")
    _text(snapshot["index_id"], "index_id", 256)
    generation = snapshot["generation"]
    if type(generation) is not int or not 0 <= generation <= _MAX_GENERATION:
        raise ValueError("generation must be a bounded nonnegative integer.")
    if generation == 0:
        if snapshot["parent_hash"] is not None or snapshot["fragments"] or snapshot["coverage"]:
            raise ValueError("Generation zero must be empty and have no parent.")
    else:
        _digest(snapshot["parent_hash"], "parent_hash")
    _digest(snapshot["index_hash"], "index_hash")
    for field in ("fragments", "coverage"):
        items = snapshot[field]
        if type(items) is not list or len(items) > MAX_FRAGMENTS:
            raise ValueError(f"{field} must be a list of at most 256 entries.")
        prior = None
        for item in items:
            (_fragment if field == "fragments" else _feed)(item)
            if prior is not None and item["id"] <= prior:
                raise ValueError(f"{field} must be sorted by unique id.")
            prior = item["id"]
    feed_ids = {item["id"] for item in snapshot["coverage"]}
    if any(fragment["feed_id"] not in feed_ids for fragment in snapshot["fragments"]):
        raise ValueError("Every fragment must reference a declared feed.")
    postings = snapshot["postings"]
    if type(postings) is not dict or len(postings) > MAX_FRAGMENTS * MAX_TERMS:
        raise ValueError("Invalid postings dictionary.")
    membership_count = 0
    for term, ids in postings.items():
        _text(term, "posting term", 256)
        if type(ids) is not list or not 1 <= len(ids) <= MAX_FRAGMENTS:
            raise ValueError("Invalid posting identifiers.")
        membership_count += len(ids)
        if membership_count > MAX_FRAGMENTS * MAX_TERMS:
            raise ValueError("Postings exceed the 65536-membership budget.")
        prior = None
        for item in ids:
            _text(item, "posting id", 256)
            if prior is not None and item <= prior:
                raise ValueError("Posting identifiers must be unique and sorted.")
            prior = item
    _size(snapshot, "Index")
    if postings != _postings(snapshot["fragments"]):
        raise ValueError("Postings differ from the exact fragment projection.")
    if snapshot["index_hash"] != hash_input(_payload(snapshot)):
        raise ValueError("index_hash differs from the index payload.")


def update_knowledge_index(
    snapshot: Any, *, upserts: list[dict[str, Any]], removals: list[str],
    coverage: list[dict[str, str]], expected_head: str,
) -> dict[str, Any]:
    """Apply explicit changes to a value, retaining all omitted fragments/feeds.

    The expected hash is a value precondition, not a shared-storage lock. No
    version ordering or replacement of an older decision is inferred. Updating
    a lifecycle state requires a new version just like updating source prose.
    """
    validate_knowledge_index(snapshot)
    _digest(expected_head, "expected_head")
    if expected_head != snapshot["index_hash"]:
        raise ValueError("Stale expected_head; inspect the current snapshot first.")
    for field, values in (("upserts", upserts), ("removals", removals), ("coverage", coverage)):
        if type(values) is not list or len(values) > MAX_FRAGMENTS:
            raise ValueError(f"{field} must be a list of at most 256 entries.")
    incoming: dict[str, dict[str, Any]] = {}
    for item in upserts:
        _fragment(item)
        _terms(item["text"])
        if item["id"] in incoming:
            raise ValueError("Duplicate fragment upsert.")
        incoming[item["id"]] = item
    feeds = {item["id"]: deepcopy(item) for item in snapshot["coverage"]}
    new_feeds = set()
    for item in coverage:
        _feed(item)
        if item["id"] in new_feeds:
            raise ValueError("Duplicate coverage update.")
        feeds[item["id"]] = deepcopy(item)
        new_feeds.add(item["id"])
    if len(feeds) > MAX_FRAGMENTS:
        raise ValueError("Too many declared feeds.")
    remove_ids = set()
    current = {item["id"]: item for item in snapshot["fragments"]}
    for item in removals:
        _text(item, "removal id", 256)
        if item in remove_ids or item in incoming or item not in current:
            raise ValueError("Removal must identify one existing fragment without an upsert.")
        remove_ids.add(item)
    fragments = {key: deepcopy(value) for key, value in current.items() if key not in remove_ids}
    added = changed = 0
    for key, item in incoming.items():
        if item["feed_id"] not in feeds:
            raise ValueError("New fragments require a declared feed.")
        old = current.get(key)
        if old is not None and old != item and old["version"] == item["version"]:
            raise ValueError("Changed fragment data requires a new version.")
        if old is None:
            added += 1
        elif old != item:
            changed += 1
        fragments[key] = deepcopy(item)
    if len(fragments) > MAX_FRAGMENTS:
        raise ValueError("Index exceeds 256 fragments.")
    ordered = [fragments[key] for key in sorted(fragments)]
    delta = {
        "added": added, "changed": changed, "removed": len(remove_ids),
        "reused": len(current) - changed - len(remove_ids),
    }
    if ordered == snapshot["fragments"] and list(sorted(feeds.values(), key=lambda v: v["id"])) == snapshot["coverage"]:
        return {"index": deepcopy(snapshot), "delta": delta}
    if snapshot["generation"] == _MAX_GENERATION:
        raise ValueError("Generation bound reached.")
    # Incremental membership changes use old term memberships for retained
    # fragments. Public validation above still retokenizes the supplied input
    # for integrity; delta counts are not measurements of avoided CPU work.
    postings = {
        term: [key for key in ids if key in fragments and key not in incoming]
        for term, ids in snapshot["postings"].items()
    }
    for key, item in incoming.items():
        for term in _terms(item["text"]):
            postings.setdefault(term, []).append(key)
    postings = {term: sorted(ids) for term, ids in sorted(postings.items()) if ids}
    index = _seal({
        "schema": INDEX_SCHEMA, "index_id": snapshot["index_id"],
        "generation": snapshot["generation"] + 1,
        "parent_hash": snapshot["index_hash"], "fragments": ordered,
        "coverage": sorted(feeds.values(), key=lambda item: item["id"]),
        "postings": postings,
    })
    return {"index": index, "delta": delta}


def _citation(fragment: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: fragment[key] for key in _FRAGMENT_FIELDS - {"text"}},
        "content_sha256": hashlib.sha256(fragment["text"].encode("utf-8")).hexdigest(),
        "excerpt": fragment["text"],
    }


def find_knowledge_candidates(
    snapshot: Any, *, fragment_id: str, limit: int = 5,
) -> dict[str, Any]:
    """Return cross-feed/project lexical candidates, never inferred relations.

    The full bounded fragment is cited to retain negations and context. A source
    marked unavailable is retained but cannot supply an anchor or a candidate.
    Exact mirrored text is deduplicated even when source identifiers differ.
    """
    validate_knowledge_index(snapshot)
    _text(fragment_id, "fragment_id", 256)
    if type(limit) is not int or not 1 <= limit <= MAX_FRAGMENTS:
        raise ValueError("limit must be an integer from 1 to 256.")
    indexed = {item["id"]: item for item in snapshot["fragments"]}
    anchor = indexed.get(fragment_id)
    coverage = {item["id"]: item["status"] for item in snapshot["coverage"]}
    if anchor is None:
        raise ValueError("Anchor fragment is absent from the supplied index.")
    if anchor["state"] != "active" or coverage[anchor["feed_id"]] == "unavailable":
        raise ValueError("Anchor fragment is inactive or its feed is unavailable.")
    anchor_terms = _terms(anchor["text"])
    shared: dict[str, set[str]] = defaultdict(set)
    for term in sorted(anchor_terms):
        for key in snapshot["postings"].get(term, []):
            if key != fragment_id:
                shared[key].add(term)
    candidates = []
    seen_texts = {hashlib.sha256(anchor["text"].encode("utf-8")).hexdigest()}
    source = _citation(anchor)
    for key in sorted(shared):
        other = indexed[key]
        if (
            len(shared[key]) < 2 or other["state"] != "active"
            or coverage[other["feed_id"]] == "unavailable"
            or (other["feed_id"] == anchor["feed_id"] and other["project"] == anchor["project"])
        ):
            continue
        target = _citation(other)
        if target["content_sha256"] in seen_texts:
            continue
        seen_texts.add(target["content_sha256"])
        candidates.append({
            "kind": "lexical_candidate", "status": "unverified",
            "score": len(shared[key]), "shared_terms": sorted(shared[key]),
            "source": source, "target": target,
        })
    candidates.sort(key=lambda item: (-item["score"], item["target"]["id"]))
    result = {
        "schema": CANDIDATES_SCHEMA, "index_hash": snapshot["index_hash"],
        "anchor": source, "scope": "caller_declared_feeds",
        "coverage": deepcopy(snapshot["coverage"]),
        "coverage_incomplete": any(state != "complete" for state in coverage.values()),
        "matches": [], "omitted_count": len(candidates),
        "truncation_reasons": ["limit", "output_budget"],
    }
    # Reserve the largest metadata envelope and account for each row once.
    # ASCII is the actual compact CLI representation; it also upper-bounds
    # canonical UTF-8 bytes. Keeping a prefix preserves the declared ranking.
    def output_bytes(value: Any) -> int:
        return len(json.dumps(value, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=True, allow_nan=False).encode("ascii"))

    reserved = output_bytes(result)
    if reserved > MAX_INDEX_BYTES:
        raise ValueError("Candidate metadata exceeds the 2 MiB output budget.")
    output_limited = False
    for candidate in candidates[:limit]:
        row_bytes = output_bytes(candidate) + (1 if result["matches"] else 0)
        if reserved + row_bytes > MAX_INDEX_BYTES:
            output_limited = True
            break
        result["matches"].append(candidate)
        reserved += row_bytes
    result["omitted_count"] = len(candidates) - len(result["matches"])
    result["truncation_reasons"] = (
        (["limit"] if len(candidates) > limit else [])
        + (["output_budget"] if output_limited else [])
    )
    _size(result, "Candidate result")
    return deepcopy(result)
