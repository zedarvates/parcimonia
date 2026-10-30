"""Offline authored fixture: reject a broken export despite its visual score.

This executes no model, renderer or editor. It demonstrates only the iteration
contract and prints a payload-free summary; it does not measure token savings.
"""

from __future__ import annotations

import json
import platform

from tiberium_ai.local_iteration import IterationBudget, improve_candidate
from tiberium_ai.measurement import Environment
from tiberium_ai.verification import VerifierRegistry


def main() -> int:
    registry = VerifierRegistry()
    registry.register("fixture/export", "1", lambda value: value["export_ok"] is True)
    candidates = iter([
        {"export_ok": False, "visual_score": 0.99, "revision": "broken"},
        {"export_ok": True, "visual_score": 0.75, "revision": "retained"},
        {"export_ok": True, "visual_score": 0.65, "revision": "regression"},
        {"export_ok": True, "visual_score": 0.75, "revision": "tie"},
    ])
    result = improve_candidate(
        task_id="authored-asset-fixture", route_id="fixture/no-model",
        produce=lambda index, best: next(candidates),
        evaluate=lambda value: value["visual_score"],
        registry=registry, verifier_id="fixture/export", verifier_version="1",
        evaluator_id="fixture/declared-score", evaluator_version="1",
        environment=Environment("cloud-fixture", {"python": platform.python_version()}),
        baseline={"export_ok": True, "visual_score": 0.5, "revision": "baseline"},
        budget=IterationBudget(max_iterations=6, patience=2),
    )
    report = {"data_origin": "authored_fixture", "model_calls": 0,
              "renderer_calls": 0, "result": result.to_record()}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
