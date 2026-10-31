"""Recheck exact saved locators and prepare a private provenance-backed review packet."""
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from tiberium_ai.context_provenance import attach_context_provenance, propose_paraphrase_pairs, recover_context_provenance
from tiberium_ai.context_review_ui import render_context_review

ROOT = Path(__file__).resolve().parents[1]


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _legacy_record(locator, *, max_bytes=64 * 1024 * 1024):
    path, wanted = Path(locator["path"]), locator["line"]
    total = 0
    with path.open("rb") as stream:
        for number, line in enumerate(stream, 1):
            total += len(line)
            if total > max_bytes:
                raise ValueError("saved source locator exceeds the bounded read budget")
            if number == wanted:
                return json.loads(line), total
    raise ValueError("saved source line is absent")


def recover_saved_locators(pack, sql_index, legacy_index, *, store_root):
    cutoff = sql_index["cutoff_ms"]
    if set(sql_index["matches"]) != {case["case_id"] for case in pack["cases"]}:
        raise ValueError("saved lookup index does not belong to this case set")
    records, failures = [], []
    with sqlite3.connect((store_root / "thread_history_1.sqlite").as_uri() + "?mode=ro", uri=True, timeout=10) as db:
        db.execute("PRAGMA query_only=ON")
        for entries in sql_index["matches"].values():
            for entry in entries:
                row = db.execute("SELECT rollout_ordinal,created_at_ms,item_json FROM thread_items WHERE thread_id=? AND turn_id=? AND item_id=? AND item_type='userMessage'",
                    (entry["thread_id"], entry["turn_id"], entry["item_id"])).fetchone()
                if row is None:
                    failures.append({"thread_id": entry["thread_id"], "reason": "saved_user_item_absent"})
                    continue
                ordinal, stamp, raw = row
                records.append({"thread_id": entry["thread_id"], "timestamp_ms": stamp, "item": json.loads(raw),
                    "source_kind": "sqlite_user_message", "locator": {"database": "thread_history_1.sqlite",
                    "turn_id": entry["turn_id"], "item_id": entry["item_id"], "rollout_ordinal": ordinal}})
    legacy_bytes = 0
    for entry in legacy_index["legacy_matches"]:
        locator = {"path": entry["path"], "line": entry["line"]}
        try:
            record, count = _legacy_record(locator)
            legacy_bytes += count
            stamp = int(datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
            records.append({"thread_id": entry["thread_id"], "timestamp_ms": stamp, "item": record["payload"],
                            "source_kind": "rollout_jsonl", "locator": locator})
        except (OSError, KeyError, TypeError, ValueError):
            failures.append({"thread_id": entry["thread_id"], "reason": "saved_rollout_source_unavailable"})
    recovery = recover_context_provenance(pack, records, cutoff_ms=cutoff)
    recovery["locator_failures"] = failures
    recovery["legacy_bytes_read"] = legacy_bytes
    return recovery


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--sql-index", type=Path, required=True)
    parser.add_argument("--legacy-index", type=Path, required=True)
    parser.add_argument("--store-root", type=Path, default=Path.home() / ".codex")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.relative_to((ROOT / "runs").resolve())
    names = ("provenance.json", "review-packet.json", "review.html", "manifest.json")
    if any((output / name).exists() for name in names):
        raise FileExistsError("review output already exists; choose a new directory")
    pack = _read_json(args.pack)
    recovery = recover_saved_locators(pack, _read_json(args.sql_index), _read_json(args.legacy_index), store_root=args.store_root.resolve())
    packet = attach_context_provenance(pack, recovery)
    packet["paraphrase_candidates"] = propose_paraphrase_pairs(packet)
    packet["review_instructions_version"] = "context-review/1"
    output.mkdir(parents=True, exist_ok=True)
    for name, value in (("provenance.json", recovery), ("review-packet.json", packet)):
        with (output / name).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with (output / "review.html").open("x", encoding="utf-8") as stream:
        stream.write(render_context_review(packet))
    manifest = {"parent_pack_sha256": sha256(args.pack.read_bytes()).hexdigest(),
        "files": {name: sha256((output / name).read_bytes()).hexdigest() for name in names[:-1]},
        "recovered_cases": recovery["recovered_cases"], "occurrences": recovery["occurrences"],
        "distinct_threads": recovery["distinct_threads"], "source_components": packet["source_component_count"],
        "paraphrase_candidates": len(packet["paraphrase_candidates"]), "labelled_cases": 0,
        "automatic_routing_activated": False, "model_inference_executed": False}
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, indent=2)
    print(json.dumps({k: v for k, v in manifest.items() if k not in {"parent_pack_sha256", "files"}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
