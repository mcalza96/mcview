---
name: mcview-repo
description: >-
  For MEASURING a repository's entropy with the `mcview/` tool — dead code, duplication, a
  PageRank usage map, modularity, guards that fail silently — and for CLEANING UP with
  evidence. Use it when the user asks "what code is unused?", "is this duplicated?", "which
  files are used most?", "is this well modularized?", "should this file be split?", "what
  did this commit do to the repo?", when they ask to delete/clean/slim down code, or when
  they want to know whether a change adds noise or value. It triggers even when they never
  say "mcview" or name the tool — e.g. "strip out what pkg/ai doesn't use", "is this
  refactor worth it?", "show me where the fat is". Do NOT use it to GET LOCATED before
  touching an area (that is `orient-session`, the focused view of the same tool), nor to
  explore without the tool (`discovery-sweep`), nor to prove liveness against a running
  service (`purge-verify-alive`). This skill starts when you want a MEASURED NUMBER about
  the repo.
---

# Repo health

`mcview/` answers with evidence which code is unused, what is duplicated, where the system
goes, and which guards may be switched off without warning. It is agnostic: everything
project-specific lives in a `.toml`.

```bash
mcview/mcview.py                     # liveness levels + duplicates (the base view)
mcview/mcview.py --map               # usage mass per file
mcview/mcview.py --modules           # declared vs discovered lines of work (MCL)
mcview/mcview.py --k                 # natural k (Newman modularity)
mcview/mcview.py --hierarchy         # split (cohesion) / merge (ΔQ)
mcview/mcview.py --islands           # which file to split and WHERE
mcview/mcview.py --risk              # dead candidates, safest to riskiest
mcview/mcview.py --status DEAD_CANDIDATE --limit 200 --json
mcview/mcview.py --diff HEAD         # what a change did to the repo
mcview/mcview.py --exists <file>     # does this already exist?
mcview/mcview.py --reindex           # refresh the gate cache
mcview/mcview.py --services          # what runs in each process → what to restart
mcview/mcview.py --seams             # the literals joining this project to others
mcview/mcview.py --bridges           # the whole workspace, joining the mcview*.toml files
mcview/mcview.py --orient <target>   # brief for ONE area — see the `orient-session` skill
```

All of them accept `--json`. `--project <name>` uses `mcview.<name>.toml`; `--config` takes
a path. The config discovers itself by walking up from the current directory.

`--no-duplicates` skips the expensive part of the base view (the full base takes tens of
seconds; without duplicates, seconds).

**Level 2** (`mcview/views/guards.py`) is a LIBRARY with no CLI flag and, today, no caller
inside the tool — you import it and pass it level-1 output. Treat the section below as the
method it encodes; the four findings it describes were reached by asking those questions by
hand, not by running a command.

## Pick the depth before starting

Not every question deserves the same work:

| what the user asks | what to do | cost |
|---|---|---|
| understand the state, "how is this?" | run the view that answers + report with caveats | seconds |
| decide whether a change helps | `--diff` + read the commit | ~1 min |
| **delete code** | the full protocol below | minutes |

Only the third justifies the whole protocol, because it is the only one where being wrong
breaks something. If the user asks for a reading and you hand back a twenty-minute audit,
you wasted their time.

**What does NOT get trimmed with the depth: if a number is going to travel in your answer
and it depends on a preprocessing decision, measure it under both configurations.** That
holds for a thirty-second reading too. A headline without that check propagates as fact, and
the depth level you chose does not travel with it.

Measured case: `--k` reports modularity capture **after removing the top 1% of hubs**; with
the hubs in, the same repo comes out several points lower. Reporting only the high number
claims something stronger than what was measured.

## First things first: "alive" is not a boolean

Collapsing liveness to yes/no overestimates what is alive by a large factor. The tool
returns grades of evidence, and the difference between them is what decides what can be
touched:

| status | what holds it up |
|---|---|
| `ALIVE_PROVEN` | it ran at runtime — never touch |
| `ALIVE_PRODUCT` | reachable from a real root, unambiguous name |
| `ALIVE_PRODUCT_WEAK` | **only** via an ambiguous name (homonyms) |
| `ALIVE_NOT_PRODUCT` | reachable, but never from a product root |
| `ALIVE_BY_NESTING` | alive only by being nested inside something alive |
| `DEAD_CANDIDATE` | no references at all |

`ALIVE_PRODUCT_WEAK` and `ALIVE_NOT_PRODUCT` are where the entropy lives: code nobody deletes
because the graph says it is used, when what holds it up is a homonym or its own test. When
reporting, name them — do not hide them behind the total.

**But `ALIVE_NOT_PRODUCT` is not automatically fat: look at what that test proves.** Measured case:
a 22-line component marked `@deprecated`, alive only through its test — read mechanically,
fat. But the test was not testing the shim: it was testing **the real component through it**,
with 13 cases, in a frontend where almost nothing has tests. Deleting both cost real
coverage; the correct output was to delete the shim and **re-point the test**.

**And a low `ALIVE_NOT_PRODUCT` is not good news either.** In this monorepo the backend is above 50%
and the frontend near 2% — that is not the frontend having less fat, it is the frontend
having almost no tests. The same metric says opposite things depending on how much the
project is tested.

**`DEAD_CANDIDATE` is a hypothesis, not a deletion order.** The whole chain is fail-open:
when in doubt, alive. False "dead" is the failure mode that hurts.

If the base view reports that a `DEAD_CANDIDATE` **ran at runtime**, that is not a detail:
the static analysis was wrong and there is an undeclared root. Fix the `.toml` before reading
any further into the run.

## Which metric answers which question

Picking the wrong metric leads to concluding that a cleanup "did nothing" when what failed
was the instrument:

| question | metric |
|---|---|
| where does the system go? | `--map` (mass) |
| how much fat is there? | cold symbols + dead components |
| how is what is **alive** organized? | `--k` (Newman's Q) |
| is this module one thing or several? | `--hierarchy` (cohesion) |
| should this file be split? | `--islands` |
| what is duplicated? | base view (Type-1/2, Type-3) |
| what did this change do? | `--diff` |
| does this connection still hold? | `--locks` (declared contracts) |
| where is it worth putting a lock? | `--propose <from> <to>` |
| what actually runs? | `--runtime` (probe census) |

Four traps:

- **High mass = a lot of traffic, NOT a lot of value.** Plumbing modules (auth, cache,
  telemetry) top the map because every request crosses them.
- **Q is insensitive to cleanup.** Deleting dead code moves it ~0.001, and that is correct:
  Q measures the separation between live modules, and the dead is disconnected from the
  graph. To measure fat, look at cold symbols and dead components.
- **Mass means different things depending on what an EDGE is there.** Where most references
  are internal to the file —a component UI— the walker stays inside and the mass reflects the
  internal complexity of large files, not traffic between modules. Measured: in a service
  backend I predicted plumbing would dominate the map and it did; in a frontend I predicted
  the same and the design system did not reach 1%. Before reading it in a new kind of
  codebase, ask yourself what an edge represents.
- **A percentage can move because the DENOMINATOR moved.** After a consolidation, modularity
  capture dropped two points and the declared Q came out **identical**: what went up was the
  ceiling. The partition did not get worse; the yardstick grew. Facing a ratio that moves,
  ALWAYS look at both of its terms before telling a story.

## What the tool does NOT see

These are the blind spots that produce false "dead":

**References inside strings.** The analysis walks AST identifiers, so a name living inside a
string is invisible: `patch("module.function")` in a test,
`importlib.import_module(name)`, dispatch from config, routes in YAML.

```bash
grep -rn "\"<symbol>\"\|'<symbol>'" .    # the name as a string, not as an identifier
```

**Homonyms that are not code.** A `grep` of the name returns uses that are not uses: Pydantic
fields, dict keys, RPC parameters. Real case: a `p_apply_scope_penalty` in a call to Postgres
is not the Python function `apply_scope_penalty`, and counting it gives a "1 use" that does
not exist. **Look at what each match is, not how many there are.**

**Cycles between packages, file size, dependency direction.** The tool measures symbols and
references; it does not see that `api/` and `services/` import each other, nor that a file
has 2,400 lines, nor that `core/` imports upward. If the question is about **architecture**
and not entropy, complement with LOC per package, an import matrix, and a search for deferred
imports inside functions (they are coupling debt measured in patches).

## Cleaning up: the protocol

The order matters because each step rules out a different failure mode.

### 1. Pick the target by COHERENCE, not by count

One dead symbol on its own is a finding; **ten that call each other and that nobody calls is
a switched-off subsystem** — safer to delete (it holds itself up) and more valuable. A file
with 100% of its symbols dead and zero importers is the ideal case.

This can invert the priority: a directory with 30 *scattered* dead symbols is worth less than
a file with 12 forming one block.

### 2. Ask WHY it is dead

```bash
git log --oneline -S "<symbol>" -- <file>   # when it arrived and when it stopped being used
```

Three stories, three endings:

- **It was never alive** (untouched since the initial commit) → delete without drama.
- **It got disconnected** when its consumer was replaced → delete, and the commit message
  should say which migration it is a residue of.
- **Its destination is a stub.** Real case: an entire validation module dead because the
  endpoint that was going to use it returns a literal. There the question is not "do I
  delete?" but "was this supposed to be wired up?" — and that decision belongs to the
  project's owner, not to you.

**The dominant pattern, measured across four real purges: a contract written before its
consumer, a consumer that never arrived or got replaced, and nobody deleted it because nobody
knew whether it was alive.** A `git log` saying "untouched since the initial commit" plus an
endpoint that does not exist is the exact signature. It is not carelessness: without evidence,
deleting is riskier than leaving — which is precisely what this tool exists to change.

### 3. Verify everything in one pass

Verifying symbol by symbol is four greps each —with 30 candidates, 120 passes over the tree—;
the script reads the tree **once**. Measured in a real case: **0.3 s against ~20 minutes**.

```bash
mcview/mcview.py --status DEAD_CANDIDATE --limit 200 --json \
  | python3 <skill>/scripts/check_dead.py --root <project/dir> --json-stdin
```

Filter the JSON by `loc` if you care about one module. `--git` dates each symbol (slower).

What matters is not that it counts but that it **classifies each match**:

| column | what it means |
|---|---|
| `code` | a real reference in another file → **it is NOT dead** |
| `str` | inside a string: `mock.patch`, `importlib`, config → review by hand |
| `doc` | a mention in prose → counts as zero |
| `hom` | homonym: Pydantic field, dict key → counts as zero |

Without that distinction, a `grep` reports "1 use" both for a real call and for a Pydantic
field that happens to share the name.

If there is a runtime running, evidence of execution is stronger than any static analysis —
there, use `purge-verify-alive`.

### 4. Measure paired, not in two loose runs

```bash
git stash -q && <measure>      # BEFORE
git stash pop -q && <measure>  # AFTER
```

If another agent is working —or if you touched something in between— the repo moves between
measurements and the delta mixes your change with theirs.

**And comparing a verifier's output has TWO traps of its own**, in opposite directions:

- **Normalize positions before comparing.** A compiler reports `file(line,column): error`. If
  you delete 20 lines, every error below shifts and a `diff` counts them as new. Measured: 3
  pre-existing errors looked like regressions and I was about to revert a correct deletion.
  ```bash
  <verifier> | sed 's/([0-9]*,[0-9]*)//' | sort   # on both sides
  ```
- **Disable the incremental cache for the baseline.** A `tsbuildinfo` makes errors appear and
  disappear between identical runs. Measured: 4 phantom errors that survived reverting the
  change supposedly causing them.

The rule behind both: **a baseline that is not reproducible is not a baseline.** Run the
measurement twice without touching anything and demand the same number before saving it.

### 5. Cut with the AST, not by counting lines

To extract functions from a **live** file, parse it and use `lineno`/`end_lineno` instead of
hand-made ranges. Afterwards: the file still parses, no orphan imports remain
(`ruff check --select F401,F811,F821`), and the module's tests pass.

### 6. Which indicator moves, and which does not

| indicator | answers |
|---|---|
| `DEAD_CANDIDATE` | drops by exactly what you deleted |
| symbols in dead subsystems | **the metric of the cleanup** |
| Newman's Q | **does not move** (~0.001): it measures separation between LIVE modules |
| cold files | does not move if you deleted inert classes — they are different things |
| Type-1/2 groups and Type-3 pairs | drop when duplication is collapsed; **they do not move when deleting dead code** |

If what you changed was the DECLARATION (moving something between modules in the `.toml`),
the only valid indicator is **Q of the declared partition**: it measures whether your labels
describe the graph well.

**A null ΔQ there is a result, not a failure — and it says something precise.** Measured:
declaring five lines of work that had been falling back to the directory heuristic gave
**ΔQ = +0.0002** with the partition changing across five groups. The reading is not "it did
not work": it is that **the fallback was already grouping just as well**, so the missing
percentage is real structure and not a forgotten label. That rules out an entire front of
work, which is worth more than a small improvement.

When you measure with three decimals and nothing moves, **ask for more decimals before
concluding**: the difference between "did not change" and "changed by 0.0002" is the
difference between suspecting the instrument and knowing the hypothesis was false.

**Cohesion is NOT useful for validating "this does not belong here".** It measures
connectivity, not membership. Measured case: pulling a self-contained island out of a module
—68% of its references inside itself— **lowered** the module's cohesion, because it took 19
internal edges against 9 external ones. The reclassification was correct and the number said
the opposite.

### 7. The lock

**If no LIVE status moved, the verdict was correct.** When deleting N dead symbols,
`DEAD_CANDIDATE` drops by N and `ALIVE_PRODUCT` / `ALIVE_NOT_PRODUCT` / `WEAK` stay **identical**. If
any of them moves, something alive depended on what you removed — revert and review.

**And validate the verifier you did NOT write yourself.** A typecheck or a test run can be a
**no-op that comes out green**: in this repo `tsc --noEmit` aborted on a configuration error
—before looking at a single line— and exited with code 0 and zero errors. It looked exactly
like a healthy project. It only surfaced by deliberately injecting an obvious error and seeing
that it went unreported; with the verifier fixed there were 197 accumulated errors.

The rule: **before resting a decision on a tool, break something on purpose and confirm that
it screams.** It applies above all to whatever came with the project, which is where suspicion
is lowest. A broken verifier does not fail loudly: **it fails by agreeing with you.**

### 8. Delete in waves, re-measuring

Deleting wave 1 **creates new orphans**: whatever was only called by the code you removed. Do
not guess them — run the tool again and let them appear. One commit per wave, ordered by
increasing blast radius: pure orphans first, then cascade roots, then whatever was left loose.

And separate what is **not your decision**: a symbol with no callers but documented as an
operations API, a constant left with no reader, an unwired stub, something better *moved* than
deleted. That changes the shape of the system — list it separately and let the owner decide.

## Redundancy: similarity proposes, the RULE decides

The base view lists groups with identical skeletons (Type-1/2) and pairs of similar shape
(Type-3), ordered by duplicated volume. That order is a **candidate ranking**, not a priority
one: the largest pair may be the one not to touch.

It includes **nested blocks**, not just functions: a name with a slash (`resolve/try`) is a
block. The most useful case is the mixed one — an inline block paired against an
already-extracted function means *"you already pulled this helper out in one file and in the
other it is still copied by hand"*.

The deciding question is not *how similar they are* but **what is being duplicated**:

| what is duplicated | action |
|---|---|
| a **rule** (a semantic, a default, an abstention condition, a security comparison) | collapse |
| a **shape** (a CRUD, a route declaration, a framework wrapper) | leave it |

The operational test: **ask yourself what would happen if ONE of the copies diverged.**

- If the answer is a **silent** failure —a `==` where there was a `compare_digest`, two
  counters that stop being comparable, a default that used to protect and got inverted—
  **collapse it**. Duplication does not cost lines: it costs the failure being invisible when
  reading the other copy's diff.
- If the answer is "nothing, just more lines", leave it. A configurable version of two CRUDs
  touching different tables and returning different shapes is more complex than both of them
  together.

**Look for the helper that already exists before writing one.** The most common pattern is not
"this needs abstracting": it is that **the general version has already been written** —usually
later, for case N— and the old ones were never migrated. There the fix adds no abstraction at
all, it just uses the one that was there. Grep the duplicated block: if it shows up a third
time already parameterized, that is the destination.

**Two instances are not a pattern.** If only two out of sixteen functions share a shape, and
each differs in thresholds and in the text it shows the user, a generic helper ends up taking
six parameters: more surface than it removes.

### False positives that will always be there

They are not noise to fix; they are a consequence of how the measurement works:

- **A function and its own recursive closure.** The inner `_walk` resembles the function
  containing it by construction.
- **Twin route declarations** (`pause`/`resume`, `enable`/`disable`). What is duplicated is
  the declaration that makes them two distinct endpoints.
- **Families of tools or handlers registered by name.** The registration and the description
  HAVE to be repeated —that is what distinguishes them for the caller—; what gets collapsed is
  the body, not the declaration.

And in the **dead** list there is an equivalent kind: what the type system consumes through
**declaration merging**. `declare module 'x' { interface Y }` is referenced by nobody —the
compiler merges it with the original interface— and will show up dead on every run.

### When reporting redundancy

State explicitly **what you did NOT collapse and why**. A report that only lists what was done
leaves the reader assuming the rest is pending, when it was already evaluated and dismissed.
And the highest-volume candidate is the one that most deserves that sentence, because it is
the one anyone will look at first.

## Splitting files: `--islands`

Islands are the connected components INSIDE a file. They say two things: whether it is worth
splitting and, if so, **where** — each island already comes with its members.

| signal | reading |
|---|---|
| largest island ≥ 60% | one big thing → **do not split**, even at 2,000 lines |
| largest island < 30% with ≥3 islands | several things cohabiting |
| cohesion < 0.15 | it is not even cohesive → rethink, do not split |

**Size is not a criterion.** Measured: this repo's largest file does not even appear in the
split list —it is one big thing—, while one a third its size has eight islands with the
largest below 20%: that is not a file, it is a folder. A list of "files over 1,000 lines" is
**not** a refactor list.

### Before recommending a split, two filters

**There are layers fragmented by design, and the metric will always flag them.** A router is a
collection of independent endpoints; a data access layer, of independent queries; a schema
module, of loose definitions. In all three, the functions **do not call each other by
construction**, so internal connectivity is low by nature and not by disorder. Fragmentation is
only a signal where the file claims to be a coherent unit.

**When you suspect a false positive, look at WHAT each island is, not how many there are.**
That is usually where the real finding is, and it is almost never the one the headline
suggested. Measured case: a data access module flagged "split along its islands (4)" —where
splitting bought nothing— had a 176-line function of which **two** lines were data access; the
rest was business inference over rows already in memory. The problem was not size: it was logic
in the wrong layer. The metric pointed at the right file for the wrong reason.

A useful shortcut for a data access file: group its functions by the **table or external
resource** they touch instead of by their internal references. That grouping does reveal real
seams, because it is the one the island metric cannot see.

**Extracting pure logic out of an I/O layer enables locks that were impossible before.** While
the computation lives inside the data access, testing it requires simulating the whole client;
separated, the test is a literal. When a split produces that, **write the lock in the same
commit**, or the separation justifies itself and nothing is left holding it up.

**The correct action is almost never to split.** When the islands reveal that something does
not belong there —a documentation renderer inside the protocol module, data access inside the
dispatch layer— **the action is to move, not to split**. Splitting leaves the same code spread
around; moving reduces coupling.

And say it when recommending: **there is no evidence that splitting files improves anything
measurable**. It reduces conflict surface and clarifies what a change touches, but no study
connects it with fewer bugs. The cost is real: more files, more imports, fragmented git
history.

## Level 2: from signals to GUARDS

> Not wired: `views/guards.py` has no flag and nothing imports it. What follows is the method —
> the two questions that pay off and how to read their answers. Questions 1 and 4 are computed
> from what level 1 already gives you; the module implements them if you import it.

Everything above is a **graph** question: who references whom. It finds what is *left over*. It
does not find what is *wrong*, and it does not tell a `require_admin` from a CRUD.

`mcview/views/guards.py` is the complementary question —**what does this code promise**— and it
**consumes** level 1: the graph says WHERE to look, the predicate says WHAT to ask.

**It is not "auditing security".** That space is infinite and cannot be walked. What can be
walked is one kind:

> a guard whose failure mode is **silence**: it does not crash, it stops protecting, and it
> looks identical to one that works.

Measured in one day over a real monorepo, five findings and all five of that kind — an allowlist
that came out empty when given a YAML scalar (**empty = no restriction**), four cross-tenant
leaks where the isolation was a manual `.eq()` that 10 of 31 routes never wrote, an SSRF
re-check calling functions that did not exist, a write deny-list missing the agent's own config
files, and a typecheck that came out green without checking.

**Three of the five came out of level-1 signals** (duplication, undefined names). What was
missing was not another metric: it was knowing which of those findings were guards.

### The four questions

| | question | why |
|---|---|---|
| 1 | how many **copies**? | a rule in N places is N places to loosen it unnoticed |
| 2 | what is its **permissive** state? | if empty/`None`/exception let things through, it is fail-open by construction |
| 3 | **chokepoint** or by hand? | count the sites that apply it against the ones that should |
| 4 | does it have **red** tests? | a red test over a guard **is** the finding |

Questions 1 and 4 are computed with what level 1 already measures. Number 4 is the cheapest and
the highest-yielding.

**A red test over a guard is not noise: it is the guard saying it does not protect.** The
measured case: nine tests demanded that the write deny-list cover `auth.json` and `config.yaml`;
they **had failed since the day they were written** because that coverage was never implemented.
They stayed red for months, mixed in with dozens of others, and that is why nobody read them —
the agent could overwrite its own guardrails. Out of 56 red tests, **18** were about a guard:
reading 18 with a specific question is feasible; reading 56 with no question is what did not
happen for months.

Corollary for the cleanup protocol: **before deleting code so that its red tests go away, ask
which side the error is on.** I was about to delete a toolset for exactly that reason.

### To tell which side: read WHEN each side arrived

A red test over a guard has **two opposite causes**:

- a missing guard → **the test is right, fix the code**;
- a deliberate decision that **did not update its tests** → the code is right, and "fixing" it
  REVERTS the decision.

They cannot be told apart by reading the test. They can be told apart with a command:

```bash
git log -1 --format="%h %ad %s" --date=short -S "<the assertion>" -- tests/
git log -1 --format="%h %ad %s" --date=short -S "<the code line>" -- <file>
```

Measured case, and I got it wrong: I concluded "guard never implemented" and added it. History
said otherwise — upstream had **relaxed** that policy on purpose, the fork adopted the change
with a documented trade-off, and updated ONE test file while skipping the other. My fix reverted
the owner's decision, and what gave it away was another test passing that asserted exactly the
opposite.

**Two tests contradicting each other about the same thing are the strongest signal that the
decision lives in the history, not in the code.** In a fork this is not an edge case: it is the
typical case.

### Validate the classifier against KNOWN findings before using it

It is lexical (`require*`, `*_guard*`, `is_*_denied`, `allow*`, `*_gate*`, `tenant*`…) and that
is exactly why it has to be tested rather than trusted. Measured: the first version **did not
recognize the two allowlists that motivated the module**, because the regex required the word to
end there (`allow(_|$)` does not match `allowed_channels`). An unvalidated classifier gives you a
module that looks fine and finds nothing — **the same failure mode it exists to hunt**.

Like level 1: **it generates candidates, not verdicts.**

## The pre-write gate

`mcview/gate.py` as a `PreToolUse` hook on `Write|Edit`: before writing, it queries the index and
warns if that already exists. It costs ~60 ms.

**It never blocks and it fails open** — any error or missing index lets the write through. A
hygiene tool cannot stop the work.

The default threshold (0.75, overridable with `MCVIEW_GATE_THRESHOLD`) **loses recall on
purpose**: lowering it would catch more real duplication but would fire on most files, and a gate
that always shouts becomes invisible. If the index is stale, `--reindex`.

## Locking a CONNECTION, not a component

A component is protected by a test: you call it and look at what it returns. A connection is not
— *"every request crosses the tenant resolver before touching the database"* is not a call, it is
a property of EVERY path, and there is no way to write it as an assertion about a function. That
is why repos tend to have their components secured and their connections not.

```bash
mcview/mcview.py --propose "<from>" "<to>"   # candidates + the ready-made TOML block
mcview/mcview.py --locks                     # run the declared contracts
```

Three contracts, one single idea: **remove what guarantees the connection and ask whether the
sink is still reachable.** If it is, that path IS the bypass and it is its own evidence.

| contract | what it demands |
|---|---|
| `crosses G` | interposition: the data always goes through G |
| `requires G` | precondition: someone on the path called G first |
| `cannot_reach` | isolation: no path exists |

**`requires` is not `crosses` under another name.** A guard is not ON the path: it is called
BEFORE, as a precondition with an early return, so in the graph it is a SIBLING. Treating it as
an interposition —which is what a dominator does— produces false bypasses on routes that ARE
protected.

### Reading an empty result

`--propose` can return zero candidates, and that is **not "I found nothing"**: it is "I found
that nothing is interposed". The origin reaches the destination with no mandatory step. Protection
is not missing — **the chokepoint to put it on is missing**, and building one is a design
decision, not a cleanup.

### The verdict comes in two grades

The unambiguous graph decides; what only appears once ambiguous edges are admitted comes out as
`SUSPECT` and does not break. Same criterion as `ALIVE_PRODUCT` vs `ALIVE_PRODUCT_WEAK`.

## The runtime census: the only evidence where loading happens by name

Where code is resolved BY NAME —plugins, platforms, dispatch tables, an agent's tools— **no static
analysis reaches**, and there a low number does not mean "unused" but "I cannot see it".

**The protocol, in order:**

1. **Turn the probe on and use the system the way it is used.** Ten minutes of real use are worth
   more than an hour of analysis. With one flow per surface (each entry door) and whatever
   commands exist.
2. **Verify that it MEASURED, not that it is on.** The probe is wired inside a `try/except` so it
   cannot block startup, and that same `try/except` makes it fail silently: an empty census reads
   as "it did not run" instead of "it was not measured". Check the file and its lines.
3. **Verify in the DEPLOYED PROCESS, not at import.** Two measured traps (2026-08-06): the new
   module was not in the baked image, and the container started the service IN PROCESS instead of
   launching the script, so the `main()` holding the hook never ran. Both produced an empty census
   and neither was visible by reading the code.
4. **Cross-tabulate by module**, not by loose symbol: `executed / total` per line of work is what
   orders a purge.

**The direction is non-negotiable: the probe only PROMOTES to alive.** Something not showing up
may simply mean it did not run inside the observed window. And it is ONE window: a module that
only runs in a scheduled task or in a command you did not use shows up at zero and **is not
dead**. For fine-margin decisions, leave it running for days, not minutes.

## The ratio ranks candidates, it does NOT rule

The most useful indicator for finding fat is **symbols / %mass**: many symbols for little use.
And it is also the one that most easily leads to a wrong decision.

Measured (2026-08-06) over a third-party dependency of 41,000 symbols: the ratio flagged four
modules with four-digit values. The census of one real turn **refuted two**, and both were **live
guards** —the pool rotating the API credentials and the one computing the paths the agent cannot
write to. Without the census, the purge would have deleted two guardrails with an impeccable
number as justification.

**Rule:** the ratio produces a LIST to look at. What authorizes deletion is the census, or a
`cannot_reach` lock that breaks if someone reaches it again. Never the ratio alone.

## Evaluating a change

`--diff <ref>` compares two states of the tree using a temporary worktree. It returns **typed
signals, never a single score**: a composite number is unfalsifiable, and the moment it becomes a
gate, the number gets optimized instead of the code.

| signal | confidence |
|---|---|
| `net_symbols` | validated against history — docs +0, fix +2/+5, feat +9/+29 |
| `duplication_introduced` | usable, partial recall (0 false positives in 18 commits, 1 of 2 true ones) |
| `new_orphans` | works, not validated against history |
| `change_heat`, `concentration` | **not validated** |

When reporting, distinguish the validated ones from the rest.

**A `0` can mean "not measured".** The duplication detector honors the `.toml` exclusions
(`[duplicates] exclude`), so if the change only touches an excluded area, the zero says nothing.
Look at the config before believing the number.

## Analyzing another project

Write a new `.toml`. The only mandatory part is **declaring the roots**: without them reachability
declares the whole project dead, and it is where the mature tools in this space concentrate their
advantage.

```toml
[project]
name = "my-api"
root = "src"

[roots]
decorators    = ["task", "command"]     # @task(...) registers into a dict → root
route_methods = ["get", "post", "api_route"]
route_objects = ["router", "app"]
dirs          = ["src/cli/", "tests/"]  # every module in here is a root
product_dirs  = ["src/cli/"]            # of those, which ones are NOT tests

[areas]        # auxiliary = cold BY DESIGN; judging it with the core yardstick is noise
core = ["src/"]
auxiliary = ["tools/", "bench/"]
test = ["tests/"]

[modules]      # lines of work, crossing folders
"Search" = ["src/search/", "src/api/query.py"]

[services]     # each process's ENTRYPOINT; the reach is computed (see --services)
api    = "src/main.py"
worker = "src/worker.py"
```

Cases that break a naive analysis and are already covered: decorators, aliased imports,
module-level code, closures, homonyms, dynamic plugin registration. If a false "dead" shows up, it
is almost always an **undeclared root** — add it before doubting the code.

**Declaring roots by whole directory has a cost**: where almost everything is a root, reachability
stops discriminating and `--orient` loses its "how you get in". Declare real roots (decorators,
routes) whenever the framework allows it.

### A THIRD-PARTY DEPENDENCY is measured with YOUR yardstick, not theirs

This holds for a fork, a vendored copy, a submodule, anything you did not write and use partially.
And it is the most expensive mistake in this family, because the result looks perfectly reasonable.

Declaring the roots at **their** entrypoints answers *"how is that built"*. The question is almost
always a different one: *"how much of it do I use"*. That is answered by declaring the roots at
**your points of contact** — and those roots are not invented: they come out of what is already
declared somewhere.

```
the product config      which plugins/platforms/modules it TURNS ON
compose / deploy        which files it mounts or overrides
the process             which is the single entrypoint you actually run
```

Measured (2026-08-06) over a fork with 41,000 symbols: with the fork's yardstick our own
integration weighed **1.0%** of the mass and looked marginal. With the right yardstick, **11.5%** —
the system's third-largest module. Same tool, same repo, opposite conclusion.

**How to do it:** a separate `.toml` —do not touch the third-party project's own— with `dirs` and
`product_dirs` pointing at your contact points. Then you compare the two yardsticks: what goes up
is yours, what collapses is what exists and you do not use.

### Another LANGUAGE: enumerate its reference classes first

A new language does not add one more edge case: it adds **entire categories of reference**. And
omitting a category does not produce noise —which would be noticeable— but a confident error **in a
single direction**: everything used only that way shows up dead, in bulk and with no alarm.

Before believing the first run, make the list: how does something get referenced here? A name in an
expression, yes. What about a **type annotation**? A markup element? An **object shorthand**
(`{ Foo }`)? An implicit interface implementation?

**You are not going to complete the list by thinking: you complete it by deleting.** In this repo
TypeScript contributed **three** classes, found at three different moments and always the same way —
the number looked reasonable, a deletion broke the build, and there the category appeared:

| kind | how it showed up | cost of missing it |
|---|---|---|
| type annotations | "dead" types used 2 lines below | 60% of the candidates |
| object shorthand (`{ Bar, Input }`) | deleting them broke the compile | 25% of the candidates |
| JSX elements | anticipated in advance | — |

That is why the correct order is not "list and trust" but **delete a small batch, let the compiler
scream, and read the scream as a category rather than as a case**. If it broke, the question is not
"which symbol do I revive?" but "**what kind of reference am I not seeing?**".

**And there is a SCOPE trap that shows up once per language.** Filtering references by lexical scope
requires telling a name that *shadows* the symbol from one that *is* the symbol: a nested `def` in
Python, a `const f = () => {}` in TypeScript. Counting them as shadows kills every symbol defined
that way, in bulk. In this repo it happened **twice**, once per language, and both times it was the
`DEAD_CANDIDATE` delta that caught it, not reading the diff.

**When two paths of the same tool give different numbers, that discrepancy IS the bug.** Do not
average it and do not pick the one you like. Measured: modularity capture gave one number from a
bespoke computation and another from the CLI; investigating the difference revealed that the CLI was
scoring the two partitions **over different graphs** (one with hubs, one without) and inflating the
headline in all three repos.

**Framework conventions are free roots.** Where the framework loads by filename, the roots are
complete and free — you do not have to hunt them like decorators in a backend, where one escaped and
only turned up with a runtime probe.

**GENERATED code is never evidence.** Build directories (`.next`, `out`, `dist`, `coverage`) contain
artifacts referenced by nobody by definition. In one case they contributed **90% of the "dead"** in
the first run, and would have been the entire finding if nobody had looked at the list. Exclude them
BEFORE reading a number.

### The chain of defects: do not stop at the first

Each fix to the instrument uncovers the next, and the intermediate numbers all look reasonable. In
one repo the sequence was **1088 → 179 → 45 dead**, three different causes, and at every step the
number looked plausible.

Two conditions for stopping the search, and you need both:

1. the number is **plausible** for the project's size, and
2. a **hand-verified sample** confirms the candidates are genuine.

The first alone is self-deception: 179 sounded perfectly reasonable and was four times the real
value.

## When reporting

Bring the number with its caveat attached. Three that apply almost always:

- The usage map is **not validated** against observed execution. It is plausible, not measured —
  and it is measured that **it does not predict execution** (AUC 0.506 against a probe census).
- The optimal partition `--k` returns is **not identifiable**: there are exponentially many with
  almost equal Q. Q as a scalar compares well; "these are the N modules" does not hold.
- None of these metrics has external validation against bugs or maintainability.

And if a result depends on a preprocessing decision, **measure it under both configurations before
reporting it**. In this repo, removing hubs flipped an entire conclusion: a combination of signals
that seemed to give +25% became +0.6% by changing only that step.

## The numbers in this guide

There are two classes, and only one can drift:

- **Dated anecdotes** — "3 pre-existing errors looked like regressions", "of 56 red tests, 18 were
  guards", "1088 → 179 → 45". They happened. They do not change with a commit, and they are what
  makes the lesson credible. **They get quoted.**
- **Current state of the repo** — how many symbols there are, what percentage is `ALIVE_NOT_PRODUCT`, what
  the optimal k is, which is the largest file. They change with every merge. **They are not quoted
  from memory: they are recomputed**, which is why they are described here by their shape ("above
  50%", "the largest file") and not by their value.

It is the same rule that makes the tool exist, applied to its own manual. And it is not theoretical:
this guide once claimed "1300 symbols" and "the 54 modules" when the repo already had 5,790 and the
optimal k was a different one.
