"""GLB framing, declared resources and atomic refusal, without decoders or I/O."""

import hashlib
import json
import struct

import pytest

from examples.glb_catalog_demo import fixture, glb_bytes
from tiberium_ai.glb_probe import PROFILE_ID, probe_glb


def metadata(report):
    return {item["name"]: item["value"] for item in report["metadata"]}


def minimal(**extra):
    return {"asset": {"version": "2.0"}, **extra}


def raw_json(payload):
    payload += b" " * (-len(payload) % 4)
    return b"glTF" + struct.pack("<IIII", 2, 20+len(payload), len(payload), 0x4E4F534A) + payload


def refused(data, reason=None, **options):
    report = probe_glb(data, **options)
    assert report["analysis_scope"] == "header_only"
    assert not any(item["id"].startswith("glb:") for item in report["evidence"])
    assert not any(item["name"].startswith(("gltf_", "glb_")) for item in report["metadata"])
    assert not any(tag["namespace"] == "resource" for tag in report["tag_proposals"])
    assert report["spatial"] is None
    if reason is not None: assert reason in report["issues"]
    return report


def test_minimal_json_only_and_framing_proof_do_not_claim_a_full_asset():
    payload = glb_bytes(minimal())
    report = probe_glb(payload)
    assert report["analysis_scope"] == "glb_core_resource_profile"
    assert report["issues"] == ["glb_profile_not_full_gltf_validation"]
    values = metadata(report)
    assert values["glb_chunk_count"] == 1 and values["gltf_core_resources"] == []
    assert all(count == 0 for count in values["gltf_declared_counts"].values())
    chunks = next(e for e in report["evidence"] if e["id"] == "glb:chunks")
    assert chunks["profile"] == PROFILE_ID
    assert chunks["chunks"][0]["byte_range"] == [20, len(payload)]


def test_buffer_and_image_ranges_are_actual_unpadded_bytes_and_uri_declarations_are_unknown():
    document, binary = fixture()
    payload = glb_bytes(document, binary)
    report = probe_glb(payload)
    values = metadata(report)
    resources = values["gltf_core_resources"]
    assert len(resources) == 5
    owner, external, embedded_uri, image, external_image = resources
    assert owner["storage"] == "bin_chunk" and owner["availability"] == "range_present"
    assert payload[slice(*owner["byte_range"])] == binary
    assert external["uri"] == "geometry/extra.bin" and external["availability"] == "not_checked"
    assert embedded_uri["storage"] == "data_uri" and embedded_uri["uri"] is None
    assert embedded_uri["uri_sha256"] == hashlib.sha256(document["buffers"][2]["uri"].encode()).hexdigest()
    assert embedded_uri["availability"] == "not_checked"
    assert image["storage"] == "buffer_view" and image["availability"] == "range_present"
    assert payload[slice(*image["byte_range"])] == binary[36:]
    assert external_image["uri"] == "textures/bois%20été.png" and external_image["availability"] == "not_checked"
    proofs = {e["id"]: e for e in report["evidence"]}
    for resource in resources:
        proof = proofs[resource["evidence_ref"]]
        assert proof["json_pointer"] == resource["pointer"]
        assert proof["evidence_refs"] == ["glb:json"]
        if "byte_range" in resource: assert proof["byte_range"] == resource["byte_range"]
    assert values["gltf_declared_counts"]["meshes"] == 1
    assert report["modalities"] == ["3d"] and report["spatial"] is None


@pytest.mark.parametrize("size", [1,2,3,4,5])
def test_bin_padding_zero_to_three_bytes_and_leading_space_are_preserved(size):
    binary = b" " + bytes(range(size-1))
    payload = glb_bytes(minimal(buffers=[{"byteLength":size}]), binary)
    resource = metadata(probe_glb(payload))["gltf_core_resources"][0]
    assert payload[slice(*resource["byte_range"])] == binary


@pytest.mark.parametrize("binary,length,reason", [
    (None,1,"glb_bin_buffer_missing"),
    (b"1234",5,"glb_bin_buffer_extent_mismatch"),
    (b"12345678",4,"glb_bin_buffer_extent_mismatch"),
    (b"abcX",3,"glb_bin_padding_not_zero"),
])
def test_bin_buffer_missing_extent_and_padding_fail_atomically(binary,length,reason):
    refused(glb_bytes(minimal(buffers=[{"byteLength":length}]),binary),reason)


def test_external_owner_makes_its_buffer_view_image_availability_unknown():
    document = minimal(buffers=[{"byteLength":5,"uri":"https://example.invalid/buffer"}],
                       bufferViews=[{"buffer":0,"byteOffset":1,"byteLength":4}],
                       images=[{"bufferView":0,"mimeType":"image/png"}])
    resources = metadata(probe_glb(glb_bytes(document)))["gltf_core_resources"]
    assert resources[1]["availability"] == "not_checked" and "byte_range" not in resources[1]


@pytest.mark.parametrize("mutation,reason", [
    (lambda d:d["buffers"][0].update(byteLength=True),"glb_resource_integer_outside_profile"),
    (lambda d:d["buffers"][0].update(byteLength=0),"glb_resource_integer_outside_profile"),
    (lambda d:d["buffers"][0].update(byteLength=1.0),"glb_resource_integer_outside_profile"),
    (lambda d:d["buffers"][1].pop("uri"),"glb_implicit_buffer_outside_profile"),
    (lambda d:d["bufferViews"][0].update(buffer=True),"glb_resource_integer_outside_profile"),
    (lambda d:d["bufferViews"][0].update(buffer=3),"glb_buffer_view_out_of_declared_bounds"),
    (lambda d:d["bufferViews"][0].update(byteLength=2**32),"glb_resource_integer_outside_profile"),
    (lambda d:d["bufferViews"][0].update(byteOffset=-1),"glb_resource_integer_outside_profile"),
    (lambda d:d["bufferViews"][0].update(byteOffset=2**32-1),"glb_buffer_view_out_of_declared_bounds"),
    (lambda d:d["bufferViews"][0].update(byteLength=0),"glb_resource_integer_outside_profile"),
    (lambda d:d["images"][0].update(uri="both.png"),"glb_image_core_source_outside_profile"),
    (lambda d:d["images"][0].pop("mimeType"),"glb_buffer_view_image_mime_missing"),
    (lambda d:d["images"][0].update(bufferView=True),"glb_resource_integer_outside_profile"),
    (lambda d:d["images"][0].update(bufferView=999),"glb_image_buffer_view_out_of_range"),
    (lambda d:d["images"][1].pop("uri"),"glb_image_core_source_outside_profile"),
    (lambda d:d["images"][1].update(uri="x\n.png"),"glb_resource_text_outside_profile"),
    (lambda d:d.update(meshes=[None]),"glb_declaration_array_outside_profile"),
    (lambda d:d.update(asset={"version":"1.0"}),"glb_gltf_version_outside_profile"),
    (lambda d:d["asset"].update(minVersion="2.1"),"glb_min_version_outside_profile"),
])
def test_profile_failures_after_partial_local_work_never_leak_inventory(mutation,reason):
    document,binary=fixture()
    mutation(document)
    refused(glb_bytes(document,binary),reason)


@pytest.mark.parametrize("payload", [b'{"asset":{"version":"2.0","version":"2.0"}}',
    b'{"asset":{"version":"2.0"},"extras":NaN}', b'{"asset":{"version":"2.0"},"extras":1e999}',
    b'{"asset":{"version":"2.0"},"extras":"\\ud800"}', b'\xef\xbb\xbf{"asset":{"version":"2.0"}}',
    b'{"asset":{"version":"2.0"}}\0', b'\xff\xff', b'[]', b'{}', b''])
def test_json_duplicates_encoding_nonfinite_and_nonprofile_roots_are_refused(payload):
    refused(raw_json(payload))


def test_json_whitespace_is_parsed_without_claiming_strict_space_padding_validation():
    report = probe_glb(raw_json(b'{"asset":{"version":"2.0"}}\n\t'))
    assert report["analysis_scope"] == "glb_core_resource_profile"
    assert "glb_profile_not_full_gltf_validation" in report["issues"]


def test_unknown_chunks_and_extensions_are_recorded_without_following_them():
    document = minimal(extensionsUsed=["EXT_not_interpreted"],extensionsRequired=["EXT_not_interpreted"],
                       extensions={"EXT_not_interpreted":{"uri":"hidden-resource.bin"}})
    report = probe_glb(glb_bytes(document,extras=[(0x11223344,b"more")]))
    values = metadata(report)
    assert values["glb_unknown_chunk_count"] == 1 and values["gltf_core_resources"] == []
    assert values["gltf_extensions_required"] == ["EXT_not_interpreted"]
    assert {"glb_unknown_chunks_not_interpreted","gltf_extensions_not_interpreted"} <= set(report["issues"])


@pytest.mark.parametrize("options", [
    {"extensionsUsed":[True]}, {"extensionsUsed":["x","x"]},
    {"extensionsRequired":["x"]}, {"extensionsUsed":None},
    {"extensionsUsed":["x"*129]}, {"extensionsUsed":[str(i) for i in range(65)]},
])
def test_extension_declaration_profile_is_strict(options):
    refused(glb_bytes(minimal(**options)))


def test_orphan_bin_is_only_a_chunk_and_never_an_available_resource():
    report=probe_glb(glb_bytes(minimal(),b"data"))
    assert metadata(report)["glb_chunk_count"] == 2
    assert metadata(report)["gltf_core_resources"] == []
    assert not any(t["value"]=="bin_buffer_range_present" for t in report["tag_proposals"])


@pytest.mark.parametrize("scheme", ["data:","DATA:opaque", "file:///unreadable/file.bin", "../relative name.bin", "https://example.invalid/image?x#fragment"])
def test_uri_storage_classification_is_opaque_and_never_a_validity_or_existence_claim(scheme):
    report=probe_glb(glb_bytes(minimal(images=[{"uri":scheme}])))
    resource=metadata(report)["gltf_core_resources"][0]
    assert resource["storage"] == ("data_uri" if scheme.lower().startswith("data:") else "external_uri")
    assert resource["availability"] == "not_checked"


@pytest.mark.parametrize("count,valid", [(16,True),(17,False)])
def test_exact_chunk_budget(count,valid):
    data=glb_bytes(minimal(),extras=[(123,b"") for _ in range(count-1)])
    if valid: assert metadata(probe_glb(data))["glb_chunk_count"] == count
    else: refused(data,"glb_chunk_budget_exceeded")


@pytest.mark.parametrize("count,valid", [(64,True),(65,False)])
def test_buffer_and_image_resource_budgets(count,valid):
    document=minimal(buffers=[{"byteLength":1,"uri":"a.bin"} for _ in range(count)],
                     images=[{"uri":"a.png"} for _ in range(count)])
    if valid: assert len(metadata(probe_glb(glb_bytes(document)))["gltf_core_resources"])==128
    else: refused(glb_bytes(document),"glb_declaration_array_outside_profile")


@pytest.mark.parametrize("count,valid", [(256,True),(257,False)])
def test_declaration_and_buffer_view_budgets(count,valid):
    document=minimal(meshes=[{} for _ in range(count)],buffers=[{"byteLength":1,"uri":"a.bin"}],
                     bufferViews=[{"buffer":0,"byteLength":1} for _ in range(count)])
    if valid: assert metadata(probe_glb(glb_bytes(document)))["gltf_declared_counts"]["meshes"]==256
    else: refused(glb_bytes(document),"glb_declaration_array_outside_profile")


@pytest.mark.parametrize("extra,valid", [(0,True),(1,False)])
def test_exact_json_byte_budget(extra,valid):
    empty=json.dumps(minimal(extras=""),separators=(",",":")).encode()
    data=glb_bytes(minimal(extras="x"*(256*1024-len(empty)+extra)))
    if valid: assert probe_glb(data)["analysis_scope"] == "glb_core_resource_profile"
    else: refused(data,"glb_json_byte_budget_exceeded")


@pytest.mark.parametrize("count,valid", [(19996,True),(19997,False)])
def test_exact_json_node_budget(count,valid):
    data=glb_bytes(minimal(extras=[0]*count))
    if valid: assert probe_glb(data)["analysis_scope"] == "glb_core_resource_profile"
    else: refused(data,"glb_json_unusable")


@pytest.mark.parametrize("depth,valid", [(63,True),(64,False)])
def test_json_depth_budget(depth,valid):
    value=0
    for _ in range(depth):value=[value]
    data=glb_bytes(minimal(extras=value))
    if valid: assert probe_glb(data)["analysis_scope"] == "glb_core_resource_profile"
    else: refused(data,"glb_json_unusable")


@pytest.mark.parametrize("length,valid", [(2048,True),(2049,False)])
def test_external_uri_byte_budget(length,valid):
    data=glb_bytes(minimal(images=[{"uri":"a"*length}]))
    if valid: assert metadata(probe_glb(data))["gltf_core_resources"][0]["uri_bytes"]==length
    else: refused(data,"glb_external_uri_budget_exceeded")


@pytest.mark.parametrize("length,valid", [(65536,True),(65537,False)])
def test_data_uri_budget_and_no_payload_copy(length,valid):
    data=glb_bytes(minimal(images=[{"uri":"data:"+"a"*(length-5)}]))
    if valid:
        resource=metadata(probe_glb(data))["gltf_core_resources"][0]
        assert resource["uri"] is None and resource["uri_bytes"]==length
    else: refused(data,"glb_resource_text_outside_profile")


def test_chunk_order_duplicate_types_alignment_truncation_and_header_mismatch():
    good=glb_bytes(minimal())
    json_chunk=good[12:]
    cases=[
        b"glTF"+struct.pack("<II",2,12),
        good[:-1],good+b"more",
        b"glTF"+struct.pack("<II",2,12+len(json_chunk)*2)+json_chunk*2,
        glb_bytes(minimal(),extras=[(0x004E4942,b"data"),(0x004E4942,b"data")]),
        glb_bytes(minimal(),extras=[(123,b"data"),(0x004E4942,b"data")]),
        b"glTF"+struct.pack("<IIII",2,24,4,0x004E4942)+b"data",
        good[:12]+struct.pack("<I",len(good)-21)+good[16:],
        good[:12]+struct.pack("<I",len(good))+good[16:],
    ]
    for case in cases: refused(case)


def test_trailing_partial_chunk_header_with_consistent_file_length_is_refused():
    payload=bytearray(glb_bytes(minimal())+b"tail")
    struct.pack_into("<I",payload,8,len(payload))
    refused(bytes(payload),"glb_chunk_header_truncated")


def test_exact_complete_source_byte_limit_with_a_large_bin_payload():
    document=minimal(buffers=[{"byteLength":1}])
    length=1
    for _ in range(4):
        length=1024*1024-len(glb_bytes(document,b""))
        document["buffers"][0]["byteLength"]=length
    payload=glb_bytes(document,b"x"*length)
    assert len(payload)==1024*1024
    resource=metadata(probe_glb(payload))["gltf_core_resources"][0]
    assert resource["byte_range"][1]==len(payload)


def test_prefix_is_header_only_and_results_are_fresh_and_pure(monkeypatch):
    document,binary=fixture()
    payload=glb_bytes(document,binary)
    refused(payload,"glb_complete_source_required",complete=False)
    first=probe_glb(payload)
    def forbidden(*args,**kwargs): raise AssertionError("unexpected I/O")
    monkeypatch.setattr("builtins.open",forbidden)
    monkeypatch.setattr("subprocess.Popen",forbidden)
    monkeypatch.setattr("socket.socket",forbidden)
    assert probe_glb(payload)==first
    metadata(first)["gltf_core_resources"][0]["byte_range"][0]=0
    assert metadata(probe_glb(payload))["gltf_core_resources"][0]["byte_range"][0]>0
    assert probe_glb(b"ordinary text") is None


@pytest.mark.parametrize("data,complete", [(bytearray(b"glTF"),True),(b"x"*(1024*1024+1),True),(b"glTF",1)])
def test_public_input_budget_and_types(data,complete):
    with pytest.raises(ValueError):probe_glb(data,complete=complete)
