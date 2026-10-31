"""Provenance-bound, blind source review; a declared reviewer is not certified truth."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from ..context_review import freeze_context_review_split
from .core import canonical, fingerprint, unique
from .source_triage import RELATIONS, attention_state, novelty_state, retrieve_source_candidates


ATTENTION_LABELS = {"process", "defer", "skip_candidate", "needs_context", "uncertain"}
ANNOTATION_KEYS = {"case_hash", "reviewer_id", "source_reviewed", "event_group", "language",
                   "rationale", "labels", "complete"}


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _bounded_bytes(path, limit):
    if type(limit) is not int or limit < 1:
        raise ValueError("saved source read budget exhausted")
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise ValueError("saved source exceeds its read budget")
    return content


def load_saved_source_manifest(path: str | Path, *, max_files: int = 32,
                               max_file_bytes: int = 65536,
                               max_total_bytes: int = 1048576) -> dict[str, Any]:
    if any(type(n) is not int or n < 1 for n in (max_files, max_file_bytes, max_total_bytes)):
        raise ValueError("invalid saved source read bounds")
    manifest_path = Path(path).resolve(strict=True)
    manifest_bytes = _bounded_bytes(manifest_path, 131072)
    manifest = json.loads(manifest_bytes.decode("utf-8"))
    stamp = _text(manifest["consulted_at_utc"], "capture timestamp")
    if datetime.fromisoformat(stamp.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("capture timestamp must have a timezone")
    root, records, total = manifest_path.parent, [], 0
    repositories = manifest["repositories"]
    if not isinstance(repositories, list) or len(repositories) > max_files:
        raise ValueError("invalid repository count")
    declared = sum(len(repo["files"]) for repo in repositories)
    if not 1 <= declared <= max_files:
        raise ValueError("saved source file budget exceeded")
    for repository in repositories:
        name, revision = repository["repo"], repository["revision"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", name) or any(part in {".", ".."} for part in name.split("/")):
            raise ValueError("invalid source repository identity")
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("source revision must be pinned")
        for entry in repository["files"]:
            filename = Path(_text(entry["file"], "snapshot filename"))
            if filename.is_absolute() or ".." in filename.parts or ":" in str(filename):
                raise ValueError("snapshot path escapes capture root")
            target = (root / name.replace("/", "--") / filename).resolve(strict=True)
            target.relative_to(root)
            expected_url = f"https://huggingface.co/{name}/resolve/{revision}/{filename.as_posix()}"
            if entry["url"] != expected_url:
                raise ValueError("snapshot URL does not match its revision")
            remaining = min(max_file_bytes, max_total_bytes - total)
            content = _bounded_bytes(target, remaining)
            total += len(content)
            digest = sha256(content).hexdigest()
            if type(entry["bytes"]) is not int or entry["bytes"] != len(content) or entry["sha256"] != digest:
                raise ValueError("snapshot content does not match saved manifest")
            text = content.decode("utf-8")
            source = {"id": fingerprint({"reference": expected_url, "sha256": digest}),
                      "title": name + " / " + filename.as_posix(), "text": text, "reference": expected_url}
            records.append({"source": source, "provenance": {
                "snapshot_path": str(target), "sha256": digest, "bytes": len(content),
                "captured_at": stamp, "reference": expected_url, "revision": revision,
                "lineage_id": "huggingface:" + name}})
    unique([record["source"] for record in records])
    return {"schema": "saved-public-sources/1", "manifest_path": str(manifest_path),
            "manifest_sha256": sha256(manifest_bytes).hexdigest(), "read_bytes": total,
            "records": sorted(records, key=lambda row: row["source"]["id"]),
            "model_inference_executed": False}


def _record(record, context):
    if not isinstance(record, Mapping) or set(record) != {"source", "provenance"}:
        raise ValueError("source record needs source and provenance only")
    state = attention_state(record["source"], context)
    provenance = deepcopy(record["provenance"])
    content = state["source"]["text"].encode("utf-8")
    if (provenance["sha256"] != sha256(content).hexdigest()
            or type(provenance["bytes"]) is not int or provenance["bytes"] != len(content)
            or provenance["reference"] != state["source"]["reference"]):
        raise ValueError("review text differs from its captured content")
    for key in ("snapshot_path", "captured_at", "reference", "revision", "lineage_id"):
        _text(provenance[key], key)
    return {"source": state["source"], "provenance": provenance}


def _packet_identity(packet):
    return fingerprint({key: packet[key] for key in ("schema", "corpus_revision", "seed", "cases")})


def build_source_review_pack(records: Sequence[Mapping[str, Any]], context: Mapping[str, Any], *,
                            seed: int = 20261008, limit: int = 100,
                            candidate_limit: int = 2) -> dict[str, Any]:
    if type(seed) is not int or type(limit) is not int or limit < 1:
        raise ValueError("invalid source review selection bounds")
    rows = sorted((_record(row, context) for row in records), key=lambda row: row["source"]["id"])
    if not rows:
        raise ValueError("source review needs real captured records")
    unique([row["source"] for row in rows])
    by_id = {row["source"]["id"]: row for row in rows}
    sources = [row["source"] for row in rows]
    selected = sorted(rows, key=lambda row: fingerprint({"seed": seed, "source": row["source"]["id"]}))[:limit]
    cases = []
    for row in selected:
        state = attention_state(row["source"], context)
        retrieval = retrieve_source_candidates(state["source"], sources, limit=candidate_limit)
        candidates = retrieval["selected"]
        case = {"source": state["source"], "context": state["context"], "provenance": row["provenance"],
                "candidates": candidates,
                "candidate_provenance": {item["id"]: by_id[item["id"]]["provenance"] for item in candidates},
                "retrieval": retrieval, "labels": {"must_retain": None, "attention": None,
                    "relations": {item["id"]: None for item in candidates}},
                "annotation": None, "split": None}
        case["case_id"] = fingerprint({key: case[key] for key in ("source", "context", "candidates")})
        cases.append(case)
    packet = {"schema": "source-review-pack/1", "corpus_revision": fingerprint(rows),
              "seed": seed, "candidate_count": len(rows), "selected_count": len(cases), "cases": cases,
              "reviewed_cases": 0, "pending_cases": len(cases), "split_manifest": None,
              "split_status": "awaiting_independent_review", "independent_labels_established": False,
              "quality_metrics": None, "cost_savings": None, "claim_allowed": False,
              "auto_act_allowed": False, "model_inference_executed": False}
    packet["pack_id"] = _packet_identity(packet)
    return packet


def validate_source_review_pack(packet):
    if packet["schema"] != "source-review-pack/1" or packet["pack_id"] != _packet_identity(packet):
        raise ValueError("source review packet identity changed")
    if type(packet["seed"]) is not int or not packet["cases"]:
        raise ValueError("invalid source review packet")
    unique(packet["cases"], "case_id")
    for case in packet["cases"]:
        _record({"source": case["source"], "provenance": case["provenance"]}, case["context"])
        novelty_state(case["source"], case["candidates"])
        if case["case_id"] != fingerprint({key: case[key] for key in ("source", "context", "candidates")}):
            raise ValueError("source review case identity changed")
        if set(case["candidate_provenance"]) != {item["id"] for item in case["candidates"]}:
            raise ValueError("candidate provenance is incomplete")
        for item in case["candidates"]:
            _record({"source": item, "provenance": case["candidate_provenance"][item["id"]]}, case["context"])
        if case["annotation"] is None:
            if case["labels"] != _blank_labels(case) or case["split"] is not None:
                raise ValueError("unreviewed source cannot have labels or a split")
        else:
            original = {**case, "labels": _blank_labels(case), "annotation": None, "split": None}
            _check_annotation(case["annotation"], case, fingerprint(original))
            if case["annotation"]["complete"] is not True or case["labels"] != case["annotation"]["labels"]:
                raise ValueError("source labels differ from completed review")


def _blank_labels(case):
    return {"must_retain": None, "attention": None,
            "relations": {item["id"]: None for item in case["candidates"]}}


def _check_annotation(annotation, case, expected_hash):
    if not isinstance(annotation, Mapping) or set(annotation) != ANNOTATION_KEYS:
        raise ValueError("invalid source annotation contract")
    if annotation["case_hash"] != expected_hash:
        raise ValueError("annotation source or context has changed")
    if type(annotation["complete"]) is not bool:
        raise ValueError("annotation completion must be boolean")
    if annotation["complete"] is not True:
        return
    _text(annotation["reviewer_id"], "reviewer identity")
    _text(annotation["rationale"], "annotation rationale")
    if annotation["source_reviewed"] is not True or annotation["language"] not in {"fr", "en", "mixed", "other", "unknown"}:
        raise ValueError("source provenance and language must be reviewed")
    if annotation["event_group"] is not None:
        _text(annotation["event_group"], "event group")
    labels = annotation["labels"]
    if not isinstance(labels, Mapping) or set(labels) != {"must_retain", "attention", "relations"}:
        raise ValueError("source labels must include explicit unknowns")
    if labels["must_retain"] is not None and type(labels["must_retain"]) is not bool:
        raise ValueError("must_retain must be boolean or unknown")
    if labels["attention"] not in ATTENTION_LABELS:
        raise ValueError("attention label must be explicit, including uncertainty")
    relations = labels["relations"]
    if (not isinstance(relations, Mapping) or set(relations) != {item["id"] for item in case["candidates"]}
            or any(label not in RELATIONS for label in relations.values())):
        raise ValueError("every candidate needs an explicit relationship label")
    if labels["must_retain"] is True and labels["attention"] == "skip_candidate":
        raise ValueError("a required source cannot be labelled for skipping")
    if case["source"].get("protected", False) and labels["attention"] == "skip_candidate":
        raise ValueError("a protected source cannot be labelled for skipping")


def source_review_template(packet):
    validate_source_review_pack(packet)
    return {"schema": "source-human-review/1", "packet_id": packet["pack_id"],
            "annotations": {case["case_id"]: {"case_hash": fingerprint({**case,
                "labels": _blank_labels(case), "annotation": None, "split": None}), "reviewer_id": None,
                "source_reviewed": False, "event_group": None, "language": None,
                "rationale": None, "labels": _blank_labels(case), "complete": False}
                for case in packet["cases"]}, "independent_labels_established": False,
            "claim_allowed": False, "auto_act_allowed": False}


def _freeze(cases, seed):
    if len(cases) < 2:
        raise ValueError("no source-disjoint held-out split is possible.")
    parent = {case["case_id"]: case["case_id"] for case in cases}
    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key
    seen = {}
    for case in cases:
        provenance = [case["provenance"], *case["candidate_provenance"].values()]
        keys = [("lineage", item["lineage_id"]) for item in provenance]
        keys += [("content", item["sha256"]) for item in provenance]
        if case["annotation"]["event_group"] is not None:
            keys.append(("event", case["annotation"]["event_group"]))
        for key in keys:
            if key in seen:
                parent[find(case["case_id"])] = find(seen[key])
            else:
                seen[key] = case["case_id"]
    components = {}
    for case in cases:
        components.setdefault(find(case["case_id"]), []).append(case["case_id"])
    group_for = {case_id: fingerprint(sorted(ids)) for ids in components.values() for case_id in ids}
    projection = [{"case_id": case["case_id"], "text": case["source"]["text"],
                   "source_group": group_for[case["case_id"]], "group_reviewed": True}
                  for case in cases]
    return freeze_context_review_split(projection, seed=seed)


def apply_source_review(packet, review, *, require_complete=False):
    validate_source_review_pack(packet)
    if type(require_complete) is not bool:
        raise TypeError("require_complete must be boolean")
    if review["schema"] != "source-human-review/1" or review["packet_id"] != packet["pack_id"]:
        raise ValueError("review belongs to another packet")
    annotations = review["annotations"]
    if not isinstance(annotations, Mapping) or set(annotations) - {case["case_id"] for case in packet["cases"]}:
        raise ValueError("review contains foreign source cases")
    result = deepcopy(packet)
    for case in result["cases"]:
        annotation = annotations.get(case["case_id"])
        if annotation is None:
            continue
        original = {**case, "labels": _blank_labels(case), "annotation": None, "split": None}
        _check_annotation(annotation, case, fingerprint(original))
        if annotation["complete"] is not True:
            continue
        case.update(labels=deepcopy(annotation["labels"]), annotation=deepcopy(annotation))
    done = sum(case["annotation"] is not None for case in result["cases"])
    pending = len(result["cases"]) - done
    if require_complete and pending:
        raise ValueError("source review is incomplete")
    split, status = None, "awaiting_independent_review"
    if not pending:
        try:
            split = _freeze(result["cases"], packet["seed"])
        except ValueError as error:
            if "no source-disjoint" not in str(error):
                raise
            status = "no_source_disjoint_split"
        else:
            status = "frozen"
            heldout = set(split["heldout"])
            for case in result["cases"]:
                case["split"] = "heldout" if case["case_id"] in heldout else "development"
            split["case_hashes"] = {case["case_id"]: fingerprint(case) for case in result["cases"]}
            split["case_hash_scope"] = "final_source_case/1"
    result.update(reviewed_cases=done, pending_cases=pending, split_status=status, split_manifest=split,
                  parent_pack_id=packet["pack_id"], independent_labels_established=False,
                  quality_metrics=None, cost_savings=None, claim_allowed=False, auto_act_allowed=False)
    result["pack_id"] = _packet_identity(result)
    return result


def source_comparison_readiness(packet, *, min_heldout=20):
    validate_source_review_pack(packet)
    if type(min_heldout) is not int or min_heldout < 1:
        raise ValueError("invalid heldout minimum")
    reasons, split = [], packet.get("split_manifest")
    if packet.get("pending_cases") != 0 or any(case["annotation"] is None for case in packet["cases"]):
        reasons.append("human_review_incomplete")
    if packet.get("split_status") != "frozen" or not isinstance(split, Mapping):
        reasons.append("split_not_frozen")
        heldout = []
    else:
        expected = _freeze(packet["cases"], packet["seed"])
        if any(split.get(key) != expected[key] for key in ("development", "heldout", "groups")):
            reasons.append("split_source_leakage_or_assignment_changed")
        if (split.get("case_hash_scope") != "final_source_case/1"
                or split.get("case_hashes") != {case["case_id"]: fingerprint(case) for case in packet["cases"]}
                or any(case["split"] != ("heldout" if case["case_id"] in split["heldout"] else "development")
                       for case in packet["cases"])):
            reasons.append("split_case_identity_changed")
        heldout = [case for case in packet["cases"] if case["case_id"] in split["heldout"]]
    labelled = [case for case in heldout if type(case["labels"]["must_retain"]) is bool
                and case["labels"]["attention"] != "uncertain"
                and all(label != "uncertain" for label in case["labels"]["relations"].values())]
    if len(labelled) < min_heldout:
        reasons.append("insufficient_labelled_heldout")
    return {"schema": "source-comparison-readiness/1", "packet_id": packet["pack_id"],
            "cases": len(packet["cases"]), "human_reviewed_cases": sum(case["annotation"] is not None for case in packet["cases"]),
            "heldout_cases": len(heldout), "labelled_heldout_cases": len(labelled),
            "min_heldout": min_heldout, "capture_ready": not reasons, "reason_codes": reasons,
            "metric_basis": "agreement with declared human review only",
            "independence_certified": False, "quality_metrics": None, "cost_savings": None,
            "claim_allowed": False, "auto_act_allowed": False, "model_inference_executed": False}
