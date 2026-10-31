"""Header observations and limits, with no decoding or content inference."""

import binascii
from copy import deepcopy
import json
import random
import struct

import pytest

from tiberium_ai.media_probe import MAX_SAMPLE_BYTES, probe_media


def _png(width=3, height=2):
    body = b"IHDR" + struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + body + struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF)


def _gif(width=3, height=2):
    return b"GIF89a" + struct.pack("<HH", width, height) + b"\x00\x00\x00"


def _jpeg(width=3, height=2):
    payload = struct.pack(">BHHB", 8, height, width, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xc0" + struct.pack(">H", len(payload) + 2) + payload


def _wav(*, sample_rate=8, channels=1, bits=16, payload=b"\x00" * 16):
    alignment = channels * (bits // 8)
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, sample_rate * alignment, alignment, bits)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def _ply(properties=None, *, faces=False, count=1):
    if properties is None:
        properties = ["x", "y", "z"]
    header = ["ply", "format ascii 1.0", f"element vertex {count}"]
    header += [f"property float {name}" for name in properties]
    if faces:
        header += ["element face 1", "property list uchar int vertex_indices"]
    return ("\n".join(header + ["end_header", ""]) + "0 0 0\n").encode("ascii")


def _values(report):
    return {item["name"]: item["value"] for item in report["metadata"]}


def _representations(report):
    return {item["value"] for item in report["tag_proposals"] if item["namespace"] == "representation"}


@pytest.mark.parametrize("data,format_name,modality", [
    (_png(), "png", "image"), (_gif(), "gif", "image"),
    (_jpeg(), "jpeg", "image"), (_wav(), "wav", "audio"),
    (b"fLaC", "flac", "audio"), (b"OggS", "ogg", "container"),
    (struct.pack(">I", 16) + b"ftypisom\x00\x00\x00\x00", "iso_bmff", "container"),
    (b"glTF" + struct.pack("<II", 2, 20) + b"\x00" * 8, "glb", "3d"),
    (_ply(), "ply", "3d"),
])
def test_supported_signatures_remain_header_observations(data, format_name, modality):
    report = probe_media(data)
    assert report["format"] == format_name
    assert report["modalities"] == [modality]
    assert report["analysis_scope"] == "header_only"
    assert all("confidence" not in item and "status" not in item for item in report["tag_proposals"])
    references = {item["id"] for item in report["evidence"]}
    for item in report["metadata"]:
        assert item["evidence_ref"] in references
    for item in report["tag_proposals"]:
        assert set(item["evidence_refs"]) <= references
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize("factory", [_png, _gif, _jpeg])
def test_dimensions_are_read_from_headers(factory):
    values = _values(probe_media(factory(width=31, height=17)))
    assert values["width"] == 31
    assert values["height"] == 17


def test_png_bad_crc_does_not_return_dimensions():
    data = bytearray(_png())
    data[-1] ^= 1
    report = probe_media(bytes(data))
    assert "invalid_png_ihdr_crc" in report["issues"]
    assert report["metadata"] == []


@pytest.mark.parametrize("factory", [_png, _gif, _jpeg])
def test_zero_dimensions_are_not_returned_as_usable_metadata(factory):
    report = probe_media(factory(width=0))
    assert report["issues"]
    assert "width" not in _values(report)


def test_jpeg_segments_are_bounded_and_bad_lengths_fail_closed():
    report = probe_media(b"\xff\xd8\xff\xe0\x00\x01")
    assert report["issues"] == ["invalid_jpeg_segment_length"]
    assert report["metadata"] == []
    report = probe_media(b"\xff\xd8" + b"\xff\x01" * 513)
    assert "jpeg_segment_budget_exceeded" in report["issues"]


def test_wav_frames_and_duration_are_explicitly_declared_not_measured():
    report = probe_media(_wav())
    values = _values(report)
    assert values["channels"] == 1
    assert values["sample_rate"] == 8
    assert values["declared_frames"] == 8
    assert values["declared_duration_seconds"] == 1.0
    assert "frames" not in values and "duration_seconds" not in values
    assert all(item["basis"] == "declared_header" for item in report["metadata"])


def test_wav_prefix_retains_declared_duration_without_claiming_actual_frames():
    prefix = _wav()[:44]
    report = probe_media(prefix, complete=False)
    assert _values(report)["declared_duration_seconds"] == 1.0
    assert "truncated_wav_chunk" not in report["issues"]
    assert "wav_declared_length_mismatch" not in report["issues"]
    truncated = probe_media(prefix, complete=True)
    assert "truncated_wav_chunk" in truncated["issues"]
    assert "wav_declared_length_mismatch" in truncated["issues"]


def test_inconsistent_wav_alignment_never_generates_duration():
    data = bytearray(_wav())
    struct.pack_into("<H", data, 32, 3)
    report = probe_media(bytes(data))
    assert "inconsistent_wav_pcm_header" in report["issues"]
    assert "declared_duration_seconds" not in _values(report)


def test_unaligned_wav_payload_does_not_round_frame_count():
    report = probe_media(_wav(payload=b"\x00" * 3))
    assert "wav_data_not_frame_aligned" in report["issues"]
    assert "declared_frames" not in _values(report)


def test_unsupported_wav_encoding_has_no_duration():
    data = bytearray(_wav())
    struct.pack_into("<H", data, 20, 3)
    report = probe_media(bytes(data))
    assert "unsupported_wav_encoding" in report["issues"]
    assert "declared_duration_seconds" not in _values(report)


@pytest.mark.parametrize("data,expected_issue", [
    (b"glTF", "truncated_glb_header"),
    (b"glTF" + struct.pack("<II", 1, 20) + b"\x00" * 8, "unsupported_glb_container_version"),
    (b"glTF" + struct.pack("<II", 2, 12), "invalid_glb_declared_length"),
    (b"glTF" + struct.pack("<II", 2, 100), "glb_declared_length_mismatch"),
])
def test_glb_container_header_is_not_asset_validation(data, expected_issue):
    report = probe_media(data)
    assert report["format"] == "glb"
    assert expected_issue in report["issues"]
    assert "asset_version" not in _values(report)


def test_glb_prefix_does_not_invent_a_length_mismatch():
    report = probe_media(b"glTF" + struct.pack("<II", 2, 100), complete=False)
    assert "glb_declared_length_mismatch" not in report["issues"]
    assert _values(report)["declared_total_bytes"] == 100


def test_bmff_avif_or_mp4_brand_does_not_assert_audio_or_video_streams():
    for brand in (b"isom", b"avif", b"M4A "):
        report = probe_media(struct.pack(">I", 16) + b"ftyp" + brand + b"\x00" * 4)
        assert report["modalities"] == ["container"]
        assert _values(report)["major_brand"] == brand.decode("ascii")
        assert "video" not in report["modalities"] and "audio" not in report["modalities"]


def test_bmff_extended_header_and_truncation_are_bounded():
    data = struct.pack(">I4sQ4sI", 1, b"ftyp", 24, b"isom", 0)
    report = probe_media(data)
    assert _values(report)["declared_ftyp_bytes"] == 24
    assert probe_media(data[:12])["issues"] == ["truncated_bmff_extended_size"]


def test_ply_point_cloud_and_mesh_are_only_schema_candidates():
    cloud = probe_media(_ply())
    mesh = probe_media(_ply(faces=True))
    assert _representations(cloud) == {"point_cloud_candidate"}
    assert _representations(mesh) == {"mesh_candidate"}
    assert all(item["basis"] == "header_schema_candidate" for item in mesh["tag_proposals"] if item["namespace"] == "representation")
    assert _values(cloud)["declared_vertex_count"] == 1


def test_ply_gaussian_candidate_requires_all_expected_vertex_properties():
    names = ["x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity", "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    complete = probe_media(_ply(names))
    incomplete = probe_media(_ply(names[:-1]))
    assert "gaussian_splat_candidate" in _representations(complete)
    assert "gaussian_splat_candidate" not in _representations(incomplete)
    assert not any("gps" in item["value"] for item in complete["tag_proposals"])
    empty = probe_media(_ply(names, count=0))
    assert "gaussian_splat_candidate" not in _representations(empty)


def test_ply_faces_with_float_indices_do_not_claim_mesh_schema():
    data = _ply(faces=True).replace(b"list uchar int", b"list uchar float")
    assert "mesh_candidate" not in _representations(probe_media(data))


@pytest.mark.parametrize("data,issue", [
    (b"ply\nformat ascii 1.0\n", "truncated_ply_header"),
    (b"ply\n" + b"comment x\n" * 2048 + b"end_header\n", "ply_header_line_budget_exceeded"),
    (b"ply\ncomment " + b"x" * (64 * 1024) + b"\nend_header\n", "ply_header_byte_budget_exceeded"),
    (b"ply\nformat ascii 1.0\nelement vertex -1\nend_header\n", "invalid_ply_header"),
    (b"ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float x\nend_header\n", "invalid_ply_header"),
])
def test_invalid_or_excessive_ply_headers_abstain_from_geometry(data, issue):
    report = probe_media(data)
    assert issue in report["issues"]
    assert _representations(report) == set()


def test_huge_declared_ply_counts_are_not_allocated_or_decoded():
    report = probe_media(_ply(count=4_000_000_000))
    assert _values(report)["declared_vertex_count"] == 4_000_000_000
    assert report["analysis_scope"] == "header_only"


@pytest.mark.parametrize("data", [b"", b"plain text", b"RIFF", b"{\"asset\": {\"version\": \"2.0\"}}", b"__import__('os').system('false')"])
def test_unknown_signatures_return_none_without_guessing(data):
    assert probe_media(data) is None


@pytest.mark.parametrize("value", [None, "PNG", bytearray(b"fLaC"), memoryview(b"fLaC"), 1])
def test_input_types_are_strict(value):
    with pytest.raises(ValueError):
        probe_media(value)


@pytest.mark.parametrize("value", [1, 0, None, "true"])
def test_complete_flag_does_not_coerce_values(value):
    with pytest.raises(ValueError):
        probe_media(b"fLaC", complete=value)


def test_input_byte_limit_is_enforced():
    with pytest.raises(ValueError):
        probe_media(b"fLaC" + b"\x00" * MAX_SAMPLE_BYTES)


def test_all_fixture_prefixes_have_bounded_valid_evidence_and_no_crash():
    samples = [_png(), _gif(), _jpeg(), _wav(), _ply(), b"glTF" + struct.pack("<II", 2, 20) + b"\x00" * 8]
    for sample in samples:
        for size in range(len(sample) + 1):
            data = sample[:size]
            for complete in (False, True):
                report = probe_media(data, complete=complete)
                if report is None:
                    continue
                if not complete:
                    assert not any(issue.startswith("truncated_") for issue in report["issues"])
                for evidence in report["evidence"]:
                    start, end = evidence["byte_range"]
                    assert 0 <= start <= end <= size


def test_determinism_and_hostile_header_fuzz_are_bounded():
    rng = random.Random(340129)
    signatures = [b"\x89PNG\r\n\x1a\n", b"GIF89a", b"\xff\xd8", b"RIFF\x00\x00\x00\x00WAVE", b"glTF", b"ply\n"]
    for signature in signatures:
        for _ in range(60):
            sample = signature + bytes(rng.randrange(256) for _ in range(rng.randrange(100)))
            before = deepcopy(sample)
            first = probe_media(sample)
            second = probe_media(sample)
            assert first == second and sample == before
            json.dumps(first, allow_nan=False)
