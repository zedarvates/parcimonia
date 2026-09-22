"""Ingest real prompt situations from the local rollout stores into a revision.

The corpus is written outside the repository, is identified by its content rather
than by its date, and is never labelled here: ingesting situations and deciding
what a task needed are different acts with different provenance.

The default action is a dry run that only reports what would be ingested. With
--update the revision is written as an immutable file, the latest pointer is
refreshed, and the delta against the previous revision is printed.

Usage:
    python examples/prompt_ingest.py
    python examples/prompt_ingest.py --update
    python examples/prompt_ingest.py --store-root C:/path/to/.codex --out runs/corpus
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from tiberium_ai.signature_ingest import (
    IngestConfig,
    compare_revisions,
    default_codex_sources,
    ingest,
    read_revision,
    write_revision,
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store-root", default=None, help="root of the rollout stores")
    parser.add_argument("--out", default="runs/signature-corpus")
    parser.add_argument("--user", default="local", help="label of the person ingesting")
    parser.add_argument("--max-prompt-chars", type=int, default=1200)
    parser.add_argument("--update", action="store_true", help="write the revision")
    parser.add_argument("--generated-at", default=None, help="ISO-8601 stamp to record")
    return parser.parse_args(list(argv))


def _band(chars: int) -> str:
    if chars < 30:
        return "short<30"
    if chars < 100:
        return "30-99"
    if chars < 300:
        return "100-299"
    if chars < 1000:
        return "300-999"
    return "1000+"


def summarise(revision: dict[str, Any]) -> dict[str, Any]:
    buckets: dict[str, int] = {}
    repeats: list[int] = []
    harness_stripped = 0
    truncated = 0
    for prompt in revision["prompts"]:
        band = _band(prompt["chars"])
        buckets[band] = buckets.get(band, 0) + 1
        repeats.append(prompt["count"])
        harness_stripped += 1 if prompt["harness_stripped"] else 0
        truncated += 1 if prompt["truncated"] else 0
    return {
        "revision_id": revision["revision_id"],
        "messages_seen": revision["messages_seen"],
        "distinct_prompts": revision["distinct_prompts"],
        "redactions": revision["redactions"],
        "harness_stripped": harness_stripped,
        "truncated": truncated,
        "repeated_asks": sum(1 for count in repeats if count > 1),
        "max_repeat": max(repeats),
        "buckets": buckets,
        "sources": revision["sources"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    store_root = Path(arguments.store_root) if arguments.store_root else None
    sources = default_codex_sources(store_root)
    if not sources:
        raise SystemExit(
            "no rollout store was found; pass --store-root explicitly rather than "
            "ingesting nothing."
        )
    out = Path(arguments.out)
    config = IngestConfig(
        user=arguments.user,
        sources=sources,
        max_prompt_chars=arguments.max_prompt_chars,
    )
    stamp = arguments.generated_at or datetime.now(timezone.utc).isoformat()
    revision = ingest(config, generated_at=stamp)
    summary = summarise(revision)
    for entry in summary.pop("sources"):
        print(
            f"source {entry['label']}: {entry['files']} file(s), "
            f"{entry['prompts']} prompt(s)"
        )
    for key, value in summary.items():
        print(f"{key}: {value}")

    latest = out / "latest.json"
    if latest.is_file():
        delta = compare_revisions(read_revision(latest), revision)
        print("delta:", json.dumps(delta, sort_keys=True))
    else:
        print("delta: no previous revision in " + str(out))

    if not arguments.update:
        print("dry run: nothing written. Use --update to store this revision.")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    target = out / f"revision-{revision['revision_id'][:16]}.json"
    if target.exists():
        print("already stored:", target)
    else:
        write_revision(target, revision)
        print("wrote:", target)
    # Revisions are immutable; only this pointer moves.
    latest.write_text(
        json.dumps(revision, indent=1, ensure_ascii=False) + chr(10),
        encoding="utf-8",
        newline=chr(10),
    )
    print("latest pointer:", latest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
