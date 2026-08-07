#!/usr/bin/env python3
"""Lock over the contract primitive, on graphs where the answer is known.

It is validated against synthetic graphs and not against the repo for one reason: over the
real project there is nothing to compare the verdict with —if it says BROKEN, is that right?—
and a lock that cannot fail tests nothing. Here every case carries the answer written next to
it, and the ones that matter are those the PREVIOUS formulation answered wrong.

    python3 mcview/locks/check_contracts.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import contracts  # noqa: E402


class _Graph:
    """The minimum `verify` consumes. Both graphs are identical except where a case
    quiera distinguir evidencia strong de ambigua."""

    def __init__(self, fuertes, todas=None):
        self.strong_edges = {k: set(v) for k, v in fuertes.items()}
        self.edges = {k: set(v) for k, v in (todas or fuertes).items()}


# (name, grafo, src, dst, kind, guarantee, verdict esperado)
CASOS = [
    # --- interposition -------------------------------------------------------------
    ("crosses: the only path goes through the chokepoint",
     _Graph({"R": ["A"], "A": ["CHOKE"], "CHOKE": ["S"]}),
     {"R"}, {"S"}, "crosses", {"CHOKE"}, contracts.PASS),

    ("crosses: there is a shortcut around it",
     _Graph({"R": ["A", "B"], "A": ["CHOKE"], "CHOKE": ["S"], "B": ["S"]}),
     {"R"}, {"S"}, "crosses", {"CHOKE"}, contracts.BROKEN),

    # THE CASE THAT BROKE SAMPLING: the root arrives by two paths, the SHORT one is
    # protected and the long one is not. One path per root —the shortest— returned PASS.
    ("crosses: the short path crosses, the long one does not",
     _Graph({"R": ["A", "X"], "A": ["CHOKE"], "CHOKE": ["S"],
             "X": ["Y"], "Y": ["Z"], "Z": ["S"]}),
     {"R"}, {"S"}, "crosses", {"CHOKE"}, contracts.BROKEN),

    # --- precondition (the guard is a SIBLING, it is not on the path) ------------
    ("requires: the route calls the guard before touching the sink",
     _Graph({"GET": ["GUARD", "DB"], "DB": ["S"]}),
     {"GET"}, {"S"}, "requires", {"GUARD"}, contracts.PASS),

    ("requires: one route does not call it",
     _Graph({"GET": ["GUARD", "DB"], "OTRA": ["DB"], "DB": ["S"]}),
     {"GET", "OTRA"}, {"S"}, "requires", {"GUARD"}, contracts.BROKEN),

    # THE MEASURED FALSE POSITIVE: with the vertex-cut formulation —that is, treating the
    # guard as an interposition— this returned BROKEN on 64 routes that WERE protected,
    # because the guard is not on the path: it is a sibling. It must return PASS.
    ("requires: the guard is a sibling and does not interpose — not a bypass",
     _Graph({"GET": ["GUARD", "CLIENTE"], "CLIENTE": ["S"]}),
     {"GET"}, {"S"}, "requires", {"GUARD"}, contracts.PASS),

    # --- isolation ---------------------------------------------------------------
    ("cannot_reach: there is no path",
     _Graph({"R": ["A"], "B": ["S"]}), {"R"}, {"S"}, "cannot_reach", set(), contracts.PASS),

    ("cannot_reach: there is a path",
     _Graph({"R": ["A"], "A": ["S"]}), {"R"}, {"S"}, "cannot_reach", set(), contracts.BROKEN),

    # --- the two grades of evidence ------------------------------------------------
    ("two grades: the bypass only exists through an ambiguous edge → SUSPECT, not BROKEN",
     _Graph(fuertes={"R": ["A"], "A": ["CHOKE"], "CHOKE": ["S"]},
            todas={"R": ["A", "B"], "A": ["CHOKE"], "CHOKE": ["S"], "B": ["S"]}),
     {"R"}, {"S"}, "crosses", {"CHOKE"}, contracts.SUSPECT),

    # --- contracts that say nothing --------------------------------------------------
    ("empty: the guarantee swallows the sink (it would always pass)",
     _Graph({"R": ["S"]}), {"R"}, {"S"}, "crosses", {"S"}, contracts.EMPTY),

    ("empty: the sink did not resolve",
     _Graph({"R": ["S"]}), {"R"}, set(), "crosses", {"CHOKE"}, contracts.EMPTY),

    ("empty: the guarantee did not resolve",
     _Graph({"R": ["S"]}), {"R"}, {"S"}, "crosses", set(), contracts.EMPTY),
]


def main() -> int:
    failures = []
    for name, grafo, src, dst, kind, guarantee, esperado in CASOS:
        r = contracts.verify(grafo, src, dst, kind, guarantee)
        if r["verdict"] != esperado:
            failures.append(f"{name}\n      esperado {esperado}, obtuvo {r['verdict']}"
                          f"{'  path=' + '→'.join(r['path']) if r.get('path') else ''}")

    # The returned path is not decoration: it is the evidence pasted into the report.
    # If a BROKEN carries no path, the finding cannot be verified by reading.
    g = _Graph({"R": ["B"], "B": ["S"]})
    r = contracts.verify(g, {"R"}, {"S"}, "crosses", {"CHOKE"})
    if r["verdict"] != contracts.BROKEN or r.get("path") != ["R", "B", "S"]:
        failures.append(f"a BROKEN with no verifiable witness path: {r}")

    if failures:
        print(f"\n  ✗ contracts: {len(failures)} de {len(CASOS) + 1} cases\n")
        for f in failures:
            print(f"    · {f}")
        return 1
    print(f"  ✓ contracts: {len(CASOS) + 1}/{len(CASOS) + 1} "
          f"(interposition, precondition, isolation, two grades, empty contracts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
