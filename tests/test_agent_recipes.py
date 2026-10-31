import json
from pathlib import Path

import pytest

from tiberium_ai.agent_recipes import (
    BrowserRunner, BrowserSnapshot, Control, DecisionSession, SkillCatalog,
    audit_skills, check_rules, classify_feedback, compact_context, rank_files,
    select_skill, trace_requirements, triage_review,
)
from tiberium_ai.agent_recipes.benchmark import PhaseResult, compare_pipelines, measure_pipeline
from tiberium_ai.agent_recipes.cache import CachedBackend
from tiberium_ai.agent_recipes.core import fingerprint
from tiberium_ai.agent_recipes.providers import TypeSafeBackend
from tiberium_ai.agent_recipes.__main__ import main
from tiberium_ai.reflex import InjectedReflexBackend, ReflexKind, ReflexQuestion


def noul(p):
    return {"noul": p, "probabilities": {"false": 1 - p, "true": p}}


def choice(selected, options, confidence=0.96):
    return {"choice": selected, "confidence": confidence,
            "probabilities": {k: 1.0 if k == selected else 0.0 for k in options}}


def session(answers):
    return DecisionSession(InjectedReflexBackend(answers, latin_only=False))


def skill(id="s"):
    return {"id": id, "name": "debug", "description": "debug Python errors",
            "content_hash": "content"}


def test_index_invalidation_preserves_usage_and_detects_removal(tmp_path):
    root = tmp_path / "skills"
    source = root / "debug" / "SKILL.md"
    source.parent.mkdir(parents=True)
    source.write_text("---\nname: debug\ndescription: >\n  debug Python\n  errors\n---\nbody", encoding="utf-8")
    with SkillCatalog(tmp_path / "catalog.db") as cat:
        assert cat.sync(root, at="2026-10-01T12:00:00Z")["added"] == 1
        row = cat.rows()[0]
        assert row["description"] == "debug Python errors"
        assert cat.record_use(row["id"], event_id="e", at="2026-10-01T14:00:00+02:00", outcome="success")
        assert not cat.record_use(row["id"], event_id="e", at="2026-10-01T12:00:00Z", outcome="success")
        with pytest.raises(ValueError, match="different content"):
            cat.record_use(row["id"], event_id="e", at="2026-10-01T12:00:00Z", outcome="failure")
        assert cat.sync(root, at="2026-10-02T00:00:00Z")["unchanged"] == 1
        assert cat.rows()[0]["indexed_at"] == row["indexed_at"]
        source.write_text(source.read_text() + " modified", encoding="utf-8")
        assert cat.sync(root, at="2026-10-02T00:00:00Z")["changed"] == 1
        assert cat.rows()[0]["uses"] == 1
        assert cat.shortlist("debug Python", eligible_ids=[] ) == []
        source.unlink()
        assert cat.sync(root, at="2026-10-02T00:00:00Z")["removed"] == 1
        assert cat.rows() == []


def test_failed_sync_does_not_mark_previous_skills_removed(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    source = root / "SKILL.md"
    source.write_text("---\nname: good\n---\nworking", encoding="utf-8")
    with SkillCatalog(tmp_path / "catalog.db") as cat:
        cat.sync(root, at="2026-10-01T00:00:00Z")
        source.write_text("---\nname: malformed", encoding="utf-8")
        with pytest.raises(ValueError):
            cat.sync(root, at="2026-10-02T00:00:00Z")
        assert cat.rows()[0]["name"] == "good"


def test_explicit_skill_never_calls_model_and_cannot_bypass_eligibility():
    s = DecisionSession()
    result = select_skill("question", [skill()], s, explicit_id="s")
    assert result.data == "s" and s.calls == []
    assert select_skill("question", [], s, explicit_id="s").status == "abstained"


def test_skill_none_uncertainty_and_invalid_answer():
    assert select_skill("hello", [skill()], session({"choice": choice("none", ["s", "none"])})).data is None
    assert select_skill("debug", [skill()], session({"choice": choice("s", ["s", "none"], .2)})).status == "abstained"
    result = select_skill("debug", [skill()], session({"choice": choice("invented", ["s", "none"])}))
    assert result.status == "abstained" and not result.auto_act_allowed


def test_audit_never_deletes_unused_or_duplicate_skills():
    result = audit_skills([skill("a"), skill("b")])
    assert all(r["recommendation"] == "review" and not r["delete_allowed"] for r in result.data)


def test_file_ranking_batches_and_incomplete_scores_do_not_hide_fallback():
    files = [{"id": f"f{i}", "excerpt": "source"} for i in range(21)]
    s = session({f"r{i}": noul(.95 if i == 0 else .1) for i in range(20)})
    result = rank_files("source", files, s)
    assert result.status == "proposed" and len(s.calls) == 2
    assert len(result.data) == 5
    result = rank_files("source", files, session({"r0": noul(.99)}))
    assert result.status == "abstained" and result.data["fallback"] == "expand_lexical_search"


def test_compaction_is_verbatim_reversible_and_retains_uncertainty():
    blocks = [{"id": "instruction", "kind": "instruction", "text": "keep me"},
              {"id": "old", "kind": "tool", "text": "stale output"}]
    result = compact_context(blocks, session({"relevant": noul(.01)}), query="task", target_chars=7)
    assert result.data["kept"] == blocks[:1]
    assert result.data["recall"]["old"]["block"] == blocks[1]
    uncertain = compact_context(blocks, DecisionSession(), query="task", target_chars=7)
    assert uncertain.data["kept"] == blocks and not uncertain.data["within_target"]


def test_sensitive_review_and_semantic_shadow_cannot_reduce_real_review():
    s = DecisionSession()
    assert triage_review([{"path": "auth.py", "diff": "..."}], s).data["depth"] == "full"
    assert s.calls == []
    from tiberium_ai.agent_recipes.recipes import REVIEW_QUESTIONS
    s = session({k: noul(.01) for k in REVIEW_QUESTIONS})
    result = triage_review([{"path": "format.py", "diff": "..."}], s)
    assert result.data["depth"] == "quick_candidate"
    assert result.data["effective_depth"] == "full" and not result.auto_act_allowed


def test_rules_block_syntax_and_pattern_and_escalate_unknown_semantics():
    assert check_rules({"path": "x.py", "after": "def broken("}, [], DecisionSession()).data["verdict"] == "block"
    rule = {"id": "r", "kind": "forbid_regex", "pattern": "eval\\(", "glob": "*.py"}
    assert check_rules({"path": "x.py", "after": "eval(x)"}, [rule], DecisionSession()).data["verdict"] == "block"
    semantic = {"id": "s", "kind": "semantic", "instructions": "no access bypass"}
    assert check_rules({"path": "x.py", "after": "print(1)"}, [semantic], DecisionSession()).data["verdict"] == "review"


def test_requirement_link_is_not_a_coverage_certificate():
    result = trace_requirements([{"id": "r", "text": "reject guest"}],
            [{"id": "t", "requirement_ids": ["r"], "result": "passed", "source": "assert True"}],
            session({"covers": noul(.01)}))
    assert result.data[0]["links"][0]["assertion_relevance"] == .01
    assert not result.data[0]["coverage_certified"]


def test_feedback_totals_include_unresolved_and_duplicate_ids_rejected():
    result = classify_feedback([{"id": "1", "text": "good"}, {"id": "2", "text": "bad"}], DecisionSession())
    assert result.data["totals"]["unresolved"] == 2
    assert sum(result.data["totals"].values()) == 2
    with pytest.raises(ValueError, match="duplicate"):
        classify_feedback([{"id": "1"}, {"id": "1"}], DecisionSession())


def test_call_deadline_and_state_budgets_fail_before_or_after_call():
    now = [0.]
    class Backend:
        latin_only = False
        def evaluate(self, state, questions):
            now[0] = 10
            return {"q": noul(.9)}
    s = DecisionSession(Backend(), clock=lambda: now[0], deadline_ms=1)
    with pytest.raises(ValueError, match="deadline"):
        s.nouls("state", {"q": "yes?"})
    assert len(s.calls) == 1 and s.calls[0]["status"] == "error"
    s = session({"q": noul(.9)})
    s.max_calls = 1
    s.nouls("state", {"q": "yes?"})
    with pytest.raises(ValueError, match="call_budget"):
        s.nouls("state", {"q": "yes?"})
    s = session({"q": noul(.9)})
    s.max_state_bytes = 1
    with pytest.raises(ValueError, match="state_budget"):
        s.nouls("state", {"q": "yes?"})
    assert not s.calls


def test_browser_has_no_implicit_execution_and_does_not_trust_done():
    snapshot = BrowserSnapshot("v1", "/", (Control("login", "Login"),))
    actions = []
    runner = BrowserRunner(session({"choice": choice("c0", ["c0", "done", "blocked"])}))
    result = runner.run("login", observe=lambda: snapshot, verify_goal=lambda _: False,
                        execute=lambda *a: actions.append(a))
    assert result.reason == "host_authorization_required" and actions == []
    runner = BrowserRunner(session({"choice": choice("done", ["c0", "done", "blocked"])}))
    result = runner.run("login", observe=lambda: snapshot, verify_goal=lambda _: False,
                        execute=lambda *a: actions.append(a))
    assert result.reason == "goal_not_verified" and actions == []


def test_browser_freshness_verified_effect_and_loop_guard():
    first = BrowserSnapshot("v1", "/", (Control("login", "Login"),))
    second = BrowserSnapshot("v2", "/account", ())
    observations = iter([first, second])
    s = session({"choice": choice("c0", ["c0", "done", "blocked"])})
    actions = []
    result = BrowserRunner(s).run("login", observe=lambda: next(observations), verify_goal=lambda _: False,
            execute=lambda *a: actions.append(a), approve=lambda *_: True)
    assert result.reason == "stale_snapshot" and actions == []
    current = [first]
    def execute(control, version):
        assert version == current[0].version
        current[0] = second
    result = BrowserRunner(session({"choice": choice("c0", ["c0", "done", "blocked"])})).run(
        "login", observe=lambda: current[0], verify_goal=lambda s: s.url == "/account",
        execute=execute, approve=lambda *_: True)
    assert result.status == "verified" and len(result.data["history"]) == 1
    result = BrowserRunner(session({"choice": choice("c0", ["c0", "done", "blocked"])})).run(
        "login", observe=lambda: first, verify_goal=lambda _: False,
        execute=lambda *_: None, approve=lambda *_: True)
    assert result.reason == "loop_detected"


def test_typesafe_normalizes_noul_and_score_and_observes_usage_without_network():
    seen = []
    def post(payload, key, timeout):
        seen.append(payload)
        return {"model": "jev-1.13.0", "usage": {"input_tokens": 9, "output_tokens": 2},
                "answers": {"n": {"type": "noul", "noul": .7},
                "s": {"type": "score", "score": .8, "probabilities": {"0": .2, "1": .8}, "confidence": .8}}}
    backend = TypeSafeBackend(api_key="fake", model="jev-1.13.0", post=post)
    s = DecisionSession(backend)
    answers = s.evaluate("state", [ReflexQuestion("n", ReflexKind.NOUL, "yes?"),
                     ReflexQuestion("s", ReflexKind.SCORE, "rate", ("low", "high"))])
    assert answers["n"].confidence is None
    assert answers["s"].probabilities == {"low": .2, "high": .8}
    assert s.calls[0]["usage"]["input_tokens"] == 9
    assert s.calls[0]["usage"]["billed_cost"] is None
    assert "fake" not in json.dumps(s.calls)
    with pytest.raises(ValueError, match="call_budget"):
        backend.evaluate("state", [])
    assert len(seen) == 1


def test_transport_refuses_network_by_default():
    backend = TypeSafeBackend(api_key="fake", model="jev-1.13.0")
    with pytest.raises(ValueError, match="network_not_authorized"):
        backend.evaluate("private", [])
    assert backend.calls == 0


def test_cache_reuses_only_same_input_questions_and_backend(tmp_path):
    class Counting:
        latin_only = False
        calls = 0
        def evaluate(self, state, questions):
            self.calls += 1
            return {"n": noul(.8)}
    backend = Counting()
    cached = CachedBackend(backend, tmp_path / "cache.db", identity="counter/1")
    q = [ReflexQuestion("n", ReflexKind.NOUL, "relevant?")]
    try:
        assert cached.evaluate("a", q) == cached.evaluate("a", q)
        assert backend.calls == 1 and cached.last_usage["origin"] == "cache"
        cached.evaluate("b", q)
        assert backend.calls == 2
        cached.evaluate("b", [ReflexQuestion("n", ReflexKind.NOUL, "different?")])
        assert backend.calls == 3
    finally:
        cached.close()


def test_pipeline_records_full_phases_and_unknown_cost_prevents_gain_claim():
    phases = {"collect": lambda v: PhaseResult(v + 1, cost=0),
              "prepare": lambda v: PhaseResult(v * 2, cost=0),
              "decide": lambda v: PhaseResult(v, cost=None)}
    base = measure_pipeline("c", "baseline", 2, phases, lambda v: v == 6)
    candidate = measure_pipeline("c", "candidate", 2, phases, lambda v: v == 6)
    assert base["verified"] and len(base["phases"]) == 3
    comparison = compare_pipelines(base, candidate)
    assert "unknown_cost" in comparison["reasons"] and not comparison["claim_allowed"]
    candidate["input_hash"] = "different"
    assert "unpaired_inputs" in compare_pipelines(base, candidate)["reasons"]


def test_rules_cli_emits_machine_readable_hook_result(tmp_path, capsys):
    source = tmp_path / "input.json"
    source.write_text(json.dumps({"change": {"path": "x.py", "after": "def broken("}, "rules": []}))
    assert main(["rules", "--input", str(source), "--enforce-rules"]) == 10
    result = json.loads(capsys.readouterr().out)
    assert result["result"]["data"]["verdict"] == "block"


@pytest.mark.parametrize("threshold", [0, .5, float("nan"), True])
def test_invalid_session_thresholds(threshold):
    with pytest.raises(ValueError):
        DecisionSession(threshold=threshold)


def test_structural_verifier_rejects_dropped_instruction_and_forged_totals():
    import copy
    from tiberium_ai.agent_recipes.integration import verify_structure
    blocks = [{"id": "goal", "kind": "goal", "text": "keep"},
              {"id": "old", "kind": "tool", "text": "old output"}]
    result = compact_context(blocks, session({"relevant": noul(.01)}), query="task", target_chars=4)
    state = {"query": "task", "blocks": blocks, "target_chars": 4}
    payload = {"state": state, "result": result.to_dict()}
    assert verify_structure(payload)
    forged = copy.deepcopy(payload)
    forged["result"]["data"]["kept"][0]["text"] = "rewritten"
    assert not verify_structure(forged)
    records = [{"id": "f", "text": "hello"}]
    result = classify_feedback(records, DecisionSession())
    payload = {"state": records, "result": result.to_dict()}
    assert verify_structure(payload)
    payload["result"]["data"]["totals"]["unresolved"] = 0
    assert not verify_structure(payload)


def test_browser_nonboolean_authority_never_executes():
    snapshot = BrowserSnapshot("v1", "/", (Control("login", "Login"),))
    actions = []
    result = BrowserRunner(session({"choice": choice("c0", ["c0", "done", "blocked"])})).run(
        "login", observe=lambda: snapshot, verify_goal=lambda _: "false",
        execute=lambda *a: actions.append(a), approve=lambda *_: "false")
    assert not actions and result.reason == "host_authorization_required"


def test_backend_version_mismatch_cannot_be_accepted_or_cached(tmp_path):
    backend = TypeSafeBackend(api_key="fake", model="jev-1.13.0", post=lambda *_: {
        "model": "different", "usage": {"input_tokens": 1, "output_tokens": 1},
        "answers": {"q": {"type": "noul", "noul": .9}}})
    cached = CachedBackend(backend, tmp_path / "cache.db", identity="typesafe/jev-1.13.0")
    try:
        with pytest.raises(ValueError, match="pinned"):
            cached.evaluate("state", [ReflexQuestion("q", ReflexKind.NOUL, "yes?")])
        assert cached.connection.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 0
    finally:
        cached.close()


def test_offline_walkthrough_has_all_nine_recipes_without_provider_calls():
    import importlib.util
    script = Path(__file__).resolve().parents[1] / "examples" / "agent_recipes_suite.py"
    spec = importlib.util.spec_from_file_location("agent_recipes_suite", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    report = module.run_suite()
    assert report["origin"] == "fixture" and len(report["recipes"]) == 9
    assert report["index"]["second"]["unchanged"] == 1
    assert not report["saving_claim_allowed"] and not report["semantic_quality_measured"]


def test_manifest_loads_in_existing_registry_but_has_no_calibrated_confidence():
    from tiberium_ai.agent_recipes.integration import (
        CAPABILITIES, recipe_manifest, register_recipe_verifier,
    )
    from tiberium_ai.registry import RouteRegistry
    from tiberium_ai.verification import VerifierRegistry
    verifiers = VerifierRegistry()
    register_recipe_verifier(verifiers)
    registry = RouteRegistry.from_manifest(recipe_manifest(), known_capabilities=CAPABILITIES, verifiers=verifiers)
    assert len(registry.routes) == 9
    assert all(r.confidence is None and r.estimated_cost is None for r in registry.routes)
