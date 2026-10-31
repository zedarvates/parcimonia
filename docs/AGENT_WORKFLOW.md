# Portable agent workflow

The repository's [AGENTS.md](../AGENTS.md) carries the entry instructions for
compatible coding agents. A new contributor gets them with the checkout; no
personal skill or earlier conversation is required. Reading these instructions
does not install software or activate automatic routing.

## The two integration surfaces

| Surface | Responsibility |
| --- | --- |
| Parcimonia Python library in this repository | Proposals, evidence contracts, verification and explicitly gated execution APIs. It does not automatically intercept an agent's tasks. |
| Botte Secrète's optional `assess_task` and `plan_github_research` tools | Consultative task assessment and bounded GitHub read planning when the connected runtime exposes them. They do not execute the proposed research, model calls or host actions. |

Use the installed tool schemas and the actual available-tool list. A checkout of
this Python library alone does not supply those Botte Secrète tools. Do not add a
new dependency, endpoint or hook merely because the instructions mention them.

## Task entry and fallback

Before choosing tools for substantive work, consult `assess_task` when available.
Include the original task and only relevant tool metadata within a small context
budget. Keep secrets, unrelated conversation and bulk source out of this planning
call. The host still interprets the task and its permissions.

If assessment abstains, fails or is unavailable, retain the original request and
make an explicit host decision: select sufficient deterministic checks, existing
evidence or local capabilities first, and use more capable reasoning when needed.
Mention the limitation once for the affected phase and continue within the
authorized scope. Split genuinely independent workflows when useful; never drop
a negation or constraint to obtain a confident classification.

For GitHub research, ask `plan_github_research` when exposed, then use a supported
connector or CLI to retrieve the planned evidence progressively. Verify branch,
commit, PR state and checks when they matter. A planned URL is not a fetched
source, and a closed PR is not necessarily merged.

Reuse an assessment across related reads or test runs. Reassess only when the
objective, scope, prerequisites or tool availability materially change. Trivial
answers do not need a planning call. This avoids turning the cost check itself
into repeated overhead.

Record the chosen mechanism, verification performed and unresolved prerequisites
in the normal work report. Do not infer token, latency or cost savings from tool
use alone; distinguish measured outcomes from estimates and unavailable metrics.

## Shipping this workflow in another repository or plugin

Put the entry rule in that repository's committed `AGENTS.md` (or its documented
equivalent). For a plugin, include it inside the skill or instruction file named
by its actual distribution manifest. Bundle any referenced supporting guide in
the installed subset; an absolute path to a maintainer's personal skill will not
work for a new user.

Keep the optional-tool and abstention fallback with the rule. Verify the generated
bootstrap output or packaged subset, including an installation without the
optional runtime. Document the supported host: an instruction file is not a hook,
and a hook supported by one host is not automatically active in another.

## Development verification

From the repository root, with Python 3.10 or newer:

```sh
python -m pip install -e ".[dev]"
python -m pytest -q
```

Run relevant existing tests while iterating. For documentation-only changes,
check relative links and command names rather than adding tests that only assert
the wording of the instructions. The CI suite runs offline on Python 3.10 and
3.14; a local run proves only the interpreter actually used.
