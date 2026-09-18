# Escalation policy

`EscalationPolicy.decide(...)` answers one question after an attempt: accept,
retry, escalate, abstain or stop hard. It never executes anything, and every
decision carries a machine-readable `reason_code` naming the rule that fired.

## States

| State | Meaning |
| --- | --- |
| `ACCEPT` | The attempt produced a verified result |
| `RETRY` | Another attempt at the same cost, only when the caller marks the action retry-safe |
| `ESCALATE` | A bounded move to another, typically more expensive route |
| `ABSTAIN` | No claim can be made |
| `FAIL_HARD` | A deterministic limit or a contradiction stops the task |

## Budgets

`Budget(max_cost, max_escalations, max_attempts, max_latency_ms)` is cumulative
and checked before any new attempt starts. `max_attempts` is the loop guard: it
stops a task that keeps escalating without converging. The latency budget stands
in for a wall-clock deadline so the decision stays deterministic; a real deadline
needs the clock that only the active mode will own.

## Decision order

1. An unspecified task stops immediately (`ill_specified_task`).
2. A verified result is accepted, even when the attempt budget is exhausted.
3. The attempt budget is checked before any continuation.
4. A rejected result escalates or stops hard; it never retries the same mechanism.
5. A failed or unverified route escalates when a bounded alternative exists,
   otherwise retries when the caller declared the action retry-safe, otherwise
   abstains.

## Budget rules

The next attempt must have a known estimated cost: an unknown cost never
escalates (`rejected_unknown_cost`). Cost and latency are compared against what
was already spent plus the next estimate, and the escalation count is checked
against `max_escalations`.

## Limits

Estimates gate the budget while measurements remain the evidence, and a hard stop
is never overridden by a learned component. The policy does not choose
candidates, does not execute them and does not decide intent: it only decides
whether to continue, inside limits the caller declares.
