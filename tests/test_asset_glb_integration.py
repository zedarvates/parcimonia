"""GLB evidence through the actual inspection, snapshot, review and CLI APIs."""

from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

import pytest

from examples.asset_catalog_demo import _png, _wav
from examples.glb_catalog_demo import fixture, glb_bytes, run_demo
from tiberium_ai.asset_catalog import search_asset_reports
from tiberium_ai.asset_catalog_snapshot import create_asset_catalog, export_asset_reports, put_asset_report
from tiberium_ai.asset_cli import main
from tiberium_ai.asset_inspection import inspect_asset
from tiberium_ai.asset_tag_journal import append_tag_decision, create_tag_journal, validated_review_report_hash
from tiberium_ai.asset_tag_review import search_reviewed_assets
from tiberium_ai.glb_probe import PROFILE_ID
from tiberium_ai.media_probe import probe_media
from tiberium_ai.verification import hash_input


def inspect(data=None, **kwargs):
    document,binary=fixture()
    return inspect_asset(glb_bytes(document,binary) if data is None else data,
                         filename="model.glb", source_id="fixture:glb", revision="v1", **kwargs)


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    return path


def ok(capsys,*args):
    assert main([str(arg) for arg in args])==0
    result=capsys.readouterr()
    assert result.err==""
    return json.loads(result.out)


def test_inspection_identity_exact_hash_and_limits_bind_the_new_profile():
    report=inspect(topic_terms={"model":["model"]})
    assert report["analyser"]=={"id":"asset-glb-inspection","version":"1"}
    assert report["input_hash"]==hash_input({"source":report["source"],"sample":report["sample"],
        "topic_terms":{"model":["model"]},"glb_profile":PROFILE_ID})
    assert report["limits"]["semantic_content"]=="not_assessed_glb_structure_only"
    assert report["limits"]["external_uri_access"]=="not_performed"
    assert report["limits"]["json_padding"]=="json_whitespace_accepted_not_strict_space_padding"
    assert report["status"]=="partial" and report["spatial"] is None
    assert json.loads(json.dumps(report,allow_nan=False))==report
    assert validated_review_report_hash(report)==hash_input(report)
    known={item["id"] for item in report["evidence"]}
    assert all(set(tag["evidence_refs"])<=known and tag["status"]=="proposed" for tag in report["tag_proposals"])


def test_original_media_header_api_is_unchanged_and_other_formats_keep_their_identity():
    document,binary=fixture()
    header=probe_media(glb_bytes(document,binary))
    assert header["analysis_scope"]=="header_only"
    assert not any(e["id"].startswith("glb:") for e in header["evidence"])
    for data,name in [(_png(),"picture.png"),(_wav(),"sound.wav"),(b"text","text.txt"),(b'{"asset":{"version":"2.0"}}',"scene.gltf")]:
        report=inspect_asset(data,filename=name,source_id="other",revision="v1")
        assert report["analyser"]=={"id":"asset-inspection","version":"1"}
        assert report["input_hash"]==hash_input({"source":report["source"],"sample":report["sample"],"topic_terms":None})


@pytest.mark.parametrize("data,options", [(b"glTF",{}),(glb_bytes({"asset":{"version":"2.0"}},None),{"complete":False,"total_bytes":1000})])
def test_bad_or_prefix_glb_reports_remain_searchable_headers_without_body_proposals(data,options):
    report=inspect(data,**options)
    validated_review_report_hash(report)
    assert search_asset_reports([report],tags=["format:glb"])["count"]==1
    assert search_asset_reports([report],tags=["resource:glb_json_read"])["count"]==0


def test_report_budget_at_maximum_resource_cardinality_and_gps_noninference():
    document={"asset":{"version":"2.0"},"extras":{"crs":"EPSG:4326","coordinates":[2,48]},
              "buffers":[{"uri":"x.bin","byteLength":1} for _ in range(64)],
              "images":[{"uri":"x.png"} for _ in range(64)]}
    report=inspect(glb_bytes(document))
    validated_review_report_hash(report)
    snapshot=create_asset_catalog("fixture:maximum")
    snapshot=put_asset_report(snapshot,report,expected_head=snapshot["snapshot_hash"],expected_report_hash=None)
    assert len(export_asset_reports(snapshot))==1
    assert search_asset_reports([report],tags=["resource:external_uri_declared"])["count"]==1
    assert search_asset_reports([report],bbox=[-180,-90,180,90])["count"]==0
    assert len(report["tag_proposals"])<256


def test_binary_change_invalidates_acceptance_and_saved_snapshot_retains_its_report():
    document,binary=fixture()
    payload=glb_bytes(document,binary)
    original=inspect(payload)
    journal=append_tag_decision(create_tag_journal(),original,namespace="resource",value="external_uri_declared",
        action="accept",actor_id="fixture:reviewer",reason="Declarations checked",event_id="accept",expected_head=None)
    snapshot=create_asset_catalog("fixture:catalog")
    snapshot=put_asset_report(snapshot,original,expected_head=snapshot["snapshot_hash"],expected_report_hash=None)
    changed=inspect(glb_bytes(document,binary[:-1]+b"X"))
    assert changed["sample"]["sha256"]!=original["sample"]["sha256"]
    assert search_reviewed_assets([changed],journal,tags=["resource:external_uri_declared"],states=["accepted"])["count"]==0
    assert search_reviewed_assets(export_asset_reports(snapshot),journal,tags=["resource:external_uri_declared"],states=["accepted"])["count"]==1
    assert original["sample"]["sha256"]==hashlib.sha256(payload).hexdigest()


def test_actual_cli_snapshot_export_and_search_preserve_source_and_old_files(tmp_path,capsys):
    document,binary=fixture()
    source=tmp_path/"fixture.glb"
    source.write_bytes(glb_bytes(document,binary))
    report=ok(capsys,"inspect",source,"--source-id","fixture:glb","--revision","v1")
    report_path=dump(tmp_path/"report.json",report)
    empty_path=tmp_path/"empty.json"
    initial=ok(capsys,"catalog-init",empty_path,"--catalog-id","fixture:glb")
    old={path:path.read_bytes() for path in (source,report_path,empty_path)}
    selected=tmp_path/"selected.json"
    ok(capsys,"catalog-put",empty_path,report_path,"--expected-head",initial["snapshot_hash"],"--expected-report-hash","none","--out",selected)
    reports=ok(capsys,"catalog-export",selected)
    result_path=dump(tmp_path/"reports.json",reports)
    search=ok(capsys,"search",result_path,"--tag","resource:external_uri_declared")
    assert search["count"]==1
    assert {path:path.read_bytes() for path in old}==old


def test_demo_search_and_review_outcomes_reproduce_exactly():
    demo=run_demo()
    assert demo==run_demo()
    assert [demo[k] for k in ["proposed","accepted_before","accepted_after","accepted_after_binary_change","gps_matches"]]==[1,0,1,0,0]
    validated_review_report_hash(demo["report"])


def test_foreign_identity_is_still_refused_and_returned_reports_do_not_share_state():
    original=inspect()
    changed=deepcopy(original)
    changed["analyser"]["version"]="2"
    with pytest.raises(ValueError):search_asset_reports([changed])
    original["metadata"][0]["value"]=99
    assert inspect()["metadata"][0]["value"]==2


def test_real_cli_and_demo_execute_with_ascii_pipes(tmp_path):
    document,binary=fixture()
    path=tmp_path/"fixture.glb"
    path.write_bytes(glb_bytes(document,binary))
    env={**os.environ,"PYTHONPATH":"src","PYTHONIOENCODING":"ascii:strict"}
    call=subprocess.run([sys.executable,"-m","tiberium_ai.asset_cli","inspect",str(path),"--source-id","modèle:été","--revision","v1"],
        env=env,capture_output=True,timeout=15,check=True)
    assert call.stderr==b""
    report=json.loads(call.stdout.decode("ascii"))
    assert report["source"]["id"]=="modèle:été"
    validated_review_report_hash(report)
    demo=subprocess.run([sys.executable,"-m","examples.glb_catalog_demo"],env=env,capture_output=True,timeout=15,check=True)
    assert demo.stderr==b"" and json.loads(demo.stdout.decode("ascii"))==run_demo()
