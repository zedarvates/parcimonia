"""Audit a source tree with the deterministic route and demonstrate verdict reuse.

Every file is scanned, classified and scored locally. The second pass over the
same tree proves the cheap path: the store answers with a previously measured
verdict instead of redoing the analysis, and each verdict is then recomputed by
the named verifier rather than trusted.

These are measurements of a local audit. No model was called, so there is no
baseline to compare against and no cost saving is claimed anywhere in the
output.

Usage:
    python examples/audit_suite.py --out runs/audit --root src/tiberium_ai
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from tiberium_ai.audit import (
    AUDIT_VERIFIER_ID,
    AUDIT_VERIFIER_VERSION,
    AuditRequest,
    audit_policy_version,
    audit_source,
    register_audit_verifiers,
)
from tiberium_ai.audit_store import SqliteAuditStore
from tiberium_ai.verification import VerifierRegistry

POLICY_BASE = "static-audit-v1"
PROJECT_ID = "parcimonia"
DATA_ORIGIN = "measured"

#: Vendored, cached and build trees: widening the root must not widen what
#: counts as authored code, or a run on a repository root measures its
#: dependencies instead of the repository.
VENDOR_PARTS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages", "build", "dist"}
)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default="src/tiberium_ai", help="directory to audit")
    parser.add_argument("--out", default="runs/audit", help="output directory")
    parser.add_argument(
        "--timestamp",
        default=None,
        help="ISO-8601 record timestamp; defaults to the current UTC time",
    )
    return parser.parse_args(list(argv))


def read_sources(root: Path) -> list[tuple[str, str]]:
    """Return (path, text) pairs in a stable order, plus the number skipped."""
    if not root.exists():
        raise SystemExit(f"{root} does not exist")
    candidates = sorted(root.rglob("*.py"))
    files = [path for path in candidates if not set(path.parts) & VENDOR_PARTS]
    if not files:
        raise SystemExit(f"no authored Python file under {root}")
    skipped = len(candidates) - len(files)
    return ([(path.as_posix(), path.read_text(encoding="utf-8")) for path in files], skipped)


def verify_all(outcomes, sources, verifiers):
    """Recompute each determined verdict through the registered verifier."""
    counts = Counter()
    for outcome, (path, source) in zip(outcomes, sources):
        if not outcome.determined:
            counts["abstained"] += 1
            continue
        payload = {
            "source": source,
            "path": path,
            "policy_version": outcome.policy_version,
            "claimed": {
                "band": outcome.band,
                "deficit": outcome.deficit,
                "content_hash": outcome.content_hash,
            },
        }
        verdict = verifiers.verify(AUDIT_VERIFIER_ID, AUDIT_VERIFIER_VERSION, payload)
        counts[str(verdict.verdict)] += 1
    return counts


def summarise(outcomes, reused, verdict_counts, skipped) -> dict[str, Any]:
    determined = [outcome for outcome in outcomes if outcome.determined]
    deficits = [outcome.deficit for outcome in determined if outcome.deficit is not None]
    rules = Counter()
    for outcome in determined:
        rules.update(outcome.rule_counts)
    return {
        "kind": "static_audit_suite",
        "data_origin": DATA_ORIGIN,
        "policy_base": POLICY_BASE,
        "policy_version": outcomes[0].policy_version if outcomes else None,
        "files": len(outcomes),
        "skipped_vendor_files": skipped,
        "determined": len(determined),
        "abstained": len(outcomes) - len(determined),
        "bands": dict(sorted(Counter(o.band for o in outcomes).items())),
        "roles": dict(sorted(Counter(o.role for o in outcomes).items())),
        "mean_deficit": round(sum(deficits) / len(deficits), 4) if deficits else None,
        "max_deficit": round(max(deficits), 4) if deficits else None,
        "rule_counts": dict(sorted(rules.items())),
        "reused_on_second_pass": reused,
        "verification": dict(sorted(verdict_counts.items())),
        "claim": "measured local audit; no model call and no saving claim",
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary_path = out / "summary.json"
    export_path = out / "records.jsonl"
    for target in (summary_path, export_path):
        if target.exists():
            raise SystemExit(f"{target} already exists; use another --out directory")

    recorded_at = args.timestamp or datetime.now(timezone.utc).isoformat()
    policy = audit_policy_version(POLICY_BASE)
    sources, skipped = read_sources(Path(args.root))
    verifiers = VerifierRegistry()
    register_audit_verifiers(verifiers)

    first_pass = []
    reused = 0
    with SqliteAuditStore(out / "audit.sqlite3") as store:
        for index, (path, source) in enumerate(sources):
            first_pass.append(
                audit_source(
                    AuditRequest(f"audit-{index:04d}", path, source),
                    policy_version=policy,
                    store=store,
                    recorded_at=recorded_at,
                    project_id=PROJECT_ID,
                    data_origin=DATA_ORIGIN,
                )
            )
        for index, (path, source) in enumerate(sources):
            second = audit_source(
                AuditRequest(f"audit-{index:04d}", path, source),
                policy_version=policy,
                store=store,
                recorded_at=recorded_at,
                project_id=PROJECT_ID,
                data_origin=DATA_ORIGIN,
            )
            reused += 1 if second.reused else 0
        records = store.count()
        exported = store.export_jsonl(export_path)

    verdict_counts = verify_all(first_pass, sources, verifiers)
    summary = summarise(first_pass, reused, verdict_counts, skipped)
    summary["records"] = records
    summary["exported_lines"] = exported
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + chr(10), encoding="utf-8", newline=chr(10))

    print("root:", args.root)
    print("files audited:", summary["files"])
    print("skipped (vendor, cache, build):", summary["skipped_vendor_files"])
    print("bands:", summary["bands"])
    print("roles:", summary["roles"])
    print("mean deficit (determined):", summary["mean_deficit"])
    print("rule findings:", summary["rule_counts"])
    print("reused verdicts on the second pass:", summary["reused_on_second_pass"])
    print("verification:", summary["verification"])
    print("export:", export_path, f"({exported} line(s))")
    print("note:", summary["claim"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
