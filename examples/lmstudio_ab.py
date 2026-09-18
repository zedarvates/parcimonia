"""Run a real A/B on a local LM Studio server and write every artefact.

Requires LM Studio's OpenAI-compatible server (default 127.0.0.1:1234) with a
loaded model. Each repetition measures the run, verifies the output in the same
pass, writes a measurement/2 record and keeps the attributed evidence. The
observation is built from the last pair, because it compares two routes, and all
measurements are stored so medians stay auditable.

Usage:
    python examples/lmstudio_ab.py --model neohorse-1-9b --repeats 3
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from time import perf_counter

from tiberium_ai.adapters import completion_text, completion_tokens
from tiberium_ai.contracts import CandidateRoute, Task
from tiberium_ai.measurement import (
    WALL_CLOCK_METHOD,
    BaselineRun,
    Environment,
    write_measurement,
)
from tiberium_ai.observations import (
    compare_observation,
    record_observation,
    write_observation,
)
from tiberium_ai.resources import ResourceVector
from tiberium_ai.verification import (
    VerifierRegistry,
    attributed_evidence,
    exact_match_verifier,
)

PROMPT = "Reply with exactly: OK"
EXPECTED = "OK"
TASK_ID = "lmstudio-ab"
COST_UNIT = "synthetic-unit/task"
VERIFIER_ID = "answer/exact"
VERIFIER_VERSION = "ok"


def call(base_url: str, model: str, cap: int, timeout: float) -> tuple[dict, float]:
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": cap,
            "temperature": 0,
        }
    ).encode()
    request = urllib.request.Request(
        base_url + "/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    started = perf_counter()
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode())
    return payload, (perf_counter() - started) * 1000.0


def run_repetition(
    caps: list[int],
    *,
    base_url: str,
    model: str,
    repeats: int,
    timeout: float,
    out_dir: Path,
    registry: VerifierRegistry,
    environment: Environment,
) -> dict[str, dict]:
    summary: dict[str, dict] = {}
    for cap in caps:
        route_id = f"cap-{cap}"
        latencies: list[float] = []
        token_counts: list[int] = []
        verdicts: list[bool | None] = []
        last_evidence = None
        for attempt in range(1, repeats + 1):
            payload, latency_ms = call(base_url, model, cap, timeout)
            text = completion_text(payload).strip()
            tokens = completion_tokens(payload)
            verification = registry.verify(VERIFIER_ID, VERIFIER_VERSION, text)
            record = BaselineRun(
                task_id=TASK_ID,
                route_id=route_id,
                ok=True,
                error_type=None,
                latency_ms=latency_ms,
                cost=None,
                cost_unit=COST_UNIT,
                measured_at=datetime.now(timezone.utc).isoformat(),
                method=WALL_CLOCK_METHOD,
                environment=environment,
                resources=ResourceVector(tokens=tokens),
            ).to_record()
            write_measurement(
                out_dir / f"{TASK_ID}.{route_id}.run-{attempt}.json", record
            )
            latencies.append(latency_ms)
            token_counts.append(tokens)
            verdicts.append(verification.verdict)
            last_evidence = attributed_evidence(
                verification,
                task_id=TASK_ID,
                route_id=route_id,
                measured_latency_ms=latency_ms,
                measured_cost=None,
            )
        summary[route_id] = {
            "median_latency_ms": round(median(latencies), 1),
            "latencies_ms": [round(value, 1) for value in latencies],
            "tokens": token_counts,
            "verdicts": verdicts,
            "evidence": last_evidence,
        }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="neohorse-1-9b")
    parser.add_argument("--base-url", default="http://127.0.0.1:1234")
    parser.add_argument("--out", type=Path, default=Path("runs/lmstudio/ab"))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--cheap-cap", type=int, default=24)
    parser.add_argument("--full-cap", type=int, default=32)
    arguments = parser.parse_args(argv)
    if arguments.repeats < 1:
        print("repeats must be at least 1", file=sys.stderr)
        return 2

    registry = VerifierRegistry()
    registry.register(VERIFIER_ID, VERIFIER_VERSION, exact_match_verifier(EXPECTED))
    environment = Environment(
        "lmstudio-host", {"python": platform.python_version(), "lmstudio": "local"}
    )
    cheap_cap, full_cap = arguments.cheap_cap, arguments.full_cap
    arguments.out.mkdir(parents=True, exist_ok=True)
    try:
        summary = run_repetition(
            [cheap_cap, full_cap],
            base_url=arguments.base_url,
            model=arguments.model,
            repeats=arguments.repeats,
            timeout=arguments.timeout,
            out_dir=arguments.out,
            registry=registry,
            environment=environment,
        )
    except FileExistsError as exc:
        print(f"refusing to overwrite existing records: {exc}", file=sys.stderr)
        return 2

    full_id, cheap_id = f"cap-{full_cap}", f"cap-{cheap_cap}"
    observation = record_observation(
        Task(TASK_ID, "instruction", {}),
        [
            CandidateRoute(full_id, ["instruction"], 1.0, None, 0.99),
            CandidateRoute(cheap_id, ["instruction"], 0.75, None, 0.99),
        ],
        baseline_route_id=full_id,
        cost_unit=COST_UNIT,
        data_origin="synthetic",
        baseline_evidence=summary[full_id]["evidence"],
        proposal_evidence=summary[cheap_id]["evidence"],
    )
    write_observation(arguments.out / f"{TASK_ID}.json", observation)
    print(
        json.dumps(
            {
                "routes": {
                    route_id: {
                        key: value
                        for key, value in summary[route_id].items()
                        if key != "evidence"
                    }
                    for route_id in summary
                },
                "status": compare_observation(observation)["status"],
                "observation": str(arguments.out / f"{TASK_ID}.json"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
