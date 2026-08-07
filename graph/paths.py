# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""STRUCTURAL LEVEL 2 — a guard is not a name: it is a SEPARATOR.

The first version of level 2 classified guards with regular expressions over the name. It
worked as a candidate generator and computed nothing: the one doing the reasoning was the
agent. This replaces it with a graph question, with evidence and without guessing:

    If a ROOT → SINK path exists that crosses no guard,
    that path IS the finding — and it comes with its own proof: the path.

THREE CONSEQUENCES OF THINKING ABOUT IT THIS WAY
-----------------------------------
1. Guards are DISCOVERED, not declared. A node that 95% of root→sink paths go through **is**
   a guard, structurally. The name becomes corroboration.
2. The only thing that has to be declared are the SINKS — a short, stable list the owner
   knows (the client that bypasses RLS, `subprocess`, `eval`). Declaring sinks is far more
   robust than guessing guards: there are few of them and they do not change.
3. The answer is not a boolean but a FRACTION: what proportion of paths to the sink cross the
   guard. 1.0 = chokepoint. 0.7 = 30% dodge it, and there are the 30.

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


def _index_by_name(project) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for sid, s in project.symbols.items():
        out[s.name].append(sid)
    return out


def resolve_sinks(project, names: list[str]) -> set[str]:
    """Declared names → symbol ids. A name that does not resolve is silently ignored because it
    may come from an external dependency (`subprocess.run` is not a project symbol); the one
    that matters is the one that resolves."""
    idx = _index_by_name(project)
    out: set[str] = set()
    for n in names:
        out.update(idx.get(n.split(".")[-1], []))
    return out


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


def bypasses(paths: list[list[str]], guards: set[str], project) -> list[dict]:
    """Paths that reach the sink without ANYONE on the path calling a guard.

    It is the finding, and its own evidence. Unlike a name match, here the path can be pasted
    into the report and the reader verifies it by reading three functions.
    """
    out = []
    sinks = {c[-1] for c in paths}
    for c in paths:
        neighbors: set[str] = set()
        for n in c[:-1]:
            neighbors |= project.edges.get(n, set())
        if not ((neighbors | set(c[1:-1])) & guards):
            out.append({
                "root": project.symbols[c[0]].name,
                "loc": project.symbols[c[0]].loc,
                "path": [project.symbols[n].name for n in c],
                "saltos": len(c) - 1,
            })
    return sorted(out, key=lambda x: x["saltos"])


def analyze(project, declared_sinks: list[str], guard_threshold: float = 0.30) -> dict:
    """The complete structural level 2, for a set of sinks.

    IT RUNS OVER THE UNAMBIGUOUS EDGES, not over the complete graph. A path is a stronger
    claim than a reference and needs stronger evidence: over CIRE there are 120,123 edges
    against 7,502 unambiguous ones, and with the former everything reaches everything. Here
    that hurts twice as much as in the rest of the tool, because a false bypass is not an
    imprecise datum: it is an accusation of a security hole, and it sends somebody to audit
    code that is in fact protected. See `flow._UnambiguousOnly`.
    """
    from flow import _UnambiguousOnly
    from heatmap import _is_product

    project = _UnambiguousOnly(project)
    sinks = resolve_sinks(project, declared_sinks)
    if not sinks:
        return {"error": f"no sink resolved: {declared_sinks}"}
    roots = {s for s in project.product_roots
              if _is_product(project, project.symbols[s].file)}
    paths = paths_to(project, sinks, roots)
    discovered = discovered_guards(paths, project, guard_threshold)
    ids_guard = {g["id"] for g in discovered}
    return {
        "sinks": sorted(project.symbols[s].loc for s in sinks),
        "raices_que_llegan": len(paths),
        "discovered_guards": discovered,
        "bypasses": bypasses(paths, ids_guard, project),
    }
