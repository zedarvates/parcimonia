"""Prepare a blind review from bounded, hash-checked saved public sources."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tiberium_ai.agent_recipes.source_review import (
    build_source_review_pack, load_saved_source_manifest, source_comparison_readiness, source_review_template,
)
from tiberium_ai.agent_recipes.source_review_ui import render_source_review

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT = {"id": "parcimonia.source-triage", "revision": "project-objective-20261008",
    "objective": "Comparer des mecanismes de decision bornes pour Parcimonia, avec preuves et cout total",
    "constraints": ["Conserver les corrections et contradictions", "Aucune execution de code source externe",
                    "Separer mesures auteur, fixtures et resultats observes"],
    "required_context": ["evaluation_scope"],
    "values": {"evaluation_scope": "Routage, tri de sources, nouveaute, contrats, ressources et verification"}}


def prepare(manifest, output, *, context=None):
    output = Path(output).resolve()
    output.relative_to((ROOT / "runs").resolve())
    if output.exists():
        raise FileExistsError("choose a new source review directory")
    captured = load_saved_source_manifest(manifest)
    packet = build_source_review_pack(captured["records"], DEFAULT_CONTEXT if context is None else context)
    files = {"capture-provenance.json": json.dumps(captured, ensure_ascii=False, indent=2, allow_nan=False),
             "review-packet.json": json.dumps(packet, ensure_ascii=False, indent=2, allow_nan=False),
             "review-template.json": json.dumps(source_review_template(packet), ensure_ascii=False, indent=2, allow_nan=False),
             "comparison-readiness.json": json.dumps(source_comparison_readiness(packet), indent=2, allow_nan=False),
             "review.html": render_source_review(packet)}
    output.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for name, text in files.items():
        content = (text + "\n").encode("utf-8")
        with (output / name).open("xb") as stream:
            stream.write(content)
        hashes[name] = sha256(content).hexdigest()
    summary = {"schema": "source-review-preparation/1", "packet_id": packet["pack_id"],
        "source_manifest_sha256": captured["manifest_sha256"], "files": hashes,
        "captured_records": len(captured["records"]), "cases": len(packet["cases"]),
        "lineages": len({row["provenance"]["lineage_id"] for row in captured["records"]}),
        "read_bytes": captured["read_bytes"], "human_reviewed_cases": 0,
        "independent_labels_established": False, "quality_metrics": None, "cost_savings": None,
        "model_inference_executed": False, "automatic_routing_activated": False}
    with (output / "manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--context", type=Path, help="explicit trusted host context JSON")
    args = parser.parse_args(argv)
    context = json.loads(args.context.read_text(encoding="utf-8")) if args.context else None
    result = prepare(args.manifest, args.output_dir, context=context)
    print(json.dumps({key: value for key, value in result.items() if key != "files"}, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
