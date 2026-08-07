"""The declared contracts: running them, and proposing which ones to declare.

`graph/contracts.py` knows how to decide ONE contract. What lives here are the two things
that make it usable: reading the ones written in the `.toml` and running them all, and
—so that declaring your first one does not require knowing the whole subsystem— proposing
candidates.

THE PROPOSAL IS HEURISTIC AND THE VERDICT IS NOT. They are two different qualities of
claim, and mixing them is what kept the previous version from ever being a lock: it
discovered guards by frequency over a sample of paths and then ruled on that same basis.
Here the mass ranking orders a list for you to look at; what becomes a lock is what you
write, and that is verified exactly.
"""
from __future__ import annotations

from collections import defaultdict

import contracts as _contracts
import orient as _orient

KINDS = ("requires", "crosses", "cannot_reach")


def _resolve(project, target: str) -> tuple[set[str], str | None]:
    """Declared target → symbols. Reuses the `--orient` resolver, which already accepts a
    module, a path or a symbol name — the seam between parts of a system is made of routes
    and tables as much as of functions."""
    d = _orient.resolve(project, target)
    if "error" in d:
        return set(), d["error"]
    # `resolve` returns FILES, not symbols — a target is an area, and membership is decided
    # per file in all four cases resolve knows about (module, path, symbol, seam). Reading
    # it as if it returned symbols gave the empty set, and the empty set does not fail: it
    # exits through "no connection to lock", which reads exactly like a finding.
    # `by_file` holds Symbol objects, not their ids; the id is the dict key.
    # A surface may name the exact symbols that are its doors. Widening those back out to
    # their whole files would undo the only thing that made the declaration worth writing.
    if d.get("symbol_ids"):
        return set(d["symbol_ids"]), None
    wanted = set(d.get("files", ()))
    ids = {sid for sid, s in project.symbols.items() if s.file in wanted}
    if not ids:
        return set(), f"«{target}» resolved to {d.get('class', '?')} with no symbols"
    return ids, None


def read_rows(cfg) -> list[dict]:
    """The `[[locks]]` from the `.toml`, normalized. A contract with no kind, or with two,
    is a declaration error and is reported as such: failing here is cheap, and a malformed
    contract that gets skipped silently is a green nobody asked for."""
    out = []
    for i, c in enumerate(getattr(cfg, "locks", ()) or ()):
        kinds = [t for t in KINDS if t in c]
        d = {"name": c.get("name", f"lock {i + 1}"),
             "src": c.get("src"), "dst": c.get("dst")}
        if len(kinds) != 1:
            d["error"] = (f"must declare exactly one of {', '.join(KINDS)}; "
                          f"it has {len(kinds)}")
        elif not d["src"] or not d["dst"]:
            d["error"] = "missing `src` and/or `dst`"
        else:
            d["kind"] = kinds[0]
            d["guarantee"] = None if kinds[0] == "cannot_reach" else c[kinds[0]]
        out.append(d)
    return out


def verify(project, cfg) -> dict:
    declared = read_rows(cfg)
    results = []
    for d in declared:
        if "error" in d:
            results.append({**d, "verdict": _contracts.EMPTY, "why": d["error"]})
            continue
        src, e1 = _resolve(project, d["src"])
        dst, e2 = _resolve(project, d["dst"])
        guarantee, e3 = ((set(), None) if d["guarantee"] is None
                         else _resolve(project, d["guarantee"]))
        if e1 or e2 or e3:
            results.append({**d, "verdict": _contracts.EMPTY,
                            "why": e1 or e2 or e3})
            continue
        r = _contracts.verify(project, src, dst, d["kind"], guarantee)
        if r.get("path"):
            r["path"] = [project.symbols[n].loc for n in r["path"]]
        results.append({**d, **r})

    count: dict[str, int] = defaultdict(int)
    for r in results:
        count[r["verdict"]] += 1
    return {"project": cfg.name, "locks": results, "count": dict(count)}


def propose(project, rank: dict[str, float], src: str, dst: str,
            top: int = 10) -> dict:
    """What is worth locking on the `src`→`dst` path, ordered by mass.

    A `crosses` candidate is a node that interposes TODAY: remove it and the path
    disconnects. A `requires` candidate is a node that everyone who arrives calls today:
    remove its callers and the path disconnects. Both are tested by removal, which is the
    same primitive the verdict uses — so what gets proposed is exactly what later gets
    verified, and not a lookalike approximation that stops matching one day.
    """
    origin, e1 = _resolve(project, src)
    sink, e2 = _resolve(project, dst)
    if e1 or e2:
        return {"error": e1 or e2}
    if _contracts.reaches(project.strong_edges, origin, sink) is None:
        return {"error": f"there is no unambiguous path from «{src}» to «{dst}» — "
                         f"there is no connection to lock"}

    # Only nodes that sit on some path are candidates: the rest can neither interpose nor
    # be a precondition, and testing them would be spending on impossibilities.
    forward = _reachable(project.strong_edges, origin)
    backward = _reachable(_invert(project.strong_edges), sink)
    middle = (forward & backward) - origin - sink

    out = []
    for sid in sorted(middle, key=lambda s: -rank.get(s, 0.0))[:top * 12]:
        for kind in ("crosses", "requires"):
            if _contracts.evaluate(project.strong_edges, origin, sink,
                                   kind, {sid}) is None:
                out.append({"kind": kind, "guarantee": project.symbols[sid].name,
                            "loc": project.symbols[sid].loc,
                            "mass_pct": round(rank.get(sid, 0.0) * 100, 3)})
                break
    out = out[:top]
    if not out:
        # An empty list reads as "the tool found nothing", and here it means the opposite:
        # it found that THERE IS NOTHING INTERPOSED. Measured on CIRE — from
        # `api/v1/routers/documents.py` to `store/supabase/client.py` there are 3 nodes on
        # the path and none of them cuts it, because the router calls the client directly.
        # That is precisely "this connection has no lock", and returning a blank lost it.
        direct = _contracts.reaches(project.strong_edges, origin, sink)
        return {"src": src, "dst": dst, "candidates": [], "toml": "",
                "no_candidates": (
                    "no node interposes today: the origin reaches the sink without any "
                    "mandatory step to lock. It is not that the measurement is missing — "
                    "there is no chokepoint. To have one, it has to be built."),
                "direct_path": [project.symbols[n].loc for n in (direct or [])]}
    return {"src": src, "dst": dst, "candidates": out,
            "toml": "\n".join(_toml(src, dst, c) for c in out)}


def _toml(src: str, dst: str, c: dict) -> str:
    return (f'[[locks]]\n'
            f'name = "{src} → {dst} {c["kind"]} {c["guarantee"]}"\n'
            f'src  = "{src}"\ndst  = "{dst}"\n'
            f'{c["kind"]:12s} = "{c["guarantee"]}"\n')


def _invert(edges: dict[str, set[str]]) -> dict[str, set[str]]:
    inv: dict[str, set[str]] = defaultdict(set)
    for o, ds in edges.items():
        for d in ds:
            inv[d].add(o)
    return inv


def _reachable(edges: dict[str, set[str]], src: set[str]) -> set[str]:
    seen, stack = set(src), list(src)
    while stack:
        for nxt in edges.get(stack.pop(), ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen
