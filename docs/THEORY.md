# The math, and where it runs

Only what executes. Every formula here is reached by a command listed next to it; nothing is
included because it would be nice to have.

---

## One graph, three questions

Three steps produce the graph — inventory, scope, references — and no view looks at the code
again. An edge is not a boolean: `weights[(i,j)]` is a **quota**. An ambiguous reference splits
one unit across its N homonyms instead of giving one to each.

That detail is load-bearing. Counting one per candidate *reinforces* ambiguity instead of
diluting it: `get`, with 10 homonyms, once absorbed 47% of the mass because every dictionary
`.get(...)` injected 10 units.

Everything below is the same row-normalized weight matrix, asked three different things.

---

## 1 · Stationary distribution → mass

> `--map`, `--orient`, `--diff` · `views/heatmap.py`

Personalized PageRank. Damping `d = 0.85`:

```
rank ← d·Mᵀ·rank  +  [(1−d) + d·dangling]·p
```

What makes it correct here is not PageRank, it is **where it teleports**. Classic PageRank
jumps to any node — it models someone who can start browsing on any page. A program cannot: it
**always starts at an entry point**. The personalization vector `p` is uniform over the declared
**product roots**, which is what turns generic centrality into "how much this is used when the
system runs".

Two details that matter:

- **Dangling nodes** (no outgoing edges) return their mass through `p`, back to the roots — not
  uniformly. Uniform redistribution is the correct handling for the unpersonalized version and
  the wrong one here.
- **Self-loops are dropped.** A module calling itself is normal and would only inflate itself.

It gives two properties a reference count does not have: transitivity — a helper called once
from the heart of the system outweighs one called twenty times from a cold corner — and mass
distribution across ambiguity.

**It does not predict execution.** Measured against a probe census: AUC **0.506**, where 0.50 is
predicting nothing, and the deciles are not even monotonic. Mass orders by structural
centrality, which is exactly what it says and nothing more.

---

## 2 · Convergence to attractors → modules

> `--k`, `--modules`, `--hierarchy`, `--islands` · `views/communities.py`

Markov Clustering. Two operations alternating on the same matrix:

```
expansion    M ← M·M      the walker takes two steps: flow follows the paths
inflation    M ← M^r      differences are exaggerated: strong paths reinforce,
                          weak ones evaporate
```

Iterating, flow concentrates in densely connected regions and is cut between them. Each column's
`argmax` is its attractor, and the attractors are the groups.

**`r` is the granularity knob, and that is why sub-modules come free.** A low `r` gives a few
coarse lines of work; a high one splits them into sub-lines. No second algorithm for a second
level — the same one, more inflated.

Practical notes from the implementation: the matrix is **sparse** (2.76% density on a real core;
dense would be 36× the memory and unworkable at 40k symbols), it is **symmetrized** because
grouping cares about relatedness and not direction, self-loops are set to the row max to
stabilize, and each pass is pruned — without pruning, expansion densifies the matrix and the
advantage disappears.

**Hubs are removed first** (top 1% by degree). Common infrastructure touches everything and
glues the modules into one block: without that, a single group took 1,169 symbols and 79.6% of
the mass. Removing connectors is standard practice in community detection — they belong to no
module because they belong to all of them.

### Newman modularity

```
Q = Σ_c [ e_c/2m − (k_c/2m)² ]
```

Internal density minus what chance predicts. Used for two different things: scoring a *declared*
partition, and finding the graph's natural `k` by sweeping inflation.

**Both partitions must be scored on the same graph**, and once they were not: the matrix came
from the full product core while the groups came from the hub-stripped clustering. The hubs
stayed inside the declared partition and outside every discovered community, so their degree
term penalized the discovered one for free. On one frontend those 13 nodes held 16.7% of the
graph's total degree, and the headline "you capture X% of reachable modularity" was inflated in
three repositories. Two partitions scored on different graphs measure nothing.

**Known limit** (Fortunato–Barthélemy): maximizing Q tends to *merge* small communities, and the
optimum depends on graph size. The `k` that comes out is an order of magnitude, not a number.
That is also why `--hierarchy` recurses — running the same chain *inside* each module makes the
subgraph small enough that its internal structure becomes visible.

And why cohesion, not internal Q, decides splitting: against the global 0.3 threshold, internal
Q said "split" on **20 of 20** modules. In a sparsely connected subgraph Q comes out high by
construction.

---

## 3 · Absorbing chain → the weight of a route

> `--decisions` · `graph/markov.py`

Expected visits before absorption — classically the fundamental matrix **N = (I − Q)⁻¹**.
Computed by iterating the front instead of inverting:

```
visits[j] += Σ_i front[i] · P(i→j) · d
```

Same result, and — the deciding factor — **no numpy**, so the main path keeps running on the
bare stdlib. Inverting would force a dependency onto it.

The damping factor is not cosmetic: a call graph has cycles, and without it the count diverges.

This is not the same quantity as mass. Mass is centrality across the whole repository; expected
visits are how much of *this route's* flow crosses the node. A symbol can be the heart of the
system and take no part in the turn.

### What the transition matrix must not contain

**A seam is not a transition.** It means "this name is mentioned here", and the weight it
carries was assigned, not counted. Fed into the matrix it becomes flow with a probability, and
that manufactured a concrete false finding: a function appeared to decide 50/50 between two
tools. It decides nothing — both names sit there as string literals inside a comparison, and the
real choice is made by an LLM that no static analysis sees. Two seams of equal weight give 50/50
*by construction*; the number was the shape of the artifact.

### The split is not a branch probability

`weights` normalized per row gives the **share of references**, and it has the shape of a
probability without being one. The AST cannot tell a call inside an `if` from the one on the
next line, so two consecutive calls come out 50/50 **and both execute**.

What *can* be proven is a fork: calls in **different branches of the same conditional**, which
`core` records as `file:line → cond#branch`. Only `If`, `Try` and `Match` count — a `for` body
is repetition, not an alternative, and counting it would say the system chooses where it
iterates.

Measured over a 102-symbol route: the reference split flagged 12 "decisions"; the proven forks
were **one**. Not a defect of the view — in a system where an LLM or the data makes the choice,
there are almost no choices in the code. A rich decision tree drawn from the AST would have been
pretty and false.

---

## Information theory: exactly one place

> `--views` · `views/views.py`

Normalized mutual information between the discovered partition and the declared one:

```
NMI = 2·I(X;Y) / (H(X) + H(Y))
```

It is here because **purity cannot compare views**: it grows with `k` by construction — in the
limit, single-symbol groups give purity 1.0 — and the views produce very different `k`. NMI
penalizes fragmentation, so it is comparable.

### "Entropy" is a metaphor

The tool calls itself an entropy census and there is **no Shannon entropy in the measurement** —
no `log2` outside the NMI above. What the word points at is operationalized as things you can
count and delete:

| stands for "entropy" | what it is |
|---|---|
| `ALIVE_PRODUCT_WEAK` | alive only through a homonym |
| `ALIVE_NOT_PRODUCT` | reachable, but never from a product root |
| cold symbols | referenced, mass ~0 |
| Type-1/2/3 duplication | the same shape repeated |

That is a defensible operationalization — those are the things that accumulate and can be
removed. But the name promises a measure the code does not compute, so it is worth saying rather
than letting someone go looking for it.

---

## Reachability, and grades of evidence

> the census, and everything downstream · `extraction/core.py`

Liveness is not a boolean. Collapsing it overestimated liveness by a factor of eight on the
first project measured. The chain is **fail-open**: when in doubt, alive. A false "dead" deletes
working code; a false "alive" costs a review.

The same principle applies to the graph itself. **Paths and locks run on unambiguous edges
only** — a path is a stronger claim than a reference and needs stronger evidence. On the
reference project the complete graph has 124,531 edges against 8,058 unambiguous ones, and with
the former everything reaches everything: a first attempt reported 351 of 402 roots "reaching"
one subsystem, listing `client` and `get` from test files as what the flow crosses.

### Lexical scope is part of the measurement

A local variable whose name matches a unique function elsewhere fabricates an edge — and
fabricates it with the *strongest* evidence available, because `strong_edges` means "only one
symbol has this name", not "this is a real call". Measured before the fix: **502 of 8,001 strong
edges (6.3%)**, and one subsystem's flow reported 166 roots where there are 20.

Four of the five scope rules are "do **not** suppress", because over-suppressing deletes real
edges and kills live symbols by cascade — counting a nested `def`'s own name as a shadow killed
38 symbols at once. It has a lock with fixtures in both languages (`selfcheck/check_reach.py`).

---

## Duplication: bottom-k MinHash

> the census and the pre-write gate · `graph/index.py`, `views/duplicates.py`

Storing the complete n-gram set of thousands of functions would make the cache enormous. With
the `k` smallest fingerprints, Jaccard is estimated without storing the sets:

```
Ĵ(A,B) = |bottom_k(A ∪ B) ∩ A ∩ B| / |bottom_k(A ∪ B)|
```

Type-1/2 clones come from an exact hash of the *anonymized* skeleton (identifiers, attributes
and literals erased); Type-3 from the n-gram estimate above. Type-4 — same responsibility,
divergent code — is invisible by definition: if the code diverges so does the skeleton.

**The unit is not the function.** Comparing only function bodies leaves the tool blind to the
duplication nobody has extracted yet, which is the worst kind: one subsystem had the same
error-translation pattern in 9 units and the detector saw 2 — exactly the 2 somebody had already
pulled out. So fingerprints include **nested blocks**: the body of an `if`, an `except`, a `for`
— control constructs the author already delimited. Arbitrary statement windows would produce
O(N²) candidates per function, almost none of them extractable.

The block threshold was measured, not chosen — recall over a known 7-instance pattern:

| `min_statements_block` | recall | fingerprints | Type-3 pairs | cost |
|---|---|---|---|---|
| 5 | — | 405 | 39 | 11 s |
| 4 | 3/7 | 657 | 63 | 15 s |
| **3** (default) | **6/7** | 1,100 | 109 | 20 s |
| 2 | — | 2,368 | 388 | 34 s |

At 2 it fires without buying anything: 388 pairs is more than anyone reads.

---

## Connection locks: removal, not domination

> `--locks`, `--propose` · `graph/contracts.py`

Not a Markov question. One primitive:

> Remove the nodes that guarantee the connection and ask whether the sink is still reachable.
> If it is, that path **is** the bypass.

Exact and linear — it does not sample paths or compare against a threshold. That matters because
the previous attempt did (one path per root, "guard" if it appeared in 30% of a sample), and a
root reachable by two paths, one protected and one not, came out GREEN. False green is the
failure that cannot be tolerated: a lock that lies is worse than no lock, because it is believed.

The three contracts are the same function changing what gets removed:

| contract | removes |
|---|---|
| `crosses G` | `{G}` |
| `requires G` | `{n : n→G} ∪ {G}` |
| `cannot_reach` | nothing |

**`requires` is not `crosses` renamed**, and the difference was paid for by measuring. A guard is
not on the path: it is called *before*, as a precondition with an early return, so in the graph
it is a **sibling** — `GET → requireAuth` and `GET → createClient` are two edges of the same
node, neither on the other's path. Looking for a vertex cut produced **64 false bypasses** on a
frontend whose routes were protected.

Verdicts come in two grades, for the same reason the census does: the unambiguous graph decides,
and a bypass that only appears once ambiguous edges are admitted is reported as `SUSPECT`
without breaking anything.

---

## Layout: the map is computed, not drawn

> `--atlas` · `views/atlas.py`

The renderer draws and decides nothing — layers and columns arrive resolved, so the same
repository yields the same map, a diff of the map means something, and `--json` hands over
exactly what is on screen. A layout decided in the browser is irreproducible by construction.

**Coffman–Graham layering** with bounded width. Longest-path layering gave 18 layers for 36
modules — one node per layer, a column, which is the visual form of not showing a distribution.
Bounding the width preserves the only thing the axis asserts (if A uses B, A sits higher) and
fills sideways.

**Barycenter ordering** within each layer: place each node near the average position of its
neighbors in the adjacent layer, a few passes. Without it, edges cross everywhere and the
drawing is unreadable even when the data is right. Optimal ordering is NP-hard and unnecessary
here.

**Basic-block condensation** collapses linear chains, with four cuts: a proven fork, a confluence
(in-degree ≠ 1 — mandatory, or two stories merge into one that never happened), a seam, and a
lane change. The fourth is what separates a correct condensation from a useful one: with only the
first two, a 102-node route collapses to two or three — impeccable and unreadable.

---

## What is not here

`views/guards.py` implements a lexical classifier for guard-like names. It has no CLI flag and
nothing imports it; the method it encodes is documented in the `mcview-repo` skill, and the
findings attributed to it were reached by asking its questions by hand.

`graph/paths.py::analyze` — the structural security pass over declared sinks — has no callers
either, and it still runs over the complete graph, so its guards and bypasses would carry the
inflation described above. If it is ever wired in, it needs the restricted view.
