import copy
import json

import pytest

from tiberium_ai.compact_memory import CompactMemory, MemoryContext, MemoryFact, MemoryLimits
from tiberium_ai.verification import VerifierRegistry, hash_input


def memory(source, *, limits=None, verifier=lambda value: True):
    registry = VerifierRegistry()
    registry.register("facts", "1", verifier)
    return CompactMemory(source, registry, limits=limits)


def fact(entity="project-a", key="budget", version="v1", value=0, verifier_id="facts"):
    return MemoryFact(entity, key, version, value, verifier_id, "1")


def test_exact_retrieval_separates_homonyms_and_keeps_values_out_of_checkpoint():
    values = {"project-a": {"name": "Alex", "budget": 0},
              "project-b": {"name": "Alex", "budget": False}}
    m = memory(lambda e, k, v: fact(e, k, v, values[e][k]))
    a = m.context("project-a", "v1", ["name", "budget"])
    b = m.context("project-b", "v1", ["name", "budget"])
    assert [f["value"] for f in a.to_record()["facts"]] == ["Alex", 0]
    assert [f["value"] for f in b.to_record()["facts"]] == ["Alex", False]
    assert a.fingerprint != b.fingerprint
    assert "Alex" not in json.dumps(m.checkpoint())
    assert all("value" not in ref for e in m.checkpoint()["entities"] for ref in e["references"])


@pytest.mark.parametrize("returned,reason", [
    (None, "source_missing"),
    (fact(entity="project-b"), "scope_or_version_mismatch"),
    (fact(version="v2"), "scope_or_version_mismatch"),
    (fact(verifier_id="unknown"), "unregistered_verifier"),
])
def test_unresolved_facts_are_explicit_and_never_filled_from_old_state(returned, reason):
    source = [fact()]
    m = memory(lambda e, k, v: source[0])
    assert m.context("project-a", "v1", ["budget"]).complete
    source[0] = returned
    context = m.context("project-a", "v1", ["budget"])
    assert not context.complete
    assert context.to_record()["facts"] == []
    assert context.to_record()["missing"] == [{"key": "budget", "reason": reason}]


def test_failed_and_mutating_verifiers_do_not_release_facts():
    rejected = memory(lambda e, k, v: fact(), verifier=lambda value: False)
    assert rejected.context("project-a", "v1", ["budget"]).to_record()["missing"][0]["reason"] == "verification_rejected"

    def mutate(payload):
        payload["value"] = 99
        return True

    m = memory(lambda e, k, v: fact(), verifier=mutate)
    assert m.context("project-a", "v1", ["budget"]).to_record()["missing"][0]["reason"] == "verifier_mutated_input"
    assert m.checkpoint()["entities"][0]["references"] == []


def test_source_failure_abstains_without_exposing_exception_message():
    def fail(*args):
        raise RuntimeError("private source details")

    context = memory(fail).context("project-a", "v1", ["budget"])
    assert context.to_record()["missing"] == [{"key": "budget", "reason": "source_error:RuntimeError"}]


def test_new_versions_invalidate_old_pins_and_same_version_mutation_is_rejected():
    value = [10]
    m = memory(lambda e, k, v: fact(e, k, v, value[0]))
    assert m.context("project-a", "v1", ["budget"]).complete
    value[0] = 20
    stale = m.context("project-a", "v1", ["budget"])
    assert stale.to_record()["missing"][0]["reason"] == "reference_changed_without_version"
    fresh = m.context("project-a", "v2", ["budget"])
    assert fresh.to_record()["facts"][0]["value"] == 20
    assert m.checkpoint()["entities"][0]["source_version"] == "v2"


def test_checkpoint_retrieval_reverifies_source_and_restore_is_atomic():
    calls = []
    values = [10]
    original = memory(lambda e, k, v: fact(e, k, v, values[0]))
    original.context("project-a", "v1", ["budget"])
    checkpoint = original.checkpoint()

    restored = memory(lambda e, k, v: fact(e, k, v, values[0]),
                      verifier=lambda p: calls.append(p["value"]) is None)
    restored.restore(checkpoint)
    assert calls == []
    assert restored.context("project-a", "v1", ["budget"]).complete
    assert calls == [10]
    values[0] = 11
    assert not restored.context("project-a", "v1", ["budget"]).complete
    before = restored.checkpoint()
    corrupted = copy.deepcopy(checkpoint)
    corrupted["entities"][0]["references"][0]["input_hash"] = "x" * 64
    corrupted["input_hash"] = hash_input({k: v for k, v in corrupted.items() if k != "input_hash"})
    with pytest.raises(ValueError, match="reference input_hash"):
        restored.restore(corrupted)
    assert restored.checkpoint() == before
    corrupted = copy.deepcopy(checkpoint)
    corrupted["entities"][0]["source_version"] = "v3"
    with pytest.raises(ValueError, match="hash mismatch"):
        restored.restore(corrupted)
    assert restored.checkpoint() == before


def test_reference_and_entity_lru_bounds_and_detached_records():
    m = memory(lambda e, k, v: fact(e, k, v, {"nested": [k]}),
               limits=MemoryLimits(max_entities=2, max_refs_per_entity=2))
    first = m.context("a", "v1", ["x", "y"])
    detached = first.to_record()
    detached["facts"][0]["value"]["nested"].append("changed")
    assert first.to_record()["facts"][0]["value"]["nested"] == ["x"]
    m.context("a", "v1", ["z"])
    assert [r["key"] for r in m.checkpoint()["entities"][0]["references"]] == ["y", "z"]
    m.context("b", "v1", ["x"])
    m.context("a", "v1", ["z"])
    m.context("c", "v1", ["x"])
    assert [e["entity_id"] for e in m.checkpoint()["entities"]] == ["a", "c"]


def test_fact_budget_abstains_and_context_overflow_does_not_commit_state():
    m = memory(lambda e, k, v: fact(e, k, v, "x" * 1000),
               limits=MemoryLimits(max_fact_bytes=100))
    assert m.context("a", "v1", ["x"]).to_record()["missing"][0]["reason"] == "fact_budget_exceeded"
    tiny = memory(lambda e, k, v: fact(e, k, v, 1),
                  limits=MemoryLimits(max_context_bytes=100))
    before = tiny.checkpoint()
    with pytest.raises(ValueError, match="max_context_bytes"):
        tiny.context("a", "v1", ["x"])
    assert tiny.checkpoint() == before


def test_invalid_requests_and_forged_context_shape_are_rejected():
    m = memory(lambda e, k, v: fact(e, k, v, 1))
    for keys in (["x", "x"], "x", [" x"], ["é" * 65]):
        with pytest.raises(ValueError):
            m.context("a", "v1", keys)
    context = m.context("a", "v1", ["x"]).to_record()
    context["facts"][0]["value"] = 2
    with pytest.raises(ValueError, match="matching verification"):
        MemoryContext(json.dumps(context))
    context = m.context("a", "v1", ["x"]).to_record()
    context["missing"].append({"key": "x", "reason": "source_missing"})
    with pytest.raises(ValueError, match="duplicate"):
        MemoryContext(json.dumps(context))


@pytest.mark.parametrize("kwargs", [{"max_entities": True}, {"max_context_bytes": 0},
                                     {"max_refs_per_entity": -1}, {"max_fact_bytes": 1.5}])
def test_limits_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        MemoryLimits(**kwargs)
