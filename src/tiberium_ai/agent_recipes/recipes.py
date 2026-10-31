"""Recipes compose model judgments with explicit deterministic policy."""
from __future__ import annotations

import ast
import fnmatch
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from .catalog import terms
from .core import DecisionSession, Proposal, abstain, fingerprint, propose, unique


def select_skill(query: str, skills: Sequence[Mapping[str, Any]],
                 session: DecisionSession, *, explicit_id: str | None = None) -> Proposal:
    unique(skills)
    if len(skills) > 19:
        raise ValueError("provide at most 19 eligible shortlisted skills")
    state = {"query": query, "skills": [{k: r[k] for k in
             ("id", "name", "description", "content_hash", "execution_profile") if k in r} for r in skills]}
    if explicit_id is not None:
        if explicit_id not in {r["id"] for r in skills}:
            return abstain("skill.select@1", state, ValueError("explicit_skill_ineligible"))
        return propose("skill.select@1", state, explicit_id, "explicit_user_selection")
    if not skills:
        return propose("skill.select@1", state, None, "no_lexical_candidates_expand_search")
    options = {r["id"]: r["description"] for r in skills}
    options["none"] = "No skill is appropriate, or evidence is insufficient."
    if "none" in {r["id"] for r in skills}:
        raise ValueError("reserved skill id: none")
    try:
        chosen = session.choice(state, options)
        return propose("skill.select@1", state, None if chosen == "none" else chosen)
    except (ValueError, TypeError, KeyError, OSError) as error:
        return abstain("skill.select@1", state, error,
                       {"fallback": "agent_selection", "candidates": state["skills"]})


def audit_skills(skills: Sequence[Mapping[str, Any]]) -> Proposal:
    unique(skills)
    groups: dict[str, list[str]] = {}
    for s in skills:
        groups.setdefault(s["content_hash"], []).append(s["id"])
    rows = []
    for s in skills:
        duplicates = sorted(i for i in groups[s["content_hash"]] if i != s["id"])
        rows.append({"id": s["id"], "name": s["name"], "uses": s.get("uses", 0),
                     "last_used": s.get("last_used"), "duplicates": duplicates,
                     "recommendation": "review" if duplicates or not s.get("uses", 0) else "keep",
                     "reason": "exact_duplicate" if duplicates else
                               "no_recorded_usage_is_not_obsolescence" if not s.get("uses", 0)
                               else "recorded_usage", "delete_allowed": False})
    return propose("skill.audit@1", skills, rows, "deterministic_metadata_only")


def lexical_files(root: str | Path, query: str, *, limit: int = 40,
                  max_files: int = 2000, max_bytes: int = 65536) -> list[dict[str, Any]]:
    """Bounded lexical fallback. A host may instead supply rg candidates to rank_files."""
    directory = Path(root).resolve(strict=True)
    if not directory.is_dir() or min(limit, max_files, max_bytes) < 1:
        raise ValueError("invalid search bounds")
    candidates = []
    visited = 0
    for path in sorted(directory.rglob("*")):
        if any(p in {".git", ".venv", "node_modules", "runs", "__pycache__"}
               for p in path.relative_to(directory).parts):
            continue
        if not path.is_file():
            continue
        visited += 1
        if visited > max_files:
            break
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(directory) or path.stat().st_size > max_bytes:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            continue
        score = len(terms(query) & terms(str(path.relative_to(directory)) + " " + text))
        if score:
            # Include matched lines rather than only a file prefix.
            lines = [l for l in text.splitlines() if terms(query) & terms(l)]
            candidates.append({"id": str(path.relative_to(directory)), "content_hash": fingerprint(text),
                               "excerpt": "\n".join(lines)[:1500], "lexical_overlap": score})
    return sorted(candidates, key=lambda r: (-r["lexical_overlap"], r["id"]))[:limit]


def rank_files(query: str, files: Sequence[Mapping[str, Any]], session: DecisionSession,
               *, top_k: int = 5, batch_size: int = 20) -> Proposal:
    unique(files)
    if top_k < 1 or not 1 <= batch_size <= 64:
        raise ValueError("invalid ranking bounds")
    state = {"query": query, "files": list(files)}
    scored = []
    try:
        for offset in range(0, len(files), batch_size):
            batch = files[offset:offset + batch_size]
            probabilities = session.nouls({"query": query, "files": list(batch)}, {
                f"r{i}": f"Does file {f['id']!r} contain evidence needed to answer the query?"
                for i, f in enumerate(batch)})
            scored.extend({**f, "relevance": probabilities[f"r{i}"]} for i, f in enumerate(batch))
        ranked = sorted(scored, key=lambda f: (-f["relevance"], f["id"]))
        if not ranked or ranked[0]["relevance"] < session.threshold:
            raise ValueError("uncertain_scores")
        return propose("code.search.rank@1", state, ranked[:top_k])
    except (ValueError, TypeError, KeyError, OSError) as error:
        return abstain("code.search.rank@1", state, error,
                       {"fallback": "expand_lexical_search", "candidates": list(files)[:top_k]})


def compact_context(blocks: Sequence[Mapping[str, Any]], session: DecisionSession,
                    *, query: str, target_chars: int = 20000) -> Proposal:
    """Never drop instructions, unresolved issues, evidence or an uncertain block."""
    unique(blocks)
    if target_chars < 1:
        raise ValueError("target_chars must be positive")
    mandatory = {"instruction", "goal", "authorization", "decision", "pending", "error", "evidence"}
    keep, removed, recall = [], [], {}
    total = sum(len(b["text"]) for b in blocks)
    state = {"query": query, "blocks": list(blocks), "target_chars": target_chars}
    for b in blocks:
        if not isinstance(b["text"], str):
            raise ValueError("block text must be a string")
        protected = b.get("kind") in mandatory or b.get("protected", False)
        if protected or total <= target_chars:
            keep.append(dict(b))
            continue
        try:
            probability = session.nouls({"query": query, "block": b},
                {"relevant": "Is this block relevant to continuing the current task?"})["relevant"]
        except (ValueError, TypeError, KeyError, OSError):
            probability = 0.5
        if probability > 1 - session.threshold:
            keep.append(dict(b))
        else:
            removed.append(b["id"])
            recall[b["id"]] = {"text": b["text"], "content_hash": fingerprint(b["text"]),
                               "block": dict(b)}
            total -= len(b["text"])
    return propose("context.select@1", state,
        {"kept": keep, "removed": removed, "recall": recall,
         "within_target": total <= target_chars, "kept_chars": total},
        "verbatim_reversible_selection")


REVIEW_QUESTIONS = {
    "authorization": "Does this diff affect authorization or access control?",
    "data": "Does this diff affect persistent data or a migration?",
    "secret": "Does this diff expose secrets or change credential handling?",
    "interface": "Does this diff change a public interface?",
    "concurrency": "Does this diff change concurrency or lifecycle behavior?",
    "tests": "Does this diff omit necessary regression verification?",
    "rules": "Does this diff conflict with the supplied requirements?",
}


def triage_review(changes: Sequence[Mapping[str, Any]], session: DecisionSession,
                  *, rules: Sequence[str] = ()) -> Proposal:
    unique(changes, "path")
    state = {"changes": list(changes), "rules": list(rules)}
    sensitive = ("*auth*", "*permission*", "*migration*", "*secret*", "*.sql")
    if not changes:
        return propose("review.triage@1", state, {"depth": "full"}, "empty_change_set")
    if any(any(fnmatch.fnmatch(c["path"].lower(), p) for p in sensitive) for c in changes):
        return propose("review.triage@1", state, {"depth": "full"}, "sensitive_path")
    try:
        p = session.nouls(state, REVIEW_QUESTIONS)
        # Even a confident negative proposal requires calibration before reducing a real review.
        depth = "quick_candidate" if all(v <= 1 - session.threshold for v in p.values()) else "full"
        return propose("review.triage@1", state,
                       {"depth": depth, "checks": p, "effective_depth": "full"})
    except (ValueError, TypeError, KeyError, OSError) as error:
        return abstain("review.triage@1", state, error, {"depth": "full"})


def check_rules(change: Mapping[str, Any], rules: Sequence[Mapping[str, Any]],
                session: DecisionSession) -> Proposal:
    """Recognize forbidden patterns, syntax errors, and semantic review candidates."""
    unique(rules)
    state = {"change": dict(change), "rules": list(rules)}
    matched = [r for r in rules if fnmatch.fnmatch(change["path"], r.get("glob", "*"))]
    violations, unknown = [], []
    after = change["after"]
    if change["path"].endswith(".py"):
        try:
            ast.parse(after)
        except SyntaxError:
            violations.append("python_syntax")
    semantic = {}
    for r in matched:
        if r["kind"] == "forbid_regex":
            if re.search(r["pattern"], after):
                violations.append(r["id"])
        elif r["kind"] == "semantic":
            semantic[r["id"]] = "Does this proposed change violate this rule: " + r["instructions"]
        else:
            unknown.append(r["id"])
    probabilities = {}
    if semantic:
        try:
            probabilities = session.nouls(state, semantic)
            unknown.extend(k for k, v in probabilities.items() if v > 1 - session.threshold)
        except (ValueError, TypeError, KeyError, OSError):
            unknown.extend(semantic)
    return propose("rules.check@1", state,
        {"verdict": "block" if violations else "review" if unknown else "pass",
         "deterministic_violations": violations, "review_rules": sorted(set(unknown)),
         "semantic_probabilities": probabilities}, "policy_proposal_requires_host_enforcement")


def trace_requirements(requirements: Sequence[Mapping[str, Any]],
                       tests: Sequence[Mapping[str, Any]], session: DecisionSession) -> Proposal:
    """A passing test and an asserted requirement are separate pieces of evidence."""
    unique(requirements)
    unique(tests)
    state = {"requirements": list(requirements), "tests": list(tests)}
    results = []
    for r in requirements:
        candidates = [t for t in tests if r["id"] in t.get("requirement_ids", [])]
        links = []
        for t in candidates:
            supplied = {"requirement": r, "test": t}
            try:
                probability = session.nouls(supplied, {"covers":
                    "Do this test's actual assertions check this requirement?"})["covers"]
            except (ValueError, TypeError, KeyError, OSError):
                probability = None
            links.append({"test_id": t["id"], "result": t.get("result", "not_run"),
                          "assertion_relevance": probability, "execution_ref": t.get("execution_ref"),
                          "test_hash": fingerprint(t.get("source", ""))})
        results.append({"requirement_id": r["id"], "links": links,
                        "status": "missing_test" if not links else "review_evidence",
                        "coverage_certified": False})
    return propose("requirements.trace@1", state, results)


def classify_feedback(records: Sequence[Mapping[str, Any]], session: DecisionSession) -> Proposal:
    unique(records)
    rows, totals = [], {k: 0 for k in ("positive", "negative", "neutral", "mixed", "unresolved")}
    for r in records:
        try:
            sentiment = session.choice(r, {
                "positive": "Positive feedback", "negative": "Negative feedback",
                "neutral": "Neutral or factual question", "mixed": "Both positive and negative"}, "sentiment")
            labels = session.nouls(r, {"help": "Does this request help?",
                                     "bug": "Does this report a malfunction?"})
        except (ValueError, TypeError, KeyError, OSError):
            sentiment, labels = "unresolved", {}
        totals[sentiment] += 1
        rows.append({"id": r["id"], "source_hash": fingerprint(r),
                     "sentiment": sentiment, "signals": labels})
    return propose("feedback.classify@1", records, {"rows": rows, "totals": totals})
