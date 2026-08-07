"""A ROUTE: everything a message can traverse between two points.

It does not enumerate paths. They are exponential, and a list of the first twelve is not an
answer: it is a sample that reads as if it were everything — the same mistake that kept the
guard detector from ever being a lock.

What it returns is the DAG that CONTAINS them:

    alcanzables_desde(A)  ∩  alcanzan_a(B)

Exact and linear. Every symbol in there lies on some path from A to B, and nothing left out
does. Over that subgraph, three things the tool already knows how to compute start meaning
something precise, because the origin is ONE:

    depth         hops from A — here it really is the axis, unlike in the global map
    chokepoints   the nodes whose removal disconnects: what EVERYTHING goes through
    branches      where the route opens up

The way there and the way back. "Until the user receives the answer" travels back up the
`return` of the same stack, not over new edges: the route is A→B and the return trip is those
same edges reversed. A real return path —a webhook, a callback— would show up as its own seam
and would be a different route.
"""
from __future__ import annotations

import contracts as _contracts
import weave as _weave


def _reachable(edges: dict[str, set[str]], src: set[str]) -> set[str]:
    seen, stack = set(src), list(src)
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _invert(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    inv: dict[str, set[str]] = {}
    for o, ds in edges.items():
        for d in ds:
            inv.setdefault(d, set()).add(o)
    return inv


def trace(weave, src: str, dst: str) -> dict:
    origin, e1 = weave.resolve(src)
    sink, e2 = weave.resolve(dst)
    if e1 or e2:
        return {"error": e1 or e2}

    edges = weave.strong_edges
    if _contracts.reaches(edges, origin, sink) is None:
        return {"error": f"there is no unambiguous path from «{src}» to «{dst}». "
                         f"If there has to be one, the junction is probably a seam that is "
                         f"not declared in the `.toml` of the project that uses it."}

    forward = _reachable(edges, origin)
    backward = _reachable(_invert(edges), sink)
    inside = forward & backward

    # EXACT chokepoints: tested by removal, the same primitive the lock uses. Not "appears in
    # 45% of a path sample" — it is "without this you do not get there".
    middle = inside - origin - sink
    chokes = [s for s in middle
              if _contracts.reaches(edges, origin, sink, without=frozenset({s})) is None]

    seams = [c for c in weave.applied_seams
                if c["from"] in inside and c["to"] in inside]
    return {
        "src": src, "dst": dst,
        "inside": inside, "origin": origin, "sink": sink,
        "symbols": len(inside),
        "projects": sorted({s.split(_weave.SEP)[0] for s in inside}),
        "chokepoints": sorted(chokes, key=lambda s: weave.symbols[s].loc),
        "seams": seams,
        "shortest_path": _contracts.reaches(edges, origin, sink),
    }


def report(weave, r: dict) -> str:
    if "error" in r:
        return f"\n  {r['error']}\n"
    f = [f"\n  ROUTE — {r['src']}  →  {r['dst']}\n",
         f"  {r['symbols']} symbols on some path · "
         f"{len(r['projects'])} projects ({', '.join(r['projects'])}) · "
         f"{len(r['seams'])} seams crossed\n"]
    if r["chokepoints"]:
        f.append(f"  ── EVERYTHING GOES THROUGH HERE ── {len(r['chokepoints'])} nodes: without "
                 f"them you do not get there ──")
        for s in r["chokepoints"][:12]:
            f.append(f"     {weave.symbols[s].name:34s} {weave.symbols[s].loc}")
    else:
        f.append("  ── no chokepoints: there is no single mandatory step, so today there is "
                 "nowhere to put an interposition lock ──")
    if r["seams"]:
        f.append(f"\n  ── CROSSES REPOSITORY ── through a string, not through a call ──")
        for c in r["seams"][:8]:
            f.append(f"     {c['kind']:5s} {c['literal']:40s} "
                     f"{weave.symbols[c['from']].loc} → {weave.symbols[c['to']].loc}")
    f.append(f"\n  ── ONE CONCRETE PATH ── to verify by reading ──")
    for s in (r["shortest_path"] or [])[:14]:
        f.append(f"     {weave.symbols[s].loc}")
    return "\n".join(f) + "\n"
