from copy import deepcopy

import pytest

from tiberium_ai.decision_gym import (
    fingerprint, generate_episodes, propose, replay, run_benchmark, verify_result,
)


def test_corpus_reproducible_and_groups_never_cross_splits():
    episodes = generate_episodes()
    assert len(episodes) == 300
    assert fingerprint(episodes) == fingerprint(generate_episodes())
    assert fingerprint(episodes) != fingerprint(generate_episodes(21))
    groups = {}
    for episode in episodes:
        groups.setdefault(episode["group_id"], set()).add(episode["split"])
    assert all(len(splits) == 1 for splits in groups.values())
    assert [sum(e["split"] == s for e in episodes) for s in ("train", "dev", "test")] == [150, 78, 72]


def test_verifier_rejects_wrong_values_boolean_and_malformed_results():
    doc = {"rows": [{"item": "a", "value": -2}, {"item": "b", "value": 5}]}
    assert verify_result(doc, {"operation": "sum"}, 3)
    for invalid in (True, "3", 4, None, {"value": 3}):
        assert not verify_result(doc, {"operation": "sum"}, invalid)
    assert verify_result(doc, {"operation": "lookup", "item": "a"}, -2)


@pytest.mark.parametrize("arm", ["rules", "rules_retrieval"])
def test_all_episodes_have_expected_terminal_outcome_and_bounded_calls(arm):
    for episode in generate_episodes():
        original = deepcopy(episode)
        record = replay(episode, arm)
        expected = {"budget": "budget_exhausted", "unavailable": "escalate"}.get(episode["scenario"], "verified")
        assert record["status"] == expected
        assert episode == original
        assert len(record["trace"]) <= 4
        assert record["auto_act_allowed"] is False
        for previous, current in zip(record["trace"], record["trace"][1:]):
            assert previous["next_state_hash"] == current["input_hash"]


def test_recovery_changes_state_and_rejects_stale_cache():
    episodes = generate_episodes()
    stale = next(e for e in episodes if e["scenario"] == "stale")
    trace = replay(stale, "rules_retrieval")["trace"]
    assert trace[0]["route"] == "repair_context"
    assert trace[0]["input_hash"] != trace[0]["next_state_hash"]
    bad = next(e for e in episodes if e["scenario"] == "malformed")
    trace = replay(bad, "rules_retrieval")["trace"]
    assert trace[0]["verified"] is False
    assert trace[1]["input"]["previous_error"] == "invalid_result"
    assert trace[1]["verified"] is True
    replaced = next(e for e in episodes if e["scenario"] == "replaced" and e["initial_state"]["objective"]["operation"] == "lookup")
    assert propose(replaced["initial_state"], "rules_retrieval") == "deterministic"


def test_report_keeps_unknown_costs_and_unexecuted_models_explicit():
    report = run_benchmark(generate_episodes())
    assert report["data_origin"] == "fixture"
    assert report["promotion"] == "inconclusive"
    for name in ("jev", "sft", "unadapted_model", "existing_signature_cascade"):
        assert report["arms"][name]["status"] == "not_run"
        assert "records" not in report["arms"][name]
    for record in report["arms"]["rules"]["records"]:
        for step in record["trace"]:
            assert step["money"] is None and step["energy"] is None
            assert step["wall_seconds"] >= 0
            assert "oracle_document" not in step["input"]
