# Local multimodal worker checkpoint — 2026-10-31

Need: continue local code/3D tool work when OpenAI is unavailable, using the
existing local worker and second-brain retrieval. This is the first transport
and proposal-validation increment, not a deployed autonomous agent.

Base: `ea126dc1a41090df5cb840c9b08602b37e42a803`, existing draft PR #17,
`codex/eurekai-local-agent-bootstrap-20261030`. This continuation is isolated in
`feat/uo-local-vision-20261031`; it does not treat #17 or any memory PR as merged.

Implemented: explicit request v2 for bounded embedded PNG/JPEG inputs; output
v4 with image header/hash receipts; unchanged v1 text/context/retrieval output
contracts; caller-named local image preparation; existing RAG context insertion
and failure handling reused. No model-generated command is executed.

Validation on Python 3.12: 1,176 tests passed, 34 subtests passed. The base had
1,079 tests; this increment adds 63 client vision cases, 24 request preparation
cases and 10 worker integration cases. Three old refusal tests now reject
unknown versions rather than the newly supported v2. Python 3.10 grammar checks
passed for the six changed/new Python implementation/feature-test files.

Independent review ran 215 focused tests plus 34 subtests. No blocking defect
was reproduced. One compatibility nuance is retained: the initial bounded
stdin read is now 6 MiB for all inputs before parsing the version, so callers
must still close stdin and impose an overall subprocess deadline.

All images, context and endpoint responses exercised here are authored fixtures.
Image checks inspect headers, not compressed pixels. No real model, GPU,
LM Studio instance, vault, editor, renderer or gameplay was qualified. No
performance, cost saving or autonomous-routing claim follows from these tests.

Next: inspect the installed runtime/model/vision component through the existing
machine bridge; qualify one real vision response and one caller-owned artifact
modification with its owning validator and renderer. Keep request/result and
the original artifact in private caller storage. If a request times out, inspect
the server/job state before issuing another; do not retry to repair logging.

Fallback: continue the existing v1 text path. No service, schedule, model or
memory index was changed by this increment. See [contract and commands](../docs/LOCAL_VISION.md).
