"""Print an authored fixture catalogue; no files, models or services are used.

The fixture coordinates are synthetic. Semantic scene
recognition is not demonstrated. Run with --summary for a compact walkthrough.
"""

from __future__ import annotations

import argparse
import io
import json
import struct
import wave
import zlib

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset


def _png() -> bytes:
    def chunk(kind: bytes, content: bytes) -> bytes:
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")


def _wav() -> bytes:
    data = io.BytesIO()
    with wave.open(data, "wb") as output:
        output.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
        output.writeframes(b"\x00\x00" * 16)
    return data.getvalue()


def build_demo_catalogue() -> list[dict]:
    fixtures = [
        ("image", "portrait.jpg", _png()),
        ("text", "notes.txt", "Le robot prépare un outil pour le jardin.".encode("utf-8")),
        ("sound", "sound.wav", _wav()),
        ("code", "worker.py", b"def run(operation):\n    try:\n        operation()\n    except Exception:\n        pass\n"),
        ("map", "map.geojson", json.dumps({"type": "Point", "coordinates": [0.0, 0.0]}).encode("utf-8")),
        ("3d", "points.ply", b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n"),
        ("video-container", "clip.mp4", struct.pack(">I", 20) + b"ftypisom" + b"\x00\x00\x00\x00isom"),
    ]
    return [
        inspect_asset(
            data, filename=name, source_id=f"fixture:{identity}", revision="fixture-v1",
            topic_terms={"robotique": ["robot"]} if identity == "text" else None,
        )
        for identity, name, data in fixtures
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", action="store_true")
    arguments = parser.parse_args()
    reports = build_demo_catalogue()
    if arguments.summary:
        result = {
            "data_origin": "authored_fixture",
            "assets": [
                {"id": report["source"]["id"], "format": report["format"]["detected"], "status": report["status"], "tags": [f"{tag['namespace']}:{tag['value']}" for tag in report["tag_proposals"]]}
                for report in reports
            ],
            "image_search": search_asset_reports(reports, tags=["modality:image"]),
            "topic_search": search_asset_reports(reports, tags=["topic:robotique"]),
            "spatial_search": search_asset_reports(reports, bbox=[-1, -1, 1, 1]),
        }
    else:
        result = reports
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
