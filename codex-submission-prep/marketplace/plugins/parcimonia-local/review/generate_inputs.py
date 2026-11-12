"""Print authored review inputs with fresh timestamps; execute no tool or route.

The route numbers are synthetic, not a measured benchmark. Refreshing their
timestamps is for this authored example only, never for stale real evidence.
"""
from pathlib import Path
import copy
import json
import time

documents = json.loads(Path(__file__).with_name("supplied-documents.json").read_text(encoding="utf-8"))
now = time.time()
gib = 1024 ** 3
snapshot = {"observed_at": now, "hardware_key": "a" * 64, "ram_available_bytes": 24 * gib,
            "commit_available_bytes": 32 * gib, "disk_free_bytes": 64 * gib,
            "gpu_free_bytes": [], "heavy_busy": False}
measurement = {"workload_sha256": "b" * 64, "hardware_key": "a" * 64, "recorded_at": now - 1,
    "samples": 3, "passed": 3, "verifier_revision": "fixture.exact/v1", "p50_ms": 2,
    "p95_ms": 4, "cold_start_ms": 100, "warm_start_ms": 1, "cloud_cost_usd": 0}
warm = {"id": "warm-cpu", "task": "json_minify", "device": "cpu", "availability": "ready",
        "warm": True, "heavy": False, "ram_bytes": gib, "commit_bytes": gib,
        "disk_bytes": 0, "vram_bytes": 0, "measurement": measurement}
cold = copy.deepcopy(warm)
cold.update(id="cold-cpu", warm=False)
cold["measurement"].update(p50_ms=1, p95_ms=2)
context = {"query": "fraîcheur profils cache mémoire", "documents": documents, "top_k": 5}
plan = {"request": {"task": "json_minify", "workload_sha256": "b" * 64},
        "snapshot": snapshot, "candidates": [warm, cold]}
missing = copy.deepcopy(plan)
for route in missing["candidates"]:
    route["measurement"] = None
wrong_hash = copy.deepcopy(context)
wrong_hash["documents"][0]["content_sha256"] = "0" * 64
escaping = copy.deepcopy(context)
escaping["documents"][0]["path"] = "../private/credentials.txt"
print(json.dumps({"data_origin": "authored_fixture_not_measured", "cases": {
    "P1": ["parcimonia_local_hardware", {}],
    "P2": ["parcimonia_local_context", context],
    "P3": ["parcimonia_local_context", context],
    "P4": ["parcimonia_local_context", {**context, "top_k": 1}],
    "P5": ["parcimonia_local_plan", plan], "N1": ["parcimonia_local_plan", missing],
    "N2": ["parcimonia_local_context", wrong_hash], "N3": ["parcimonia_local_context", escaping],
}}, ensure_ascii=True, indent=2))
