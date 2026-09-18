# Architecture

This document describes the target architecture. The implemented subset is
documented in [Shadow routing policy](SHADOW_ROUTING.md); components listed here
must not be assumed to be wired into the current prototype.

Tiberium is an orchestration and economic-routing layer, not a replacement foundation model.

```text
User / Application
        |
Agent / Planner / LLM
        |
        v
+------------------------+
|      Tiberium Core     |
|------------------------|
| Task normalizer        |
| Capability discovery   |
| Candidate generator    |
| Cost/risk estimator    |
| Policy gate            |
| Router                 |
| Evidence collector     |
| Verifier               |
| Escalation controller  |
+------------------------+
   |    |    |    |    |
   v    v    v    v    v
 rules cache KNN tinyNN LLM/tools
```

## Typed contracts

### Task
Stable task ID, kind, inputs, output schema, evidence level, risk class, locality policy, latency/cost budgets.

### CandidateRoute
Route ID, capability IDs, estimated cost/latency, confidence, hardware requirements, known failure modes, evidence plan and fallback.

### Decision
Selected route, rejected candidates, rationale, policy checks, uncertainty and shadow/active mode.

### Evidence
Input fingerprint, versions/SHAs, outputs, verifier results and measured resources.

## Candidate layers
- T0 deterministic
- T1 cache/proof reuse
- T2 KNN
- T3 nano-NN
- T4 micro-NN / predictive specialist
- T5 small local LLM
- T6 large local/cloud model

The router may skip layers.

## Shadow mode
V0 proposes an alternative route beside the baseline and does not silently replace it.

## Botte Secrète
Botte Secrète remains the broader agent/tool orchestration system. CapabilityAtlas exposes capabilities and consequences; Tiberium chooses economical combinations and evidence-aware escalation.

## ShardJEPA
ShardJEPA is a predictive capability. Tiberium decides when it is appropriate, whether confidence is sufficient, and when escalation is required.

## Safety properties
- deterministic hard-stop policies outrank learned routing
- uncertain routes abstain or escalate
- measured and estimated costs are distinct
- capability versions are recorded
- production activation is explicit
- no model self-promotion based only on its own score
- high-risk actions require independently verifiable evidence
