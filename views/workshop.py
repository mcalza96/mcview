"""The whole workspace: the three projects and the seams joining them.

A per-repository map leaves out the one thing no repository can show —how they join— and that
is where half of this system's errors live: the gateway does not import a backend function, it
hits `/api/v1/internal/platform-auth/resolve` and asks for the `retrieval__query` tool. **The
seam between projects is made of STRINGS**, so no call graph crosses it and no tool that looks
at a single repo sees it.

Here it is crossed with what `seams.py` already detects: each project declares in its `.toml`
which literals it EXPORTS (its routes, its tools) and which it CONSUMES, and crossing those
catalogs gives the edge. Nothing is inferred: if the literal does not match, there is no
bridge.

Seam edges are marked as such and drawn dashed, for the same reason as the dispatch node: a
call and a string that happens to match are not the same evidence, and a map that draws them
identically asserts too much.
"""
from __future__ import annotations

from collections import defaultdict

import atlas as _atlas
import config as _config
import seams as _seams
import factory as _factory
import heatmap as _heatmap

# `touches` means tables and RPCs: shared state, not a call. Two projects writing the same
# table are coupled —tightly— but neither calls the other, so the edge would be directionally
# false. They are counted separately and reported.
CALL_KINDS = ("path", "tool")


def _is_product_loc(cfg, loc: str) -> bool:
    rel = loc.split(":")[0]
    return cfg.area_of(rel) == "core" and not rel.startswith(("tests/", "test/", "scripts/"))


def _module_of_loc(cfg, loc: str) -> str:
    return cfg.module_of(loc.split(":")[0])


def combine(configs: dict[str, str]) -> dict:
    """A map model with every project's modules and their seams.

    `configs` is {label: path to the .toml}. The label is used and not the declared name
    because two projects can have similar names and a node id has to be unique — a collision here
    silently merges two modules from different repos.
    """
    nodes: list[dict] = []
    edges: list[dict] = []
    catalogs: dict[str, dict] = {}
    cfgs: dict[str, object] = {}
    recursos: list[dict] = []

    # Two configs over the SAME tree (the gateway's dev and prod) are the same code, and
    # drawing both says there are two gateways. The one that DECLARES THE MOST SEAMS wins, not
    # the alphabetically first: that criterion looked deterministic and was arbitrary — sorted,
    # `hermes-prod` comes before `hermes` and the variant that declares no `[seams]` won, so
    # the gateway ended up with no junction to the backend at all. The gateway's seam is the
    # most important one in the system and it disappeared silently.
    loaded = {e: _config.load(r) for e, r in configs.items()}
    chosen: dict[str, str] = {}
    for label in sorted(loaded, key=lambda e: (-len(loaded[e].seams), e)):
        chosen.setdefault(loaded[label].root, label)
    kept = set(chosen.values())

    for label, path in configs.items():
        if label not in kept:
            continue
        cfg = loaded[label]
        project = _factory.make_project(cfg)
        rank = _heatmap.pagerank(project)
        statuses = {s: e for e, ss in project.levels().items() for s in ss}
        roots = {s for s in project.product_roots
                  if _heatmap._is_product(project, project.symbols[s].file)}
        m = _atlas.build(project, rank, statuses, roots)
        level = m["levels"][_atlas.MODULO]
        for n in level["nodes"]:
            n["id"] = f"{label}▸{n['id']}"
            n["project"] = label
            nodes.append(n)
        for a in level["edges"]:
            edges.append({"from": f"{label}▸{a['from']}", "to": f"{label}▸{a['to']}",
                            "weight": a["weight"]})
        catalogs[label] = _seams.detect(project)
        cfgs[label] = cfg

    # --- the seams: who consumes a literal another one exports -----------------
    crossings: dict[tuple[str, str], int] = defaultdict(int)
    for consumer, cat in catalogs.items():
        for kind in CALL_KINDS:
            for literal, locs in cat.get("consumes", {}).get(kind, {}).items():
                for producer, other in catalogs.items():
                    if producer == consumer:
                        continue
                    target_node = other.get("exports", {}).get(kind, {}).get(literal)
                    if not target_node:
                        continue
                    # A test calling the tool is not a PRODUCTION seam: it is the test
                    # bench. Unfiltered, `hermes▸tests` tops the list with 20 uses and buries
                    # the real junctions, which is the same bias as
                    # `--mermaid map` already corrects this in a single repo's flow.
                    for lc in [x for x in locs if _is_product_loc(cfgs[consumer], x)]:
                        for ld in [y for y in target_node
                                   if _is_product_loc(cfgs[producer], y)]:
                            a = f"{consumer}▸{_module_of_loc(cfgs[consumer], lc)}"
                            b = f"{producer}▸{_module_of_loc(cfgs[producer], ld)}"
                            crossings[(a, b)] += 1

    ids = {n["id"] for n in nodes}
    for (a, b), weight in sorted(crossings.items(), key=lambda kv: -kv[1]):
        if a in ids and b in ids:
            edges.append({"from": a, "to": b, "weight": weight, "seam": True})

    # Shared state: not an edge, a fact about two projects at once.
    for kind in ("table", "rpc"):
        por_literal: dict[str, set[str]] = defaultdict(set)
        for label, cat in catalogs.items():
            for literal in cat.get("touches", {}).get(kind, {}):
                por_literal[literal].add(label)
        for literal, quienes in sorted(por_literal.items()):
            if len(quienes) > 1:
                recursos.append({"kind": kind, "literal": literal,
                                 "projects": sorted(quienes)})

    pct = {n["id"]: n["pct"] for n in nodes}
    layer = _atlas.layers([n["id"] for n in nodes], edges)
    col = _atlas.sort_rows(layer, edges, pct)
    for n in nodes:
        n["layer"], n["col"] = layer[n["id"]], col[n["id"]]

    return {
        # The ones that are DRAWN, not the ones requested: the title listed `hermes-prod`
        # after deduplicating it, i.e. it named a project that is not on the map.
        "project": " + ".join(sorted(kept)),
        "workspace": sorted(kept),
        "levels": {_atlas.MODULO: {"nodes": nodes, "edges": edges,
                                    "layers": max(layer.values(), default=0) + 1}},
        "seams": sum(1 for a in edges if a.get("seam")),
        "shared_resources": recursos,
        "symbols": sum(n["symbols"] for n in nodes),
    }
