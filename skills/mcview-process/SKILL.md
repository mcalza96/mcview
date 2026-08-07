---
name: mcview-process
description: >-
  For understanding WHAT HAPPENS WHEN SOMETHING OCCURS, end to end and across
  repositories: what a message traverses from the moment it arrives until it leaves, in
  what order, where the flow splits, and how much of that actually executes. Use it when
  the question is about a PROCESS rather than a place in the code — "what happens when a
  user sends a message?", "what does a request traverse from the frontend to the
  database?", "how is the answer assembled?", "in what order does this happen?", "where
  does the system decide?", "does this really run?", "draw me the flow" — even when the
  tool is never named. It delivers the ordered route with its code alongside, the proven
  forks, the mark of what was seen executing, and diagrams (interactive map, timeline,
  PNG). Do NOT use it to orient yourself in ONE area before touching it (that is
  `orient-session`), nor to measure or clean the repo (`mcview-repo`), nor when there is
  no `mcview.toml` yet (`mcview-install`).
---

# Understanding a process, not a place

Every other view reads a GRAPH, and **a graph has no before and after**: it knows the
handler calls `resolve_tenant` and `score_complexity`, not that the tenant is resolved
first. For a process that is not enough — "the user sends a message, the space is
resolved, the agent decides" is a SEQUENCE, and a sequence cannot be deduced from a set
of edges.

```bash
# what it traverses, from A to B, across repositories
mcview/mcview.py --route "<name declared in mcview.workspace.toml>"

# what happens and in what order
mcview/mcview.py --sequence <target>
mcview/mcview.py --sequence <target> --to <destination>    # without pruning by mass
mcview/mcview.py --sequence <target> --all                 # every edge it CAN traverse
mcview/mcview.py --sequence "<proj>▸<target>" --to "<proj>▸<destination>"   # across repos

# confirm against actual execution
mcview/mcview.py --sequence <target> --runtime

# where the flow splits
mcview/mcview.py --sequence <target> --to <dest> --decisions

# to look at it
mcview/mcview.py --sequence <target> --runtime --html > process.html
mcview/mcview.py --atlas --from <surface> > map.html
```

## The order of work

1. **`--route`** first: the set of what participates, and whether there are chokepoints.
2. **`--sequence … --to`**: the ordered narrative, without pruning what leads to the target.
3. **`--runtime`**: how much of that actually runs.
4. **`--decisions`** only if the question is where the system chooses.

Skipping step 1 is the typical mistake: with no destination, `--sequence` prunes by mass,
and the step that explains how the result is assembled usually weighs very little.

## Four things the output asserts, and one it does not

**`--route` does not enumerate paths.** They are exponential, and a list of the first
twelve reads as if it were everything — which is exactly how a sample disguises itself as
a census. It returns the DAG that CONTAINS them: everything that lies on some path, and
nothing else.

**Chokepoints are exact.** They are proven by removal: "without this you do not get
there", not "appears in 45% of a sample". If there are none, the answer is not "I found
nothing": it is **there is no mandatory step**, and then there is nowhere to put a
guarantee — building one is design, not cleanup.

**The order is the WRITTEN one, not the executed one.** A call inside an `if` shows up
even if it never happens; a dynamically dispatched one does not show up even if it always
happens. Say so when reporting.

**Repetition is collapsed with the counter in view.** «×20» is not a footnote: it says
there is a loop there, and that is information about the process.

## `--decisions`: two planes that do NOT mix

| plane | what it is | how much it asserts |
|---|---|---|
| **proven fork** | calls in DIFFERENT branches of the SAME conditional | the flow goes one way or the other |
| **reference split** | what fraction of A's references go to B | it ranks candidates, **it does not rule** |

The second has the shape of a probability and **is not one**: the AST cannot tell a call
inside an `if` from the one on the next line, so two consecutive calls give 50/50 **and
both execute**. Never call it "branch probability".

Measured (2026-08-06) over a 102-symbol route: the split flagged 12 "decisions"; the
proven forks were **one**. This is not a defect of the view — in a system where an LLM or
the data makes the choice, **there are almost no choices in the code**. A rich decision
tree drawn from the AST would have been pretty and false.

## Seams: where the process stops being traceable

A real process crosses boundaries **no call graph traverses**, because the junction is
made of STRINGS: an HTTP route, a tool name, a shared table, a plugin loaded by name.

That has two operational consequences:

- **They are declared, not inferred.** If the literal does not match, there is no bridge.
  A route that dies after a handful of symbols is almost always an undeclared seam, not a
  short process.
- **They are drawn differently.** A matching string and a call proven by the AST are not
  the same evidence; blending them into one stroke makes the diagram assert too much.

And the trap that costs the most: **if a seam enters a computation with an invented
weight, it manufactures findings.** Measured — two seams with the same weight produced a
"decides 50/50" that did not exist: both names were sitting there as string literals
inside an `if`, and the real choice was made by an LLM no static analysis can see.

## `--runtime`: it confirms, it never rules out

`✓` seen executing · `·` not observed. **`·` does not mean "does not happen"**: it may sit
behind an `if`, fall outside the measured window, or live in a process with no probe.

It is the only view that sees what gets loaded BY NAME, which is why it closes a process's
blind spots. Before believing a census, verify that it MEASURED —file present and with
lines— rather than that the variable is set: the probe is wired inside a `try/except` so
it cannot block startup, and that same choice makes it fail silently.

**And the timestamps reconstruct the process on their own.** Symbols cluster into groups
matching the real phases of the turn — receive, think, answer, close. It is the most
honest way to draw a process: the phases are not chosen by whoever draws, they appear.
State the granularity (the flush interval) and that it is ONE window.

## Diagrams

| what you want to see | how |
|---|---|
| the process, to read it | `--sequence … --html` — timeline plus step-by-step narrative |
| how it is distributed | `--atlas` (modules → files → symbols, interactive) |
| what ONE user door reaches | `--atlas --from <surface>` |
| every repo and its seams | `--atlas --workshop` |
| a PNG for a document | hand-written SVG + `rsvg-convert`; version the GENERATOR, not the image |

**An architecture diagram with no measurement draws what you BELIEVE happens.** Annotate
every box with what was measured, and add a footer with **what the diagram does NOT
assert** — which junctions are declared, which hop is only proven by runtime, what part of
the repo does not appear. That section is often worth as much as the drawing.

And **a diagram's defects only show up by opening it**: overlapping labels, text
illegible over a line, content off-canvas, two names fused into one. None of them is
visible by reading the code that generates it. Always open it before handing it over.

## When reporting a process

- The **concrete route** —a chain of `file:line`— so the reader can verify it by reading
  three functions rather than by trusting.
- **Where it crosses** and by what means (call · route · tool name · shared state).
- **What was seen executing** and what was not, with the caveat that not observed ≠ does
  not happen.
- **Where the process stops being traceable.** That is not an apology for the tool: it is
  a finding about the system, and usually the place where you have to intervene.
