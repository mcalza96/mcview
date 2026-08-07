"""A lock on a CONNECTION, not on a component.

A component is protected by a test: you call it and look at what it returns. A
connection is not — "every request crosses the tenant resolver before touching the
database" is not a call, it is a property of EVERY path, and there is no way to write it
as an assertion about a function.

One single primitive makes it verifiable:

    REMOVE THE NODES THAT GUARANTEE THE CONNECTION AND ASK WHETHER THE SINK IS STILL
    REACHABLE. If it is, that path IS the bypass.

Exact and linear: it does not sample paths or compare against a threshold. That matters
because the previous attempt did —one path per root, "guard" if it showed up in 30% of
the sample— and with that, a root reachable by two paths, one protected and one not, came
out GREEN. False green is the failure mode that cannot be tolerated here: a lock that
lies is worse than no lock, because people believe it.

The three contracts are the SAME function changing what gets removed:

    crosses G      interposition   remove {G}                  does the data always go through it?
    requires G     precondition    remove {n : n→G} ∪ {G}      did someone on the path call it first?
    cannot_reach   isolation       remove nothing              is there a path at all?

`requires` is not `crosses` under another name, and the difference was paid for by
measuring. A guard is NOT on the path: it is called BEFORE, as a precondition with an
early return, so in the graph it is a SIBLING — `GET → requireAuth` and
`GET → createCireClient` are two edges of the SAME node, and neither is on the other's
path. Treating a guard as an interposition means looking for a vertex cut, and that
produced 64 false bypasses on a frontend whose routes WERE protected. Hence `requires`
removes G's CALLERS, not G.

TWO GRADES OF EVIDENCE, for the same reason the census distinguishes `ALIVE_PRODUCT` from
`ALIVE_PRODUCT_WEAK`. The verdict is decided on the UNAMBIGUOUS graph, where a path is a
path; bypasses that only appear once ambiguous edges are admitted are reported as SUSPECT
and break nothing. A path on the complete graph is not evidence: there it is 124,531 edges
against 8,058, and everything reaches everything.
"""
from __future__ import annotations

from collections import deque

PASS = "PASS"
BROKEN = "BROKEN"
SUSPECT = "SUSPECT"
EMPTY = "EMPTY"


def callers_of(edges: dict[str, set[str]], target: set[str]) -> set[str]:
    """Who has an edge into the target. This is the SIBLING relation: the guard is not on
    the path, it is called by someone who is."""
    return {o for o, ds in edges.items() if ds & target}


def reaches(edges: dict[str, set[str]], src: set[str], dst: set[str],
            without: frozenset[str] = frozenset()) -> list[str] | None:
    """The shortest `src`→`dst` path avoiding `without`, or None if there is none.

    It returns the path rather than a boolean on purpose: the finding of a broken lock IS
    the bypass, and its own evidence. A `False` sends someone off to search; a path of
    four names is verified by reading four functions.
    """
    origin = {d for d in src if d not in without}
    sink = {h for h in dst if h not in without}
    if not origin or not sink:
        return None
    prev: dict[str, str | None] = {d: None for d in origin}
    queue = deque(origin)
    while queue:
        n = queue.popleft()
        if n in sink:
            path = [n]
            while prev[path[-1]] is not None:
                path.append(prev[path[-1]])
            return path[::-1]
        for nxt in edges.get(n, ()):
            if nxt in prev or nxt in without:
                continue
            prev[nxt] = n
            queue.append(nxt)
    return None


def evaluate(edges: dict[str, set[str]], src: set[str], dst: set[str],
             kind: str, guarantee: set[str]) -> list[str] | None:
    """One contract over one graph. Returns the path that VIOLATES it, or None if it holds.

    All the asymmetry between the three kinds lives in `remove`; the rest is a single
    reachability question. That is why they are one contract and not three.
    """
    if kind == "cannot_reach":
        return reaches(edges, src, dst)
    if kind == "crosses":
        remove = set(guarantee)
    elif kind == "requires":
        # Removing G as well keeps a path from "passing through" the guard and counting as
        # protected without ever having called it as a precondition.
        remove = callers_of(edges, guarantee) | set(guarantee)
    else:
        raise ValueError(f"unknown contract kind: {kind}")
    return reaches(edges, src, dst, without=frozenset(remove))


def verify(project, src: set[str], dst: set[str], kind: str,
           guarantee: set[str]) -> dict:
    """The contract at both grades of evidence.

    It is evaluated first on the strong graph, which is the one that DECIDES. If it passes
    there, it is re-evaluated on the complete graph: a bypass that only shows up once
    ambiguous edges are admitted breaks nothing, but it is not swallowed either — it is
    where a hole the strong graph cannot see would be, and swallowing it would be false
    green from the other direction.
    """
    if not dst:
        return {"verdict": EMPTY,
                "why": "the sink did not resolve to any symbol in the project"}
    if kind != "cannot_reach" and not guarantee:
        return {"verdict": EMPTY,
                "why": "the guarantee did not resolve to any symbol in the project"}

    # A contract whose guarantee SWALLOWS the sink always passes and says nothing: once it
    # is removed there is no sink left to look for. `crosses submit_document` over the sink
    # `submit_document` returned PASS with zero evidence — an empty lock that reads like
    # protection. It is the same class of false green that motivates this whole file, so it
    # is rejected rather than reported.
    if kind == "crosses" and dst <= set(guarantee):
        return {"verdict": EMPTY,
                "why": "the guarantee contains the sink: the contract would always pass "
                       "without verifying anything. Declare the step BEFORE the sink."}

    violation = evaluate(project.strong_edges, src, dst, kind, guarantee)
    if violation is not None:
        return {"verdict": BROKEN, "path": violation, "evidence": "unambiguous"}

    suspect = evaluate(project.edges, src, dst, kind, guarantee)
    if suspect is not None:
        return {"verdict": SUSPECT, "path": suspect, "evidence": "ambiguous",
                "why": "only exists if ambiguous-name edges are admitted — it does not "
                       "break the contract, but it is where a hole the strong graph "
                       "cannot see would be"}
    return {"verdict": PASS, "evidence": "unambiguous"}
