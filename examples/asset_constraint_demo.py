"""Authored contradictory requirements and a revised, independently checked model."""

from copy import deepcopy
import json

from tiberium_ai.asset_expectation_constraints import (
    check_asset_expectations, register_asset_expectation_verifier,
)
from tiberium_ai.verification import VerifierRegistry


def run_demo() -> dict:
    initial = {
        "schema": "parcimonia.asset-expectations/v1", "id": "fixture:image-requirements",
        "assets": [{"source": {"id": "fixture:image", "revision": "v1"}, "checks": [
            {"id": "min-width", "fact": "metadata.width", "op": "gte", "value": 512},
            {"id": "max-width", "fact": "metadata.width", "op": "lte", "value": 256},
            {"id": "png", "fact": "format.detected", "op": "eq", "value": "png"},
        ]}],
    }
    revised = deepcopy(initial)
    revised["id"] = "fixture:revised-image-requirements"
    revised["assets"][0]["checks"][1]["value"] = 1024
    registry = VerifierRegistry()
    register_asset_expectation_verifier(registry)
    cases = []
    for label, request in [("contradictory", initial), ("revised", revised)]:
        report = check_asset_expectations(request)
        receipt = registry.verify("asset-expectation-constraints", "1", {"expectations": request, "report": report})
        cases.append({"label": label, "expectations": request, "report": report,
                      "verification": {"id": receipt.verifier_id, "version": receipt.verifier_version,
                                       "input_hash": receipt.input_hash, "verdict": receipt.verdict}})
    return {"data_origin": "authored_requirements_no_asset_inspected", "cases": cases}


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False))
