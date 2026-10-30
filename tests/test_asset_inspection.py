"""Behavioral checks for proposed tags, bounded evidence and unknown content."""

import binascii
from copy import deepcopy
import hashlib
import json
import struct
import zlib

import pytest

from tiberium_ai.asset_inspection import inspect_asset


def _inspect(data, filename="fixture.bin", **options):
    return inspect_asset(
        data, filename=filename, source_id="fixture:asset", revision="v1", **options
    )


def _tags(report, namespace):
    return [tag for tag in report["tag_proposals"] if tag["namespace"] == namespace]


def _png(width=3, height=2):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)
        )
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = (b"\x00" + b"\x00\x00\x00\xff" * width) * height
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    )


def test_png_signature_wins_over_a_forged_jpeg_suffix():
    report = _inspect(_png(), "photo.jpg")
    assert report["format"]["detected"] == "png"
    assert report["format"]["media_type"] == "image/png"
    assert report["format"]["extension_conflict"] is True
    assert "image" in report["modalities"]


def test_filename_does_not_invent_objects_places_or_semantic_topics():
    report = _inspect(_png(), "robot-tokyo-portrait-secret.jpg")
    forbidden = {"robot", "tokyo", "portrait", "secret"}
    assert not any(tag["value"].casefold() in forbidden for tag in report["tag_proposals"])
    assert not _tags(report, "topic")


def test_unknown_binary_does_not_become_an_image_from_its_suffix():
    report = _inspect(bytes(range(256)), "mystery.unrecognized")
    assert report["status"] == "indeterminate"
    assert report["format"]["detected"] is None
    assert not report["tag_proposals"]


def test_text_is_observed_and_topics_require_the_callers_lexicon():
    data = "Ce robot est documenté ici.\n".encode("utf-8")
    plain = _inspect(data, "notes.txt")
    assert "text" in plain["modalities"]
    assert not _tags(plain, "topic")
    proposed = _inspect(data, "notes.txt", topic_terms={"robotique": ["robot"]})
    topics = _tags(proposed, "topic")
    assert [item["value"] for item in topics] == ["robotique"]
    assert all(item["status"] == "proposed" for item in topics)
    assert all("lexical" in item["basis"] for item in topics)
    assert not _tags(
        _inspect(data, "robotique.txt", topic_terms={"robotique": ["drone"]}), "topic"
    )


def test_valid_python_reuses_structural_roles_and_pattern_ids():
    data = b"def operation():\n    try:\n        work()\n    except Exception:\n        pass\n"
    report = _inspect(data, "module.py")
    assert _tags(report, "code_role")
    assert any("silent" in item["value"] for item in _tags(report, "code_pattern"))


def test_analyzing_python_never_executes_a_source_sentinel(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    data = (
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed')\n"
        "def helper():\n    return 1\n"
    ).encode("utf-8")
    report = _inspect(data, "hostile.py")
    assert _tags(report, "code_role")
    assert not sentinel.exists()


def test_unparsable_python_does_not_receive_a_default_module_role():
    report = _inspect(b"def (:\n", "bad.py")
    assert not _tags(report, "code_role")
    assert not _tags(report, "code_pattern")
    assert report["reason_codes"]


def test_geojson_requires_a_recognized_structure_not_a_json_number_pair():
    actual = _inspect(
        json.dumps({"type": "Point", "coordinates": [2.3, 48.4]}).encode(), "point.geojson"
    )
    ordinary = _inspect(
        json.dumps({"coordinates": [2.3, 48.4]}).encode(), "ordinary.json"
    )
    assert actual["spatial"] is not None
    assert ordinary["spatial"] is None


def test_ply_suffix_alone_never_establishes_gaussian_splatting():
    report = _inspect(b"unrecognized plain text\n", "scene.ply")
    assert not any("gaussian" in tag["value"].casefold() for tag in report["tag_proposals"])
    assert not any("splat" in tag["value"].casefold() for tag in report["tag_proposals"])


def test_prefix_hash_is_not_reported_as_a_hash_of_the_whole_source():
    complete = _png()
    prefix = complete[:33]
    report = _inspect(prefix, "picture.png", complete=False, total_bytes=len(complete))
    assert report["sample"]["sha256"] == hashlib.sha256(prefix).hexdigest()
    assert report["sample"]["content_sha256"] is None
    assert report["sample"]["complete"] is False
    assert report["sample"]["bytes"] == len(prefix)
    assert report["sample"]["total_bytes"] == len(complete)
    assert report["status"] == "partial"


def test_complete_bytes_get_a_content_hash_without_an_external_file_read():
    data = _png()
    report = _inspect(data, "picture.png")
    assert report["sample"]["content_sha256"] == hashlib.sha256(data).hexdigest()
    assert report["sample"]["sha256"] == report["sample"]["content_sha256"]
    assert report["sample"]["complete"] is True


def test_input_binding_changes_with_revision_lexicon_or_source_bytes():
    data = b"robot notes\n"
    base = _inspect(data, "notes.txt", topic_terms={"robotique": ["robot"]})
    revision = inspect_asset(
        data, filename="notes.txt", source_id="fixture:asset", revision="v2",
        topic_terms={"robotique": ["robot"]},
    )
    terms = _inspect(data, "notes.txt", topic_terms={"robotique": ["drone"]})
    changed = _inspect(data + b"changed\n", "notes.txt", topic_terms={"robotique": ["robot"]})
    assert len({item["input_hash"] for item in (base, revision, terms, changed)}) == 4


def test_proposed_tags_have_resolvable_evidence_and_never_approval_status():
    report = _inspect(
        b"def helper():\n    return 'robot'\n", "module.py",
        topic_terms={"robotique": ["robot"]},
    )
    evidence = {item["id"] for item in report["evidence"]}
    assert report["schema"] == "parcimonia.asset-inspection/v1"
    assert report["mode"] == "shadow"
    assert report["tag_proposals"]
    for tag in report["tag_proposals"]:
        assert tag["status"] == "proposed"
        assert tag["evidence_refs"]
        assert set(tag["evidence_refs"]) <= evidence


@pytest.mark.parametrize("data", ["text", bytearray(b"text"), memoryview(b"text"), None])
def test_non_bytes_input_is_refused(data):
    with pytest.raises((ValueError, TypeError)):
        _inspect(data)


def test_sample_over_one_mib_is_refused():
    with pytest.raises(ValueError):
        _inspect(b"x" * (1024 * 1024 + 1))


@pytest.mark.parametrize("field,value", [
    ("source_id", ""), ("source_id", "  "), ("source_id", True),
    ("revision", ""), ("revision", " v1"), ("revision", 1),
    ("filename", ""), ("filename", " file.txt"), ("filename", False),
])
def test_invalid_source_identity_is_refused(field, value):
    options = {"filename": "file.txt", "source_id": "fixture:asset", "revision": "v1"}
    options[field] = value
    with pytest.raises((ValueError, TypeError)):
        inspect_asset(b"notes\n", **options)


@pytest.mark.parametrize("options", [
    {"complete": 1}, {"complete": "false"},
    {"total_bytes": True}, {"total_bytes": "5"}, {"total_bytes": -1},
    {"total_bytes": 0}, {"total_bytes": 100},
])
def test_invalid_or_contradictory_size_declarations_are_refused(options):
    with pytest.raises((ValueError, TypeError)):
        _inspect(b"notes\n", "notes.txt", **options)


@pytest.mark.parametrize("terms", [
    "robot", ["robot"], {"": ["robot"]}, {"robotique": "robot"},
    {1: ["robot"]}, {"robotique": [True]},
    {f"topic-{i}": ["word"] for i in range(1001)},
    {"robotique": [f"word-{i}" for i in range(1001)]},
    {"robotique": ["x" * 10000]},
])
def test_topic_vocabulary_has_strict_types_and_finite_budgets(terms):
    with pytest.raises((ValueError, TypeError)):
        _inspect(b"robot notes\n", "notes.txt", topic_terms=terms)


def test_declared_topic_budget_boundary_is_accepted_without_mutating_the_lexicon():
    topics = {f"topic-{index}": [f"term-{term}" for term in range(8)] for index in range(32)}
    before = deepcopy(topics)
    report = _inspect(b"term-0 notes\n", "notes.txt", topic_terms=topics)
    assert topics == before
    assert len(_tags(report, "topic")) == 32
    assert _inspect(b"term-0 notes\n", "notes.txt", topic_terms=topics) == report


@pytest.mark.parametrize("topics", [
    {f"topic-{index}": ["term"] for index in range(33)},
    {"topic": [f"term-{index}" for index in range(9)]},
    {"x" * 129: ["term"]},
    {"topic": ["x" * 65]},
    {"topic": []},
])
def test_each_declared_topic_boundary_is_enforced(topics):
    with pytest.raises(ValueError):
        _inspect(b"notes\n", "notes.txt", topic_terms=topics)


def test_lexical_topic_signal_does_not_claim_a_semantic_object_detection():
    report = _inspect(
        b"There is no robot in this scene.\n", "notes.txt",
        topic_terms={"robotique": ["robot"]},
    )
    assert [tag["value"] for tag in _tags(report, "topic")] == ["robotique"]
    assert report["limits"]["semantic_content"] == "not_assessed_lexical_hints_only"
    assert all(tag["basis"] == "lexical_hint" for tag in _tags(report, "topic"))


def test_partial_word_overlap_is_not_a_whole_lexical_term_match():
    report = _inspect(
        b"robotics robotic robotique\n", "notes.txt",
        topic_terms={"robotique": ["robot"]},
    )
    assert not _tags(report, "topic")


def test_ast_budget_failure_preserves_unknown_code_structure():
    report = _inspect(b"x = 0\n" * 3000, "large.py")
    assert report["status"] == "partial"
    assert "python_structure_unavailable" in report["reason_codes"]
    assert not _tags(report, "code_role")
    assert not _tags(report, "code_pattern")


@pytest.mark.parametrize("data,options,expected", [
    (b"robot", {"complete": False, "total_bytes": 9}, []),
    (b"robot ", {"complete": False, "total_bytes": 9}, ["robotique"]),
    (b"robot", {}, ["robotique"]),
    (b"robot\xc3", {"complete": False, "total_bytes": 9}, []),
])
def test_lexical_match_needs_a_real_observed_end_boundary(data, options, expected):
    # A byte prefix ending in 'robot' can still continue as 'robotics!'. An
    # incomplete UTF-8 sequence provides no observed word boundary either.
    report = _inspect(
        data, "notes.txt", topic_terms={"robotique": ["robot"]}, **options
    )
    assert [tag["value"] for tag in _tags(report, "topic")] == expected
