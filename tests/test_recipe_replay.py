import json

import pytest

from tiberium_ai.agent_recipes.replay import RecipeEpisode, RecipeRevision, replay_recipe_candidate
from tiberium_ai.measurement import Environment


ENV = Environment("offline-test", {"recipe-runner": "1"})


def episode(case_id, value, *, group=None, verifier=None, origin="authored"):
    return RecipeEpisode(case_id, group or case_id, "fixture:" + case_id, origin, {"value": value},
                         "expected:" + case_id, "1", verifier or (lambda output: output == value), True)


def revisions(candidate_run=None):
    return (RecipeRevision("normalize", "1", "baseline instructions", lambda _, data: data["value"]),
            RecipeRevision("normalize", "2", "candidate instructions", candidate_run or (lambda _, data: data["value"])))


def replay(*, historical=None, heldout=None, candidate_run=None):
    baseline, candidate = revisions(candidate_run)
    return replay_recipe_candidate(baseline, candidate,
             historical=historical or [episode("old", 1)], heldout=heldout or [episode("new", 2)],
             environment=ENV)


def test_retains_explicit_split_and_unknown_cost_without_promoting_fixture_success():
    result = replay()
    assert result["status"] == "ready_for_review"
    assert result["split"]["historical"] == ["old"]
    assert result["split"]["heldout"] == ["new"]
    assert result["candidate"]["source_sha256"] != result["baseline"]["source_sha256"]
    assert len(result["runs"]) == 4
    assert all(r["measurement"]["cost"] is None for r in result["runs"])
    assert result["total_cost"] is None
    assert not result["claim_allowed"] and not result["promotion_allowed"] and not result["auto_act_allowed"]
    assert result["review_required"]
    assert result["benchmark"]["claim"]["status"] == "refused"


@pytest.mark.parametrize("mode", ["group", "content", "id"])
def test_rejects_holdout_leakage_before_any_callback(mode):
    calls = []
    old = episode("old", 1, group="source-old")
    new = episode("old" if mode == "id" else "new", 1 if mode == "content" else 2,
                  group="source-old" if mode == "group" else "source-new")
    baseline, candidate = revisions(lambda *_: calls.append("called"))
    with pytest.raises(ValueError, match={"group": "groups overlap", "content": "duplicate inputs", "id": "identifiers"}[mode]):
        replay_recipe_candidate(baseline, candidate, historical=[old], heldout=[new], environment=ENV)
    assert calls == []


def test_heldout_regression_blocks_candidate_even_when_historical_case_passes():
    result = replay(candidate_run=lambda _, data: data["value"] if data["value"] == 1 else "wrong")
    assert result["status"] == "rejected"
    assert result["regressions"] == ["new"]
    assert result["rejected_cases"] == ["new"]
    assert not result["promotion_allowed"]


def test_expected_historical_failure_can_be_fixed_without_hiding_heldout_result():
    baseline = RecipeRevision("normalize", "1", "old rule", lambda _, data: 0 if data["value"] == 1 else data["value"])
    candidate = RecipeRevision("normalize", "2", "new rule", lambda _, data: data["value"])
    result = replay_recipe_candidate(baseline, candidate, historical=[episode("old", 1)],
               heldout=[episode("new", 2)], environment=ENV)
    assert result["improved_cases"] == ["old"]
    assert result["regressions"] == [] and result["status"] == "ready_for_review"


def test_failing_candidate_is_recorded_once_and_cannot_become_accepted():
    calls = []
    def fail(source, data):
        calls.append(data["value"])
        raise RuntimeError("private source details")
    result = replay(candidate_run=fail)
    assert calls == [1, 2]
    assert result["status"] == "rejected"
    assert result["unknown_cases"] == ["old", "new"]
    assert all(r["measurement"]["outcome"]["ok"] is False
               for r in result["runs"] if r["arm"] == "candidate")
    assert "private source details" not in json.dumps(result)


def test_missing_verifier_remains_unknown_instead_of_reusing_other_case_labels():
    unlabelled = RecipeEpisode("unlabelled", "unlabelled", "fixture:unlabelled", "authored",
                               {"value": 2}, "expected:old", "1", None, True)
    result = replay(heldout=[unlabelled])
    assert result["status"] == "inconclusive"
    assert result["unknown_cases"] == ["unlabelled"]


def test_revisions_receive_separate_snapshots_and_exact_instruction_text():
    original = {"value": 1, "nested": [3]}
    calls = []
    def run(source, data):
        calls.append((source, list(data["nested"])))
        data["nested"].append(9)
        return data["value"]
    baseline = RecipeRevision("normalize", "1", "baseline text", run)
    candidate = RecipeRevision("normalize", "2", "candidate text", run)
    old = RecipeEpisode("old", "a", "fixture:old", "authored", original, "v", "1", lambda out: out == 1, True)
    new = RecipeEpisode("new", "b", "fixture:new", "authored", {"value": 2, "nested": [4]}, "v2", "1", lambda out: out == 2, True)
    result = replay_recipe_candidate(baseline, candidate, historical=[old], heldout=[new], environment=ENV)
    assert calls[:2] == [("baseline text", [3]), ("candidate text", [3])]
    assert original == {"value": 1, "nested": [3]}
    assert result["status"] == "ready_for_review"
    assert "baseline text" not in json.dumps(result)
    assert '"nested"' not in json.dumps(result)


def test_invalid_or_identical_revisions_and_missing_split_are_refused():
    baseline, candidate = revisions()
    with pytest.raises(ValueError, match="identical"):
        replay_recipe_candidate(baseline, baseline, historical=[episode("old", 1)], heldout=[episode("new", 2)], environment=ENV)
    with pytest.raises(ValueError, match="nonempty"):
        replay_recipe_candidate(baseline, candidate, historical=[], heldout=[episode("new", 2)], environment=ENV)
    other = RecipeRevision("other", "2", "other text", lambda *_: 1)
    with pytest.raises(ValueError, match="same recipe"):
        replay_recipe_candidate(baseline, other, historical=[episode("old", 1)], heldout=[episode("new", 2)], environment=ENV)


def test_nonfinite_inputs_and_oversized_results_are_not_accepted():
    with pytest.raises(ValueError):
        episode("bad", float("nan"))
    with pytest.raises(TypeError, match="keys must be strings"):
        episode("bad-key", {1: "value", "1": "different"})
    result = replay(candidate_run=lambda *_: "x" * 262145)
    assert result["status"] == "rejected"
    assert result["unknown_cases"] == ["old", "new"]


def test_unreviewed_grouping_cannot_start_replay():
    unreviewed = RecipeEpisode("new", "b", "fixture:new", "authored", 2, "v", "1", lambda _: True)
    with pytest.raises(ValueError, match="explicitly reviewed"):
        replay(heldout=[unreviewed])


def test_invalid_verifier_result_is_recorded_as_unknown_not_success():
    result = replay(heldout=[episode("new", 2, verifier=lambda _: 1)])
    assert result["status"] == "inconclusive"
    verdict = next(r["verification"] for r in result["runs"] if r["episode_id"] == "new")
    assert verdict["verdict"] is None and verdict["detail_code"] == "verifier_error:TypeError"
