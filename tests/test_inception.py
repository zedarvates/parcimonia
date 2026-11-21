"""Behavioral checks for a portable, evidence-preserving discussion journal."""

from copy import deepcopy
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from tiberium_ai.inception import InceptionStore


def checkpoint(next_action="Run the smallest failing example"):
    return {"goal": "Continue a project in a fresh session", "state": "An attempt failed",
            "next_action": next_action, "acceptance": "Record the observed result",
            "decision_ids": [], "outcome_ids": [], "open_actions": []}


def source(availability="available"):
    return {"id": "repo:test-output", "version": "revision-1", "uri": "fixture:output",
            "sha256": "a" * 64, "availability": availability}


class InceptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cloud = InceptionStore.create(self.root / "cloud.db", "cloud-fixture")
        self.local = InceptionStore.create(self.root / "local.db", "local-fixture")

    def append(self, store, payload=None, **kwargs):
        return store.append("demo", "checkpoint", "main", payload or checkpoint(),
                            expected_heads=kwargs.pop("expected_heads", []),
                            scope=kwargs.pop("scope", "shared"), **kwargs)

    def exchange(self, sender, receiver, receiver_id):
        batch = sender.export_batch("demo", receiver_id)
        receipt = receiver.receive(batch)
        self.assertEqual(receipt["status"], "accepted")
        sender.acknowledge(receipt)
        return batch, receipt

    def test_reopen_and_resume_preserves_failed_attempt_and_uncertain_cause(self):
        outcome = self.cloud.append("demo", "outcome", "attempt-1", {
            "summary": "The run timed out", "result": "failure", "verification": "declared",
            "why": "A slow dependency is suspected", "cause_status": "hypothesis"},
            expected_heads=[], sources=[source("unavailable")], scope="shared")
        payload = checkpoint()
        payload["outcome_ids"] = [outcome["id"]]
        saved = self.append(self.cloud, payload)
        resumed = InceptionStore(self.root / "cloud.db").resume("demo")
        self.assertEqual(resumed["checkpoint"]["id"], saved["id"])
        self.assertEqual(resumed["outcomes"][0]["payload"]["cause_status"], "hypothesis")
        self.assertTrue(resumed["revalidation_required"])
        self.assertEqual(resumed["status"], "needs_review")

    def test_offline_roundtrip_and_lost_ack_are_idempotent(self):
        initial = self.append(self.cloud)
        batch = self.cloud.export_batch("demo", "local-fixture")
        first = self.local.receive(batch)
        self.cloud = InceptionStore(self.root / "cloud.db")
        self.local = InceptionStore(self.root / "local.db")
        self.assertEqual(self.cloud.export_batch("demo", "local-fixture"), batch)
        self.assertEqual(self.local.receive(batch), first)
        self.cloud.acknowledge(first)
        self.cloud.acknowledge(first)
        next_event = self.append(self.local, checkpoint("Review offline result"),
                                 expected_heads=[initial["id"]])
        self.exchange(self.local, self.cloud, "cloud-fixture")
        self.assertEqual(self.cloud.resume("demo")["checkpoint"]["id"], next_event["id"])
        self.assertEqual(self.local.status("demo")["event_count"], 2)

    def test_concurrent_decisions_survive_and_require_explicit_resolution(self):
        payload = {"summary": "Choose approach A", "rationale": "Initial experiment",
                   "alternatives": ["B"]}
        first = self.cloud.append("demo", "decision", "approach", payload,
                                  expected_heads=[], scope="shared")
        self.exchange(self.cloud, self.local, "local-fixture")
        left = self.cloud.append("demo", "decision", "approach", {**payload, "summary": "A2"},
                                 expected_heads=[first["id"]], scope="shared")
        right = self.local.append("demo", "decision", "approach", {**payload, "summary": "B"},
                                  expected_heads=[first["id"]], scope="shared")
        self.exchange(self.local, self.cloud, "cloud-fixture")
        self.assertEqual(set(self.cloud.heads("demo", "decision", "approach")),
                         {left["id"], right["id"]})
        self.assertTrue(self.cloud.status("demo")["record_conflicts"])
        resolved = self.cloud.append("demo", "decision", "approach", payload,
                                    expected_heads=[left["id"], right["id"]], scope="shared")
        self.assertEqual(self.cloud.heads("demo", "decision", "approach"), [resolved["id"]])
        self.exchange(self.cloud, self.local, "local-fixture")
        self.assertEqual(self.local.heads("demo", "decision", "approach"), [resolved["id"]])
        self.assertFalse(self.local.status("demo")["record_conflicts"])

    def test_stale_local_writer_cannot_replace_checkpoint(self):
        first = self.append(self.cloud)
        other = InceptionStore(self.root / "cloud.db")
        second = self.append(self.cloud, expected_heads=[first["id"]])
        with self.assertRaises(ValueError):
            self.append(other, checkpoint("Stale overwrite"), expected_heads=[first["id"]])
        self.assertEqual(other.heads("demo", "checkpoint", "main"), [second["id"]])

    def test_competing_local_writers_commit_only_one_revision(self):
        first = self.append(self.cloud)
        barrier = Barrier(2)

        def write(label):
            store = InceptionStore(self.root / "cloud.db")
            barrier.wait(timeout=3)
            try:
                return self.append(store, checkpoint(label), expected_heads=[first["id"]])["id"]
            except ValueError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(write, ("Writer A", "Writer B")))
        committed = [identifier for identifier in results if identifier is not None]
        self.assertEqual(len(committed), 1)
        self.assertEqual(self.cloud.heads("demo", "checkpoint", "main"), committed)

    def test_explicit_event_id_retry_recovers_committed_event(self):
        first = self.append(self.cloud, event_id="known-operation")
        self.assertEqual(first, self.append(self.cloud, event_id="known-operation"))
        with self.assertRaises(ValueError):
            self.append(self.cloud, checkpoint("Different content"), event_id="known-operation")

    def test_conflicting_event_identity_is_preserved_and_batch_not_acknowledged(self):
        self.append(self.cloud, event_id="collision")
        self.append(self.local, checkpoint("Incompatible content"), event_id="collision")
        batch = self.cloud.export_batch("demo", "local-fixture")
        receipt = self.local.receive(batch)
        self.assertEqual(receipt["status"], "conflict")
        self.assertEqual(self.local.status("demo")["collision_count"], 1)
        self.assertEqual(self.local.status("demo")["event_count"], 1)
        with self.assertRaises(ValueError):
            self.cloud.acknowledge(receipt)
        self.assertEqual(self.cloud.export_batch("demo", "local-fixture"), batch)

    def test_private_events_and_projects_never_enter_bundle(self):
        self.append(self.cloud, scope="local", event_id="private")
        self.cloud.append("another-project", "checkpoint", "main", checkpoint(),
                          expected_heads=[], scope="shared", event_id="other")
        shared = self.cloud.append("demo", "checkpoint", "shared-main", checkpoint(),
                                   expected_heads=[], scope="shared")
        batch = self.cloud.export_batch("demo", "local-fixture")
        self.assertEqual([e["id"] for e in batch["events"]], [shared["id"]])
        self.assertEqual(batch["to_cursor"], 1)

    def test_shared_event_cannot_depend_on_local_parent(self):
        initial = self.append(self.cloud, scope="local")
        with self.assertRaises(ValueError):
            self.append(self.cloud, expected_heads=[initial["id"]], scope="shared")

    def test_tampered_bundle_and_wrong_peer_do_not_write(self):
        self.append(self.cloud)
        batch = self.cloud.export_batch("demo", "local-fixture")
        changed = deepcopy(batch)
        changed["events"][0]["payload"]["next_action"] = "Tampered"
        with self.assertRaises(ValueError):
            self.local.receive(changed)
        third = InceptionStore.create(self.root / "third.db", "third-fixture")
        with self.assertRaises(ValueError):
            third.receive(batch)
        self.assertEqual(self.local.status("demo")["event_count"], 0)

    def test_unissued_receipt_cannot_advance_outbox(self):
        self.append(self.cloud)
        batch = self.cloud.export_batch("demo", "local-fixture")
        receipt = self.local.receive(batch)
        forged = deepcopy(receipt)
        forged["to_cursor"] += 1
        with self.assertRaises(ValueError):
            self.cloud.acknowledge(forged)
        self.assertEqual(self.cloud.export_batch("demo", "local-fixture"), batch)

    def test_resealed_wrong_peer_receipt_is_rejected(self):
        from tiberium_ai.inception import _seal

        self.append(self.cloud)
        batch = self.cloud.export_batch("demo", "local-fixture")
        receipt = self.local.receive(batch)
        changed = {key: value for key, value in receipt.items() if key != "receipt_hash"}
        changed["receiver"] = "another-store"
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.cloud.acknowledge(_seal(changed, "receipt_hash"))
        self.assertEqual(self.cloud.status("demo", "local-fixture")["pending_event_count"], 1)

    def test_bounded_batches_continue_from_confirmed_cursor(self):
        for i in range(3):
            self.cloud.append("demo", "lesson", f"lesson-{i}",
                              {"summary": f"Lesson {i}", "limits": "Fixture only"},
                              expected_heads=[], scope="shared")
        first = self.cloud.export_batch("demo", "local-fixture", limit=2)
        self.assertEqual(len(first["events"]), 2)
        self.cloud.acknowledge(self.local.receive(first))
        second = self.cloud.export_batch("demo", "local-fixture", limit=2)
        self.assertEqual(second["from_cursor"], 2)
        self.assertEqual(len(second["events"]), 1)
        self.cloud.acknowledge(self.local.receive(second))

    def test_empty_exchange_replay_does_not_block_later_work(self):
        for _ in range(2):
            self.exchange(self.cloud, self.local, "local-fixture")
        event = self.append(self.cloud)
        self.exchange(self.cloud, self.local, "local-fixture")
        self.assertEqual(self.local.resume("demo")["checkpoint"]["id"], event["id"])

    def test_interruption_before_commit_rolls_back_every_event_and_receipt(self):
        for i in range(2):
            self.cloud.append("demo", "lesson", f"lesson-{i}",
                              {"summary": f"Lesson {i}", "limits": "Fixture only"},
                              expected_heads=[], scope="shared")
        batch = self.cloud.export_batch("demo", "local-fixture")
        original = InceptionStore._insert
        count = 0

        def interrupted(connection, event):
            nonlocal count
            count += 1
            original(connection, event)
            if count == 2:
                raise OSError("Simulated interruption before transaction commit")

        with patch.object(InceptionStore, "_insert", side_effect=interrupted):
            with self.assertRaises(OSError):
                self.local.receive(batch)
        self.local = InceptionStore(self.root / "local.db")
        self.assertEqual(self.local.status("demo")["event_count"], 0)
        self.assertEqual(self.local.status("demo")["streams"], [])
        self.cloud.acknowledge(self.local.receive(batch))
        self.assertEqual(self.local.status("demo")["event_count"], 2)

    def test_missing_causal_parent_refuses_whole_batch(self):
        from tiberium_ai.inception import _seal

        initial = self.append(self.cloud)
        self.append(self.cloud, expected_heads=[initial["id"]])
        batch = self.cloud.export_batch("demo", "local-fixture")
        modified = {k: v for k, v in batch.items() if k != "batch_hash"}
        modified["events"] = [batch["events"][1]]
        modified["to_cursor"] = 1
        broken = _seal(modified, "batch_hash")
        with self.assertRaisesRegex(ValueError, "Missing causal parent"):
            self.local.receive(broken)
        self.assertEqual(self.local.status("demo")["event_count"], 0)
        self.assertEqual(self.local.status("demo")["streams"], [])

    def test_shared_checkpoint_does_not_publish_local_reference(self):
        private = self.cloud.append("demo", "decision", "private-choice", {
            "summary": "Private choice", "rationale": "Local only", "alternatives": []},
            expected_heads=[])
        value = checkpoint()
        value["decision_ids"] = [private["id"]]
        with self.assertRaisesRegex(ValueError, "local event reference"):
            self.append(self.cloud, value)
        self.assertEqual(self.cloud.export_batch("demo", "local-fixture")["events"], [])

    def test_future_reference_cannot_become_private_or_wrong_kind(self):
        value = checkpoint()
        value["decision_ids"] = ["future-decision"]
        self.append(self.cloud, value)
        with self.assertRaisesRegex(ValueError, "local event reference"):
            self.cloud.append("demo", "decision", "private-choice", {
                "summary": "Private choice", "rationale": "Local only", "alternatives": []},
                expected_heads=[], event_id="future-decision")
        with self.assertRaisesRegex(ValueError, "wrong event kind"):
            self.cloud.append("demo", "lesson", "wrong-kind", {
                "summary": "A lesson", "limits": "Not a decision"},
                expected_heads=[], event_id="future-decision", scope="shared")
        self.assertEqual(self.cloud.status("demo")["event_count"], 1)

    def test_resume_and_sync_metadata_describe_one_database_snapshot(self):
        first = self.append(self.cloud)
        self.exchange(self.cloud, self.local, "local-fixture")
        self.append(self.cloud, checkpoint("Cloud branch"), expected_heads=[first["id"]])
        self.append(self.local, checkpoint("Local branch"), expected_heads=[first["id"]])
        incoming = self.local.export_batch("demo", "cloud-fixture")
        original = self.cloud._connection
        fired = False

        @contextmanager
        def receive_after_first_read(*, write=False):
            nonlocal fired
            with original(write=write) as connection:
                yield connection
            if not fired and not write:
                fired = True
                self.cloud.receive(incoming)

        # A remote branch arrives immediately after the read transaction closes.
        # Both report sections must still describe that same earlier snapshot.
        with patch.object(self.cloud, "_connection", side_effect=receive_after_first_read):
            resumed = self.cloud.resume("demo")
        self.assertEqual(resumed["record_conflicts"], resumed["sync"]["record_conflicts"])
        self.assertTrue(self.cloud.status("demo")["record_conflicts"])

    def test_links_distinguish_exact_identity_candidates_and_explicit_links(self):
        first = self.cloud.append("demo", "lesson", "lesson-a",
                                  {"summary": "Memory checkpoint recovery failure", "limits": "One trial"},
                                  expected_heads=[], sources=[source()])
        second = self.cloud.append("demo", "lesson", "lesson-b",
                                   {"summary": "Memory checkpoint recovery success", "limits": "One trial"},
                                   expected_heads=[], sources=[source()])
        self.cloud.append("demo", "link", "link-ab", {
            "from_id": first["id"], "to_id": second["id"], "relation": "related_to",
            "mode": "explicit", "status": "confirmed", "reason": "Requested comparison"},
            expected_heads=[])
        links = self.cloud.links("demo", first["id"])
        self.assertEqual(links["automatic"][0]["relation"], "same_source_revision")
        self.assertTrue(links["proposed"]["matches"])
        self.assertTrue(all(c["status"] == "unverified" for c in links["proposed"]["matches"]))
        self.assertEqual(links["explicit"][0]["payload"]["mode"], "explicit")

    def test_missing_checkpoint_reference_is_visible(self):
        value = checkpoint()
        value["decision_ids"] = ["not-available"]
        self.append(self.cloud, value)
        resumed = self.cloud.resume("demo")
        self.assertEqual(resumed["status"], "needs_review")
        self.assertIn("not-available", resumed["missing_references"])

    def test_unrelated_outcomes_do_not_match_only_on_schema_keys(self):
        first = self.cloud.append("demo", "outcome", "apples", {
            "summary": "Apples harvested", "result": "failure", "verification": "declared",
            "why": "Rain", "cause_status": "hypothesis"}, expected_heads=[])
        self.cloud.append("demo", "outcome", "satellite", {
            "summary": "Satellite navigation", "result": "failure", "verification": "declared",
            "why": "Interference", "cause_status": "hypothesis"}, expected_heads=[])
        self.assertEqual(self.cloud.links("demo", first["id"])["proposed"]["matches"], [])

    def test_create_does_not_replace_existing_database_or_follow_link(self):
        with self.assertRaises((ValueError, OSError)):
            InceptionStore.create(self.root / "cloud.db", "replacement")
        link = self.root / "link.db"
        try:
            link.symlink_to(self.root / "cloud.db")
        except (OSError, NotImplementedError):
            return
        with self.assertRaises((ValueError, OSError)):
            InceptionStore(link)


if __name__ == "__main__":
    unittest.main()
