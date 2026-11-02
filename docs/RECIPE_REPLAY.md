# Evaluate a recipe revision before adopting it

`tiberium_ai.agent_recipes.replay.replay_recipe_candidate` compares the current
recipe and one candidate on preserved episodes. It reuses the normal
`BenchmarkCase`, measured `capture_run`, verifier and benchmark report contracts.
It does not change a skill, install a hook, choose a route or promote a candidate.

Provide two `RecipeRevision` objects with the same recipe identifier, explicit
versions, the exact instruction text, and host-owned callbacks. The callback
receives that text and a fresh JSON copy of each input. The report records the
text's SHA-256; it does not certify that a model followed the instructions.

Supply nonempty `historical` and `heldout` lists of `RecipeEpisode` objects. Each
episode identifies its source, declared origin, reviewed source group, input and
named/versioned outcome verifier. Keep paraphrases and episodes derived from the
same source in one group and explicitly set `group_reviewed=True` after review.
The adapter rejects unreviewed grouping, group overlap, exact duplicate
inputs across the split, and duplicate episode identifiers before running work.
It preserves the supplied split rather than randomly reallocating old episodes.

Each revision runs once per episode, with no automatic retry, for at most 256
episodes. Callbacks still need the host's authorization, resource reservations
and process deadlines; this helper cannot sandbox arbitrary Python callbacks.
There are no built-in network or model calls.

The returned `parcimonia.recipe-replay/v1` record includes both recipe identities,
the corpus revision, explicit split, measurements, attributed verdicts,
improvements and regressions. A failed/unknown candidate cannot pass by returning
normally or by reusing a verifier from another case. A regression on a held-out
episode blocks the candidate even if all historical episodes improve.

`ready_for_review` means the supplied offline checks passed. Source origins and
grouping remain caller declarations. Fixture success does not establish a
production gain. Monetary cost remains `null`; the workflow ledger should retain
actual usage, review, retry and human costs. `claim_allowed`, `promotion_allowed`
and `auto_act_allowed` are always false. A separate reviewed decision is needed
to adopt a recipe; keep its baseline and this report for rollback.

Run the behavior checks with:

```sh
python -m pytest -q tests/test_recipe_replay.py
```
