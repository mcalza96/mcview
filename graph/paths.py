# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""STRUCTURAL LEVEL 2 — a guard is not a name: it is a SEPARATOR.

The first version of level 2 classified guards with regular expressions over the name. It
worked as a candidate generator and computed nothing: the one doing the reasoning was the
agent. This replaces it with a graph question, with evidence and without guessing:

    A node that 95% of root→sink paths go through **is** a guard, structurally.
    The name becomes corroboration.

TWO CONSEQUENCES OF THINKING ABOUT IT THIS WAY
-----------------------------------
1. Guards are DISCOVERED, not declared.
2. The answer is not a boolean but a FRACTION: what proportion of paths to the sink cross the
   guard. 1.0 = chokepoint. 0.7 = 30% dodge it, and there are the 30.

RETIRED 2026-08-08: the declared-sinks + bypass-report machinery (`resolve_sinks`,
`bypasses`) never got a consumer — every view asks `paths_to` + `discovered_guards`
directly, and `graph/contracts.py` is where reach-guarantees with a consumer live.
Contract without consumer → deleted, not kept "just in case".

WHY THE GRAPH IS `mcview`'S AND NOT codegraph'S
-------------------------------------------------------
Measured before choosing, which is what avoids building on sand:

    TypeScript   mcview 2.962 edges · codegraph 660  → codegraph pierde el 81 %
    Python       mcview 13.221        · codegraph 5.970 → pierde el 56 %

A PATH analysis over a graph missing 8 out of every 10 edges produces false bypasses in bulk
— the worst possible outcome here, because a false bypass is an accusation of a security
hole. codegraph is still better for NAVIGATING (it resolves dynamic-dispatch hops the AST
does not see); for counting paths, it is not.

WHAT THIS DOES NOT SEE, AND IT HAS TO BE SAID
-------------------------------------
The tenant filter —`.eq('tenant_id', …)`— **is not an edge**: it is an argument in a method
chain. This module finds "reaches the sink without crossing a guard"; it does NOT find
"arrives with the guard but without filtering". That kind needs AST over the call site, not a
graph. Of the four measured cross-tenant leaks, this would have found the ones with no guard,
not the ones that had it and forgot the `.eq`.
"""
from __future__ import annotations

from collections import defaultdict, deque


def _incoming(project) -> dict[str, set[str]]:
    inv: dict[str, set[str]] = defaultdict(set)
    for o, ds in project.edges.items():
        for d in ds:
            inv[d].add(o)
    return inv


def paths_to(project, sinks: set[str], roots: set[str], top: int = 12) -> list[list[str]]:
    """One ROOT→SINK path per root that reaches it, walking backwards from the sink.

    ONE path per root is returned, not all of them: the number of paths grows exponentially
    and to decide "does this root arrive without crossing a guard?" one is enough. The
    backwards BFS gives the SHORTEST, which is also the easiest to read as evidence.
    """
    # SORTED at both ends, and this is the chokepoint of a whole class of variance. This BFS
    # records the FIRST path that reaches each node, so the order in which it starts and
    # expands decides WHICH path survives. `sinks` and the values of `inv` are sets, whose
    # iteration order depends on the process's string hashing — so the same command produced
    # different paths, and with them different guard fractions: `get_async_supabase_client`
    # came out at 67% under one seed and 72% under another. A number that moves with the hash
    # seed is not a measurement.
    #
    # It is fixed HERE and not in the twelve views that consume it: `--orient`, `--flow`, both
    # mermaid outputs and the HTML page all read these paths, and `golden.py --seeds` reported
    # all twelve as seed-dependent.
    inv = _incoming(project)
    seen: dict[str, list[str]] = {s: [s] for s in sorted(sinks)}
    queue = deque(sorted(sinks))
    paths: list[list[str]] = []
    raices_halladas: set[str] = set()
    while queue:
        n = queue.popleft()
        if len(seen[n]) > top:
            continue
        for prev in sorted(inv.get(n, ())):
            if prev in seen:
                continue
            seen[prev] = [prev] + seen[n]
            if prev in roots and prev not in raices_halladas:
                raices_halladas.add(prev)
                paths.append(seen[prev])
            queue.append(prev)
    return paths


def discovered_guards(paths: list[list[str]], project,
                        threshold: float = 0.30) -> list[dict]:
    """Nodes that the paths to the sink CALL besides the sink.

    ⚠️ A DESIGN CORRECTION, found while validating: a guard is NOT *on* the path. It is called
    BEFORE, as a precondition with an early return, so in the graph it is a SIBLING —
    `GET → requireAuth` and `GET → createCireClient` are two edges of the SAME node, and
    neither is on the other's path.

    The first version looked for a vertex cut (does the guard separate root from sink?) and
    produced 64 "bypasses" over a frontend where most of those routes DO have a guard. The
    correct formulation is not "is it on the path?" but **"did somebody on the
    path?"**.

    The sink is EXCLUDED: everyone calls it by construction.
    """
    if not paths:
        return []
    count: dict[str, int] = defaultdict(int)
    sinks = {c[-1] for c in paths}
    for c in paths:
        neighbors: set[str] = set()
        for n in c[:-1]:
            neighbors |= project.edges.get(n, set())
        for v in neighbors - sinks - set(c):
            count[v] += 1
    total = len(paths)
    out = [{"id": n, "name": project.symbols[n].name,
              "loc": project.symbols[n].loc,
              "fraccion": v / total, "en": v, "from": total}
             for n, v in count.items() if v / total >= threshold]
    return sorted(out, key=lambda x: -x["fraccion"])
