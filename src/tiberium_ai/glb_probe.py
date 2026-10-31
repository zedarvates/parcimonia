"""Bounded GLB chunk framing and core buffer/image declaration inventory.

No URI is resolved or decoded. Meshes, accessors, pixels, extensions and scene
semantics are not validated; this is not a full glTF validator or renderer.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import struct
from typing import Any

from .asset_tag_journal import _validate_report_json
from .geo_probe import _reject_constant, _unique_object
from .media_probe import probe_media

__all__ = ["PROFILE_ID", "probe_glb"]

PROFILE_ID = "parcimonia.glb-core-resources/v1"
_JSON = 0x4E4F534A
_BIN = 0x004E4942
_MAX_JSON = 256 * 1024
_ARRAYS = ("scenes", "nodes", "meshes", "materials", "textures", "samplers",
           "accessors", "animations", "skins", "cameras")


class _InvalidGLB(ValueError):
    pass


def _integer(value: Any, *, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= 2**32-1:
        raise _InvalidGLB("glb_resource_integer_outside_profile")
    return value


def _text(value: Any, maximum: int) -> str:
    if (type(value) is not str or not value or value != value.strip()
            or len(value.encode("utf-8")) > maximum or any(ord(c) < 32 for c in value)):
        raise _InvalidGLB("glb_resource_text_outside_profile")
    return value


def _objects(document: dict[str, Any], name: str, maximum: int) -> list[dict[str, Any]]:
    value = document.get(name, [])
    if type(value) is not list or len(value) > maximum or any(type(item) is not dict for item in value):
        raise _InvalidGLB("glb_declaration_array_outside_profile")
    return value


def _chunks(data: bytes) -> list[dict[str, Any]]:
    chunks = []
    offset = 12
    seen: set[int] = set()
    while offset < len(data):
        if len(chunks) >= 16:
            raise _InvalidGLB("glb_chunk_budget_exceeded")
        if offset + 8 > len(data):
            raise _InvalidGLB("glb_chunk_header_truncated")
        length, kind = struct.unpack_from("<II", data, offset)
        start, end = offset + 8, offset + 8 + length
        if length % 4 or end > len(data):
            raise _InvalidGLB("glb_chunk_extent_invalid")
        if not chunks and kind != _JSON:
            raise _InvalidGLB("glb_first_chunk_must_be_json")
        if kind in {_JSON, _BIN}:
            if kind in seen or (kind == _JSON and chunks) or (kind == _BIN and len(chunks) != 1):
                raise _InvalidGLB("glb_known_chunk_order_or_count_invalid")
            seen.add(kind)
        chunks.append({"index": len(chunks), "type_hex": f"{kind:08x}",
                       "kind": "JSON" if kind == _JSON else "BIN" if kind == _BIN else "unknown",
                       "header_range": [offset, start], "byte_range": [start, end]})
        offset = end
    if not chunks:
        raise _InvalidGLB("glb_json_chunk_missing")
    return chunks


def _uri(value: Any) -> dict[str, Any]:
    # This is declaration classification, not URI syntax/content validation.
    uri = _text(value, 64 * 1024)
    embedded = uri[:5].lower() == "data:"
    if not embedded and len(uri.encode("utf-8")) > 2048:
        raise _InvalidGLB("glb_external_uri_budget_exceeded")
    payload = uri.encode("utf-8")
    return {"storage": "data_uri" if embedded else "external_uri", "uri": None if embedded else uri,
            "uri_sha256": hashlib.sha256(payload).hexdigest(), "uri_bytes": len(payload),
            "availability": "not_checked"}


def _inventory(document: Any, chunks: list[dict[str, Any]], data: bytes) -> tuple[dict, list, list, list]:
    if type(document) is not dict or type(document.get("asset")) is not dict or document["asset"].get("version") != "2.0":
        raise _InvalidGLB("glb_gltf_version_outside_profile")
    if "minVersion" in document["asset"] and document["asset"]["minVersion"] != "2.0":
        raise _InvalidGLB("glb_min_version_outside_profile")
    arrays = {name: _objects(document, name, 256) for name in _ARRAYS}
    buffers = _objects(document, "buffers", 64)
    views = _objects(document, "bufferViews", 256)
    images = _objects(document, "images", 64)
    extensions = []
    for name in ("extensionsUsed", "extensionsRequired"):
        values = document.get(name, [])
        if type(values) is not list or len(values) > 64:
            raise _InvalidGLB("glb_extensions_outside_profile")
        for value in values:
            _text(value, 128)
        if len(values) != len(set(values)):
            raise _InvalidGLB("glb_extensions_outside_profile")
        extensions.append(list(values))
    if not set(extensions[1]) <= set(extensions[0]):
        raise _InvalidGLB("glb_required_extension_not_declared_used")
    binary = next((chunk for chunk in chunks if chunk["kind"] == "BIN"), None)
    resources = []
    for index, buffer in enumerate(buffers):
        length = _integer(buffer.get("byteLength"), minimum=1)
        resource = {"kind": "buffer", "index": index, "pointer": f"/buffers/{index}", "declared_bytes": length}
        if "uri" in buffer:
            resource.update(_uri(buffer["uri"]))
        else:
            if index != 0:
                raise _InvalidGLB("glb_implicit_buffer_outside_profile")
            if binary is None:
                raise _InvalidGLB("glb_bin_buffer_missing")
            start, end = binary["byte_range"]
            if not length <= end - start <= length + 3:
                raise _InvalidGLB("glb_bin_buffer_extent_mismatch")
            if any(data[start + length:end]):
                raise _InvalidGLB("glb_bin_padding_not_zero")
            resource.update(storage="bin_chunk", availability="range_present",
                            byte_range=[start, start + length])
        resources.append(resource)
    for view in views:
        buffer_index = _integer(view.get("buffer"))
        offset = _integer(view.get("byteOffset", 0))
        length = _integer(view.get("byteLength"), minimum=1)
        if buffer_index >= len(buffers) or offset + length > buffers[buffer_index]["byteLength"]:
            raise _InvalidGLB("glb_buffer_view_out_of_declared_bounds")
    for index, image in enumerate(images):
        if ("uri" in image) == ("bufferView" in image):
            raise _InvalidGLB("glb_image_core_source_outside_profile")
        mime = _text(image["mimeType"], 128) if "mimeType" in image else None
        resource = {"kind": "image", "index": index, "pointer": f"/images/{index}", "declared_mime_type": mime}
        if "uri" in image:
            resource.update(_uri(image["uri"]))
        else:
            if mime is None:
                raise _InvalidGLB("glb_buffer_view_image_mime_missing")
            view_index = _integer(image["bufferView"])
            if view_index >= len(views):
                raise _InvalidGLB("glb_image_buffer_view_out_of_range")
            view = views[view_index]
            owner = resources[view["buffer"]]
            resource.update(storage="buffer_view", buffer_view=view_index, buffer=view["buffer"],
                            availability="range_present" if owner["storage"] == "bin_chunk" else "not_checked")
            if owner["storage"] == "bin_chunk":
                start = owner["byte_range"][0] + view.get("byteOffset", 0)
                resource["byte_range"] = [start, start + view["byteLength"]]
        resources.append(resource)
    counts = {name: len(value) for name, value in arrays.items()}
    counts.update(buffers=len(buffers), bufferViews=len(views), images=len(images))
    return counts, resources, extensions[0], extensions[1]


def probe_glb(data: bytes, *, complete: bool = True) -> dict[str, Any] | None:
    """Atomically inventory this core profile, retaining only headers on refusal."""
    base = probe_media(data, complete=complete)
    if base is None or base["format"] != "glb":
        return None
    report = deepcopy(base)
    report["spatial"] = None
    if not complete:
        report["issues"].append("glb_complete_source_required")
        return report
    if report["issues"]:
        report["issues"].append("glb_header_unusable")
        return report
    try:
        chunks = _chunks(data)
        start, end = chunks[0]["byte_range"]
        if end - start > _MAX_JSON:
            raise _InvalidGLB("glb_json_byte_budget_exceeded")
        document = json.loads(data[start:end].decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        _validate_report_json(document)
        counts, resources, used, required = _inventory(document, chunks, data)
    except _InvalidGLB as exc:
        report["issues"].append(str(exc))
        return report
    except (ValueError, UnicodeError, TypeError, RecursionError, OverflowError):
        report["issues"].append("glb_json_unusable")
        return report
    report["analysis_scope"] = "glb_core_resource_profile"
    report["issues"].append("glb_profile_not_full_gltf_validation")
    report["evidence"].append({"id": "glb:chunks", "kind": "bounded_glb_chunks", "profile": PROFILE_ID,
                               "byte_range": [12, len(data)], "chunks": chunks})
    report["evidence"].append({"id": "glb:json", "kind": "parsed_gltf_json", "profile": PROFILE_ID,
                               "byte_range": chunks[0]["byte_range"]})
    proposals: dict[str, list[str]] = {"glb_json_read": ["glb:json"]}
    for resource in resources:
        ref = f"glb:resource:{resource['kind']}:{resource['index']}"
        report["evidence"].append({"id": ref, "kind": "core_resource_declaration",
                                   "json_pointer": resource["pointer"], "evidence_refs": ["glb:json"],
                                   **({"byte_range": list(resource["byte_range"])} if "byte_range" in resource else {})})
        resource["evidence_ref"] = ref
        key = {"external_uri": "external_uri_declared", "data_uri": "data_uri_declared",
               "bin_chunk": "bin_buffer_range_present", "buffer_view": "buffer_view_image_declared"}[resource["storage"]]
        proposals.setdefault(key, []).append(ref)
    unknown = sum(chunk["kind"] == "unknown" for chunk in chunks)
    if unknown:
        report["issues"].append("glb_unknown_chunks_not_interpreted")
    if used:
        report["issues"].append("gltf_extensions_not_interpreted")
    values = {"gltf_declared_counts": counts, "gltf_core_resources": resources,
              "gltf_extensions_used": used, "gltf_extensions_required": required,
              "glb_chunk_count": len(chunks), "glb_unknown_chunk_count": unknown}
    for name, value in values.items():
        report["metadata"].append({"name": name, "value": value, "basis": "parsed_core_resource_declarations",
                                   "evidence_ref": "glb:chunks" if name.startswith("glb_") else "glb:json"})
    report["tag_proposals"].extend({"namespace": "resource", "value": key,
                                     "basis": "parsed_core_resource_declarations", "evidence_refs": refs}
                                    for key, refs in sorted(proposals.items()))
    return report
