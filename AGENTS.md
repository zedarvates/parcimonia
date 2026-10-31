# Working on Parcimonia

Read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[agent workflow](docs/AGENT_WORKFLOW.md) before substantive work. These committed
instructions apply to new contributors as well as returning agents; they do not
install a runtime, enable active routing or register a hook.

## Choose a mechanism before executing

- For a substantive task or materially changed phase, consult Botte Secrète's
  `assess_task` once **if the connected runtime actually exposes it**. Supply the
  task and a bounded list of relevant available tools. Inspect the installed
  schema; do not invent arguments or send secrets and whole repositories.
- Treat its result as advice. Preserve the user's intent, negations, constraints,
  evidence requirements and existing authorization. On absence, failure or
  abstention, state the limitation briefly and choose the least costly available
  mechanism that can satisfy the task. Do not reformulate merely to force a match.
- Before GitHub research, use `plan_github_research` if exposed, then perform the
  actual reads with a supported GitHub connector or CLI. A plan is not a search
  result. Reuse the assessment and plan for a homogeneous batch; reassess when
  scope, prerequisites or available tools materially change. Skip this overhead
  for trivial responses and already assessed follow-up calls.
- Keep preparation, execution and verification distinct. Neither a routing
  proposal nor a tool's availability grants permission to publish or activate a
  route. Do not claim savings without comparable measurements.

## Repository checks

- Python 3.10+; the distribution/import names remain `tiberium-ai`/`tiberium_ai`.
- From the repository root, install development dependencies with
  `python -m pip install -e ".[dev]"`; run `python -m pytest -q` for the offline
  suite. Use the relevant existing tests while iterating.
- Preserve deterministic verification, provenance, explicit abstention and
  fallback. Keep estimates separate from measurements; unknown cost is not zero.
- Experimental learned routing stays in shadow mode until its evidence gates are
  met. This repository's `ShadowRouter` is not Botte Secrète's MCP assessment tool.
- Report what changed, the checks actually run and any remaining limits. Keep
  patches focused and leave unrelated work intact.
