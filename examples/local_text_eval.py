"""Plan, explicitly capture, and replay text-only authored local-model fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from tiberium_ai.local_text_eval import capture, compare, load_corpus, replay


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ValueError("invalid arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    default_corpus = Path(__file__).resolve().parent / "fixtures" / "local_text_cases_fr.json"
    for name in ("plan", "capture", "replay", "compare"):
        command = commands.add_parser(name)
        command.add_argument("--corpus", type=Path, default=default_corpus)
        if name == "capture":
            command.add_argument("--model", required=True)
            command.add_argument("--out", type=Path, required=True)
            command.add_argument("--base-url", default="http://127.0.0.1:1234")
            command.add_argument("--allow-lan", action="store_true")
            command.add_argument("--resources-checked", action="store_true")
            command.add_argument("--max-tokens", type=int, default=512)
            command.add_argument("--temperature", type=float, default=0.1)
            command.add_argument("--timeout", type=float, default=30)
            command.add_argument("--total-timeout", type=float, default=300)
            command.add_argument("--machine-id")
            command.add_argument("--runtime-version")
            command.add_argument("--model-revision")
        elif name == "replay":
            command.add_argument("--run", type=Path, required=True)
        elif name == "compare":
            command.add_argument("--left", type=Path, required=True)
            command.add_argument("--right", type=Path, required=True)
    try:
        arguments = vars(parser.parse_args(argv))
        command = arguments.pop("command")
        corpus = load_corpus(arguments.pop("corpus"))
        if command == "plan":
            report = {"kind": "local_text_eval_plan", "schema_version": 1,
                      "case_count": len(corpus["cases"]), "label_origin": corpus["label_origin"],
                      "cases": [{"id": c["id"], "family": c["family"]} for c in corpus["cases"]],
                      "inference_attempted": False, "auto_act_allowed": False, "saving_claim": False}
        elif command == "capture":
            destination = arguments.pop("out")
            report = capture(corpus, destination, **arguments)
        elif command == "replay":
            report = replay(corpus, arguments["run"])
        else:
            report = compare(corpus, arguments["left"], arguments["right"])
        print(json.dumps(report, ensure_ascii=True, allow_nan=False))
        return 2 if command == "capture" and report["stop_reason"] is not None else 0
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        # Do not echo URLs, source texts, model replies or private local paths.
        print(json.dumps({"status": "error", "error_type": "invalid_input_or_capture"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
