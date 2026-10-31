"""Authored GLB resource declarations; no URI is opened and no render is made."""

from __future__ import annotations

import json
import struct

from examples.asset_catalog_demo import _png
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal
from tiberium_ai.asset_tag_review import search_reviewed_assets


def glb_bytes(document: dict, binary: bytes | None = None, *, extras: list[tuple[int, bytes]] | None = None) -> bytes:
    payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    payload += b" " * (-len(payload) % 4)
    body = struct.pack("<II", len(payload), 0x4E4F534A) + payload
    if binary is not None:
        binary += b"\0" * (-len(binary) % 4)
        body += struct.pack("<II", len(binary), 0x004E4942) + binary
    for kind, content in extras or []:
        assert len(content) % 4 == 0
        body += struct.pack("<II", len(content), kind) + content
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def fixture() -> tuple[dict, bytes]:
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    png = _png()
    binary = positions + png
    document = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3,
                       "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
        "buffers": [{"byteLength": len(binary)}, {"byteLength": 4, "uri": "geometry/extra.bin"},
                    {"byteLength": 3, "uri": "data:application/octet-stream;base64,AAAA"}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
                        {"buffer": 0, "byteOffset": len(positions), "byteLength": len(png)}],
        "images": [{"bufferView": 1, "mimeType": "image/png"}, {"uri": "textures/bois%20été.png"}],
    }
    return document, binary


def run_demo() -> dict:
    document, binary = fixture()
    payload = glb_bytes(document, binary)
    report = inspect_asset(payload, filename="authored.glb", source_id="fixture:glb", revision="v1")
    journal = create_tag_journal()
    accepted_before = search_reviewed_assets([report], journal, tags=["resource:external_uri_declared"], states=["accepted"])
    journal = append_tag_decision(journal, report, namespace="resource", value="external_uri_declared", action="accept",
                                  actor_id="fixture:reviewer", reason="Reviewed authored URI declarations only",
                                  event_id="fixture:external-refs", expected_head=None)
    changed = inspect_asset(glb_bytes(document, binary[:-1] + b"X"), filename="authored.glb", source_id="fixture:glb", revision="v1")
    return {
        "data_origin": "authored_glb_no_external_file_check_or_render", "report": report,
        "proposed": search_asset_reports([report], tags=["resource:external_uri_declared"])["count"],
        "accepted_before": accepted_before["count"],
        "accepted_after": search_reviewed_assets([report], journal, tags=["resource:external_uri_declared"], states=["accepted"])["count"],
        "accepted_after_binary_change": search_reviewed_assets([changed], journal, tags=["resource:external_uri_declared"], states=["accepted"])["count"],
        "gps_matches": search_asset_reports([report], bbox=[-180, -90, 180, 90])["count"],
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
