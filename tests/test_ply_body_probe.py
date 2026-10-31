"""Independent PLY body fixtures exercise structure, not rendering quality.

The fixtures deliberately include unusual but finite Gaussian parameters and
degenerate polygons. Profile compatibility does not establish useful content,
topology, visual quality, world coordinates or a working renderer.
"""

import builtins
import json
import struct

import pytest

from tiberium_ai.media_probe import probe_media
from tiberium_ai.ply_body_probe import PROFILE_ID, probe_ply_body


XYZ = [("float", "x"), ("float", "y"), ("float", "z")]
POINTS = [(1, 2, 3), (-4, 8, 6), (0, -2, 9)]
TYPE_FORMAT = {
    "char": "b", "int8": "b", "uchar": "B", "uint8": "B",
    "short": "h", "int16": "h", "ushort": "H", "uint16": "H",
    "int": "i", "int32": "i", "uint": "I", "uint32": "I",
    "float": "f", "float32": "f", "double": "d", "float64": "d",
}
ENCODINGS = ["ascii", "binary_little_endian", "binary_big_endian"]


def header(elements, encoding="ascii", comments=()):
    lines = ["ply", f"format {encoding} 1.0", *comments]
    for name, properties, rows in elements:
        lines.append(f"element {name} {len(rows)}")
        lines.extend("property " + " ".join(prop) for prop in properties)
    return ("\n".join([*lines, "end_header", ""]).encode("ascii"))


def encoded_rows(properties, rows, encoding):
    output = bytearray()
    prefix = "<" if encoding == "binary_little_endian" else ">"
    for row in rows:
        tokens = []
        for prop, value in zip(properties, row):
            values = [(prop[0], value)] if prop[0] != "list" else [
                (prop[1], len(value)), *((prop[2], item) for item in value)
            ]
            for kind, item in values:
                if encoding == "ascii":
                    tokens.append(str(item).encode("ascii"))
                else:
                    output.extend(struct.pack(prefix + TYPE_FORMAT[kind], item))
        if encoding == "ascii":
            output.extend(b" ".join(tokens) + b"\n")
    return bytes(output)


def ply(vertices=POINTS, *, properties=XYZ, faces=None, face_properties=None,
        encoding="ascii", face_first=False, comments=()):
    elements = [("vertex", properties, vertices)]
    if faces is not None:
        face_properties = face_properties or [("list", "uchar", "int", "vertex_indices")]
        element = ("face", face_properties, faces)
        elements.insert(0 if face_first else len(elements), element)
    return header(elements, encoding, comments) + b"".join(
        encoded_rows(props, rows, encoding) for _, props, rows in elements
    )


def values(report):
    return {item["name"]: item["value"] for item in report["metadata"]}


def tags(report):
    return {(item["namespace"], item["value"]) for item in report["tag_proposals"]}


def body_proof(report):
    matches = [item for item in report["evidence"] if item["id"] == "ply:body"]
    assert len(matches) == 1
    assert matches[0]["kind"] == "validated_ply_body"
    return matches[0]


def extrema_proof(report):
    matches = [item for item in report["evidence"] if item["id"] == "ply:position_extrema"]
    assert len(matches) == 1
    assert matches[0]["kind"] == "ply_position_extrema"
    return matches[0]


def no_body_geometry(data, *, complete=True):
    report = probe_ply_body(data, complete=complete)
    assert report is not None
    assert report["format"] == "ply"
    assert report["issues"]
    assert not any(item["id"] in {"ply:body", "ply:position_extrema"} for item in report["evidence"])
    assert not {"observed_vertex_count", "observed_face_count", "geometry_bounds_xyz", "gaussian_parameters"} & set(values(report))
    assert not tags(report) & {
        ("geometry", "has_local_positions"),
        ("representation", "point_cloud_structure"),
        ("representation", "mesh_structure"),
        ("representation", "gaussian_splat_body_candidate"),
    }
    assert report.get("spatial") is None
    return report


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_equivalent_ascii_and_binary_endians_have_the_same_local_bounds(encoding):
    data = ply(encoding=encoding)
    report = probe_ply_body(data)
    metadata = values(report)
    assert report["format"] == "ply" and report["modalities"] == ["3d"]
    assert report.get("spatial") is None
    assert metadata["observed_vertex_count"] == 3
    assert metadata["observed_face_count"] == 0
    assert metadata["geometry_bounds_xyz"] == {
        "min": [-4, -2, 3], "max": [1, 8, 9],
        "axis_order": ["x", "y", "z"], "units": "unknown",
        "coordinate_frame": "file_local_unspecified",
    }
    assert ("geometry", "has_local_positions") in tags(report)
    assert ("representation", "point_cloud_structure") in tags(report)
    assert not any(item["namespace"] in {"place", "crs", "quality"} for item in report["tag_proposals"])
    proof = body_proof(report)
    assert proof["profile"] == PROFILE_ID
    assert proof["encoding"] == encoding
    assert proof["vertex_count"] == 3 and proof["face_count"] == 0
    assert proof["field_value_count"] == 9
    assert proof["byte_range"] == [data.index(b"end_header\n") + len(b"end_header\n"), len(data)]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_property_order_and_extra_scalars_are_consumed_as_declared(encoding):
    props = [("double", "z"), ("uchar", "red"), ("float", "y"), ("short", "x")]
    rows = [(3, 255, 2, 1), (6, 0, 8, -4), (9, 32, -2, 0)]
    report = probe_ply_body(ply(rows, properties=props, encoding=encoding))
    assert values(report)["geometry_bounds_xyz"]["min"] == [-4, -2, 3]
    assert values(report)["geometry_bounds_xyz"]["max"] == [1, 8, 9]
    assert body_proof(report)["field_value_count"] == 12


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("face_first", [False, True])
def test_face_element_order_and_polygon_indices_follow_the_header(encoding, face_first):
    props = [("uchar", "material"), ("list", "uchar", "int", "vertex_indices")]
    rows = [(7, [0, 1, 2, 0])]
    report = probe_ply_body(ply(faces=rows, face_properties=props, encoding=encoding, face_first=face_first))
    assert values(report)["observed_face_count"] == 1
    assert body_proof(report)["field_value_count"] == 15  # nine XYZ + scalar + count + four indices
    assert ("representation", "mesh_structure") in tags(report)


@pytest.mark.parametrize("name", ["vertex_indices", "vertex_index"])
def test_both_standard_integer_face_index_property_names_are_supported(name):
    report = probe_ply_body(ply(faces=[([0, 1, 2],)], face_properties=[("list", "ushort", "uint32", name)]))
    assert body_proof(report)["face_count"] == 1
    assert body_proof(report)["field_value_count"] == 13


def test_ascii_records_are_token_based_and_extrema_spans_replay_whole_records():
    head = header([("vertex", XYZ, [(0, 0, 0)] * 2)])
    data = head + b" \t1\n2 3\r\n  -4 5\t6 \n"
    report = probe_ply_body(data)
    extrema = extrema_proof(report)["extrema"]
    first = [len(head) + 2, len(head) + 7]
    second_start = data.index(b"-4", len(head))
    second = [second_start, second_start + len(b"-4 5\t6")]
    assert extrema["x_max"] == {"row": 1, "field": "x", "value": 1, "byte_range": first}
    assert extrema["x_min"] == {"row": 2, "field": "x", "value": -4, "byte_range": second}
    assert data[slice(*first)].split() == [b"1", b"2", b"3"]
    assert data[slice(*second)].split() == [b"-4", b"5", b"6"]
    for bound, item in extrema.items():
        assert item["field"] == bound[0]
        assert item["byte_range"] in (first, second)


@pytest.mark.parametrize("encoding,prefix", [("binary_little_endian", "<"), ("binary_big_endian", ">")])
def test_binary_extrema_ranges_replay_exact_vertex_records(encoding, prefix):
    data = ply(encoding=encoding)
    start = data.index(b"end_header\n") + len(b"end_header\n")
    extrema = extrema_proof(probe_ply_body(data))["extrema"]
    for item in extrema.values():
        expected = [start + 12 * (item["row"] - 1), start + 12 * item["row"]]
        assert item["byte_range"] == expected
        coordinates = struct.unpack(prefix + "fff", data[slice(*expected)])
        assert coordinates["xyz".index(item["field"])] == item["value"]


def test_first_binary_space_byte_is_data_and_must_not_be_trimmed():
    props = [("uchar", "red"), *XYZ]
    data = ply([(32, 1, 2, 3)], properties=props, encoding="binary_little_endian")
    start = data.index(b"end_header\n") + len(b"end_header\n")
    assert data[start:start + 1] == b" "
    report = probe_ply_body(data)
    assert values(report)["geometry_bounds_xyz"]["min"] == [1, 2, 3]
    assert extrema_proof(report)["extrema"]["x_min"]["byte_range"] == [start, start + 13]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_zero_vertices_and_faces_have_observed_counts_but_no_invented_bounds(encoding):
    report = probe_ply_body(ply([], faces=[], encoding=encoding))
    assert body_proof(report)["vertex_count"] == 0
    assert body_proof(report)["face_count"] == 0
    assert values(report)["observed_vertex_count"] == 0
    assert values(report)["observed_face_count"] == 0
    assert values(report).get("geometry_bounds_xyz") is None
    assert not any(item["id"] == "ply:position_extrema" for item in report["evidence"])
    assert ("geometry", "has_local_positions") not in tags(report)


def test_float32_uses_its_declared_precision_even_in_ascii():
    value = struct.unpack("<f", struct.pack("<f", 0.1))[0]
    report = probe_ply_body(ply([(0.1, 0, 0)]))
    assert values(report)["geometry_bounds_xyz"]["min"][0] == value
    assert extrema_proof(report)["extrema"]["x_min"]["value"] == value


@pytest.mark.parametrize("encoding", ENCODINGS)
@pytest.mark.parametrize("kind", ["float32", "float64"])
def test_float_aliases_support_finite_values_in_each_encoding(encoding, kind):
    properties = [(kind, "x"), ("double", "y"), ("float", "z")]
    report = probe_ply_body(ply([(0.1, 2, 3)], properties=properties, encoding=encoding))
    expected = struct.unpack("<f", struct.pack("<f", 0.1))[0] if kind == "float32" else 0.1
    assert values(report)["geometry_bounds_xyz"]["min"] == [expected, 2, 3]


@pytest.mark.parametrize("encoding", ["binary_little_endian", "binary_big_endian"])
def test_binary_integer_aliases_and_extra_fields_follow_their_declared_sizes(encoding):
    properties = [
        ("int8", "x"), ("uint16", "y"), ("int32", "z"),
        ("int16", "extra_signed"), ("uint8", "extra_byte"),
        ("uint32", "extra_unsigned"), ("float32", "extra_float"), ("float64", "extra_double"),
    ]
    rows = [(-2, 65535, -123, -32768, 255, 4294967295, 0.1, 0.2)]
    report = probe_ply_body(ply(rows, properties=properties, encoding=encoding))
    assert values(report)["geometry_bounds_xyz"]["min"] == [-2, 65535, -123]
    assert body_proof(report)["field_value_count"] == 8


def test_ascii_scientific_notation_and_signed_integers_are_type_checked():
    props = [("float", "x"), ("double", "y"), ("int", "z")]
    data = header([("vertex", props, [(0, 0, 0)])]) + b"+1.25e2 -2.5E-1 +003\n"
    assert values(probe_ply_body(data))["geometry_bounds_xyz"]["min"] == [125, -0.25, 3]


@pytest.mark.parametrize("kind,low,high", [
    ("char", -128, 127), ("int8", -128, 127),
    ("uchar", 0, 255), ("uint8", 0, 255),
    ("short", -32768, 32767), ("int16", -32768, 32767),
    ("ushort", 0, 65535), ("uint16", 0, 65535),
    ("int", -2147483648, 2147483647), ("int32", -2147483648, 2147483647),
    ("uint", 0, 4294967295), ("uint32", 0, 4294967295),
])
def test_integer_scalar_aliases_accept_their_exact_declared_range(kind, low, high):
    props = [(kind, "x"), ("float", "y"), ("float", "z")]
    report = probe_ply_body(ply([(low, 0, 0), (high, 0, 0)], properties=props))
    assert values(report)["geometry_bounds_xyz"]["min"][0] == low
    assert values(report)["geometry_bounds_xyz"]["max"][0] == high
    no_body_geometry(ply([(low - 1, 0, 0)], properties=props))
    no_body_geometry(ply([(high + 1, 0, 0)], properties=props))


@pytest.mark.parametrize("kind", ["float", "float32", "double", "float64"])
@pytest.mark.parametrize("token", ["NaN", "nan", "inf", "-Infinity"])
def test_nonfinite_xyz_scalars_refuse_all_body_evidence(kind, token):
    props = [(kind, "x"), ("float", "y"), ("float", "z")]
    no_body_geometry(ply([(1, 2, 3), (token, 0, 0)], properties=props))


@pytest.mark.parametrize("kind,token", [("float", "3.5e38"), ("float32", "1e100"), ("double", "1e309"), ("float64", "1e999")])
def test_declared_float_overflow_is_not_silently_clamped(kind, token):
    props = [(kind, "x"), ("float", "y"), ("float", "z")]
    no_body_geometry(ply([(token, 0, 0)], properties=props))


@pytest.mark.parametrize("encoding", ["binary_little_endian", "binary_big_endian"])
@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_binary_values_do_not_leak_a_previously_valid_row(encoding, number):
    no_body_geometry(ply([(1, 2, 3), (4, 5, number)], encoding=encoding))


@pytest.mark.parametrize("token", ["1_0", "0x1p0", "1,2"])
def test_ascii_float_lexical_forms_do_not_accept_python_or_locale_extensions(token):
    no_body_geometry(ply([(token, 0, 0)]))


def test_ascii_whitespace_does_not_include_unicode_word_separators():
    data = header([("vertex", XYZ, [(0, 0, 0)])]) + "1\u00a02 3\n".encode("utf-8")
    no_body_geometry(data)


@pytest.mark.parametrize("token", ["1.0", "1e0", "0x10", "1_0", "+", "١", "true"])
def test_ascii_integer_fields_do_not_coerce_non_integer_lexical_forms(token):
    props = [("int", "x"), ("float", "y"), ("float", "z")]
    data = header([("vertex", props, [(0, 0, 0)])]) + (token + " 0 0\n").encode("utf-8")
    no_body_geometry(data)


def test_unknown_vertex_scalars_are_consumed_and_must_also_be_finite():
    props = [*XYZ, ("float", "confidence")]
    no_body_geometry(ply([(1, 2, 3, 0.5), (4, 5, 6, "nan")], properties=props))


def test_ascii_token_length_budget_is_enforced_without_partial_success():
    assert body_proof(probe_ply_body(ply([("0" * 127 + "1", 0, 0)])))["vertex_count"] == 1
    no_body_geometry(ply([("0" * 128 + "1", 0, 0)]))


def test_ascii_trailing_whitespace_is_allowed_but_extra_values_are_not():
    data = ply()
    assert body_proof(probe_ply_body(data + b" \t\r\n"))["vertex_count"] == 3
    no_body_geometry(data + b"42\n")


@pytest.mark.parametrize("encoding", ["binary_little_endian", "binary_big_endian"])
def test_binary_truncation_and_even_whitespace_trailing_bytes_are_refused(encoding):
    data = ply(encoding=encoding)
    no_body_geometry(data[:-1])
    no_body_geometry(data + b" ")


def test_declared_prefix_never_promotes_an_apparently_complete_body():
    data = ply()
    report = no_body_geometry(data, complete=False)
    assert {json.dumps(tag, sort_keys=True) for tag in probe_media(data, complete=False)["tag_proposals"]} <= {
        json.dumps(tag, sort_keys=True) for tag in report["tag_proposals"]
    }


def test_late_invalid_vertex_keeps_header_candidates_but_no_observed_geometry():
    data = ply([(1, 2, 3), (4, 5, "nan")])
    report = no_body_geometry(data)
    assert ("representation", "point_cloud_candidate") in tags(report)
    assert all(item in report["metadata"] for item in probe_media(data)["metadata"])


@pytest.mark.parametrize("indices", [[], [0], [0, 1], [-1, 1, 2], [0, 1, 3]])
def test_face_counts_and_each_index_are_validated_against_vertex_count(indices):
    no_body_geometry(ply(faces=[(indices,)]))


def test_late_bad_face_does_not_leak_the_previously_valid_vertex_bounds():
    no_body_geometry(ply(faces=[([0, 1, 2],), ([0, 1, 99],)]))


def test_face_list_limit_allows_256_indices_but_refuses_257():
    props = [("list", "ushort", "int", "vertex_indices")]
    assert body_proof(probe_ply_body(ply(faces=[([index % 3 for index in range(256)],)], face_properties=props)))["face_count"] == 1
    no_body_geometry(ply(faces=[([index % 3 for index in range(257)],)], face_properties=props))


@pytest.mark.parametrize("properties,rows", [
    ([("float", "x"), ("float", "y")], [(1, 2)]),
    ([*XYZ, ("list", "uchar", "int", "neighbors")], [(1, 2, 3, [])]),
])
def test_nonempty_vertices_require_scalar_xyz_and_no_vertex_lists(properties, rows):
    no_body_geometry(ply(rows, properties=properties))


@pytest.mark.parametrize("face_properties,faces", [
    ([("list", "uchar", "float", "vertex_indices")], [([0, 1, 2],)]),
    ([("list", "uchar", "int", "other")], [([0, 1, 2],)]),
    ([("list", "uchar", "int", "vertex_indices"), ("list", "uchar", "int", "vertex_index")], [([0, 1, 2], [0, 1, 2])]),
])
def test_unsupported_face_list_shapes_are_not_called_valid_meshes(face_properties, faces):
    no_body_geometry(ply(faces=faces, face_properties=face_properties))


def test_zero_face_records_may_have_scalar_properties_without_an_index_list():
    report = probe_ply_body(ply(faces=[], face_properties=[("uchar", "material")]))
    assert body_proof(report)["face_count"] == 0
    assert values(report)["observed_face_count"] == 0


def test_unsupported_extra_face_list_is_refused_even_without_face_records():
    no_body_geometry(ply(faces=[], face_properties=[("list", "uchar", "int", "neighbors")]))


def test_zero_vertex_records_do_not_require_unobserved_xyz_properties():
    report = probe_ply_body(ply([], properties=[("float", "weight")]))
    assert body_proof(report)["vertex_count"] == 0
    assert values(report).get("geometry_bounds_xyz") is None


def test_unknown_elements_are_unsupported_even_when_their_declared_count_is_zero():
    elements = [("vertex", XYZ, POINTS), ("edge", [("int", "vertex1")], [])]
    data = header(elements) + encoded_rows(XYZ, POINTS, "ascii")
    no_body_geometry(data)


SPLAT_NAMES = [
    "x", "y", "z", "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
    "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3",
]
SPLAT_ROWS = [
    (1, 2, 3, 0.1, 0.2, 0.3, -2, -1, 0, 1, 0, 0, 0, 0),
    (-1, 5, 8, 0.3, 0.2, 0.1, 2, -2, -3, -4, 2, 0, 0, 0),
]


@pytest.mark.parametrize("encoding", ENCODINGS)
def test_gaussian_parameters_are_schema_facts_not_normalization_or_quality_checks(encoding):
    properties = [("float", name) for name in SPLAT_NAMES]
    report = probe_ply_body(ply(SPLAT_ROWS, properties=properties, encoding=encoding))
    assert ("representation", "gaussian_splat_body_candidate") in tags(report)
    assert values(report)["gaussian_parameters"] == {
        "schema_compatible": True, "record_count": 2, "zero_rotation_records": 1,
    }
    assert not any(item["namespace"] == "quality" for item in report["tag_proposals"])
    assert body_proof(report)["field_value_count"] == 28
    assert report.get("spatial") is None


@pytest.mark.parametrize("rest_indices,expected", [([], True), ([0, 1, 2], True), ([0, 1], False), ([0, 2, 3], False), ([1, 2, 3], False)])
def test_spherical_harmonic_rest_fields_need_contiguous_triplets(rest_indices, expected):
    properties = [("float", name) for name in SPLAT_NAMES]
    properties += [("float", f"f_rest_{index}") for index in rest_indices]
    rows = [(*SPLAT_ROWS[0], *([0] * len(rest_indices)))]
    report = probe_ply_body(ply(rows, properties=properties))
    body_proof(report)
    assert (("representation", "gaussian_splat_body_candidate") in tags(report)) is expected


def test_gaussian_core_fields_must_have_float_types_even_when_integer_values_fit():
    properties = [("int" if name == "rot_3" else "float", name) for name in SPLAT_NAMES]
    report = probe_ply_body(ply([SPLAT_ROWS[0]], properties=properties))
    body_proof(report)
    assert ("representation", "gaussian_splat_body_candidate") not in tags(report)


def test_vertex_and_property_budgets_have_exact_inclusive_boundaries():
    assert body_proof(probe_ply_body(ply([(0, 0, 0)] * 10000)))["vertex_count"] == 10000
    no_body_geometry(ply([(0, 0, 0)] * 10001))
    properties = [*XYZ, *(("float", f"extra_{index}") for index in range(253))]
    assert body_proof(probe_ply_body(ply([tuple([0] * 256)], properties=properties)))["field_value_count"] == 256
    no_body_geometry(ply([tuple([0] * 257)], properties=[*properties, ("float", "one_too_many")]))


def test_face_budget_has_an_inclusive_10000_record_boundary():
    face = ([0, 1, 2],)
    assert body_proof(probe_ply_body(ply(faces=[face] * 10000)))["face_count"] == 10000
    no_body_geometry(ply(faces=[face] * 10001))


def test_field_value_budget_counts_list_lengths_and_items_without_partial_proof():
    properties = [*XYZ, *(("float", f"extra_{index}") for index in range(17))]
    rows = [tuple([0] * 20)] * 10000
    assert body_proof(probe_ply_body(ply(rows, properties=properties)))["field_value_count"] == 200000
    no_body_geometry(ply(rows, properties=properties, faces=[([0, 1, 2],)]))


def test_header_line_budget_has_an_inclusive_2048_line_boundary():
    comments = ["comment fixture"] * (2048 - 7)
    assert body_proof(probe_ply_body(ply([(0, 0, 0)], comments=comments)))["vertex_count"] == 1
    no_body_geometry(ply([(0, 0, 0)], comments=[*comments, "comment one too many"]))


def test_header_byte_budget_has_an_inclusive_64_kib_boundary():
    elements = [("vertex", XYZ, [(0, 0, 0)])]
    unpadded = header(elements, comments=["comment "])
    padding = 65536 - len(unpadded)
    assert padding > 0
    data = header(elements, comments=["comment " + "x" * padding]) + b"0 0 0\n"
    assert data.index(b"end_header\n") + len(b"end_header\n") == 65536
    assert body_proof(probe_ply_body(data))["vertex_count"] == 1
    data = header(elements, comments=["comment " + "x" * (padding + 1)]) + b"0 0 0\n"
    no_body_geometry(data)


COMMENT_CONTROLS = [b"\x0b", b"\x0c", b"\x1c", b"\x1d", b"\x1e"]


@pytest.mark.parametrize("control", COMMENT_CONTROLS)
def test_non_line_break_controls_in_a_comment_before_vertex_do_not_crash(control):
    # PLY header lines are byte-delimited. str.splitlines() would give these
    # embedded controls a different meaning and expose a stray header word.
    comment = "comment fixture" + control.decode("ascii") + "word"
    data = ply([(1, 2, 3)], comments=[comment])
    report = probe_ply_body(data)
    assert body_proof(report)["field_value_count"] == 3
    assert values(report)["geometry_bounds_xyz"]["min"] == [1, 2, 3]


@pytest.mark.parametrize("control", COMMENT_CONTROLS)
@pytest.mark.parametrize("body", [b"1 2 3\n", b"1 2 3 4\n"])
def test_property_text_inside_a_comment_never_changes_the_record_schema(control, body):
    head = header([("vertex", XYZ, [(0, 0, 0)])])
    comment = b"comment fixture" + control + b"property float x\n"
    data = head.replace(b"end_header\n", comment + b"end_header\n") + body
    if body == b"1 2 3\n":
        report = probe_ply_body(data)
        assert body_proof(report)["field_value_count"] == 3
        assert values(report)["geometry_bounds_xyz"]["min"] == [1, 2, 3]
    else:
        no_body_geometry(data)


@pytest.mark.parametrize("control", COMMENT_CONTROLS)
def test_hidden_gaussian_property_text_cannot_turn_trailing_values_into_a_candidate(control):
    head = header([("vertex", XYZ, [(0, 0, 0)])])
    hidden = [b"property float " + name.encode("ascii") for name in SPLAT_NAMES[3:]]
    comment = b"comment fixture" + control + control.join(hidden) + b"\n"
    body = b"1 2 3 0 0 0 -2 -1 0 1 0 0 0 0\n"
    data = head.replace(b"end_header\n", comment + b"end_header\n") + body
    report = no_body_geometry(data)
    assert ("representation", "point_cloud_candidate") in tags(report)
    assert ("representation", "gaussian_splat_candidate") not in tags(report)


@pytest.mark.parametrize("data", [b"", b"PLY\n", b"{}", b"not ply", b"ply", b"ply \n"])
def test_non_ply_content_returns_none(data):
    assert probe_ply_body(data) is None


@pytest.mark.parametrize("data", [
    b"ply\nformat ascii 1.0\n", b"ply\nformat ascii 1.1\nend_header\n",
    b"ply\nformat ascii 1.0\nelement vertex 1\nproperty long x\nend_header\n0\n",
])
def test_recognized_but_invalid_headers_never_gain_body_evidence(data):
    no_body_geometry(data)


@pytest.mark.parametrize("data,complete", [
    ("ply\n", True), (bytearray(b"ply\n"), True), (memoryview(b"ply\n"), True),
    (b"", 1), (b"", None), (b" " * (1024 * 1024 + 1), True),
])
def test_api_requires_exact_bytes_boolean_completeness_and_one_mib_limit(data, complete):
    with pytest.raises(ValueError):
        probe_ply_body(data, complete=complete)


def test_parser_performs_no_file_process_or_network_access(monkeypatch):
    import socket
    import subprocess

    data = ply()

    def forbidden(*args, **kwargs):
        raise AssertionError("PLY body probe attempted external access")

    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", forbidden)
        guard.setattr(socket, "create_connection", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        report = probe_ply_body(data)
    assert body_proof(report)["vertex_count"] == 3


def test_reports_repeat_and_each_metadata_and_tag_reference_resolves():
    data = ply()
    report = probe_ply_body(data)
    assert report == probe_ply_body(data)
    evidence_ids = {item["id"] for item in report["evidence"]}
    assert len(evidence_ids) == len(report["evidence"])
    for item in report["metadata"]:
        assert item["evidence_ref"] in evidence_ids
    for item in report["tag_proposals"]:
        assert set(item["evidence_refs"]) <= evidence_ids
    assert json.loads(json.dumps(report, allow_nan=False)) == report
