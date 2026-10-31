from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from tiberium_ai.execution_profiles import content_digest
from tiberium_ai.re_investigation import advise_investigation
from tiberium_ai.re_investigation_bench import compare_cases
from test_re_investigation import state, choose_first
from test_task_preparation import inventory


@pytest.fixture
def cli(tmp_path):
    source=Path(__file__).parents[1]/"examples/prepare_re_investigation.py"
    spec=importlib.util.spec_from_file_location("re_investigation_cli_fixture",source)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT=tmp_path/"delivery"
    return module


def args(tmp_path):
    data=inventory(tmp_path)
    (tmp_path/"inventory.json").write_text(json.dumps(data),encoding="utf-8")
    (tmp_path/"state.json").write_text(json.dumps(state()),encoding="utf-8")
    return ["--state",str(tmp_path/"state.json"),"--inventory",str(tmp_path/"inventory.json"),
            "--workspace-root",str(tmp_path),"--output-dir",str(tmp_path/"delivery/runs/first")]


def test_cli_writes_real_packet_with_manifest_and_no_implicit_execution(cli,tmp_path):
    argv=args(tmp_path)
    assert cli.main(argv)==0
    out=tmp_path/"delivery/runs/first"
    manifest=json.loads((out/"manifest.json").read_text())
    assert manifest["auto_act_allowed"] is False
    assert manifest["execution"]=="not_run"
    for name,sha in manifest["artifacts"].items():
        assert content_digest((out/name).read_bytes())==sha
    with pytest.raises(FileExistsError):cli.main(argv)


def test_cli_duplicate_key_rejected_before_output(cli,tmp_path):
    argv=args(tmp_path)
    (tmp_path/"state.json").write_text('{"schema_version":1,"schema_version":1}',encoding="utf-8")
    with pytest.raises(ValueError):cli.main(argv)
    assert not (tmp_path/"delivery").exists()


def test_cli_rejects_output_outside_runs(cli,tmp_path):
    argv=args(tmp_path);argv[-1]=str(tmp_path/"unowned-output")
    with pytest.raises(ValueError):cli.main(argv)
    assert not (tmp_path/"unowned-output").exists()


def test_cli_continues_saved_review_without_overwriting_first_run(cli,tmp_path):
    argv=args(tmp_path);cli.main(argv)
    first=tmp_path/"delivery/runs/first"
    before=(first/"manifest.json").read_bytes()
    feedback={"task_id":"re-test","stage_id":"inspect","reviewer":"fixture","reviewer_kind":"agent",
        "review_complete":False,"judgments":[{"source":{"root":"workspace","path":"sample.py"},
        "status":"used","reason":"read"}],"missing_files":[],"notes":[],"additional_searches":None,"additional_reads":1}
    (tmp_path/"feedback.json").write_text(json.dumps(feedback),encoding="utf-8")
    s=state();s["stage_id"]="verify"
    (tmp_path/"state.json").write_text(json.dumps(s),encoding="utf-8")
    second_args=argv[:-1]+[str(tmp_path/"delivery/runs/second"),"--previous-run",str(first),"--feedback",str(tmp_path/"feedback.json")]
    cli.main(second_args)
    second=tmp_path/"delivery/runs/second"
    packet=json.loads((second/"packet.json").read_text())
    assert packet["continuity"]["previous_stage_id"]=="inspect"
    assert (second/"file-review.json").exists()
    assert (first/"manifest.json").read_bytes()==before


def test_cli_replays_bound_record_offline(cli,tmp_path):
    argv=args(tmp_path);cli.main(argv)
    first=tmp_path/"delivery/runs/first"
    packet=json.loads((first/"packet.json").read_text())
    recorded=advise_investigation(state(),packet,transport=choose_first,
        backend_id="fixture.choice",backend_version="1")
    record_path=tmp_path/"decision-record.json"
    record_path.write_text(json.dumps(recorded["decision_record"]),encoding="utf-8")
    cli.main(argv[:-1]+[str(tmp_path/"delivery/runs/replay"),"--decision-record",str(record_path)])
    advice=json.loads((tmp_path/"delivery/runs/replay/advice.json").read_text())
    assert advice["judgment_status"]=="shadow_judgments"
    assert advice["metrics"]["decision_transport_calls"]==0
    assert advice["auto_act_allowed"] is False


def test_benchmark_labels_are_not_sent_to_advisor_and_model_arms_stay_not_run(tmp_path):
    inv=inventory(tmp_path)
    cases=[{"id":"fixture-case","origin":"authored_fixture","state":state(),"inventory":inv,
        "roots":{"workspace":tmp_path},"expected_files":["sample.py","not_in_inventory.md"],"expected_route":"lean.inspect"}]
    report=compare_cases(cases)
    assert report["arms"]["rules"][0]["missing_files"]==["not_in_inventory.md"]
    assert report["arms"]["rules_retrieval"][0]["derived_reused"]==2
    assert report["arms"]["rules_retrieval"][0]["index_files_read"]==2
    assert report["jev"]["status"]=="not_run"
    assert report["sft"]["status"]=="not_run"
    assert report["task_time_saved"] is None
    assert report["arms"]["rules"][0]["route_matches_label"]
