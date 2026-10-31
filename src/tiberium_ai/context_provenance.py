"""Exact recovery of context-review sources and conservative source components."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

from .decision_json import canonical_json
from .signature_ingest import redact, strip_harness_text


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def user_input_text(item: Mapping[str, Any]) -> str:
    if item.get("type") not in {"userMessage", "message"}:
        raise ValueError("only user-message records may establish provenance.")
    if item.get("type") == "message" and item.get("role") != "user":
        raise ValueError("only user-message records may establish provenance.")
    content = item.get("content", [])
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        raise ValueError("user content must be text or content blocks.")
    return " ".join(block["text"] for block in content
                    if isinstance(block, Mapping) and isinstance(block.get("text"), str))


def corpus_match_text(item: Mapping[str, Any], *, max_prompt_chars: int = 1200) -> str | None:
    """Repeat the corpus transform; never infer a match from a title or similarity."""
    text, _ = strip_harness_text(user_input_text(item))
    text = " ".join(text.split())
    if len(text) > max_prompt_chars:
        return None
    return redact(text)[0].lower()


def recover_context_provenance(pack: Mapping[str, Any], occurrences: Iterable[Mapping[str, Any]],
                               *, cutoff_ms: int) -> dict[str, Any]:
    if pack.get("kind") != "context_review_pack" or not isinstance(pack.get("cases"), list):
        raise ValueError("a context review pack is required.")
    if type(cutoff_ms) is not int or cutoff_ms <= 0:
        raise ValueError("a positive corpus cutoff is required.")
    targets = {}
    by_id = {}
    for case in pack["cases"]:
        text = case.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("review cases need text.")
        if case.get("case_id") != sha256(text.encode("utf-8")).hexdigest():
            raise ValueError("case identity does not match its text.")
        if case["case_id"] in by_id or text.lower() in targets:
            raise ValueError("review case identities and corpus keys must be unique.")
        by_id[case["case_id"]] = case
        targets[text.lower()] = case["case_id"]
    found = {case_id: [] for case_id in by_id}
    counters = {"records_checked": 0, "malformed_records": 0, "outside_corpus_period": 0,
                "unknown_timestamp": 0, "unmatched_records": 0}
    seen = set()
    for source in occurrences:
        counters["records_checked"] += 1
        try:
            item = source["item"]
            if not isinstance(item, Mapping):
                raise ValueError("item must be a mapping.")
            key = corpus_match_text(item)
            thread = source["thread_id"]
            if not isinstance(thread, str) or not thread.strip():
                raise ValueError("thread_id is required.")
            stamp = source.get("timestamp_ms")
            if type(stamp) is not int or stamp <= 0:
                counters["unknown_timestamp"] += 1
                continue
            if stamp > cutoff_ms:
                counters["outside_corpus_period"] += 1
                continue
            if key not in targets:
                counters["unmatched_records"] += 1
                continue
            locator = source["locator"]
            if not isinstance(locator, Mapping) or source.get("source_kind") not in {"sqlite_user_message", "rollout_jsonl"}:
                raise ValueError("an exact source locator is required.")
            if source["source_kind"] == "sqlite_user_message":
                if any(not isinstance(locator.get(key), str) or not locator[key] for key in ("turn_id", "item_id")) or type(locator.get("rollout_ordinal")) is not int:
                    raise ValueError("SQLite provenance needs a turn, item and ordinal.")
            elif not isinstance(locator.get("path"), str) or type(locator.get("line")) is not int or locator["line"] < 1:
                raise ValueError("rollout provenance needs an exact path and line.")
            identity = _hash({"source_kind": source["source_kind"], "thread_id": thread, "locator": locator})
            if identity in seen:
                continue
            seen.add(identity)
            raw_text = user_input_text(item)
            content = item.get("content", [])
            block_types = sorted({str(block.get("type", "unknown")) for block in content if isinstance(block, Mapping)}) if isinstance(content, list) else ["text"]
            tags = [tag for tag in ("environment_context", "in-app-browser-context", "app-context")
                    if f"<{tag}>" in raw_text]
            # Recover only input metadata, never model answers or harness transcripts.
            cwd_match = re.search(r"<cwd>([^<]*)</cwd>", raw_text)
            recovered_cwd = redact(cwd_match.group(1))[0] if cwd_match else None
            found[targets[key]].append({"source_kind": source["source_kind"], "thread_id": thread,
                "locator": dict(locator), "timestamp_ms": stamp, "source_identity": identity,
                "user_item_sha256": _hash(item), "match_method": "corpus_transform_exact_lowercase",
                "recorded_input": {"content_block_types": block_types, "embedded_context_tags": tags,
                                   "cwd": recovered_cwd, "availability_established": False}})
        except (KeyError, TypeError, ValueError):
            counters["malformed_records"] += 1
    for values in found.values():
        values.sort(key=lambda row: (row["timestamp_ms"], row["thread_id"], row["source_identity"]))
    return {"schema_version": 1, "kind": "context_provenance", "parent_pack_id": pack["pack_id"],
        "cutoff_ms": cutoff_ms, "matches": found, "counters": counters,
        "recovered_cases": sum(bool(values) for values in found.values()),
        "occurrences": sum(map(len, found.values())),
        "distinct_threads": len({row["thread_id"] for values in found.values() for row in values}),
        "claim_allowed": False, "auto_act_allowed": False}


def attach_context_provenance(pack: Mapping[str, Any], recovery: Mapping[str, Any]) -> dict[str, Any]:
    if recovery.get("parent_pack_id") != pack.get("pack_id"):
        raise ValueError("provenance belongs to a different pack.")
    ids = {case["case_id"] for case in pack["cases"]}
    if set(recovery.get("matches", {})) != ids:
        raise ValueError("provenance must cover the exact pack case set.")
    result = deepcopy(dict(pack))
    parent = {case_id: case_id for case_id in ids}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    by_thread = {}
    for case_id in sorted(ids):
        for row in recovery["matches"][case_id]:
            thread = row["thread_id"]
            if thread in by_thread:
                parent[find(case_id)] = find(by_thread[thread])
            else:
                by_thread[thread] = case_id
    components = {}
    for case_id in sorted(ids):
        components.setdefault(find(case_id), []).append(case_id)
    group_for = {case_id: "source-" + _hash(component)[:16]
                 for component in components.values() for case_id in component}
    for case in result["cases"]:
        matches = deepcopy(recovery["matches"][case["case_id"]])
        case["provenance"] = matches
        case["provenance_status"] = "recovered" if matches else "not_found"
        case["source_group"] = group_for[case["case_id"]] if matches else None
        case["group_reviewed"] = False
        case["split"] = None
        # Source/input metadata cannot certify hidden context or produce labels.
        case["context_snapshot"] = None
    result.update(parent_pack_id=pack["pack_id"], provenance_recovered_cases=sum(bool(recovery["matches"][key]) for key in ids),
        source_component_count=sum(any(recovery["matches"][key] for key in group) for group in components.values()),
        split_status="provenance_recovered_awaiting_paraphrase_review", quality_metrics=None,
        claim_allowed=False, auto_act_allowed=False, independent_labels_established=False)
    result["pack_id"] = _hash({"parent_pack_id": pack["pack_id"], "cases": result["cases"]})
    return result


def propose_paraphrase_pairs(pack: Mapping[str, Any], *, max_pairs: int = 24) -> list[dict[str, Any]]:
    """Lexical review candidates only; no groups or truth labels are validated."""
    if type(max_pairs) is not int or max_pairs < 0:
        raise ValueError("max_pairs must be a nonnegative integer.")
    stopwords = {"de", "des", "du", "le", "les", "la", "un", "une", "et", "en", "a", "à", "pour", "dans", "ce", "cette", "que", "qui", "sur", "avec", "il", "est", "on", "je", "tu", "notre", "peux", "faire"}
    cases = sorted(pack["cases"], key=lambda row: row["case_id"])
    tokens = {case["case_id"]: set(re.findall(r"[^\W_]+", case["text"].casefold())) - stopwords for case in cases}
    pairs = []
    for i, left in enumerate(cases):
        for right in cases[i + 1:]:
            a, b = tokens[left["case_id"]], tokens[right["case_id"]]
            if len(a & b) < 4:
                continue
            score = len(a & b) / len(a | b)
            if score >= .5:
                pairs.append({"left": left["case_id"], "right": right["case_id"],
                    "lexical_overlap": round(score, 4), "status": "unreviewed",
                    "shared_source_group": left.get("source_group") is not None and left.get("source_group") == right.get("source_group")})
    return sorted(pairs, key=lambda row: (-row["lexical_overlap"], row["left"], row["right"]))[:max_pairs]
