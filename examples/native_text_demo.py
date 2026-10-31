"""Authored native text fixtures and an explicit backend demonstration.

PNG text was rendered once with DejaVuSans32; using the fixture needs no image
library. PDF text uses a built-in font. Both sources are synthetic test data.
"""
from __future__ import annotations
import argparse
import base64
import json
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_text_extract import extract_asset_text
from tiberium_ai.asset_text_enrichment import enrich_asset_with_text
from tiberium_ai.asset_catalog import search_asset_reports

PNG_B64 = """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"""


def ocr_png_fixture() -> bytes:
    return base64.b64decode(PNG_B64, validate=True)


def pdf_fixture() -> bytes:
    content = b"BT /F1 22 Tf 30 160 Td (PARCIMONIA ROBOT GARDEN 2026) Tj ET\n"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 640 240] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n" + content + b"endstream",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(document))
        document.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    start = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        document.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    document.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode("ascii"))
    return bytes(document)


def run_demo(backend: str) -> dict:
    data = ocr_png_fixture() if backend == "tesseract" else pdf_fixture()
    name = "fixture.png" if backend == "tesseract" else "fixture.pdf"
    inspection = inspect_asset(data, filename=name, source_id="fixture:native-text", revision="v1")
    extraction = extract_asset_text(data, filename=name, source_id="fixture:native-text", revision="v1", backend=backend)
    result = {"data_origin": "authored_fixture", "extraction": extraction, "enriched": None, "search": None}
    if extraction["status"] == "completed":
        enriched = enrich_asset_with_text(inspection, extraction, topic_terms={"robotique": ["robot"], "jardin": ["garden"]})
        result["enriched"] = enriched
        result["search"] = search_asset_reports([enriched], tags=["topic:robotique"])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", required=True, choices=["tesseract", "pdftotext"])
    result = run_demo(parser.parse_args().backend)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))
    raise SystemExit(0 if result["extraction"]["status"] == "completed" else 3)
