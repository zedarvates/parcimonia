# The flagship: what Parcimonia decides, and what it refuses to decide

One command. Six fragments of an ordinary development day. For each fragment,
the router either proposes the least expensive mechanism that still clears the
declared confidence threshold, or it abstains and says why.

```bash
python examples/flagship.py
```

Nothing is executed. No route replaces a baseline. Every cost is a
caller-supplied estimate, not a measurement. That is the whole point: the
interesting behaviour is the refusal, not the proposal.

## The capture

Produced by the command above, unchanged.

```text
------------------------------------------------------------------------------
 PARCIMONIA - one command, six fragments, shadow mode
 confidence bar: 0.9     cost unit: synthetic-unit/fragment
------------------------------------------------------------------------------

[1/6] normalise-date
      intent: "normalise a date typed into a form"
      requirements: risk=low evidence=normal locality=any
      declared options:
        rule:date-parse      cost=0.0000    confidence=0.99
        micro-nn:date        cost=0.0200    confidence=0.97
        small-llm:fr         cost=1.0000    confidence=0.99
      -> PROPOSED  rule:date-parse

[2/6] summarise-ticket
      intent: "summarise a support ticket in three lines"
      requirements: risk=low evidence=normal locality=any
      declared options:
        rule:template        cost=0.0100    confidence=0.62
        micro-llm:fr         cost=0.1500    confidence=0.93
        large-llm            cost=4.0000    confidence=0.99
      -> PROPOSED  micro-llm:fr

[3/6] extract-invoice-total
      intent: "read the gross total off an invoice"
      requirements: risk=low evidence=normal locality=any
      declared options:
        rule:regex           cost=0.0000    confidence=0.88
        knn:invoice          cost=0.0300    confidence=0.94
      -> PROPOSED  knn:invoice

[4/6] review-contract-clause
      requirements: risk=high evidence=normal locality=any
      -> ABSTAINED
         Unsupported task requirements; this prototype only proposes for
         risk_class=low, evidence_level=normal, locality=any.

[5/6] diagnose-regression
      requirements: risk=low evidence=high locality=any
      -> ABSTAINED
         Unsupported task requirements; this prototype only proposes for
         risk_class=low, evidence_level=normal, locality=any.

[6/6] classify-tone
      declared options:
        uncalibrated:rules   cost=0.0100    confidence=unknown
        uncalibrated:model   cost=0.5000    confidence=unknown
      -> ABSTAINED
         No candidate meets the confidence and cost validity checks.

------------------------------------------------------------------------------
 6 fragments: 3 proposed, 3 abstained
------------------------------------------------------------------------------
 Shadow mode only: nothing was executed and no baseline route was
 replaced. Every cost is a caller-supplied estimate in one shared
 synthetic unit (synthetic-unit/fragment), not a measurement.
 This script measures no saving and claims none.
------------------------------------------------------------------------------
```

(The full capture includes the rationale paragraph under each proposal; it is
elided here only to keep this page readable.)

## The three moments that matter

**1. Fragment 3 is the whole idea.** The regex costs 0.0000 and the KNN costs
0.0300. A router optimising for cost picks the free one. This router rejects it,
because 0.88 sits below the 0.9 bar: an answer that is wrong is not cheap, it is
just wrong earlier. That single line is the difference between cost-aware and
evidence-aware.

**2. Three abstentions out of six.** High-risk review, high-evidence diagnosis,
and uncalibrated options all get a refusal with a stated reason instead of a
confident guess. A tool that proposes on everything is not making a decision,
it is decorating a prompt.

**3. The footer is the product.** Shadow mode, estimates rather than
measurements, no saving claimed. The same rule the repository applies to its own
documentation applies to its demo.

## 90-second video script

Terminal recording, one command, no cuts in the output. Read the reasons aloud;
they are the content.

| Time | Shot |
| --- | --- |
| 0:00-0:08 | Cold open on the empty terminal. Voice: "Every agent stack routes on vibes. This one refuses." |
| 0:08-0:18 | Type `python examples/flagship.py`, run it. No narration. |
| 0:18-0:45 | Fragments 1 to 3. Pause on fragment 3. Voice: "Free option, 0.88 confidence, rejected. The 0.03 option wins because it clears the bar. Wrong answers are not cheap." |
| 0:45-1:12 | Fragments 4 to 6. Voice: "Three refusals in a row. No proposal for high-risk review, none for high-evidence diagnosis, none when nobody calibrated the options. It abstains and tells you which requirement it cannot serve." |
| 1:12-1:22 | Scroll to the footer. Read it verbatim: "Shadow mode. Estimates, not measurements. No saving claimed." |
| 1:22-1:30 | Voice: "Parcimonia proposes the cheapest mechanism that keeps its word. Everything else, it declines." Cut. |

Recording notes: 1080p terminal, font large enough to read the `declared options`
block without zooming, dark theme matching the repository header. Do not speed up
the run; it finishes in under a second, which is itself a claim worth showing.

## What this proves, and what it does not

Proves: the decision rule is deterministic and inspectable; it refuses to trade
confidence for cost; abstention is a first-class outcome with an attributable
reason.

Does not prove: that any proposal is correct, cheaper in practice, or
representative of real workloads. The costs are invented by the caller for
illustration. Real savings are still unmeasured, exactly as the repository
README states.

