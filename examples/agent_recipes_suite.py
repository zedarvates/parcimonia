"""Offline integration walkthrough. Fixture results are not semantic quality measurements."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.agent_recipes import (
    BrowserRunner, BrowserSnapshot, Control, DecisionSession, SkillCatalog,
    audit_skills, check_rules, classify_feedback, compact_context, rank_files,
    select_skill, trace_requirements, triage_review,
)
from tiberium_ai.agent_recipes.benchmark import PhaseResult, measure_pipeline
from tiberium_ai.reflex import InjectedReflexBackend


def boolean(p):
    return {"noul": p, "probabilities": {"false": 1 - p, "true": p}}


def pick(key, options):
    return {"choice": key, "confidence": .99,
            "probabilities": {o: float(o == key) for o in options}}


def decision(answers):
    return DecisionSession(InjectedReflexBackend(answers, latin_only=False))


def run_suite():
    with TemporaryDirectory() as tmp:
        root = Path(tmp) / "skills"
        source = root / "debug" / "SKILL.md"
        source.parent.mkdir(parents=True)
        source.write_text("---\nname: debug\ndescription: Debug Python errors\n---\nInspect a traceback.", encoding="utf-8")
        with SkillCatalog(Path(tmp) / "skills.db") as catalog:
            first = catalog.sync(root, at="2026-10-02T00:00:00Z")
            second = catalog.sync(root, at="2026-10-02T01:00:00Z")
            rows = catalog.rows()
            id = rows[0]["id"]
            catalog.record_use(id, event_id="example-1", at="2026-10-02T02:00:00Z", outcome="success")
            selected = select_skill("Debug Python errors", catalog.shortlist("Debug Python errors"),
                                    decision({"choice": pick(id, [id, "none"])}))
            audit = audit_skills(catalog.rows())
        files = [{"id": "server.py", "content_hash": "fixture", "excerpt": "def handle_error(): ..."}]
        ranking = rank_files("handle error", files, decision({"r0": boolean(.99)}))
        compact = compact_context([
            {"id": "goal", "kind": "goal", "text": "Fix the bug"},
            {"id": "old", "kind": "tool", "text": "old unrelated output"}],
            decision({"relevant": boolean(.01)}), query="Fix the bug", target_chars=11)
        review = triage_review([{"path": "permissions.py", "diff": "..."}], DecisionSession())
        rules = check_rules({"path": "test.py", "after": "eval(user_input)"},
            [{"id": "no-eval", "kind": "forbid_regex", "pattern": "eval\\("}], DecisionSession())
        requirements = trace_requirements([{"id": "guest", "text": "Guest must be denied"}],
            [{"id": "test_guest", "requirement_ids": ["guest"], "source": "assert status == 403",
              "result": "not_run"}], decision({"covers": boolean(.99)}))
        feedback = classify_feedback([{"id": "c1", "text": "Great, but crashes"}], decision({
            "sentiment": pick("mixed", ["positive", "negative", "neutral", "mixed"]),
            "help": boolean(.1), "bug": boolean(.99)}))
        initial = BrowserSnapshot("1", "/login", (Control("open", "Open account"),))
        browser = BrowserRunner(decision({"choice": pick("c0", ["c0", "done", "blocked"])})).run(
            "Open account", observe=lambda: initial, verify_goal=lambda _: False, execute=lambda *_: None)
        measurement = measure_pipeline("fixture-index", "local", "Debug Python errors", {
            "collect": lambda v: PhaseResult(v, cost=0),
            "prepare": lambda v: PhaseResult({"query": v, "candidates": rows}, cost=0),
            "decide": lambda v: PhaseResult(selected.to_dict(), cost=0)},
            lambda v: v["data"] == id)
        return {"origin": "fixture", "semantic_quality_measured": False, "saving_claim_allowed": False,
                "index": {"first": first, "second": second},
                "recipes": [r.to_dict() for r in (selected, audit, ranking, compact, review,
                                                  rules, requirements, feedback, browser)],
                "measurement": measurement}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = run_suite()
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if args.out:
        with args.out.open("x", encoding="utf-8") as target:
            target.write(encoded + "\n")
    else:
        print(encoded)
