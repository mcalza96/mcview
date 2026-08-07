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

### Tracing A → B in order to CHANGE one of the branches

Understanding a flow and being safe to modify it are different jobs, and the second needs four
checks the first does not. Each step below exists to prevent one specific way of being
confidently wrong; run them in order and read what the tool tells you rather than what you
expected.

**Check where the walk begins, and STOP if it was not declared.** If the output warns that no
`[surfaces]` are declared, the origin was chosen by MASS — an inference, not a door — and
everything downstream is conditioned on it. The warning comes with the candidate files already
listed and the question already written: **ask the user, do not continue.**

This is not caution for its own sake. It was measured: an agent tracing a flow saw that exact
warning, continued anyway, produced an analysis whose entry point turned out to be the OUTPUT
formatter, and mentioned the caveat at the end — where it no longer protects anyone. A flow that
starts in the wrong place is not a partial answer, it is a wrong one.

If the warning says instead that all the roots come from declaring DIRECTORIES, the problem is
bigger and surfaces will not fix it: when everything is an entrance there is no "how do you get
in". Ask what really starts the project first.

**Ask for the SET before the narrative.**

```bash
mcview --sequence <A> --all
```

It returns every edge the flow CAN traverse and, next to it, what fraction the readable
narrative shows. That fraction is routinely small — the narrative descends the heaviest call at
each level on purpose, so it stays readable. Read the number it gives you for THIS repo before
believing you have seen the flow.

Read both columns. An edge whose `unambiguous` count is 0 resolved only through a name several
symbols share; it is not a connection. Whether that is rare or pervasive depends entirely on the
language and the naming conventions of the project in front of you — check, do not assume.

**Then the route to B**, which is the only form that does not prune:

```bash
mcview --sequence <A> --to <B>
```

**Ask where it really decides, and be ready for zero.**

```bash
mcview --sequence <A> --to <B> --decisions
```

It separates PROVEN forks — calls in different branches of the same conditional — from
candidates ranked by reference split. A route can legitimately come back with **no proven fork
at all**: the AST cannot tell a call inside an `if` from the one on the next line. If that
happens, the branch you want to change is not chosen by the code — it is chosen by the data, by
configuration, or by a model. Say so; do not present the reference split as a probability.

**Look for a CUT in the middle.** Where the project declares a dispatch or a seam, the target is
picked BY NAME and no edge crosses. `--blueprint` lists them. A narrative that bridges a cut
invents a call that does not happen.

**Read the branch's code — with the index, not with this.** This tool told you WHICH code to
read. Reading it is another tool's job.

**Before touching it, two cheap questions:**

```bash
mcview --orient <the branch>     # who uses it, what a change reaches
mcview --exists <new file>       # does this already exist under another name?
```

**And if the process runs somewhere, turn the probe on.** `--runtime` marks the steps seen
executing, and it is the only thing that turns "can pass through here" into "did". It confirms
and never rules out — an unmarked step may sit behind a condition, or run in a PROCESS WHERE
NOBODY STARTED THE PROBE, which makes half a flow invisible by construction and looks exactly
like code that never ran. Check which processes are instrumented before reading absence as
evidence.

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
