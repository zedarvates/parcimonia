---
name: local-plan
description: Compare local compute candidates or supplied source context with explicit evidence, budgets and abstention.
---

Use this skill when the user requests local capacity observations, a comparison of
supplied compute-route measurements or a relevance ranking of supplied source documents.
Inspect the available tool schemas. Ask only for the narrowly relevant data, not a
conversation history, private project dump or credentials. No other plugin is required.

Use parcimonia_local_hardware for current resource observations. Use
parcimonia_local_plan to compare supplied candidates; measurements must match the
workload and hardware, include three successful samples and a named verifier, and
be fresh. Missing/uncertain evidence remains unknown. Do not invent a benchmark.
The host reports are not independent attestations. A proposal never authorizes execution.

Use parcimonia_local_context only with user-authorized supplied documents and exact
SHA-256 values. Paths must be relative; they label supplied text and are not read.
Respect file/byte limits and report omissions. Recheck changed source hashes.
The ranking is lexical, not a probability. Cache hits do not prove billed savings.

Keep auto_act_allowed=false. Do not execute routes, load models, install software or
broaden access through this plugin. If a tool is unavailable or abstains, explain the
missing prerequisite. Follow the user's intent and the host's authorization policy.
