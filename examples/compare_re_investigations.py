"""Compare labelled investigation packets locally, without calling a model."""
from __future__ import annotations

import argparse
from pathlib import Path

from tiberium_ai.decision_json import canonical_json
from tiberium_ai.re_investigation_bench import compare_cases
from prepare_re_investigation import ROOT, read_json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args(argv)
    output=args.output_dir.resolve()
    output.relative_to((ROOT/"runs").resolve())
    if output.exists():
        raise FileExistsError("use a new benchmark output directory")
    spec=read_json(args.cases,262144)
    if set(spec)!={"schema_version","cases"} or type(spec["schema_version"]) is not int or spec["schema_version"]!=1:
        raise ValueError("invalid benchmark corpus")
    if not isinstance(spec["cases"],list) or not 1<=len(spec["cases"])<=100:
        raise ValueError("provide 1..100 cases")
    parent=args.cases.resolve(strict=True).parent
    cases=[]
    for row in spec["cases"]:
        if set(row)!={"id","origin","state","inventory","workspace_root","expected_files","expected_route"}:
            raise ValueError("invalid benchmark case fields")
        cases.append({"id":row["id"],"origin":row["origin"],"state":read_json(parent/row["state"],262144),
            "inventory":read_json(parent/row["inventory"],262144),
            "roots":{"workspace":(parent/row["workspace_root"]).resolve(strict=True)},
            "expected_files":row["expected_files"],"expected_route":row["expected_route"]})
    report=compare_cases(cases)
    output.mkdir(parents=True,exist_ok=False)
    (output/"report.json").write_text(canonical_json(report),encoding="utf-8")
    print(f"cases={len(cases)} arms=rules,rules_retrieval jev=not_run sft=not_run")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
