"""Explicit file-use feedback and source-bound context across task stages.

Reviews are host-provided observations, not independent truth or permissions.
No capability selection, test execution or source modification is carried out.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re

from .decision_json import canonical_json
from .execution_profiles import content_digest, digest
from .task_preparation import MAX_FILE_BYTES, VERSION as PACKET_VERSION, _path, prepare_task, render_packet

VERSION = "task-file-review/1"
CONTINUITY_VERSION = "task-continuity/1"
USEFUL = frozenset({"used", "supporting"})
STATUSES = USEFUL | {"irrelevant", "unreviewed"}
HASH = re.compile(r"[0-9a-f]{64}\Z")


def _text(value, label, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {label}")


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(f"invalid {label} fields")


def _reference(source):
    _keys(source, {"root", "path"}, "source")
    _text(source["root"], "source root", 80)
    _text(source["path"], "source path", 1000)
    _path({}, source)  # Reuse the preparer's path contract without reading.
    return canonical_json(source)


def _hash(value):
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError("invalid content hash")


def _packet_files(packet):
    if packet.get("version") != PACKET_VERSION or packet.get("auto_act_allowed") is not False:
        raise ValueError("unsupported or non-shadow packet")
    files = packet.get("files")
    if not isinstance(files, list) or len(files) > 16:
        raise ValueError("packet file budget exceeded")
    result = {}
    for row in files:
        key = _reference(row["source"])
        _hash(row["content_sha256"])
        if key in result:
            raise ValueError("duplicate packet source")
        result[key] = row
    return result


def _observe(source, roots):
    path = _path(roots, source)
    if path is None:
        return None, "root_not_supplied"
    try:
        with path.open("rb") as stream:
            raw = stream.read(MAX_FILE_BYTES + 1)
        if len(raw) > MAX_FILE_BYTES:
            return None, "file_too_large"
        return content_digest(raw), None
    except OSError:
        return None, "source_unavailable"


def record_file_review(packet, feedback, *, roots, at):
    """Bind judgments to exactly the packet presented; unreviewed stays unknown.

    Newly created files are recorded separately from pre-existing omissions.
    Only explicitly supplied missing-file references are additionally read.
    """
    originals = _packet_files(packet)
    _keys(feedback, {"task_id", "stage_id", "reviewer", "reviewer_kind", "judgments", "missing_files",
                     "notes", "review_complete", "additional_searches", "additional_reads"}, "feedback")
    for field in ("task_id", "stage_id", "reviewer"):
        _text(feedback[field], field, 200)
    if feedback["reviewer_kind"] not in {"agent", "human"}:
        raise ValueError("reviewer kind must be agent or human")
    _text(at, "review timestamp", 80)
    if datetime.fromisoformat(at.replace("Z", "+00:00")).utcoffset() is None:
        raise ValueError("review timestamp needs timezone")
    if type(feedback["review_complete"]) is not bool:
        raise ValueError("review_complete must be boolean")
    for field in ("additional_searches", "additional_reads"):
        value = feedback[field]
        if value is not None and (type(value) is not int or not 0 <= value <= 100000):
            raise ValueError("search/read counts must be nonnegative integers or null")
    for field in ("judgments", "missing_files", "notes"):
        if not isinstance(feedback[field], list) or len(feedback[field]) > 16:
            raise ValueError(f"{field} exceeds 16 entries")
    rows = {key: {"source": deepcopy(row["source"]), "content_sha256": row["content_sha256"],
                 "status": "unreviewed", "reason": None, "origin": "proposed"}
            for key, row in originals.items()}
    seen = set()
    for judgment in feedback["judgments"]:
        _keys(judgment, {"source", "status", "reason"}, "judgment")
        key = _reference(judgment["source"])
        if key not in rows or key in seen:
            raise ValueError("judgment must name a unique proposed source")
        if judgment["status"] not in STATUSES:
            raise ValueError("unknown usefulness status")
        _text(judgment["reason"], "judgment reason")
        rows[key].update(status=judgment["status"], reason=judgment["reason"])
        seen.add(key)
    for missing in feedback["missing_files"]:
        _keys(missing, {"source", "status", "reason", "origin"}, "missing file")
        key = _reference(missing["source"])
        if key in rows or missing["status"] not in USEFUL or missing["origin"] not in {"existing", "created"}:
            raise ValueError("missing file must be a unique useful discovery with explicit origin")
        _text(missing["reason"], "discovery reason")
        current, error = _observe(missing["source"], roots)
        if error:
            raise ValueError(f"cannot observe discovered file: {error}")
        rows[key] = {**deepcopy(missing), "content_sha256": current}
    if feedback["review_complete"] and any(row["status"] == "unreviewed" for row in rows.values()):
        raise ValueError("a complete review cannot leave proposed files unreviewed")
    notes = []
    for note in feedback["notes"]:
        _keys(note, {"kind", "text", "sources", "evidence"}, "note")
        if note["kind"] not in {"decision", "test_result", "open_question"}:
            raise ValueError("unsupported continuity note")
        _text(note["text"], "note text")
        if not isinstance(note["sources"], list) or not 1 <= len(note["sources"]) <= 16:
            raise ValueError("note requires source bindings")
        bindings = []
        for source in note["sources"]:
            key = _reference(source)
            if key not in rows or rows[key]["status"] not in USEFUL:
                raise ValueError("note source must be explicitly reviewed as useful")
            bindings.append({"source": deepcopy(source), "content_sha256": rows[key]["content_sha256"]})
        if note["evidence"] is not None:
            _text(note["evidence"], "note evidence")
        elif note["kind"] == "test_result":
            raise ValueError("reported test result needs evidence reference")
        notes.append({"kind": note["kind"], "text": note["text"], "bindings": bindings,
                      "evidence": note["evidence"], "proof_status": "reported_not_independently_verified"})
    proposed = [r for r in rows.values() if r["origin"] == "proposed"]
    counts = {status: sum(r["status"] == status for r in proposed) for status in sorted(STATUSES)}
    metrics = {"proposed_files": len(proposed), "proposed_statuses": counts,
        "reviewed_proposed_files": len(proposed) - counts["unreviewed"],
        "pre_existing_useful_files_missing": sum(r["origin"] == "existing" for r in rows.values()),
        "useful_files_created_during_task": sum(r["origin"] == "created" for r in rows.values()),
        "additional_searches": feedback["additional_searches"], "additional_reads": feedback["additional_reads"],
        "searches_avoided": None, "reads_avoided": None, "time_saved": None}
    review = {"version": VERSION, **{f: feedback[f] for f in ("task_id", "stage_id", "reviewer", "reviewer_kind", "review_complete")},
        "at": at, "packet_sha256": digest(packet), "files": list(rows.values()), "notes": notes,
        "metrics": metrics, "auto_act_allowed": False}
    review["review_sha256"] = digest(review)
    return review


def continue_task(goal, inventory, index, *, previous_packet, review, roots, task_id, stage_id,
                  policy=None, constraints=(), top_k=5):
    """Refresh useful references and notes; recompute capabilities from scratch."""
    _packet_files(previous_packet)
    _text(task_id, "task id", 200)
    _text(stage_id, "stage id", 200)
    payload = {key: value for key, value in review.items() if key != "review_sha256"}
    if (review.get("version") != VERSION or review.get("review_sha256") != digest(payload)
            or review.get("packet_sha256") != digest(previous_packet) or review.get("auto_act_allowed") is not False):
        raise ValueError("review incompatible with packet")
    if task_id != review["task_id"] or stage_id == review["stage_id"]:
        raise ValueError("continuation needs the same task and a new stage")
    parent = previous_packet.get("continuity")
    if parent is not None and (parent["task_id"] != task_id or parent["stage_id"] != review["stage_id"]):
        raise ValueError("review breaks the task/stage chain")
    packet = prepare_task(goal, inventory, index, policy=policy, constraints=constraints, top_k=top_k)
    useful = [row for row in review["files"] if row["status"] in USEFUL]
    if len(useful) > 32:
        raise ValueError("useful file budget exceeded")
    useful.sort(key=lambda row: (row["status"] != "used", _reference(row["source"])))
    refreshed = []
    carried = []
    states = {}
    for row in useful:
        key = _reference(row["source"])
        _hash(row["content_sha256"])
        current, error = _observe(row["source"], roots)
        state = "unavailable" if error else "unchanged" if current == row["content_sha256"] else "changed_requires_reread"
        states[key] = state
        refreshed.append({"source": deepcopy(row["source"]), "previous_sha256": row["content_sha256"],
                          "current_sha256": current, "state": state, "reason": error,
                          "previous_use": row["status"], "previous_reason": row["reason"]})
        if current is not None:
            carried.append({"source": deepcopy(row["source"]), "content_sha256": current,
                "role": "suggested_test" if row["source"]["path"].startswith("tests/") else "evidence_to_read",
                "continuity_status": state, "relevance_review_required": True})
    notes = []
    for note in review["notes"]:
        known_hashes = {_reference(row["source"]): row["content_sha256"] for row in useful}
        unchanged = all(states.get(_reference(binding["source"])) == "unchanged" and
                        known_hashes.get(_reference(binding["source"])) == binding["content_sha256"]
                        for binding in note["bindings"])
        notes.append({**deepcopy(note), "continuity_status": "sources_unchanged_review_scope" if unchanged else "stale_requires_review"})
    previous_statuses = {_reference(r["source"]): r["status"] for r in review["files"]}
    ordinary = deepcopy(packet["files"])
    for row in ordinary:
        if previous_statuses.get(_reference(row["source"])) == "irrelevant":
            row["previous_use"] = "irrelevant"
            row["relevance_review_required"] = True
    # Keep these candidates visible: a file irrelevant during implementation
    # may become relevant during testing. Only lower their default file order.
    ordinary.sort(key=lambda row: row.get("previous_use") == "irrelevant")
    combined = []
    seen = set()
    for row in carried + ordinary:
        key = _reference(row["source"])
        if key not in seen:
            combined.append(row)
            seen.add(key)
    packet["files"] = combined[:16]
    continuity = {"version": CONTINUITY_VERSION, "task_id": task_id, "stage_id": stage_id,
        "previous_stage_id": review["stage_id"], "previous_packet_sha256": digest(previous_packet),
        "review_sha256": review["review_sha256"], "files": refreshed, "notes": notes,
        "previous_stage_file_usefulness": deepcopy(review["metrics"]),
        "metrics": {"unchanged_useful_references": sum(r["state"] == "unchanged" for r in refreshed),
            "changed_useful_references": sum(r["state"] == "changed_requires_reread" for r in refreshed),
            "unavailable_useful_references": sum(r["state"] == "unavailable" for r in refreshed),
            "carried_references_in_packet": min(len(carried), 16),
            "carried_references_truncated": max(0, len(carried) - 16),
            "new_file_references_omitted_by_budget": sum(_reference(r["source"]) not in
                {_reference(f["source"]) for f in packet["files"]} for r in combined[len(carried):]),
            "previously_irrelevant_files_reproposed": sum(r.get("previous_use") == "irrelevant" for r in packet["files"]),
            "searches_avoided": None, "reads_avoided": None},
        "auto_act_allowed": False}
    packet["continuity"] = continuity
    packet["compact_context"]["files"] = deepcopy(packet["files"])
    packet["compact_context"]["continuity"] = {"task_id": task_id, "stage_id": stage_id,
        "previous_stage_id": review["stage_id"], "files": refreshed, "notes": notes,
        "previous_stage_file_usefulness": deepcopy(review["metrics"]), "metrics": continuity["metrics"],
        "auto_act_allowed": False}
    packet["metrics"]["compact_context_chars"] = len(canonical_json(packet["compact_context"]))
    return packet


def render_followup(packet):
    continuity = packet["continuity"]
    counts = continuity["previous_stage_file_usefulness"]
    lines = ["# Suite de tâche : fichiers utiles et contexte", "",
        f"Étape `{continuity['previous_stage_id']}` → `{continuity['stage_id']}`.", "",
        "## Utilité observée à l'étape précédente", "",
        f"- Fichiers proposés : {counts['proposed_files']}, relus/annotés : {counts['reviewed_proposed_files']}.",
        f"- Statuts : {canonical_json(counts['proposed_statuses'])}.",
        f"- Fichiers utiles déjà existants mais absents : {counts['pre_existing_useful_files_missing']}.",
        f"- Fichiers utiles créés pendant le travail : {counts['useful_files_created_during_task']}.",
        f"- Recherches supplémentaires déclarées : {counts['additional_searches']} ; lectures : {counts['additional_reads']}.",
        "", "## Références conservées et fraîcheur", ""]
    for row in continuity["files"]:
        lines.append(f"- `{row['source']['root']}:{row['source']['path']}` — {row['state']}.")
    lines.extend(["", "## Décisions, tests rapportés et questions", ""])
    for note in continuity["notes"]:
        lines.extend([f"- {note['kind']} — {note['continuity_status']} :", "",
                      "    " + note["text"].replace("\n", "\n    "), ""])
    lines.extend(["Notes rapportées, pas de tests réexécutés. Pertinence à revoir pour cette nouvelle étape.",
                  "Les références inchangées ne prouvent pas qu'une lecture ou recherche a été évitée.", "",
                  render_packet(packet)])
    previous = [r for r in packet["files"] if r.get("previous_use") == "irrelevant"]
    if previous:
        lines.extend(["", "## Fichiers précédemment inutiles encore proposés", ""])
        lines.extend(f"- `{r['source']['root']}:{r['source']['path']}` — réexaminer la pertinence pour cette étape." for r in previous)
    return "\n".join(lines)
