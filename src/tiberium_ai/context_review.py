"""Unlabelled context review packs and explicit, grouped development/test splits."""
from __future__ import annotations

from hashlib import sha256
import math
import unicodedata
from typing import Any, Mapping, Sequence

from .decision_json import canonical_json

LABEL_FIELDS = ("task_kind", "provided_fields", "required_context", "missing_context", "unknown_context")


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a nonempty string.")
    return value


def _digest(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalised(text: str) -> str:
    # A leakage guard, not a claim that normalised prompts mean the same thing.
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def build_context_review_pack(
    records: Sequence[Mapping[str, Any]], *, corpus_revision: str, limit: int = 120,
    seed: int = 20261007, language_target: str = "fr",
) -> dict[str, Any]:
    """Select cases deterministically; create no labels or inferred attachments."""
    _text(corpus_revision, "corpus_revision")
    _text(language_target, "language_target")
    if type(limit) is not int or limit < 1 or type(seed) is not int:
        raise ValueError("limit must be positive and seed must be an integer.")
    by_text = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise TypeError("records must contain mappings.")
        prompt = _text(row.get("text"), "prompt text")
        sources = row.get("sources", [])
        if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence):
            raise TypeError("sources must be a sequence of labels.")
        sources = tuple(sorted({_text(source, "source label") for source in sources}))
        by_text.setdefault(prompt, set()).update(sources)
    if not by_text:
        raise ValueError("no review candidates are available.")
    selected = sorted(by_text, key=lambda prompt: (_digest({"seed": seed, "prompt": prompt}), prompt))[:limit]
    cases = [{"case_id": sha256(prompt.encode("utf-8")).hexdigest(), "text": prompt,
        "sources": sorted(by_text[prompt]), "language_target": language_target,
        "language_review_required": True, "context_snapshot": None,
        "contract_id": None, "contract_version": None,
        "source_group": None, "paraphrase_group": None, "group_reviewed": False,
        "split": None, "labels": dict.fromkeys(LABEL_FIELDS),
        "labeler_id": None, "label_origin": None, "situation_origin": "captured"}
        for prompt in selected]
    pack_id = _digest({"corpus_revision": corpus_revision, "seed": seed,
                       "language_target": language_target, "cases": cases})
    return {"schema_version": 1, "kind": "context_review_pack", "pack_id": pack_id,
        "corpus_revision": corpus_revision, "seed": seed, "selection": "seeded_content_order",
        "candidate_count": len(by_text), "selected_count": len(cases), "cases": cases,
        "labelled_cases": 0, "independent_labels_established": False,
        "split_status": "awaiting_source_and_paraphrase_group_review",
        "claim_allowed": False, "auto_act_allowed": False,
        "quality_metrics": None, "model_inference_executed": False}


def freeze_context_review_split(cases: Sequence[Mapping[str, Any]], *, seed: int = 20261007,
                                development_fraction: float = .8) -> dict[str, Any]:
    """Keep shared sources, reviewed paraphrases and normalised duplicates together.

    Broad labels such as 'sessions' are not thread provenance. Source groups
    must be recovered/reviewed before calling this function; never inferred here.
    """
    if type(seed) is not int or type(development_fraction) not in (int, float) or not math.isfinite(development_fraction) or not 0 < development_fraction < 1:
        raise ValueError("invalid split settings.")
    by_id = {}
    for row in cases:
        if not isinstance(row, Mapping):
            raise TypeError("cases must contain mappings.")
        case_id = _text(row.get("case_id"), "case_id")
        _text(row.get("text"), "prompt text")
        _text(row.get("source_group"), "reviewed source_group")
        if row.get("group_reviewed") is not True:
            raise ValueError("source and paraphrase groups must be reviewed before splitting.")
        if row.get("paraphrase_group") is not None:
            _text(row["paraphrase_group"], "paraphrase_group")
        if case_id in by_id:
            raise ValueError("case ids must be unique.")
        by_id[case_id] = row
    if len(by_id) < 2:
        raise ValueError("at least two cases are required.")
    parent = {case_id: case_id for case_id in by_id}
    def find(case_id):
        while parent[case_id] != case_id:
            parent[case_id] = parent[parent[case_id]]
            case_id = parent[case_id]
        return case_id
    seen = {}
    for case_id in sorted(by_id):
        row = by_id[case_id]
        keys = [("source", row["source_group"]), ("normalised", _normalised(row["text"]))]
        if row.get("paraphrase_group") is not None:
            keys.append(("paraphrase", row["paraphrase_group"]))
        for key in keys:
            if key in seen:
                parent[find(case_id)] = find(seen[key])
            else:
                seen[key] = case_id
    components = {}
    for case_id in sorted(by_id):
        components.setdefault(find(case_id), []).append(case_id)
    groups = sorted(components.values(), key=lambda ids: _digest({"seed": seed, "case_ids": ids}))
    if len(groups) < 2:
        raise ValueError("no source-disjoint held-out split is possible.")
    cut = min(len(groups) - 1, max(1, int(len(groups) * development_fraction)))
    development = sorted(case_id for group in groups[:cut] for case_id in group)
    heldout = sorted(case_id for group in groups[cut:] for case_id in group)
    return {"schema_version": 1, "kind": "context_review_split", "seed": seed,
        "development_fraction_of_groups": development_fraction, "groups": len(groups),
        "development": development, "heldout": heldout,
        "case_hashes": {case_id: _digest(by_id[case_id]) for case_id in sorted(by_id)},
        "claim_allowed": False, "auto_act_allowed": False}
