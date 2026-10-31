# Contributing

Start with [AGENTS.md](AGENTS.md) and the
[portable agent workflow](docs/AGENT_WORKFLOW.md). These instructions travel with
the repository, including the optional Botte Secrète assessment and its fallback
when the tools are unavailable or abstain.

Contributions should:
- preserve deterministic safety gates
- include measurable evidence
- distinguish estimated from measured cost
- provide fallback/escalation
- keep model/capability versions explicit
- avoid claims beyond benchmark evidence

A PR should state:
1. problem
2. scope and explicit non-goals
3. changed capabilities
4. tests/benchmarks
5. expected cost/latency impact
6. known failure modes
7. rollback/fallback behavior

Experimental learned routing defaults to shadow mode until benchmarked.
