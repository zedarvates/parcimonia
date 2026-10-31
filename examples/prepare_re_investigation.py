"""Prepare an observation-only REA/LeanREA packet; optional offline decision replay."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from tiberium_ai.decision_adapter import DecisionRecord
from tiberium_ai.decision_json import canonical_json
from tiberium_ai.execution_profiles import content_digest
from tiberium_ai.registry import _reject_constant, _reject_duplicate_keys
from tiberium_ai.re_investigation import prepare_investigation
from tiberium_ai.task_followup import record_file_review
from tiberium_ai.task_preparation import preparation_policy, render_packet

ROOT = Path(__file__).resolve().parents[1]


def read_json(path, limit=16777216):
    with Path(path).open("rb") as stream:
        data=stream.read(limit+1)
    if len(data)>limit:
        raise ValueError("JSON input exceeds byte budget")
    return json.loads(data.decode("utf-8-sig"),parse_constant=_reject_constant,
                      object_pairs_hook=_reject_duplicate_keys)


def render_advice(advice):
    rows=["# Investigation Parcimonia–REA/LeanREA", "", "Propositions à examiner ; aucune exécution autorisée par ce rapport.",
          "", "## Prochaine investigation proposée", ""]
    selection=advice["baseline"]["next_probe"]
    rows.append(advice["option_bindings"]["next_probe"].get(selection,"Contexte supplémentaire nécessaire"))
    rows.extend(["", "## Preuves manquantes", ""])
    rows.extend(f"- {g['claim']} / {g['scenario']} : {g['level']} — {g['reason']}" for g in advice["coverage"]["missing"])
    if not advice["coverage"]["missing"]:
        rows.append("Les niveaux déclarés sont rapportés ; la portée et les preuves restent à vérifier indépendamment.")
    rows.extend(["", "## Limites", "", "Les preuves sont rapportées par l'hôte. Le module ne relit pas les artefacts de preuve.",
        "Les routes disponibles sont déclarées par l'hôte ; vérifier à nouveau leur disponibilité et leurs permissions avant action.",
        "Aucun appel réseau, aucun test du logiciel cible et aucune conclusion de parité ne sont produits par cette CLI.",
        f"Jugement auxiliaire : {advice['judgment_status']}.", ""])
    return "\n".join(rows)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state",type=Path,required=True)
    parser.add_argument("--inventory",type=Path,required=True)
    parser.add_argument("--workspace-root",type=Path,default=ROOT)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--policy",type=Path)
    parser.add_argument("--strict",action="store_true")
    parser.add_argument("--previous-run",type=Path)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--review",type=Path)
    group.add_argument("--feedback",type=Path)
    parser.add_argument("--decision-record",type=Path,help="Offline replay only; no network transport is installed")
    args=parser.parse_args(argv)
    output=args.output_dir.resolve()
    output.relative_to((ROOT/"runs").resolve())
    if output.exists():
        raise FileExistsError("use a new output directory")
    if (args.review or args.feedback) and not args.previous_run:
        raise ValueError("a review or feedback needs --previous-run")
    state=read_json(args.state,262144)
    inventory=read_json(args.inventory,262144)
    roots={"workspace":args.workspace_root.resolve(strict=True)}
    policy=preparation_policy(read_json(args.policy,65536) if args.policy else None,strict=args.strict)
    options={"policy":policy}
    review=None
    if args.previous_run:
        previous=args.previous_run.resolve(strict=True)
        options["previous_index"]=read_json(previous/"index.json")
        if args.review or args.feedback:
            packet=read_json(previous/"packet.json")
            review=read_json(args.review) if args.review else record_file_review(packet,read_json(args.feedback),roots=roots,
                at=datetime.now(timezone.utc).isoformat())
            options.update(previous_packet=packet,review=review)
    if args.decision_record:
        record=DecisionRecord(**read_json(args.decision_record,1048576))
        options.update(decision_record=record,backend_id=record.backend_id,backend_version=record.backend_version)
    result=prepare_investigation(state,inventory,roots,**options)
    artifacts={name+".json":canonical_json(result[name]) for name in ("index","packet","advice")}
    artifacts.update({"packet.md":render_packet(result["packet"]),"advice.md":render_advice(result["advice"]),
                      "state.json":canonical_json(state)})
    if review is not None:
        artifacts["file-review.json"]=canonical_json(review)
    output.mkdir(parents=True,exist_ok=False)
    for name,data in artifacts.items():
        (output/name).write_text(data,encoding="utf-8")
    manifest={"version":"re-investigation-delivery/1","status":"complete","auto_act_allowed":False,
        "execution":"not_run","artifacts":{name:content_digest((output/name).read_bytes()) for name in artifacts}}
    (output/"manifest.json").write_text(canonical_json(manifest),encoding="utf-8")
    print(json.dumps({"status":"prepared","files":len(result["packet"]["files"]),
        "gaps":len(result["advice"]["coverage"]["missing"]),"judgment":result["advice"]["judgment_status"],
        "auto_act_allowed":False,"output":str(output)}))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
