# mcview

You have to change code you have not read. Documentation describes the system as it was when
somebody wrote it down, and reading your way in does not scale — five files to answer one
question, and the answer is only as good as which five you happened to open.

mcview computes the answer instead. From today's AST, in seconds, so it cannot be stale.

```
ORIENTATION — Persistence   (module)
2 files · 16 symbols · 5.38% of the project's mass

cohesion 0.61
(complete graph; --hierarchy measures it without hubs — not interchangeable)

── TEMPERATURE ────────────────────────────────────────────
  ALIVE_PRODUCT            12
  ALIVE_PRODUCT_WEAK        2
  TEST_ONLY                 1
  DEAD_CANDIDATE            1
  cold (mass ~0)            2   referenced, but the system does not go through them
```

One directory, one `.toml`, no dependencies on the main path. Python and TypeScript. Usable as a
CLI or as an MCP server.

---

## How it works

Three steps produce a graph — inventory, scope, references — and **every view reads that graph
without looking at the code again**. A defect in one step therefore shows up in every view at
once, which is why fixes go to the step and never to the view.

```mermaid
flowchart LR
  SRC["source"] --> INV["1 · INVENTORY"] --> SCP["2 · SCOPE"] --> REF["3 · REFERENCES"]
  REF --> G(["symbols + edges"])
  G --> V1["liveness"]
  G --> V2["mass · PageRank"]
  G --> V3["modules · MCL"]
  G --> V4["flow · paths"]
  SRC -.-> DUP["duplicates · AST fingerprint"]
```

A random walker starts at the **declared entry points** and follows references. Where it spends
its time is the usage mass (personalized PageRank); where it gets trapped are the modules (Markov
clustering); how often a route crosses a node is an absorbing chain. Same matrix, three
questions.

The personalization is what makes it correct. Classic PageRank teleports to any node — it models
someone who can start browsing on any page. A program cannot: it always starts at an entry point.
Seeding the jump at the roots is what turns generic centrality into "how much this is used when
the system runs".

That also explains the one thing you have to configure. Without declared roots there is nowhere
to seed, and reachability declares the whole project dead.

[`docs/THEORY.md`](docs/THEORY.md) has the formulas, the parameters that were measured rather
than chosen, and where each one runs.

### Two decisions that shape everything downstream

**Paths run on unambiguous edges only.** A path is a stronger claim than a reference and needs
stronger evidence. On the reference project the complete graph has 124,531 edges against 8,058
unambiguous ones, and with the former everything reaches everything: a first attempt reported 351
of 402 roots "reaching" one subsystem, listing `client` and `get` from test files as what the flow
crosses. That is not a flow — it is noise shaped like one, which is worse than showing nothing.

**The AST, not a code index.** An index can have *silent holes*: calls that appear neither as
resolved nor as unresolved. A silent hole is worse than an unresolved reference — the unresolved
one is visible and can be rescued, the missing one is indistinguishable from "unused". Measured
against a real index over the same code: 112,476 edges against 9,770.

### Why every number carries a caveat

Because the measurements kept contradicting the readings. Mass looked like importance until it
was checked against a runtime probe and came out at AUC 0.506 — chance. A guard-detector looked
correct until it produced 64 false bypasses on routes that were in fact protected. A subsystem
measured 0.05% of mass and 50% of it had just run.

So every number ships with what it does *not* claim — printed on the CLI, and as a `caveat` field
on every MCP result. It is the most important content in this file, and it is [collected in one
table below](#what-each-number-does-not-claim).

---

## What it answers

| question | command | MCP tool |
|---|---|---|
| What is this area and how does it work? | `--orient <target> --flow` | `mcview_orient` |
| What happens, and in what order? | `--sequence <target> --to <dest>` | `mcview_process` |
| What can a request traverse, across repos? | `--route "<name>"` | `mcview_route` |
| Does this already exist? | `--exists <file>` | `mcview_exists` |
| Where does the system go? | `--map` | `mcview_map` |
| What code is unused? | `--status DEAD_CANDIDATE` | `mcview_status` |
| Does this connection still hold? | `--locks` · `--propose <a> <b>` | `mcview_locks` |
| How do my repositories join? | `--seams` · `--bridges` | `mcview_seams` |
| What did this change do to the repo? | `--diff <ref>` | `mcview_diff` |
| What do I have to restart? | `--services` | — |
| Is this well modularized? | `--k` · `--hierarchy` · `--islands` | — |
| What actually runs? | `--runtime` | — |

Everything accepts `--json`.

---

## Install

```bash
# as a command
pipx install git+https://github.com/mcalza96/mcview
pipx inject mcview tree_sitter tree_sitter_typescript   # only for TypeScript projects

# or copy the directory — no install, works offline
git clone https://github.com/mcalza96/mcview && cp -r mcview/ /path/to/your-project/
```

Requires Python **3.11+**. The main path has zero dependencies; `numpy`/`scipy` are needed only
by `--modules`, `--k`, `--hierarchy`, `--islands` and `--views`, and `tree_sitter` only by
TypeScript projects. Each says what to install and exits.

Copying the directory is the model the four bundled skills and the portability check document
and verify; the packaged command exists so you do not have to clone. Both work — the entrypoint
puts its own directory on `sys.path` either way.

### As an MCP server

```bash
claude mcp add --scope user mcview -- mcview --mcp
```

Ten tools, listed above. When the server is global, pass `projectPath`: one process serves many
repositories, and without it the answer depends on the directory the client launched it from.

Not on PyPI — the name is taken there by an unrelated project.

---

## First run

```bash
cd your-project
mcview --init      # derives mcview.toml from what the project already declares
mcview             # the census
mcview --map       # where the system goes
```

**Declaring the roots is half the work, and it is the only mandatory part.** `--init` will not
decide which entry points matter — that is a statement about the project, not about the file
system — but it stops you writing them from memory. It reads `[project.scripts]`, the Dockerfile
`CMD`, the decorators that register into a dispatch dict and the process entrypoints, and writes
each root with its provenance:

```toml
[roots]
#   mcp_tool: 168 uses in 28 files (e.g. api/v1/mcp_tools/ast_tools.py)
decorators = ["mcp_tool"]
#   candidate — `mcp_prompt`: 4 uses but only in 1 file. One file is not enough
#   to declare a registry; look at it.
route_methods = ["post", "get", "delete", "patch", "put"]
route_objects = ["router", "app"]
dirs = ["entrypoints/worker.py", "entrypoints/main.py", "tests/"]
product_dirs = ["entrypoints/worker.py", "entrypoints/main.py"]
```

Checked against a config a human had written by hand for a 740-file backend, `--init` derived the
two large root classes exactly (169 tools, 171 routes) and the same 6,186 symbols. What it could
not decide it flagged as candidates, and the whole census difference was those flagged roots.

If it finds no registration decorators, no routes and no entrypoint, it says so and falls back to
whole directories — which is the expensive mistake. On one 448-file project, declaring directories
gave 649 roots and the flow stopped discriminating: when everything is an entrance, "how do you
get in" has no answer.

### Before believing a number

1. **Root count against file count.** If they are close, you declared directories.
2. **Is `DEAD_CANDIDATE` plausible?** Hundreds in a healthy repo means missing roots — usually a
   registration decorator. Zero in an old repo means too many.
3. **Does the map look like your system?** If something marginal tops it, ask what an *edge*
   means in this codebase before reading the mass.
4. **Ask it something whose answer you already know.**

---

## Reading the output

### "Alive" is not a boolean

Collapsing it overestimated liveness by a factor of eight on the first project measured.

| status | means |
|---|---|
| `ALIVE_PROVEN` | ran at runtime |
| `ALIVE_PRODUCT` | reachable from a real root, unambiguous name |
| `ALIVE_PRODUCT_WEAK` | reachable **only** through an ambiguous name (homonyms) |
| `TEST_ONLY` | alive only because a test or script touches it |
| `ALIVE_BY_NESTING` | alive only by being nested inside something alive |
| `DEAD_CANDIDATE` | no references at all |

`ALIVE_PRODUCT_WEAK` and `TEST_ONLY` are where entropy accumulates: code nobody deletes because
the graph says it is used, when what holds it up is a homonym or its own test.

### What each number does not claim

| number | what it does **not** say |
|---|---|
| **mass** | Not importance, not real frequency: structural centrality. Measured against a runtime probe it does **not** predict execution (AUC 0.506). Plumbing tops the map. |
| **`DEAD_CANDIDATE`** | Not a deletion order. A hypothesis with no *static* evidence of use. Names reached only through a string — a registry, `mock.patch`, config dispatch — are invisible to it. |
| **flow / paths** | Structure, not execution. A path here may never be walked; an absent one may exist through dynamic dispatch. The bias is toward the false negative: it never invents a path. |
| **sequence** | The *written* order. A call inside an `if` appears even if it never runs; a dynamically dispatched one does not appear even if it always runs. |
| **cohesion** | Below 0.15 does not mean "split it" — it means it is not a unit, it is crosscutting infrastructure. `--hierarchy` measures it without hubs and gives a different number. |
| **runtime** | Confirms, never rules out. "Not observed" may mean it sits behind an `if`, fell outside the window, or ran in a process with no probe. |
| **`--diff`** | Typed signals, never a single score. Only `net_symbols` is validated against history; change heat and concentration are not. |
| **duplicates** | Same shape is not the same responsibility. Ask what would happen if *one* copy diverged. |

The whole chain is fail-open: when in doubt, alive. False "dead" costs something; false "alive"
costs a review.

---

## Locking a connection

A component is protected by a test — you call it and check what it returns. A connection is not:
*"every request crosses the tenant resolver before touching the database"* is a property of every
path, and there is no way to write it as an assertion about a function. Repositories tend to have
their components secured and their connections not.

One primitive: **remove what guarantees the connection and ask whether the sink is still
reachable. If it is, that path is the bypass** — and it is its own evidence, verifiable by reading
three functions.

```toml
[[locks]]
name     = "every route resolves the tenant before touching the database"
src      = "api/routers/"
dst      = "store/client.py"
requires = "get_tenant_id"
```

| contract | demands |
|---|---|
| `crosses G` | interposition — the data always goes through G |
| `requires G` | precondition — someone on the path called G first |
| `cannot_reach` | isolation — no path exists |

`requires` is not `crosses` renamed. A guard is not *on* the path: it is called before, as a
precondition with an early return, so in the graph it is a **sibling**. Treating it as an
interposition — what a dominator does — is what produced the 64 false bypasses mentioned earlier.

Verdicts are exact, not sampled. `--propose <a> <b>` ranks candidates by mass and emits the TOML
block; an empty result means nothing is interposed, so there is no chokepoint to put a guarantee
on — building one is design, not cleanup.

**Status, plainly: this is a capability, not yet a practice.** The primitive is verified against
13 graphs with known answers (`selfcheck/check_contracts.py`), and no project has declared a
contract yet — the half that gets used is `--propose`, and its finding so far has been *there is
no chokepoint here*. Read the section as "what this makes possible", not as "what teams do with
it".

---

## Crossing the repository boundary

**The seam between projects is made of strings, not symbols.** A gateway does not import a
function from the backend: it hits a route and asks for a tool by name. No call graph crosses
that, and no single-repo tool sees it.

Two relations that are not the same:

- **call** — one project writes the other's identifier. Listed with the exact line on both sides.
- **shared state** — two projects touch the same table without ever calling each other. It appears
  in no call graph, and it is usually where the authorization surface lives.

Routes are the hard case: a route is assembled across three files (`APIRouter(prefix=…)`, the
`include_router` that mounts it, and the decorator's literal). `route_prefixes` follows that chain
through the imports and reconstructed 158 of 158 on the reference project.

---

## The runtime census

Where code is resolved by name — plugins, platform adapters, dispatch tables, an agent's tools —
no static analysis reaches, and a low number there means "I cannot see it", not "unused". This is
the 0.05%-of-mass subsystem from earlier: half of it had run.

**The probe is not part of mcview.** It lives in the project being measured, because it has to run
inside that project's deployed process; mcview only reads the JSONL it leaves behind. A reference
implementation is in [`docs/liveness_probe.py`](docs/liveness_probe.py). It uses `sys.monitoring`
(PEP 669) and returns `DISABLE`, which turns monitoring off for that code object after the first
hit — each function costs once and nothing thereafter. It is a census, not a profiler, and can be
left on in a real process: measured overhead over 3M calls was indistinguishable from noise.

It only promotes to alive, never demotes to dead.

### What has to be true for it to record anything

Every one of these fails **silently and identically**: an empty census, which reads as "nothing
ran" when it means "nothing was measured".

| condition | if unmet |
|---|---|
| `MCVIEW_PROBE=1` | no-op. Off by default on purpose — turning on observability nobody asked for is the kind of change nobody can later explain. |
| **Python 3.12+** | `sys.monitoring` does not exist; the probe returns `False` and says nothing. |
| `MCVIEW_PROBE_DIR` writable | returns `False` on `OSError`. |
| Code under `MCVIEW_PROBE_ROOT` (default `/app`) | every file is filtered out as foreign. Wrong root in a container ⇒ zero rows. |
| `start()` runs **in the deployed process** | see the two traps below. |
| No other profiler holds `PROFILER_ID` | the tool id is taken and monitoring never starts. |

### What has to be true for mcview to read it

| condition | note |
|---|---|
| Files land in `<project root>/.mcview/` or `<project root>/.salud/` | point `MCVIEW_PROBE_DIR` there, or copy them in. (`.salud/` is read too, for probes predating the rename.) |
| Filename contains `liveness` | anything else in that directory is ignored. |
| The path resolves to a file in the project | the container path (`/app/api/x.py`) is trimmed by the longest suffix that is a known file — no declared prefix to age out. |
| Symbol matches file **+ name + line** (±3 tolerance) | by name alone, a project's 96 `main`s would all be confirmed by the one that ran. The tolerance exists because the probe stamps the code object's first line and the inventory stamps the `def` — with decorators those differ. |

### Two traps that produced an empty census, both measured

- **The probe was not in the baked image.** The variable was set, the service was up, the file was
  never written.
- **The container started the service in-process**, so the `main()` holding the call never ran.
  Wiring it at module import fixed it.

Both looked identical from outside: probe "on", census empty. **Before believing a census, check
that it MEASURED** — that the file exists and has lines — not that the variable is set. The probe
is wired inside a `try/except` so it cannot block startup, and that same choice is what makes it
fail quietly. Expose its `state()` somewhere: it is the cheap way to tell "measured nothing" from
"never measuring".

### Reading it

Something absent may have run outside the observed window, sat behind an `if`, or run in a process
with no probe. And it is **one window**: a module that only runs in a scheduled task shows zero
and is not dead. For fine-margin decisions, leave it running for days, not minutes.

If a `DEAD_CANDIDATE` shows up as executed, that is not a detail: the static analysis was wrong and
a root is undeclared. Fix the `.toml` before reading anything else in that run.

---

## The pre-write gate

Detecting duplication means cleaning it up later; the gate is about it not happening. A
`PreToolUse` hook on `Write|Edit` queries the index before code reaches disk and warns if it
already exists. ~60 ms. It never blocks and fails open — any error or missing index lets the write
through, because a hygiene tool cannot stop the work.

```bash
mcview --reindex          # build the cache
mcview --exists file.py
```

The default threshold (0.75, `MCVIEW_GATE_THRESHOLD`) loses recall deliberately: at 0.55 it would
catch more real duplication but fire on 58% of writes, and a gate that always shouts becomes
invisible.

---

## Design notes

| decision | why |
|---|---|
| **No dependencies on the main path** | Verified by blocking the optional modules, not by reading imports. It is what makes installing a matter of copying a directory. |
| **Config lives outside the tool** | While `mcview.toml` sat inside `mcview/`, extracting the module carried the previous project's roots with it. It is now discovered by walking up from the current directory. |
| **Layers are directories, not packages** | Mounted on `sys.path`, so imports stay flat. A real package forces `python -m mcview` and breaks the copy model. The price: two layers cannot share a file name — `_layers.collisions()` checks that rather than trusting it. |
| **The skills travel inside** | `orient-session`, `mcview-repo`, `mcview-process`, `mcview-install`. Shipping the engine without the manual is what lets somebody read a ranking as a conclusion. |
| **Expensive views are not MCP tools** | Full duplicate analysis, `--k`, `--hierarchy`, `--islands` and `--views` run in minutes on a large repo. A call that blocks for minutes is one nobody makes twice. |

Six self-checks travel with it, in `selfcheck/`. Two cover failure modes that do not crash: a
config key drifting from its reader — the view returns empty, which reads as a finding — and
encapsulation eroding until the directory no longer copies cleanly. The latter runs the CLI as a
subprocess from a temporary directory, because importing the modules proves nothing when
`sys.path` and `cwd` are already contaminated.

---

## Limits

- **Structure, not execution.** Dynamic dispatch and plugins loaded by name are invisible.
- **Mass does not predict execution** (AUC 0.506 against a probe).
- **The optimal partition `--k` returns is not identifiable**: exponentially many have almost equal
  Q. Q as a scalar compares well; "these are the N modules" does not hold.
- **It does not see argument filtering.** It finds "reaches the sink without crossing the guard",
  not "crossed the guard but forgot the tenant filter".
- **Nested blocks are Python only.** In TypeScript the report says `0 blocks` — not "no duplication
  inside functions", but "not looked for there".
- **No external validation** against bugs or maintainability.
- **Cost:** ~7 s over 5,500 symbols, ~2 min over 42,000. A real-time gate would need incremental
  analysis.

Dated measurements in this file are quoted because they happened and do not change. Anything
describing the current state of a repository is not quoted from memory — it is recomputed.

---

## License

MIT. The vendored diagram renderer (`vendor/mermaid.min.js.gz`, mermaid 11) is MIT as well.
