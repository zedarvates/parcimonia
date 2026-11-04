"""Authored two-day discussion fixtures exchanged between two local databases.

The labels cloud/local name replicas in this offline example. No real account,
conversation archive, workstation or network transport is accessed.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.inception import InceptionStore


def build_demo() -> dict:
    project = "fixture-inception"
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        cloud = InceptionStore.create(root / "cloud.sqlite", "fixture-cloud")
        local = InceptionStore.create(root / "local.sqlite", "fixture-local")
        failure = cloud.append(project, "outcome", "attempt-1", {
            "summary": "Le témoin de reprise a échoué après une révision du contexte.",
            "result": "failure", "verification": "declared",
            "why": "Un contexte périmé est suspecté ; aucune cause n'est encore établie.",
            "cause_status": "hypothesis",
        }, expected_heads=[], event_id="fixture-failure", scope="shared")
        decision = cloud.append(project, "decision", "keep-failures", {
            "summary": "Conserver les échecs et les conditions de chaque tentative.",
            "rationale": "La reprise doit expliquer ce qui a été essayé avant un nouvel essai.",
            "alternatives": ["Ne garder que la dernière réussite perdrait le témoin négatif."],
        }, expected_heads=[], event_id="fixture-decision", scope="shared")
        checkpoint = cloud.append(project, "checkpoint", "main", {
            "goal": "Reprendre le même travail dans une nouvelle discussion.",
            "state": "Premier essai échoué ; hypothèse de contexte périmé à contrôler.",
            "next_action": "Relire la révision du contexte et rejouer le même témoin.",
            "acceptance": "Conserver l'échec, le nouvel essai et leurs raisons distinctes.",
            "decision_ids": [decision["id"]], "outcome_ids": [failure["id"]],
            "open_actions": ["Vérifier les sources avant de suivre la prochaine action."],
        }, expected_heads=[], event_id="fixture-day-1", scope="shared")
        cloud.append(project, "lesson", "private-note", {
            "summary": "Une note locale reste sur sa copie d'origine.",
            "limits": "Ce témoin contrôle seulement la sélection explicite du partage.",
        }, expected_heads=[], event_id="fixture-local-only")

        exchanges = []

        def exchange(sender, receiver):
            batch = sender.export_batch(project, receiver.node_id)
            receipt = receiver.receive(batch)
            assert receipt["status"] == "accepted"
            acknowledgement = sender.acknowledge(receipt)
            exchanges.append({"sender": sender.node_id, "receiver": receiver.node_id,
                              "event_count": len(batch["events"]), "batch_hash": batch["batch_hash"],
                              "receipt_status": receipt["status"], "ack_status": acknowledgement["status"]})

        exchange(cloud, local)
        # A different instance reads the persisted DB, like a fresh process/session.
        local = InceptionStore(root / "local.sqlite")
        morning = local.resume(project)
        assert morning["checkpoint"]["id"] == checkpoint["id"]
        assert local.heads(project, "lesson", "private-note") == []

        success = local.append(project, "outcome", "attempt-2", {
            "summary": "Le même témoin de reprise réussit après relecture du contexte.",
            "result": "success", "verification": "declared",
            "why": "La révision a été relue avant l'essai ; le lien causal reste hypothétique.",
            "cause_status": "hypothesis",
        }, expected_heads=[], event_id="fixture-success", scope="shared")
        latest = local.append(project, "checkpoint", "main", {
            "goal": "Reprendre le même travail dans une nouvelle discussion.",
            "state": "Deux tentatives conservées : échec initial et réussite déclarée ensuite.",
            "next_action": "Faire vérifier les deux résultats et leurs sources indépendamment.",
            "acceptance": "Distinguer résultat observé, résultat déclaré et cause démontrée.",
            "decision_ids": [decision["id"]],
            "outcome_ids": [failure["id"], success["id"]],
            "open_actions": ["Ne pas transformer l'hypothèse causale en certitude."],
        }, expected_heads=local.heads(project, "checkpoint", "main"),
            event_id="fixture-day-2", scope="shared")
        exchange(local, cloud)
        # Complete the reverse acknowledgement for the newly shared records;
        # replaying records the other replica already owns does not duplicate them.
        exchange(cloud, local)
        final = InceptionStore(root / "cloud.sqlite").resume(project)
        cloud_status = cloud.status(project, local.node_id)
        local_status = local.status(project, cloud.node_id)
        assert cloud.heads(project, "checkpoint", "main") == local.heads(project, "checkpoint", "main") == [latest["id"]]
        assert [e["payload"]["result"] for e in final["outcomes"]] == ["failure", "success"]
        assert cloud_status["pending_event_count"] == local_status["pending_event_count"] == 0
        return {
            "schema": "parcimonia.inception-demo/v1", "fixture_only": True,
            "network_calls": 0, "transport": "explicit_exchange_between_local_databases",
            "morning_resume": morning, "final_resume": final, "exchanges": exchanges,
            "cloud_status": cloud_status, "local_status": local_status,
            "local_only_note_exported": False, "cause_verified": False,
        }


if __name__ == "__main__":
    print(json.dumps(build_demo(), ensure_ascii=True, sort_keys=True, indent=2))
