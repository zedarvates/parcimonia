# Review and cost evidence for an existing workflow

These opt-in helpers attach to the host's existing task, execution journal and
resource admission. They do not start agents, add an orchestrator, change
permissions, install hooks or mark a Kanboard/Odin job complete. Use the existing
mission identifier and immutable commit/diff identities throughout.

## Choose review effort

Run `parcimonia review-plan --input request.json` (or
`python -m tiberium_ai.agent_recipes review-plan --input request.json`). Input:

```json
{
  "scope": {
    "task_id": "WF-001",
    "base_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "head_revision": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    "diff_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  },
  "changed_paths": ["src/format.py"],
  "impact": "moderate",
  "reversibility": "easy",
  "uncertainty": "low"
}
```

Replace the example commit and diff hashes with the exact observed values.
`impact` is `low`, `moderate`, `high` or `unknown`; `reversibility` is `easy`,
`costly` or `unknown`; `uncertainty` is `low`, `high` or `unknown`.

A fully understood, easily reversible, low-impact change proposes focused
checks. Other changes propose an independent reviewer; high impact, expensive
rollback or sensitive paths propose a specialist. Deterministic path checks can
increase scrutiny but cannot prove a diff is safe. Unknowns do not earn a cheaper
review. The existing `review.triage@1` remains shadow-only with effective full
review; this proposal does not weaken it or authorize merge/deployment.

## Keep failed and incomplete reviews visible

The JSON command output wraps the plan under `result`. Preserve that exact plan,
including its `plan_sha256`. Supply `review-status` with an object containing
`plan`, `attempts` and an optional explicit `evidence_root`. Each attempt has:

```json
{
  "attempt_id": "review-1",
  "plan_sha256": "<exact hash from the generated plan>",
  "reviewer_id": "independent-reviewer",
  "implementer_id": "implementer",
  "specialties": [],
  "state": "completed",
  "started_at": "2026-11-02T12:00:00Z",
  "finished_at": "2026-11-02T12:01:00Z",
  "report_ref": "review-1.json",
  "report_sha256": "<SHA-256 of the exact report file bytes>"
}
```

`state` can be `requested`, `running`, `completed`, `failed`, `interrupted`,
`quota_exhausted`, `cancelled` or `timed_out`. Report fields and timestamps may be
null when not yet available. A claimed `completed` attempt cannot pass without
both timestamps, an author distinct from the implementer, and an exact report
re-read. Old-plan attempts remain visible as stale; they never satisfy the
current revision. A retry gets a new `attempt_id`; keep the failed attempt.

The report is a UTF-8 JSON file beneath `evidence_root`, limited to 1 MiB:

```json
{
  "schema": "workflow-review-report/1",
  "plan_sha256": "<the same exact generated-plan hash>",
  "reviewer_id": "independent-reviewer",
  "summary": "Describe the review outcome without assuming a desired verdict.",
  "findings": ["Concrete finding with location and supporting evidence."],
  "validation_gaps": ["Target-machine check not executed."]
}
```

Paths escaping the root, missing/empty/oversized files, changed bytes, duplicate
JSON keys and a mismatched internal plan/reviewer are refused. A specialist plan
also requires explicit specialty coverage in the completed attempts. Distinct
reviewer names do not certify model/provider independence. A completed review
may contain serious findings: `findings_validated` and `merge_ready` remain
unknown. The host must verify findings and perform its normal release checks.

## Account through the accepted result

Use `capture_workflow_event(captured, event_id=..., phase=..., scope=...)` on an
existing `CapturedRun` from `capture_run`. The adapter checks its task identity
and output-verifier hash and attaches only measurement and verification records;
it does not execute or retry anything and excludes raw outputs.

Keep the resulting `workflow-event/1` records in the existing execution journal,
including failures, rejected candidates, reviews and rework. Feed
`parcimonia acceptance-cost --input costs.json` with:

```json
{"scope": {"...": "same full scope as above"}, "events": [], "accepted_event_id": null}
```

The Python equivalent is `summarize_acceptance_cost(scope, events,
accepted_event_id=...)`. The chosen acceptance event must be the current
revision's final `verification` phase and have a positive named/versioned
verifier verdict. An intermediate research/review result cannot close the task.

Totals include supplied attempts that began no later than the acceptance time,
independent of their list order. A receipt's `measured_at` is its finish time;
start is derived from its measured operation latency. A task spanning that
instant has an unknown partial cost and blocks full totals rather than hiding
it. The host must use synchronized timestamps; this helper cannot establish
clock synchronization across machines. It cannot account for a missing receipt.

`research`, `implementation`, `verification`, `review`, `rework` and `human`
phases must all be explicitly covered for a full cost. An explicit measured zero
is allowed; no omitted phase, failed call or unknown provider charge becomes
zero. Mixed currencies stay separate, and overflows remain unknown. Known costs
are shown separately from `total_cost_until_acceptance`; all costs/usage on
failures count. Token totals are likewise unknown with missing receipts or an
ambiguous time boundary. Summed operation latency is not wall time and excludes
unrecorded waiting. Human and verification work need their own receipts because
the existing capture's operation measurement does not include those costs.

These are consistency checks over supplied records, not signed execution
attestations. `claim_allowed` and `auto_act_allowed` remain false. A report does
not itself mark a remote job complete or establish a production saving.

## Evaluate a recurring correction

Use the [recipe replay adapter](RECIPE_REPLAY.md) to compare the existing recipe
and one candidate on historical episodes and a separate held-out set. Keep the
source, candidate text/version/hash, split, raw checks and reviewed adoption
decision together. `ready_for_review` does not change a skill or promote a route.

Run the behavior checks with:

```sh
python -m pytest -q tests/test_workflow_evidence.py tests/test_recipe_replay.py
```
