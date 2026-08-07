---
name: orient-session
description: >-
  For GIVING STRUCTURAL CONTEXT to a session or to an agent that is about to work on an
  area, computed from today's code instead of reading documentation that may be stale. Use
  it when STARTING work on a part of the system you do not have fresh in mind, before
  dispatching a subagent to touch a module, BEFORE WRITING A NEW COMPONENT (to see whether
  the flow already crosses one that does that), or when you are about to read five files
  blind. It triggers on "get up to speed on X", "how is X put together?", "how does X
  work?", "what is the FLOW of X?", "where does a request go?", "what runs when…?", "who
  writes this table?", "what do I touch if I change X?", "what do I have to restart?",
  "how do the gateway and the backend connect?", "does this already exist?" — even when it
  never says "orient" or "context". It delivers, computed from today's code and with
  nothing to configure: mass, cohesion, who uses it, what it depends on, what is dead or
  cold, whether something similar already exists, the real ROUTE, and where it CROSSES into
  other repositories. Do NOT use it to measure the whole repo or to decide what to delete
  (that is `mcview-repo`), nor to explore with no target (`discovery-sweep`).
---

# Orienting a session

`mcview/` computes the structure of TODAY's code. It replaces half the documentation that
rots —who calls what, what is dead, where the system goes— because it cannot be out of date
by construction.

**It orients you; it does not decide for you.** It is not a health check and it has no
opinion about quality: it says what is there so you work with more discipline and less
flailing. What it points at still has to be read, and what to do about it is the user's
call. Cite its numbers with the caveat attached — a number from here reported as a verdict
is the one failure mode this tool was built to prevent.

**Use it alongside a code index, not instead of one.** For finding a symbol, reading its
source or following a call chain, a pre-indexed graph (codegraph or equivalent) is faster
and covers more languages. Ask the index WHERE things are; ask mcview WHETHER THE SHAPE
HOLDS. Do not cross them: measured on the same 6.2k-symbol repo their inventories agree to
0.3%, but 62% of symbols have no incoming edge in the index against the 1% mcview reports
as dead — a retrieval index drops ambiguous references on purpose, and reading that as dead
code turns 70 hypotheses into 3,810.

```bash
# get located (first thing, almost always). The target resolves in this order:
mcview/mcview.py --orient "<Declared Module>"     # a module from the .toml's [modules]
mcview/mcview.py --orient <path/to/file.py>       # or a directory
mcview/mcview.py --orient <a_symbol>
mcview/mcview.py --orient <a_table|an_rpc|/a/route|a_tool>   # a seam LITERAL

# the route, and where it leaves the repository. `--no-twins` goes ALWAYS unless you are
# about to write new code: without it the duplicate analysis runs, which on a large repo
# takes minutes and feels like the command hung.
mcview/mcview.py --orient <target> --no-twins --flow
mcview/mcview.py --orient <target> --no-twins --flow --cross   # + the other projects

# WHAT HAPPENS AND IN WHAT ORDER — not what is reachable. The graph has no before and
# after; these views read the CALL ORDER the AST keeps.
mcview/mcview.py --sequence <target>                  # the narrative of the turn, step by step
mcview/mcview.py --sequence <target> --to <dest>      # no pruning: EVERYTHING leading there
mcview/mcview.py --sequence <target> --runtime        # ✓ seen running · · not observed
mcview/mcview.py --sequence <target> --to <d> --decisions   # where the flow splits

# the map: how the system is DISTRIBUTED
mcview/mcview.py --atlas > atlas.html              # modules → files → symbols
mcview/mcview.py --atlas --from <surface>          # only what one door reaches
mcview/mcview.py --atlas --workshop                # every project and its seams

# the workspace and the processes
mcview/mcview.py --bridges                         # how the projects join
mcview/mcview.py --services                        # what runs in each process
mcview/mcview.py --route "<name>"                  # from A to B, across repositories

# to consume or to read
mcview/mcview.py --orient <target> --flow --json           # for a subagent
mcview/mcview.py --orient <target> --flow --html > x.html  # for a human
mcview/mcview.py --bridges --html > bridges.html
```

`--project <name>` picks another project from the workspace. The config discovers itself
from any subdirectory.

## The order of work

1. **Resolve the target.** If it does not resolve, the command prints the declared modules
   and **does not guess** — a target silently resolved wrong gives you a brief about
   something else.
2. **Run `--orient X --no-twins --flow`.** That is the default mode. The full run (without
   `--no-twins`) only if you are about to **write new code**, because that is when the
   `ALREADY EXISTS` section matters — and it costs an order of magnitude more.
3. **Read the 2-3 files the brief points at**, not the thirty in the area.
4. **Only then look for memory** — and only the kind that carries intent, not structure.

## What it replaces and what it does not

| axis | where it comes from |
|---|---|
| who calls what, mass, what is dead or cold, the route | **computed**, from today's AST |
| why something was chosen, what was measured, what was refuted | **memory and docs** |

The mistake to avoid runs in both directions: do not reconstruct from prose what is computed
in seconds, and **do not assert intent from the graph**. The graph says where the system
goes; never why. That three agents read CIRE's code and still told the same false story is
measured — the code was right there and it was not enough.

## How to read each number, and what it does NOT assert

**mass** — PageRank seeded at the roots. It is **structural centrality**, not importance and
not real frequency: it is measured that **it does not predict execution** (AUC 0.506 against
the probe census). `core/cache.py` tops CIRE because everything crosses it: it is plumbing.
Never report it as "the most important thing".

**cohesion** — the fraction of the target's references that stay inside. Below **0.15 it does
not mean "split it"**: it means *it is not a unit*, it is crosscutting infrastructure. It
comes from the complete graph; `--hierarchy` measures it without the top 1% of hubs and gives
a different number. **They are not interchangeable** — if you report it, say where it came
from.

**temperature** — the grades of liveness. `ALIVE_PRODUCT_WEAK` and `ALIVE_NOT_PRODUCT` are where the
entropy lives: code nobody deletes because the graph says it is used, when what holds it up
is a homonym or its own test. Name them; do not hide them in the total.

**cold** — referenced but with mass ~0. **They are not `DEAD_CANDIDATE`**: they are alive,
the system just barely goes through them.

**neighbors** — ordered by the mass of the file on the OTHER side, not by count: a helper
called once from the heart of the system matters more than one called twenty times from a
cold corner. Only those with at least one **unambiguous** reference are listed; the ones
linked by homonyms are counted separately. In `Retrieval` that filter drops the dependencies
from 139 to 28 — the rest was dust.

**`DEAD_CANDIDATE` is not a deletion order.** It is a hypothesis with no static evidence of
use. If the turn is about deleting, the skill that follows is `mcview-repo`.

## `--flow`: the route, not the census

The base brief is a **census**. `--flow` is the **route**, and it is what you need in order
not to duplicate a component: a file being hot says nothing, but seeing that the request
**already crosses a tenant resolver before arriving** says that writing another one would be
the second.

| section | what it answers |
|---|---|
| WHICH PROCESSES IT RUNS IN | api, worker, gateway — and how many files are shared |
| ON THE MAP | which lines of work use it and which it depends on |
| HOW YOU GET IN | the boundary, with **declared** entries marked `▶` |
| **WHAT IT CROSSES FIRST** | what the paths **call** without being on them — the guards |
| WHERE IT DECIDES | the nodes with the most outputs: reading those first explains the subsystem |
| WHERE IT REACHES | forward reachability, marking where it ends |
| ONE CONCRETE PATH | the longest chain, to verify by reading three functions |

Three things to read carefully:

**"Door" is the BOUNDARY, not the entry.** These are the symbols called from outside, and
only some are real entries: in Ingestion, **2 out of 79**. The declared ones —an MCP tool, a
route, a handler— carry `▶`; the rest are helpers somebody calls from outside.

**"What it crosses first" is not a variant of "where it goes".** A guard is not *on* the
path: it is called before, as a precondition with an early return, so in the graph it is a
**sibling**. Confusing the two produced 64 false bypasses the first time it was attempted.

**It runs on the UNAMBIGUOUS edges.** A path is a stronger claim than a reference: in CIRE
the complete graph has ~16 times more edges than the unambiguous one, and with those
everything reaches everything. The first attempt reported 351 of 402 roots "reaching"
Ingestion and listed `client` and `get` from test files as what the flow crosses. Noise
shaped like a finding, which is worse than showing nothing.

## `--sequence`: what happens and in what order

`--orient` and `--flow` read a GRAPH, and a graph has no before and after: it knows the
handler calls `resolve_tenant` and `score_complexity`, not that the tenant is resolved
first. To understand a TURN —or any process— that is not enough.

`--sequence` uses the call order the AST keeps. It is for when the question is "what does
this do, step by step" rather than "where does it reach".

**Three things the output says about itself, and you have to repeat when reporting:**

- **It is the WRITTEN order, not the executed one.** A call inside an `if` shows up even if
  it never runs, and a dynamically dispatched one does not show up even if it always runs.
- **It prunes by mass and declares it.** With `--to` the criterion changes: it descends
  through everything on some path to the destination and nothing else. A step pruned for
  "weighing little" is often exactly the one explaining how the result is assembled.
- **It collapses repetition with the counter in view.** «×20» is not a footnote: it says
  there is a loop there.

### `--decisions`: two planes that do NOT mix

The view separates what it can prove from what it merely ranks, and it has to be read in
that order:

| plane | what it is | how much confidence |
|---|---|---|
| **proven forks** | calls in DIFFERENT branches of the SAME conditional | the flow goes one way or the other |
| **reference split** | what fraction of A's references go to B | it ranks candidates, **it does not rule** |

The second has the shape of a probability and is not one: the AST cannot tell a call inside
an `if` from the one on the next line, so **two consecutive calls give 50/50 and both
execute**. When reporting, never call it "branch probability".

And a measured asymmetry (2026-08-06): over a 102-symbol route the split flagged 12
"decisions" and the proven forks were **one**. That is not a defect of the view: in a system
where an LLM or the data makes the choice, there are almost no choices IN THE CODE. A rich
decision tree drawn from the AST would have been pretty and false.

## `--runtime`: it confirms, it never rules out

It marks each step with `✓` (seen running) or `·` (not observed). **`·` does not mean "does
not happen"**: it may sit behind an `if`, fall outside the measured window, or live in a
process where nobody turned the probe on. Absence of evidence is not evidence of absence —
the same rule that governs the liveness census, where the probe only PROMOTES to alive.

It is the only view that sees what is loaded BY NAME (plugins, platforms, dispatch tables),
which is exactly where static analysis does not reach.

**Before believing a census, verify that it MEASURED.** A probe is wired inside a
`try/except` so it can never block startup, and that same `try/except` makes it fail
silently: an empty census, which reads as "it did not run" instead of "it was not measured".
Check that the file exists and has lines, not that the environment variable is set.

## A surprising number gets verified BEFORE it gets reported

The rule that helped most in this session, and it belongs to the method, not the tool.

Case (2026-08-06): a gateway's agent loop measured **0.05% of mass** — under any automatic
criterion it would have been the first thing deleted. Checked with a reachability question,
it turned out the gateway does not reach it through any unambiguous edge: it was a
measurement hole. The runtime census then showed that **50% of its symbols ran**.

If a number contradicts what you know about the system, the default hypothesis is **that the
instrument cannot see it**, not that the system is wrong. Verifying takes one command;
reporting it wrong costs a bad decision.

## Crossing the repository boundary

**The seam between projects is made of STRINGS, not symbols.** The gateway does not import a
function from the backend: it hits a route and asks for a tool by its name. That is why
`--orient` accepts a **table**, an **RPC** or a **route** as target — it was a measured blind
spot: a session investigating Telegram access fell back to `grep` because
`platform_access_grants` is not a symbol.

Two relations that are **not the same**, and confusing them is the expensive mistake:

- **call** — one project writes the other's identifier. `--bridges` lists them with the exact
  line on both sides.
- **shared state** — two projects touch the same table **without ever calling each other**.
  It appears in no call graph. In CIRE that is dozens of tables, and it is where the frontend
  (reading under RLS) and the backend (writing with `service_role`) meet: the entire
  authorization surface.

`--services` answers *"what do I restart?"*. It derives from the **entrypoint** what code runs
in each process, because declaring it by directory would be false: in this repo `services/`
runs in the api AND in the worker, so almost any backend change forces restarting both. It is
a **lower bound** — whatever is loaded by name at runtime is beyond any static analysis, so
when in doubt, restart.

## Seeing the subsystem instead of reading it

```bash
mcview/mcview.py --orient <target> --flow --mermaid       # sequence: the merged paths
mcview/mcview.py --orient <target> --flow --mermaid map   # neighborhood: the lines of work
mcview/mcview.py --orient <target> --flow --html > x.html # the page, no network
```

In the **sequence**, what to look for is **convergence**: in Ingestion, three different
creation flows enter through the same `submit_document`. That is where the system decides
once for many origins, and it is what you have to see before adding a fourth. Stadium `( )` =
declared root · bold = door · dashed = guard · **thick = crossing into another process**,
which is not a local call and is drawn differently for that reason.

The page is a single file with no build and no network: the renderer is embedded.

## The `ALREADY EXISTS` section

It includes **nested blocks**, not just functions. A name with a slash
(`get_queue_status/except`) is a block. The most useful case is the mixed one — an inline
block paired against an already-extracted function means *"you already pulled this helper out
in one file and in the other it is still copied by hand"*.

This is what pays for the full analysis. With `--no-twins` the brief drops to seconds and
loses exactly this: if you only want to get located, do not pay for it.

## Known limits

- **It is structure, not execution.** A path in the graph may never be walked; an absent one
  may exist anyway (dynamic dispatch, plugins by name). The bias is toward the false
  negative: it never invents a path.
- **It does not see argument filtering.** It finds "reaches the sink without crossing the
  guard", not "crossed the guard but forgot the `.eq('tenant_id', …)`".
- **The module partition is declared by the owner**, and the tool does not validate it. "You
  are in module M" is true because somebody wrote it in the `.toml`; "M is a unit" is not
  proven — that is what cohesion is for, and it may say no.
- **In TypeScript** the percentages are useful, but distrust bare one-word names: real code
  has functions called `x` and `y`.
- **Where roots are declared by whole directory** (projects with no registration framework)
  almost everything is a root and "how you get in" loses its meaning.

## The numbers in this guide

The ones that appear here are **lessons**: they explain why a reading is correct, and they do
not change with a commit. The ones that do change —how many edges, how many seconds, what
percentage a guard has— **are not quoted from memory: they are recomputed**.

It is the same rule that makes the tool exist, applied to its own manual. And it is not
theoretical: this guide once cited 124,531 edges and "1.3 s" when the code already said
otherwise.
