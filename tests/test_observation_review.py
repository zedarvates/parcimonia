"""Behavior of caller-reported state review; no real environment is certified."""
from copy import deepcopy
import json
import unittest

from tiberium_ai.observation_review import review_observations


NOW = 1_000.0


def requirement(identifier="connected", **changes):
    result = {"id": identifier, "source_id": "server", "source_revision": "build-1",
              "input_sha256": "a" * 64, "verifier_id": "connection", "verifier_version": "1",
              "max_age_seconds": 60}
    result.update(changes)
    return result


def observation(identifier="obs-1", **changes):
    result = {"id": identifier, "requirement_id": "connected", "task_id": "reconnect",
              "task_revision": "attempt-1", "source_id": "server", "source_revision": "build-1",
              "input_sha256": "a" * 64, "verifier_id": "connection", "verifier_version": "1",
              "observed_at": NOW - 1, "outcome": "pass"}
    result.update(changes)
    return result


def request(**changes):
    result = {"task_id": "reconnect", "task_revision": "attempt-1",
              "requirements": [requirement()], "observations": [observation()], "probes": []}
    result.update(changes)
    return result


def probe(identifier="read-server", **changes):
    result = {"id": identifier, "requirement_ids": ["connected"], "estimated_latency_ms": 2}
    result.update(changes)
    return result


class ObservationReviewTests(unittest.TestCase):
    def review(self, value):
        return review_observations(value, now=NOW)

    def test_current_pass_is_ready_without_authorization(self):
        value = request()
        original = deepcopy(value)
        result = self.review(value)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["requirements"][0]["state"], "pass")
        self.assertFalse(result["auto_act_allowed"])
        self.assertEqual(result["evidence_trust"], "host_reported_not_independently_attested")
        self.assertEqual(value, original)
        self.assertEqual(json.loads(json.dumps(result)), result)

    def test_freshness_boundary_and_zero_max_age(self):
        for limit, observed_at, state in [(60, NOW - 60, "pass"),
                                           (60, NOW - 60.01, "stale"),
                                           (0, NOW, "pass"), (0, NOW - 0.01, "stale")]:
            with self.subTest(limit=limit, observed_at=observed_at):
                result = self.review(request(requirements=[requirement(max_age_seconds=limit)],
                                             observations=[observation(observed_at=observed_at)]))
                self.assertEqual(result["requirements"][0]["state"], state)
                if state == "stale":
                    self.assertEqual(result["rejected"][0]["reasons"], ["observation_stale"])

    def test_newer_failure_and_unknown_replace_earlier_success(self):
        for outcome, status in [("fail", "blocked"), ("unknown", "needs_observation")]:
            with self.subTest(outcome=outcome):
                result = self.review(request(observations=[observation("older", observed_at=NOW - 2),
                                                          observation("latest", outcome=outcome)]))
                self.assertEqual(result["status"], status)
                row = result["requirements"][0]
                self.assertEqual(row["state"], outcome)
                self.assertEqual(row["observation_ids"], ["latest"])
                self.assertEqual(row["considered_observation_ids"], ["latest", "older"])

    def test_large_mixed_numeric_dates_do_not_round_stale_evidence_to_current(self):
        for max_age, expected in [(0, "stale"), (0.5, "stale"), (1, "pass")]:
            with self.subTest(max_age=max_age):
                result = review_observations(request(
                    requirements=[requirement(max_age_seconds=max_age)],
                    observations=[observation(observed_at=10 ** 18 - 1)]),
                    now=float(10 ** 18))
                self.assertEqual(result["requirements"][0]["state"], expected)
                self.assertEqual(result["status"],
                                 "ready" if expected == "pass" else "needs_observation")

    def test_tied_latest_outcomes_conflict_regardless_of_input_order(self):
        observations = [observation("pass"), observation("fail", outcome="fail")]
        result = self.review(request(observations=observations))
        self.assertEqual(result["status"], "needs_observation")
        self.assertEqual(result["requirements"][0]["state"], "conflict")
        self.assertEqual(result, self.review(request(observations=list(reversed(observations)))))

    def test_same_latest_outcome_is_not_a_conflict(self):
        result = self.review(request(observations=[observation("b"), observation("a")]))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["requirements"][0]["observation_ids"], ["a", "b"])

    def test_identity_mismatches_never_supply_current_evidence(self):
        for field, value in [("task_id", "other"), ("task_revision", "attempt-2"),
                             ("source_id", "other"), ("source_revision", "build-2"),
                             ("input_sha256", "b" * 64), ("verifier_id", "other"),
                             ("verifier_version", "2")]:
            with self.subTest(field=field):
                result = self.review(request(observations=[observation(**{field: value})]))
                self.assertEqual(result["status"], "needs_observation")
                self.assertEqual(result["requirements"][0]["state"], "missing")
                self.assertIn(field + "_mismatch", result["rejected"][0]["reasons"])

    def test_unknown_requirement_and_future_reports_are_explicit_rejections(self):
        result = self.review(request(observations=[
            observation("unknown", requirement_id="not-required"),
            observation("future", observed_at=NOW + 1),
            observation("valid"),
        ]))
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["rejected"], [
            {"id": "future", "requirement_id": "connected", "reasons": ["observation_future"]},
            {"id": "unknown", "requirement_id": "not-required", "reasons": ["requirement_unknown"]},
        ])

    def test_incompatible_old_report_does_not_become_stale_evidence(self):
        result = self.review(request(observations=[observation(source_revision="old", observed_at=1)]))
        self.assertEqual(result["requirements"][0]["state"], "missing")
        self.assertEqual(result["rejected"][0]["reasons"],
                         ["source_revision_mismatch", "observation_stale"])

    def test_all_requirements_need_current_pass_and_failure_blocks(self):
        base = request(requirements=[requirement(), requirement("spawned")])
        self.assertEqual(self.review(base)["status"], "needs_observation")
        base["observations"].append(observation("spawn", requirement_id="spawned", outcome="fail"))
        self.assertEqual(self.review(base)["status"], "blocked")

    def test_probe_coverage_ignores_failed_and_already_passed_requirements(self):
        value = request(requirements=[requirement(), requirement("spawned"), requirement("moved")],
                        observations=[observation(outcome="fail")], probes=[
                            probe("failed-only"),
                            probe("one-fast", requirement_ids=["spawned"], estimated_latency_ms=0),
                            probe("two", requirement_ids=["connected", "spawned", "moved"],
                                  estimated_latency_ms=None),
                        ])
        result = self.review(value)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["next_probe"], {"id": "two", "requirement_ids": ["moved", "spawned"],
                                              "coverage_count": 2, "estimated_latency_ms": None})
        self.assertIsNone(self.review(request(probes=[probe()]))["next_probe"])

    def test_probe_ties_prefer_known_latency_then_lower_latency_then_id(self):
        candidates = [probe("unknown", estimated_latency_ms=None), probe("slow", estimated_latency_ms=5),
                      probe("b", estimated_latency_ms=2), probe("a", estimated_latency_ms=2)]
        value = request(observations=[], probes=candidates)
        self.assertEqual(self.review(value)["next_probe"]["id"], "a")
        value["probes"].reverse()
        self.assertEqual(self.review(value)["next_probe"]["id"], "a")

    def test_no_probe_is_not_an_implicit_execution_or_success(self):
        result = self.review(request(observations=[]))
        self.assertEqual(result["requirements"][0]["state"], "missing")
        self.assertEqual(result["status"], "needs_observation")
        self.assertIsNone(result["next_probe"])

    def test_required_and_additional_fields_are_strict_at_every_level(self):
        for location in [(), ("requirements", 0), ("observations", 0), ("probes", 0)]:
            for mutation in ("missing", "extra"):
                with self.subTest(location=location, mutation=mutation):
                    value = request(probes=[probe()])
                    target = value
                    for part in location:
                        target = target[part]
                    if mutation == "missing":
                        del target[next(iter(target))]
                    else:
                        target["unrecognised"] = True
                    with self.assertRaises(ValueError):
                        self.review(value)

    def test_duplicate_ids_are_rejected_in_each_collection(self):
        for name in ("requirements", "observations", "probes"):
            with self.subTest(name=name):
                value = request(probes=[probe()])
                value[name].append(deepcopy(value[name][0]))
                with self.assertRaises(ValueError):
                    self.review(value)

    def test_invalid_numbers_are_rejected_in_each_numeric_field(self):
        for bad in (True, False, -1, float("nan"), float("inf"), 10 ** 19, "1"):
            for location, key in [("requirements", "max_age_seconds"),
                                  ("observations", "observed_at"), ("probes", "estimated_latency_ms")]:
                with self.subTest(bad=bad, field=key):
                    value = request(probes=[probe()])
                    value[location][0][key] = bad
                    with self.assertRaises(ValueError):
                        self.review(value)
            with self.assertRaises(ValueError):
                review_observations(request(), now=bad)

    def test_bad_labels_digests_outcomes_and_probe_references_are_rejected(self):
        cases = []
        for bad in ("", " ", "a\nb", "a\x00b", "x" * 129, 1, None):
            value = request()
            value["task_id"] = bad
            cases.append(value)
        for bad in ("a" * 63, "A" * 64, "g" * 64, None):
            value = request()
            value["requirements"][0]["input_sha256"] = bad
            cases.append(value)
        for changes in ({"requirement_ids": []}, {"requirement_ids": ["other"]},
                        {"requirement_ids": ["connected", "connected"]}):
            cases.append(request(probes=[probe(**changes)]))
        cases.append(request(observations=[observation(outcome="verified")]))
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.review(value)

    def test_empty_and_oversized_collections_are_rejected(self):
        with self.assertRaises(ValueError):
            self.review(request(requirements=[]))
        for key, count, factory in [("requirements", 65, requirement),
                                    ("observations", 129, observation), ("probes", 33, probe)]:
            value = request()
            value[key] = [factory(str(index)) for index in range(count)]
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.review(value)

    def test_report_order_does_not_depend_on_collection_order(self):
        value = request(requirements=[requirement("spawned"), requirement()],
                        observations=[observation("future", observed_at=NOW + 1),
                                      observation("valid"),
                                      observation("spawn", requirement_id="spawned")])
        result = self.review(value)
        value["requirements"].reverse()
        value["observations"].reverse()
        self.assertEqual(result, self.review(value))


if __name__ == "__main__":
    unittest.main()
