#!/usr/bin/env python3
"""Do the views still SAY something, or did they go empty without anyone noticing?

The other locks cover the ENGINE: `check_reach` that the graph respects scope, and
`check_blocks` that duplicates see nested blocks. None of them looks at the OUTPUT — and a
view returning empty structures breaks nothing, raises no exception and reads as "this
subsystem has no relations".

It is not hypothetical: one session produced two regressions caught only by a measurement and
not by reading the diff (the nested `def` counted as a shadow, which killed 38 symbols; and
the module map rendered as a 42 px strip). A third went unnoticed until it was printed: the
header said "22 declared entries" and the list showed one, because
contaban conjuntos distintos.

WHAT IT TESTS, AND WHY OVER THE REAL PROJECT
---------------------------------------------
A synthetic fixture is no use here: the question is not "does the function return the right
shape?" but "over a real codebase, does this find anything?". A three-file fixture would give
legitimately empty views and the lock would protect nothing.

BUT THE TARGET IS NOT HARDCODED. This lock protects the TOOL, so it has to travel with it: in
another repository "Ingestion" does not exist, and a lock that always skips is
indistinguishable from one that does not exist. It picks the largest target available —the
declared module with the most files, or the most populated directory if there are no
modules— which is the one most likely to exercise every section.

    mcview/selfcheck/check_view.py        # 0 = pass
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config      # noqa: E402
import factory as _factory    # noqa: E402
import flow as _flow        # noqa: E402
import heatmap as _heatmap          # noqa: E402
import orient as _orient  # noqa: E402

TOML = _config.discover()          # the config no longer lives inside the tool


def _largest_target(project) -> str | None:
    """The area with the most files: the one most likely to exercise every section.

    Choosing it instead of hardcoding it is what lets this lock travel. It prefers a declared
    module; if the project declares none, it falls back to the most populated directory, which
    `resolve` accepts just as well as a path target.
    """
    from collections import Counter
    cfg = project.cfg
    if cfg.modules:
        c = Counter(cfg.module_of(a) for a in project.by_file)
        for name, _ in c.most_common():
            if name in cfg.modules:
                return name
    dirs = Counter(a.rsplit("/", 1)[0] for a in project.by_file if "/" in a)
    return dirs.most_common(1)[0][0] if dirs else None


def _mermaid_safe(code: str) -> list[str]:
    """Subgraph balance and absence of dangling nodes: the two ways to break a diagram without
    the generator failing."""
    failures = []
    lines = [x.strip() for x in code.splitlines() if x.strip()]
    if not lines or not lines[0].startswith("flowchart"):
        return ["the diagram does not start with `flowchart`"]
    if sum(x.startswith("subgraph") for x in lines) != sum(x == "end" for x in lines):
        failures.append("subgraph/end desbalanceado")
    defined = set(re.findall(r"^(\w+)[\[(]", "\n".join(lines), re.M))
    defined |= set(re.findall(r"^subgraph (\w+)\[", "\n".join(lines), re.M))
    defined |= set(re.findall(r"^\s+(N\d+)$", code, re.M))
    used = {x for l in lines for pair in re.findall(r"(\w+)\s*-[.-]*->\s*(\w+)", l) for x in pair}
    if used - defined:
        failures.append(f"nodes used without being defined: {sorted(used - defined)}")
    return failures


def main() -> int:
    if not TOML or not os.path.exists(TOML):
        print("  · skipped (mcview.toml is missing)")
        return 0
    cfg = _config.load(TOML)
    if not os.path.isdir(cfg.root):
        print(f"  · skipped ({cfg.root} is missing)")
        return 0

    failures = []
    project = _factory.make_project(cfg)
    OBJETIVO = _largest_target(project)
    if not OBJETIVO:
        print("  · skipped (the project has no analyzable files)")
        return 0
    rank = _heatmap.pagerank(project)
    levels = project.levels()

    # --- a target that does NOT resolve invents nothing -----------------
    r = _orient.orient(project, rank, levels, None, "this-target-does-not-exist-xyz")
    if "error" not in r:
        failures.append("a nonexistent target returned a brief instead of an error")
    elif not r.get("modules"):
        failures.append("the error does not list the declared modules, so it orients nobody")

    # --- the brief carries its sections with content --------------------
    r = _orient.orient(project, rank, levels, None, OBJETIVO)
    if "error" in r:
        print(f"  ✗ {OBJETIVO} stopped resolving: {r['error']}")
        return 1
    for clave in ("files", "calientes", "incoming", "outgoing"):
        if not r.get(clave):
            failures.append(f"the brief carries `{clave}` empty")
    if sum(r["temperatura"].values()) == 0:
        failures.append("temperature classified no symbol")
    if r["mass_pct"] <= 0:
        failures.append("the target came out with mass 0")

    # --- el flow encuentra un route ----------------------------------
    files = set(r["files"])
    inside = {s for s, x in project.symbols.items() if x.file in files}
    f = _flow.trace(project, inside, rank)
    if "error" in f:
        failures.append(f"the flow traced nothing: {f['error']}")
    else:
        # `guards` is NOT included: it is legitimately empty in a project with no dominant
        # precondition. Measured on hermes — 597 paths, 1,669 called nodes, and the most
        # common reaches 12.9%, none the 0.30 threshold. Requiring it turned a property of the
        # codebase into a failure of the tool.
        for clave in ("gates", "targets", "paths", "camino_ejemplo"):
            if not f.get(clave):
                failures.append(f"the flow carries `{clave}` empty")
        if f.get("paths") and max(len(c) for c in f["paths"]) < 2:
            failures.append("no path has more than one hop: there is no chain to show")
        # the header and the list have to count the SAME set
        marked = sum(1 for p in f.get("gates", []) if p.get("declarada"))
        if f.get("puertas_declaradas", 0) and not marked:
            failures.append("it says there are declared entries but marks none in the list")

        usan, depende = _flow.neighbors_by_module(project, inside, files)
        if not usan or not depende:
            failures.append("the relations per line of work came out empty")
        f.update(usan=usan, depende=depende, target=r["target"])

        # --- both diagrams are syntactically sound ------------------------
        for name, code in (
            ("sequence", _flow.mermaid_sequence(f, r["target"])),
            ("map", _flow.mermaid(f, r["target"], usan, depende,
                                    _flow._internal_parts(files))),
        ):
            for x in _mermaid_safe(code):
                failures.append(f"diagrama `{name}`: {x}")

    for x in failures:
        print(f"  ✗ {x}")
    if not failures:
        print(f"  ✓ views over {OBJETIVO}: brief, flow and both diagrams with content")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
