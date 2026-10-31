"""Prepare a local annotation pack, or demonstrate the context contract on fixtures."""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re

from tiberium_ai.context_review import build_context_review_pack
from tiberium_ai.signature_ingest import read_revision, revision_id
from tiberium_ai.signature_taxonomy import classify_prompt
from tiberium_ai.signature_backends import VerbFrameSignatureBackend
from tiberium_ai.signature_corpus import example_schema
from tiberium_ai.task_signature import predict_signature
from tiberium_ai.task_context import ContextContract, ContextField, enrich_signature_context, reference_payload
from tiberium_ai.verification import VerifierRegistry

ROOT = Path(__file__).resolve().parents[1]
_FRENCH_SIGNAL = re.compile(r"[àâçéèêëîïôùûü]|\b(?:le|les|une|des|dans|avec|pour|ce|cette|fichier|projet|rapport)\b", re.I)


def fixture_report():
    prompt = "récupère les champs de ce fichier"
    schema = example_schema()
    signature = predict_signature(schema, prompt, predictor=VerbFrameSignatureBackend(schema),
        predictor_id="frame.verb-object", predictor_version="1")
    contract = ContextContract("extract.csv-columns", "1", "extract",
        (ContextField("document", "Concrete CSV contents"),), ("document",))
    verifiers = VerifierRegistry()
    verifiers.register("fixture.document-availability", "1", lambda payload: payload["reference_id"] == "attached-doc")
    def proof(ref):
        return verifiers.verify("fixture.document-availability", "1",
            reference_payload(contract, field="document", reference_id=ref, context_revision="snapshot-1"))
    rows = [
        ("mentioned-only", {"values": {}, "context_complete": True}, "missing_context"),
        ("inline-csv", {"values": {"document": "name,age\nAda,36"}}, "ready"),
        ("uncaptured-context", {}, "context_unknown"),
        ("unverified-reference", {"references": {"document": "attached-doc"}}, "context_unknown"),
        ("verified-reference", {"references": {"document": "attached-doc"}, "reference_evidence": {"document": proof("attached-doc")}, "verifiers": verifiers}, "ready"),
        ("unavailable-reference", {"references": {"document": "missing-doc"}, "reference_evidence": {"document": proof("missing-doc")}, "verifiers": verifiers}, "missing_context"),
        ("stale-reference", {"context_revision": "snapshot-2", "references": {"document": "attached-doc"}, "reference_evidence": {"document": proof("attached-doc")}, "verifiers": verifiers}, "context_unknown"),
    ]
    cases = []
    for case_id, inputs, expected in rows:
        result = enrich_signature_context(signature, prompt, contract,
            **{"context_revision": "snapshot-1", **inputs}).to_record()
        if result["status"] != expected:
            raise ValueError("fixture context verdict did not match its authored contract")
        cases.append({"case_id": case_id, "expected": expected, "result": result})
    return {"kind": "context_fixture_pilot", "data_origin": "fixture", "cases": cases,
        "model_inference_executed": False, "claim_allowed": False, "auto_act_allowed": False}


def prepare_pack(path, *, limit=120, seed=20261007):
    source_bytes = Path(path).read_bytes()
    revision = read_revision(path)
    if source_bytes != Path(path).read_bytes():
        raise ValueError("corpus changed during preparation")
    if revision.get("revision_id") != revision_id(revision["prompts"]):
        raise ValueError("corpus revision does not match its content")
    candidates = [row for row in revision["prompts"] if not row.get("truncated")
        and isinstance(row.get("text"), str) and 40 <= len(row["text"]) <= 2000
        and classify_prompt(row["text"])[0] == "ask" and _FRENCH_SIGNAL.search(row["text"])]
    pack = build_context_review_pack(candidates, corpus_revision=revision["revision_id"], limit=limit, seed=seed)
    pack["selection_filters"] = {"classify_prompt": "ask", "chars": [40, 2000], "exclude_truncated": True,
        "language_filter": "French lexical signal only; human language review required"}
    pack["source_file_sha256"] = sha256(source_bytes).hexdigest()
    return pack


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20261007)
    args = parser.parse_args(argv)
    # Real prompt text must remain inside the repository's ignored local run area.
    output = args.output.resolve()
    if args.corpus:
        output.relative_to((ROOT / "runs").resolve())
    report = prepare_pack(args.corpus, limit=args.limit, seed=args.seed) if args.corpus else fixture_report()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"kind": report["kind"], "cases": report.get("selected_count", len(report["cases"])),
        "labelled_cases": report.get("labelled_cases"), "split_status": report.get("split_status"),
        "claim_allowed": False, "model_inference_executed": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
