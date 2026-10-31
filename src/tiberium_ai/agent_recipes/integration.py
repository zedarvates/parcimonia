"""Route manifests and structural proof integration with the existing registry."""
from __future__ import annotations

from typing import Any, Mapping

from ..verification import VerifierRegistry
from .core import fingerprint


CAPABILITIES = (
    "skill.select@1", "skill.audit@1", "code.search.rank@1", "context.select@1",
    "review.triage@1", "rules.check@1", "requirements.trace@1",
    "feedback.classify@1", "browser.navigate@1",
)
VERIFIER_ID = "agent.recipe.structure"


def verify_structure(payload: Mapping[str, Any]) -> bool:
    """Bind a proposal to its state; verify recomposable invariants, never semantic truth."""
    state, result = payload["state"], payload["result"]
    if result["recipe"] not in CAPABILITIES or result["state_hash"] != fingerprint(state):
        return False
    if result["auto_act_allowed"] is not False:
        return False
    if result["status"] not in {"proposed", "abstained", "verified"}:
        return False
    data = result["data"]
    if result["status"] == "abstained":
        return True
    if result["recipe"] == "context.select@1":
        originals = {b["id"]: b for b in state["blocks"]}
        kept = {b["id"]: b for b in data["kept"]}
        removed = data["removed"]
        if len(kept) != len(data["kept"]) or len(set(removed)) != len(removed):
            return False
        if set(kept) & set(removed) or set(kept) | set(removed) != set(originals):
            return False
        if set(data["recall"]) != set(removed):
            return False
        for i, block in originals.items():
            if i in kept and kept[i] != block:
                return False
            if i in removed:
                r = data["recall"][i]
                if r["block"] != block or r["content_hash"] != fingerprint(block["text"]):
                    return False
                if block.get("protected") or block.get("kind") in {
                        "instruction", "goal", "authorization", "decision", "pending", "error", "evidence"}:
                    return False
        return data["kept_chars"] == sum(len(b["text"]) for b in kept.values())
    if result["recipe"] == "feedback.classify@1":
        originals = {r["id"]: r for r in state}
        rows = data["rows"]
        if {r["id"] for r in rows} != set(originals) or len(rows) != len(originals):
            return False
        counts = {k: 0 for k in ("positive", "negative", "neutral", "mixed", "unresolved")}
        for row in rows:
            counts[row["sentiment"]] += 1
            if row["source_hash"] != fingerprint(originals[row["id"]]):
                return False
        return data["totals"] == counts
    if result["recipe"] == "skill.select@1":
        return data is None or data in {r["id"] for r in state["skills"]}
    if result["recipe"] == "code.search.rank@1":
        originals = {r["id"]: r for r in state["files"]}
        return len({r["id"] for r in data}) == len(data) and all(
            all(r[k] == v for k, v in originals[r["id"]].items()) for r in data)
    if result["recipe"] == "review.triage@1":
        return data.get("effective_depth", "full") == "full"
    if result["recipe"] == "requirements.trace@1":
        return all(r["coverage_certified"] is False for r in data)
    return True


def register_recipe_verifier(registry: VerifierRegistry) -> None:
    registry.register(VERIFIER_ID, "1", verify_structure)


def recipe_manifest(*, registry_version: str = "agent-recipes/1") -> dict[str, Any]:
    return {"schema_version": 1, "registry_version": registry_version,
            "routes": [{"route_id": "recipe:" + c, "capability_ids": [c],
                        "estimated_cost": None, "estimated_latency_ms": None, "confidence": None,
                        "constraints": {"risk_classes": ["low"], "evidence_levels": ["normal"],
                                        "localities": ["any", "local"]},
                        "verifier": {"verifier_id": VERIFIER_ID, "verifier_version": "1"}}
                       for c in CAPABILITIES]}
