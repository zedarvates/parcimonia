"""Bounded media-header observations; no decoding, I/O or source execution.

Recognising a signature or declared field is not validation of a complete
media asset. In particular, PLY properties only support representation
candidates, and an ISO-BMFF/Ogg container does not establish its streams.
"""

from __future__ import annotations

import binascii
import struct
from typing import Any

MAX_SAMPLE_BYTES = 1024 * 1024
MAX_PLY_HEADER_BYTES = 64 * 1024
MAX_PLY_HEADER_LINES = 2048

__all__ = ["probe_media"]


def _report(format_name: str, media_type: str, modalities: list[str], end: int) -> dict[str, Any]:
    reference = f"media:{format_name}:header"
    return {
        "format": format_name,
        "media_type": media_type,
        "modalities": modalities,
        "metadata": [],
        "tag_proposals": [{
            "namespace": "format", "value": format_name,
            "basis": "signature", "evidence_refs": [reference],
        }],
        "evidence": [{"id": reference, "kind": "header", "byte_range": [0, end]}],
        "issues": [],
        "analysis_scope": "header_only",
    }


def _metadata(report: dict[str, Any], name: str, value: Any, *, declared: bool = False) -> None:
    report["metadata"].append({
        "name": name, "value": value,
        "basis": "declared_header" if declared else "parsed_header",
        "evidence_ref": report["evidence"][0]["id"],
    })


def _candidate(report: dict[str, Any], value: str) -> None:
    report["tag_proposals"].append({
        "namespace": "representation", "value": value,
        "basis": "header_schema_candidate",
        "evidence_refs": [report["evidence"][0]["id"]],
    })


def probe_media(data: bytes, *, complete: bool = True) -> dict[str, Any] | None:
    """Observe supported binary/media headers in at most one MiB of bytes.

    ``complete=False`` means these bytes are a prefix rather than the complete
    source. Missing source bytes then remain unobserved, not corrupt by default.
    Header evidence ranges always refer to the bytes actually supplied.
    """
    if type(data) is not bytes or len(data) > MAX_SAMPLE_BYTES:
        raise ValueError("data must be bytes of at most one MiB.")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png(data, complete)
    if data.startswith((b"GIF87a", b"GIF89a")):
        return _gif(data, complete)
    if data.startswith(b"\xff\xd8"):
        return _jpeg(data, complete)
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return _wav(data, complete)
    if data.startswith(b"fLaC"):
        return _report("flac", "audio/flac", ["audio"], 4)
    if data.startswith(b"OggS"):
        return _report("ogg", "application/ogg", ["container"], 4)
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return _bmff(data, complete)
    if data.startswith(b"glTF"):
        return _glb(data, complete)
    if data.startswith((b"ply\n", b"ply\r\n")):
        return _ply(data, complete)
    return None


def _png(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("png", "image/png", ["image"], min(33, len(data)))
    if len(data) < 33:
        report["issues"].append("truncated_png_ihdr" if complete else "png_ihdr_not_in_sample")
        return report
    if data[8:16] != b"\x00\x00\x00\rIHDR":
        report["issues"].append("invalid_png_ihdr")
        return report
    expected_crc = struct.unpack_from(">I", data, 29)[0]
    if binascii.crc32(data[12:29]) & 0xFFFFFFFF != expected_crc:
        report["issues"].append("invalid_png_ihdr_crc")
        return report
    width, height, depth, colour, compression, filtering, interlace = struct.unpack_from(">IIBBBBB", data, 16)
    depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
    if not (0 < width < 2**31 and 0 < height < 2**31 and depth in depths.get(colour, set()) and compression == filtering == 0 and interlace in (0, 1)):
        report["issues"].append("invalid_png_ihdr_fields")
        return report
    _metadata(report, "width", width)
    _metadata(report, "height", height)
    _metadata(report, "bit_depth", depth)
    return report


def _gif(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("gif", "image/gif", ["image"], min(13, len(data)))
    if len(data) < 13:
        report["issues"].append("truncated_gif_logical_screen" if complete else "gif_logical_screen_not_in_sample")
        return report
    width, height = struct.unpack_from("<HH", data, 6)
    if width == 0 or height == 0:
        report["issues"].append("invalid_gif_dimensions")
        return report
    _metadata(report, "width", width)
    _metadata(report, "height", height)
    return report


def _jpeg(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("jpeg", "image/jpeg", ["image"], 2)
    position = 2
    sof = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    for _ in range(512):
        if position >= len(data):
            report["issues"].append("jpeg_frame_header_not_in_sample")
            return report
        if data[position] != 0xFF:
            report["issues"].append("invalid_jpeg_marker")
            return report
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            report["issues"].append("truncated_jpeg_marker" if complete else "jpeg_marker_not_in_sample")
            return report
        marker = data[position]
        position += 1
        if marker in (0xD9, 0xDA):
            report["issues"].append("jpeg_frame_header_not_found")
            return report
        if marker == 0 or marker == 0xD8:
            report["issues"].append("invalid_jpeg_marker")
            return report
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue
        if position + 2 > len(data):
            report["issues"].append("truncated_jpeg_segment" if complete else "jpeg_segment_not_in_sample")
            return report
        size = struct.unpack_from(">H", data, position)[0]
        if size < 2:
            report["issues"].append("invalid_jpeg_segment_length")
            return report
        end = position + size
        if end > len(data):
            report["issues"].append("truncated_jpeg_segment" if complete else "jpeg_segment_not_in_sample")
            return report
        if marker in sof:
            if size < 8:
                report["issues"].append("invalid_jpeg_frame_header")
                return report
            height, width = struct.unpack_from(">HH", data, position + 3)
            components = data[position + 7]
            if width == 0 or height == 0 or components == 0 or size != 8 + 3 * components:
                report["issues"].append("invalid_jpeg_frame_header")
                return report
            report["evidence"][0]["byte_range"][1] = end
            _metadata(report, "width", width)
            _metadata(report, "height", height)
            return report
        position = end
    report["issues"].append("jpeg_segment_budget_exceeded")
    return report


def _wav(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("wav", "audio/wav", ["audio"], 12)
    declared_length = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_length < 12:
        report["issues"].append("invalid_wav_riff_size")
        return report
    _metadata(report, "declared_total_bytes", declared_length, declared=True)
    if complete and declared_length != len(data):
        report["issues"].append("wav_declared_length_mismatch")
    position = 12
    pcm: tuple[int, int] | None = None
    data_size: int | None = None
    fmt_seen = False
    for _ in range(512):
        if position + 8 > min(len(data), declared_length):
            break
        kind = data[position:position + 4]
        size = struct.unpack_from("<I", data, position + 4)[0]
        start, end = position + 8, position + 8 + size
        report["evidence"][0]["byte_range"][1] = start
        if end > declared_length:
            report["issues"].append("wav_chunk_exceeds_declared_riff")
            break
        if kind == b"fmt ":
            if fmt_seen:
                report["issues"].append("duplicate_wav_format_chunk")
                pcm = None
                break
            fmt_seen = True
            if size < 16 or start + 16 > len(data):
                report["issues"].append("truncated_wav_format_chunk" if complete else "wav_format_chunk_not_in_sample")
                break
            encoding, channels, rate, byte_rate, alignment, bits = struct.unpack_from("<HHIIHH", data, start)
            report["evidence"][0]["byte_range"][1] = start + 16
            if encoding != 1:
                report["issues"].append("unsupported_wav_encoding")
            elif not (channels > 0 and rate > 0 and bits > 0 and bits % 8 == 0 and alignment == channels * (bits // 8) and byte_rate == rate * alignment):
                report["issues"].append("inconsistent_wav_pcm_header")
            else:
                pcm = rate, alignment
                _metadata(report, "channels", channels, declared=True)
                _metadata(report, "sample_rate", rate, declared=True)
                _metadata(report, "bits_per_sample", bits, declared=True)
        elif kind == b"data":
            if data_size is not None:
                report["issues"].append("multiple_wav_data_chunks")
                data_size = None
                break
            data_size = size
            _metadata(report, "declared_data_bytes", size, declared=True)
        if end > len(data):
            if complete:
                report["issues"].append("truncated_wav_chunk")
            break
        position = end + size % 2
    else:
        report["issues"].append("wav_chunk_budget_exceeded")
    if pcm is not None and data_size is not None:
        rate, alignment = pcm
        if data_size % alignment:
            report["issues"].append("wav_data_not_frame_aligned")
        else:
            frames = data_size // alignment
            _metadata(report, "declared_frames", frames, declared=True)
            _metadata(report, "declared_duration_seconds", frames / rate, declared=True)
    if not fmt_seen:
        report["issues"].append("wav_format_chunk_not_in_sample")
    if data_size is None:
        report["issues"].append("wav_data_chunk_not_in_sample")
    return report


def _bmff(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("iso_bmff", "application/octet-stream", ["container"], 8)
    size = struct.unpack_from(">I", data)[0]
    brand_start = 8
    if size == 1:
        if len(data) < 16:
            report["issues"].append("truncated_bmff_extended_size" if complete else "bmff_extended_size_not_in_sample")
            return report
        size = struct.unpack_from(">Q", data, 8)[0]
        brand_start = 16
    if size < brand_start + 8 or (size - brand_start - 8) % 4:
        report["issues"].append("invalid_bmff_ftyp_size")
        return report
    if len(data) < brand_start + 8:
        report["issues"].append("truncated_bmff_brand" if complete else "bmff_brand_not_in_sample")
        return report
    report["evidence"][0]["byte_range"][1] = brand_start + 8
    if complete and size > len(data):
        report["issues"].append("truncated_bmff_ftyp")
    try:
        brand = data[brand_start:brand_start + 4].decode("ascii")
    except UnicodeError:
        report["issues"].append("invalid_bmff_brand")
        return report
    if not all(32 <= ord(character) <= 126 for character in brand):
        report["issues"].append("invalid_bmff_brand")
        return report
    _metadata(report, "major_brand", brand, declared=True)
    _metadata(report, "declared_ftyp_bytes", size, declared=True)
    return report


def _glb(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("glb", "model/gltf-binary", ["3d"], min(12, len(data)))
    if len(data) < 12:
        report["issues"].append("truncated_glb_header" if complete else "glb_header_not_in_sample")
        return report
    version, declared_length = struct.unpack_from("<II", data, 4)
    _metadata(report, "container_version", version, declared=True)
    _metadata(report, "declared_total_bytes", declared_length, declared=True)
    if version != 2:
        report["issues"].append("unsupported_glb_container_version")
    if declared_length < 20 or declared_length % 4:
        report["issues"].append("invalid_glb_declared_length")
    if (complete and declared_length != len(data)) or declared_length < len(data):
        report["issues"].append("glb_declared_length_mismatch")
    return report


_PLY_TYPES = {"char", "uchar", "short", "ushort", "int", "uint", "float", "double", "int8", "uint8", "int16", "uint16", "int32", "uint32", "float32", "float64"}
_PLY_FLOATS = {"float", "double", "float32", "float64"}
_SPLAT_PROPERTIES = {"x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"}


def _ply(data: bytes, complete: bool) -> dict[str, Any]:
    report = _report("ply", "application/octet-stream", ["3d"], min(4, len(data)))
    scanned = 0
    header_lines: list[str] = []
    for raw in data[:MAX_PLY_HEADER_BYTES].splitlines(keepends=True):
        scanned += len(raw)
        if len(header_lines) >= MAX_PLY_HEADER_LINES:
            report["issues"].append("ply_header_line_budget_exceeded")
            return report
        try:
            line = raw.decode("ascii").strip()
        except UnicodeError:
            report["issues"].append("invalid_ply_header_encoding")
            return report
        header_lines.append(line)
        if line == "end_header" and raw.endswith((b"\n", b"\r")):
            break
    else:
        issue = "ply_header_byte_budget_exceeded" if len(data) >= MAX_PLY_HEADER_BYTES else "truncated_ply_header" if complete else "ply_header_not_in_sample"
        report["issues"].append(issue)
        return report
    report["evidence"][0]["byte_range"][1] = scanned
    elements: dict[str, int] = {}
    properties: dict[str, dict[str, tuple[str, ...]]] = {}
    current: str | None = None
    encoding: str | None = None
    for line in header_lines[1:-1]:
        parts = line.split()
        if not parts:
            report["issues"].append("invalid_ply_header")
            return report
        if parts[0] in {"comment", "obj_info"}:
            continue
        valid = True
        if parts[0] == "format":
            valid = len(parts) == 3 and encoding is None and not elements and parts[1] in {"ascii", "binary_little_endian", "binary_big_endian"} and parts[2] == "1.0"
            if valid:
                encoding = parts[1]
        elif parts[0] == "element":
            valid = len(parts) == 3 and encoding is not None and len(elements) < 64 and parts[1] not in elements and parts[2].isascii() and parts[2].isdigit() and len(parts[2]) <= 10
            if valid:
                current = parts[1]
                elements[current] = int(parts[2])
                properties[current] = {}
        elif parts[0] == "property":
            scalar = len(parts) == 3 and parts[1] in _PLY_TYPES
            listing = len(parts) == 5 and parts[1] == "list" and parts[2] in _PLY_TYPES - _PLY_FLOATS and parts[3] in _PLY_TYPES
            valid = current is not None and (scalar or listing)
            if valid:
                name = parts[-1]
                valid = name not in properties[current] and len(properties[current]) < 512
                if valid:
                    properties[current][name] = tuple(parts[1:-1])
        else:
            valid = False
        if not valid:
            report["issues"].append("invalid_ply_header")
            return report
    if encoding is None:
        report["issues"].append("invalid_ply_header")
        return report
    _metadata(report, "ply_encoding", encoding, declared=True)
    for name in ("vertex", "face"):
        if name in elements:
            _metadata(report, f"declared_{name}_count", elements[name], declared=True)
    vertex_properties = properties.get("vertex", {})
    if vertex_properties:
        _metadata(report, "vertex_properties", sorted(vertex_properties), declared=True)
    has_xyz = all(name in vertex_properties and len(vertex_properties[name]) == 1 for name in ("x", "y", "z"))
    if elements.get("vertex", 0) > 0 and has_xyz:
        if all(name in vertex_properties and vertex_properties[name][0] in _PLY_FLOATS and len(vertex_properties[name]) == 1 for name in _SPLAT_PROPERTIES):
            _candidate(report, "gaussian_splat_candidate")
        face_properties = properties.get("face", {})
        has_indices = any(name in face_properties and len(face_properties[name]) == 3 and face_properties[name][2] in _PLY_TYPES - _PLY_FLOATS for name in ("vertex_indices", "vertex_index"))
        if elements.get("face", 0) > 0 and has_indices:
            _candidate(report, "mesh_candidate")
        elif elements.get("face", 0) == 0:
            _candidate(report, "point_cloud_candidate")
    return report
