"""JSON command interface for host tools, scripts and hooks. No network by default."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys

from ..reflex import InjectedReflexBackend
from .._version import __version__
from ..registry import _reject_constant, _reject_duplicate_keys
from .benchmark import compare_pipelines
from .browser import BrowserRunner, BrowserSnapshot, Control
from .catalog import SkillCatalog
from .cache import CachedBackend
from .core import DecisionSession, fingerprint
from .providers import TypeSafeBackend
from .source_triage import assess_novelty, triage_attention, retrieve_source_candidates
from .recipes import (audit_skills, check_rules, classify_feedback, compact_context,
                      lexical_files, rank_files, select_skill, trace_requirements, triage_review)


MAX_INPUT_BYTES = 16 * 1024 * 1024


def _finite_float(text):
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("JSON number must be finite")
    return value


def _read_json(path=None):
    if path is None:
        text = sys.stdin.read(MAX_INPUT_BYTES + 1)
        size = len(text.encode("utf-8"))
    else:
        with path.open("rb") as stream:
            raw = stream.read(MAX_INPUT_BYTES + 1)
        size = len(raw)
        text = raw.decode("utf-8")
    if size > MAX_INPUT_BYTES:
        raise ValueError("JSON input exceeds read budget")
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys,
                      parse_constant=_reject_constant, parse_float=_finite_float)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=f"Parcimonia {__version__}")
    p.add_argument("recipe", choices=["index", "usage", "audit-skills", "skill", "rank",
                   "compact", "review", "rules", "requirements", "feedback", "browser", "compare",
                   "attention", "novelty", "source-search"])
    p.add_argument("--input", type=Path, help="JSON file; otherwise read stdin")
    p.add_argument("--db", type=Path, help="explicit local SQLite path for skill operations")
    p.add_argument("--answers", type=Path, help="normalized recorded Reflex answers (offline)")
    p.add_argument("--allow-network", action="store_true", help="allow bounded paid TypeSafe calls")
    p.add_argument("--model", help="pinned TypeSafe model; key from TYPESAFE_API_KEY")
    p.add_argument("--cache", type=Path, help="explicit local SQLite decision cache")
    p.add_argument("--max-calls", type=int, default=16)
    p.add_argument("--csv", type=Path, help="exclusive-create audit CSV")
    p.add_argument("--enforce-rules", action="store_true", help="rules hook: exit 10 block, 11 review")
    args = p.parse_args(argv)
    cached = None
    try:
        if args.enforce_rules and args.recipe != "rules":
            raise ValueError("--enforce-rules requires rules recipe")
        data = _read_json(args.input)
        if not isinstance(data, dict):
            raise ValueError("input must be an object")
        if args.answers and args.allow_network:
            raise ValueError("choose offline answers or network")
        backend = None
        if args.answers:
            backend = InjectedReflexBackend(_read_json(args.answers), latin_only=False)
        if args.allow_network:
            backend = TypeSafeBackend(api_key=os.environ.get("TYPESAFE_API_KEY", ""),
                                      model=args.model or "", allow_network=True, max_calls=args.max_calls)
        if args.cache and backend is not None:
            identity = args.model if args.allow_network else "recorded/" + fingerprint(backend.answers)
            cached = CachedBackend(backend, args.cache, identity=identity)
            backend = cached
        session = DecisionSession(backend, max_calls=args.max_calls)
        if args.recipe in {"index", "usage", "audit-skills", "skill"}:
            if args.db is None:
                raise ValueError("--db required")
            with SkillCatalog(args.db) as catalog:
                if args.recipe == "index":
                    result = catalog.sync(data["root"], at=data.get("at", datetime.now(timezone.utc).isoformat()))
                elif args.recipe == "usage":
                    result = {"inserted": catalog.record_use(**data)}
                elif args.recipe == "audit-skills":
                    result = audit_skills(catalog.rows()).to_dict()
                    if args.csv:
                        rows = result["data"]
                        with args.csv.open("x", newline="", encoding="utf-8") as output:
                            writer = csv.DictWriter(output, fieldnames=["id", "name", "uses", "last_used", "recommendation", "reason"])
                            writer.writeheader()
                            for row in rows:
                                safe = {k: row[k] for k in writer.fieldnames}
                                # Spreadsheet formula injection from untrusted skill metadata.
                                for k, v in safe.items():
                                    if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")):
                                        safe[k] = "'" + v
                                writer.writerow(safe)
                else:
                    candidates = catalog.shortlist(data["query"], eligible_ids=data.get("eligible_ids"))
                    if data.get("explicit_id"):
                        candidates = [r for r in catalog.rows() if r["id"] == data["explicit_id"] and
                                      (data.get("eligible_ids") is None or r["id"] in data["eligible_ids"])]
                    result = select_skill(data["query"], candidates, session, explicit_id=data.get("explicit_id")).to_dict()
        elif args.recipe == "rank":
            files = data.get("files")
            if files is None:
                files = lexical_files(data["root"], data["query"])
            result = rank_files(data["query"], files, session, top_k=data.get("top_k", 5)).to_dict()
        elif args.recipe == "compact":
            result = compact_context(data["blocks"], session, query=data["query"],
                                     target_chars=data.get("target_chars", 20000)).to_dict()
        elif args.recipe == "review":
            result = triage_review(data["changes"], session, rules=data.get("rules", [])).to_dict()
        elif args.recipe == "rules":
            result = check_rules(data["change"], data["rules"], session).to_dict()
        elif args.recipe == "requirements":
            result = trace_requirements(data["requirements"], data["tests"], session).to_dict()
        elif args.recipe == "feedback":
            result = classify_feedback(data["records"], session).to_dict()
        elif args.recipe == "attention":
            result = triage_attention(data["source"], data["context"], session).to_dict()
        elif args.recipe == "novelty":
            result = assess_novelty(data["source"], data["candidates"], session).to_dict()
        elif args.recipe == "source-search":
            result = retrieve_source_candidates(data["source"], data["records"],
                limit=data.get("limit", 8), max_records=data.get("max_records", 500),
                max_bytes=data.get("max_bytes", 1048576))
        elif args.recipe == "browser":
            s = data["snapshot"]
            snapshot = BrowserSnapshot(s["version"], s["url"], tuple(Control(**c) for c in s["controls"]))
            result = BrowserRunner(session).run(data["goal"], observe=lambda: snapshot,
                         verify_goal=lambda _: False, execute=lambda *_: None).to_dict()
        else:
            result = compare_pipelines(data["baseline"], data["candidate"])
        print(json.dumps({"result": result, "calls": session.calls}, ensure_ascii=False, allow_nan=False))
        if args.enforce_rules:
            return {"pass": 0, "block": 10, "review": 11}[result["data"]["verdict"]]
        return 0
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError) as error:
        print(json.dumps({"error": type(error).__name__, "detail": "invalid input or unavailable resource"}))
        return 2
    finally:
        if cached is not None:
            cached.close()


if __name__ == "__main__":
    raise SystemExit(main())
