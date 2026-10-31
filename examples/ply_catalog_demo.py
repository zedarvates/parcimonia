"""Authored PLY bodies through local geometry observations and tag review.

The coordinates are invented file-local values with unknown units. Nothing is
rendered, executed, downloaded or interpreted as GPS. Gaussian properties are
raw exported parameters: their signs and quaternion norm do not qualify the
appearance, training quality or renderer compatibility of a scene.
"""

from __future__ import annotations

import argparse
import json
import struct

from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import create_asset_catalog, export_asset_reports, put_asset_report
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal, validated_review_report_hash
from tiberium_ai.asset_tag_review import project_tag_reviews, search_reviewed_assets


KINDS = ("cloud", "mesh", "splat")
REPRESENTATIONS = {
    "cloud": "point_cloud_structure",
    "mesh": "mesh_structure",
    "splat": "gaussian_splat_body_candidate",
}
GAUSSIAN_PROPERTIES = (
    "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
    "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
)


def cloud_fixture(*, shift_x: float = 0.0) -> bytes:
    """Return an ASCII cloud with tied extrema and authored local coordinates."""
    header = (
        "ply\nformat ascii 1.0\ncomment authored fixture, units unknown\n"
        "element vertex 3\nproperty float x\nproperty float y\nproperty float z\nend_header\n"
    )
    points = [(1.0 + shift_x, 2.0, 0.0), (-1.0 + shift_x, 3.0, 4.0), (1.0 + shift_x, 2.0, -2.0)]
    body = "".join(" ".join(str(value) for value in point) + "\n" for point in points)
    return (header + body).encode("ascii")


def mesh_fixture(endianness: str = "big", *, shift_x: float = 0.0) -> bytes:
    """Return one binary quad, reordered XYZ and additional scalar properties."""
    if endianness not in {"little", "big"}:
        raise ValueError("endianness must be little or big.")
    marker = "<" if endianness == "little" else ">"
    header = (
        f"ply\nformat binary_{endianness}_endian 1.0\n"
        "comment authored polygon mesh, no triangulation claimed\n"
        "element vertex 4\nproperty ushort quality\nproperty float z\n"
        "property float x\nproperty double y\nproperty char marker\n"
        "element face 1\nproperty float roughness\n"
        "property list uchar int vertex_indices\nproperty ushort material\nend_header\n"
    ).encode("ascii")
    points = [(1.0, 2.0, 0.0), (2.0, 2.0, 1.0), (2.0, 3.0, 2.0), (1.0, 3.0, 3.0)]
    vertices = b"".join(
        struct.pack(marker + "Hffdb", 100 + index, z, x + shift_x, y, -index)
        for index, (x, y, z) in enumerate(points)
    )
    face = struct.pack(marker + "fB4iH", 0.25, 4, 0, 1, 2, 3, 7)
    return header + vertices + face


def splat_fixture(*, shift_x: float = 0.0) -> bytes:
    """Return raw finite Gaussian parameters without activation or normalization."""
    header = (
        "ply\nformat binary_little_endian 1.0\ncomment authored raw Gaussian parameters\n"
        "element vertex 2\n" + "".join(f"property float {name}\n" for name in GAUSSIAN_PROPERTIES)
        + "end_header\n"
    ).encode("ascii")
    rows = [
        (1.0 + shift_x, 2.0, 3.0, 0.1, -0.2, 0.3, -2.0, -1.0, -2.0, -3.0, 2.0, 0.0, 0.0, 0.0),
        (-1.0 + shift_x, 4.0, 0.0, -0.1, 0.2, -0.3, -2.0, -1.0, -2.0, -3.0, 0.0, 3.0, 0.0, 0.0),
    ]
    return header + b"".join(struct.pack("<14f", *row) for row in rows)


def fixture_bytes(kind: str, *, shift_x: float = 0.0) -> bytes:
    if kind == "cloud":
        return cloud_fixture(shift_x=shift_x)
    if kind == "mesh":
        return mesh_fixture(shift_x=shift_x)
    if kind == "splat":
        return splat_fixture(shift_x=shift_x)
    raise ValueError("kind must be cloud, mesh or splat.")


def _run_fixture(kind: str) -> dict:
    identity = {"filename": f"{kind}.ply", "source_id": f"fixture:ply:{kind}", "revision": "authored-v1"}
    report = inspect_asset(fixture_bytes(kind), **identity)
    empty = create_asset_catalog(f"fixture:ply-catalog:{kind}")
    catalog = put_asset_report(empty, report, expected_head=empty["snapshot_hash"], expected_report_hash=None)
    catalog = json.loads(json.dumps(catalog, ensure_ascii=False, allow_nan=False))
    reports = export_asset_reports(catalog)
    tag = REPRESENTATIONS[kind]
    journal = create_tag_journal()
    before = search_reviewed_assets(reports, journal, tags=[f"representation:{tag}"])
    accepted = append_tag_decision(
        journal, report, namespace="representation", value=tag, action="accept",
        actor_id="fixture:reviewer", reason="Authored PLY body profile inspected.",
        event_id=f"fixture:ply-review:{kind}", expected_head=None,
    )
    after = search_reviewed_assets(reports, accepted, tags=[f"representation:{tag}"])
    changed_report = inspect_asset(fixture_bytes(kind, shift_x=0.25), **identity)
    changed_catalog = put_asset_report(
        catalog, changed_report, expected_head=catalog["snapshot_hash"],
        expected_report_hash=validated_review_report_hash(report),
    )
    changed = export_asset_reports(changed_catalog)
    metadata = {item["name"]: item["value"] for item in report["metadata"]}
    evidence = {item["id"]: item for item in report["evidence"]}
    return {
        "kind": kind, "source_sha256": report["sample"]["content_sha256"],
        "report_hash": validated_review_report_hash(report), "analyser": report["analyser"],
        "observed_vertex_count": metadata["observed_vertex_count"],
        "observed_face_count": metadata["observed_face_count"],
        "geometry_bounds_xyz": metadata["geometry_bounds_xyz"], "spatial": report["spatial"],
        "body_tags": [tag for tag in report["tag_proposals"] if "ply:body" in tag["evidence_refs"]],
        "body_evidence": evidence["ply:body"], "extrema_evidence": evidence["ply:position_extrema"],
        "proposed_search_count": search_asset_reports(reports, tags=[f"representation:{tag}"])["count"],
        "accepted_before_review": before["count"], "accepted_after_review": after["count"],
        "gps_bbox_matches": search_reviewed_assets(reports, accepted, tags=[f"representation:{tag}"], bbox=[-5, 0, 5, 5])["count"],
        "changed_report_accepted": search_reviewed_assets(changed, accepted, tags=[f"representation:{tag}"])["count"],
        "changed_review_events": project_tag_reviews(changed, accepted)["unapplied_events"],
        "old_report_still_accepted": search_reviewed_assets(reports, accepted, tags=[f"representation:{tag}"])["count"],
        "catalog_ref": {"generation": catalog["generation"], "snapshot_hash": catalog["snapshot_hash"]},
        "model_calls": report["limits"]["model_calls"],
    }


def run_demo(kind: str | None = None) -> dict:
    if kind is not None and (type(kind) is not str or kind not in KINDS):
        raise ValueError("kind must be cloud, mesh, splat or None for all three.")
    return {
        "data_origin": "authored_fixture_not_rendered_or_georeferenced",
        "fixtures": [_run_fixture(selected) for selected in (KINDS if kind is None else (kind,))],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=KINDS)
    print(json.dumps(run_demo(parser.parse_args().kind), ensure_ascii=True, sort_keys=True, allow_nan=False))
