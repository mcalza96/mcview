"""The territory: how every component connects, in a model that can be drawn.

The text views answer one question each. This one answers the question that cannot go in a
table: **how the system is distributed**. And for it to be a map and not an ornament, every
visible thing means something already measured elsewhere:

    depth    minimum hops from a product root      ← the flow axis
    mass     personalized PageRank from the roots  ← the size
    status   the census liveness level             ← the color
    edge     UNAMBIGUOUS references crossing       ← the thickness

**Depth is the axis because it answers what you want to see.** A force layout groups what is
connected but has no up or down, so it does not read as a flow; with depth, the entries stay
on one side, the sinks on the other, and **what hangs from no root has nowhere to go** —
which is exactly what has to be seen.

THREE LEVELS, and the starting one is not the most detailed. A map of 6,138 symbols is
illegible by construction, and one of 701 files is 90% noise for any concrete question. You
enter through the declared lines of work —the same ones from the `.toml`— and descend:
module → files → symbols.

OVER WHICH GRAPH. The unambiguous one, for the same reason as the flow: with the complete
graph there is 15× homonym inflation and everything connects to everything, so the map would
come out dense and uniform — which is the visual form of saying nothing.
"""
from __future__ import annotations

from collections import defaultdict, deque

MODULO, ARCHIVO, SIMBOLO = "module", "file", "symbol"

# One or two references between two modules is an accident —a convenience import, a
# borrowed type— and if they count the same as 300, the layer gets decided by noise.
# Measured: with every edge the level collapsed; with this cut the plumbing stays at the
# bottom and the startup at the top, which is the architecture you recognize when you read it.
PESO_MINIMO = 3

# What hangs from no root. It is not a large depth: it is the ABSENCE of a path, and mixing
# it with "it is far away" erases the distinction that matters most here.
SUELTO = -1


def depths(project, roots: set[str]) -> dict[str, int]:
    """Minimum hops from a product root, over the unambiguous graph.

    BFS and not longest path: the minimum depth is "how soon the system can get in here",
    which is what orders a flow diagram. The maximum would measure the most contorted branch
    and would move a node by its worst case.
    """
    prof = {r: 0 for r in roots}
    queue = deque(roots)
    while queue:
        n = queue.popleft()
        for nxt in project.strong_edges.get(n, ()):
            if nxt not in prof:
                prof[nxt] = prof[n] + 1
                queue.append(nxt)
    return prof


def layers(ids: list[str], edges: list[dict], min_weight: int = PESO_MINIMO) -> dict[str, int]:
    """Dependency level: 0 is the plumbing, above it sits whoever uses it.

    THIS is the global map's axis, and it replaced "distance to the roots" because of a
    measurement, not a preference: CIRE has 402 product roots spread across 20 of its 36
    modules, so almost every module CONTAINS an entry and its minimum depth is 0 — the axis
    flattens. And it is not fixed by starting from the process entrypoints: from `main.py` +
    `worker.py` the strong graph reaches 660 of 6,143 symbols, because the tools register
    through a decorator and nobody calls them statically.

    It is not a defect of the repo: a tool-dispatch system HAS hundreds of entries. "Distance
    to the root" is a pipeline's axis, and it is still the right one inside a subsystem
    (`--flow` uses it there); for the whole, the question that does order things is who
    depends on whom.

    Cycles do not break it: re-entering a node already in progress cuts at 0. A cycle between
    modules is real —and worth seeing— but it cannot have a level, so it gets the lowest one
    in its component instead of hanging the computation.
    """
    output: dict[str, set[str]] = defaultdict(set)
    for a in edges:
        if a["weight"] >= min_weight:
            output[a["from"]].add(a["to"])
    memo: dict[str, int] = {}

    def level(x: str, en_curso: frozenset[str]) -> int:
        if x in memo:
            return memo[x]
        if x in en_curso:
            return 0
        v = max((level(y, en_curso | {x}) for y in sorted(output[x])), default=-1) + 1
        memo[x] = v
        return v

    crudo = {i: level(i, frozenset()) for i in sorted(ids)}
    return _compact(crudo, output)


def _compact(crudo: dict[str, int], output: dict[str, set[str]]) -> dict[str, int]:
    """Same ordering, bounded width. Without this the map comes out as a vertical strip.

    Measured by OPENING the page, not by reading the code: the longest path gave 18 layers
    for 36 modules —almost one per layer— because this repo's dependencies are close to a
    total order. Each layer held one node and the drawing was a column, which is the visual
    form of not showing a distribution.

    The only thing the axis asserts is preserved —if A uses B, A sits higher— and the rest is
    filled out sideways: each node goes to the lowest layer that respects its successors and
    still has room. It is the Coffman-Graham idea: bounding the width is what turns a chain
    into a readable grid.
    """
    if not crudo:
        return crudo
    ancho_max = max(3, round(len(crudo) ** 0.5))
    ocupacion: dict[int, int] = defaultdict(int)
    out: dict[str, int] = {}
    for i in sorted(crudo, key=lambda x: (crudo[x], x)):
        piso = max((out[s] + 1 for s in output.get(i, ()) if s in out), default=0)
        while ocupacion[piso] >= ancho_max:
            piso += 1
        out[i] = piso
        ocupacion[piso] += 1
    return out


def sort_rows(levels_of: dict[str, int], edges: list[dict],
            pct: dict[str, float], pasadas: int = 4) -> dict[str, int]:
    """Horizontal position within each layer, by barycenter.

    Without this the nodes are ordered by mass and every edge crosses every other: the
    drawing is illegible even though the data is right. The barycenter —placing each node
    near the average of its neighbors in the adjacent layer, a few passes— is the classic
    heuristic and it suffices; optimal ordering is NP-hard and is not needed here.

    It is computed HERE and not in the browser on purpose: the renderer draws, it does not
    decide. That way `--json` hands over exactly the positions you see, and the layout is
    deterministic — the same repo gives the same map, and a diff of the map means something.
    """
    por_capa: dict[int, list[str]] = defaultdict(list)
    for i, n in levels_of.items():
        por_capa[n].append(i)
    for layer in por_capa.values():
        layer.sort(key=lambda x: (-pct.get(x, 0.0), x))

    neighbors: dict[str, list[str]] = defaultdict(list)
    for a in edges:
        neighbors[a["from"]].append(a["to"])
        neighbors[a["to"]].append(a["from"])

    pos = {i: float(k) for layer in por_capa.values() for k, i in enumerate(layer)}
    for _ in range(pasadas):
        for n in sorted(por_capa):
            layer = por_capa[n]
            bari = {}
            for i in layer:
                vs = [pos[v] for v in neighbors[i] if v in pos and levels_of.get(v) != n]
                bari[i] = sum(vs) / len(vs) if vs else pos[i]
            layer.sort(key=lambda x: (bari[x], -pct.get(x, 0.0), x))
            for k, i in enumerate(layer):
                pos[i] = float(k)
    return {i: int(pos[i]) for i in pos}


def _group(project, rank, prof, clave) -> dict[str, dict]:
    """Aggregates symbols into map nodes according to `clave(sid) -> str`."""
    out: dict[str, dict] = {}
    for sid, s in project.symbols.items():
        k = clave(sid, s)
        if k is None:
            continue
        n = out.setdefault(k, {"id": k, "mass": 0.0, "symbols": 0,
                                 "depths": [], "statuses": defaultdict(int)})
        n["mass"] += rank.get(sid, 0.0)
        n["symbols"] += 1
        if sid in prof:
            n["depths"].append(prof[sid])
    return out


def _close(node: dict) -> dict:
    """A GROUP's depth is the minimum of its members: where the system enters the module.
    The average would mix the door with the far end and would put every large module in the
    same middle band."""
    ps = node.pop("depths")
    node["depth"] = min(ps) if ps else SUELTO
    # How many of its symbols hang from NO root. A whole loose module and one with a single
    # orphan function look identical if you only look at the group's depth.
    node["sueltos"] = node["symbols"] - len(ps)
    node["statuses"] = dict(node["statuses"])
    return node


def _edges(project, clave, nodes: dict) -> list[dict]:
    """Unambiguous references aggregated at the map's level. Self-loops are dropped: a module
    calling itself is normal, and drawing it buries the real connections."""
    weight: dict[tuple[str, str], int] = defaultdict(int)
    for o, ds in project.strong_edges.items():
        so = project.symbols.get(o)
        if so is None:
            continue
        ko = clave(o, so)
        for d in ds:
            sd = project.symbols.get(d)
            if sd is None:
                continue
            kd = clave(d, sd)
            if ko is None or kd is None or ko == kd or ko not in nodes or kd not in nodes:
                continue
            weight[(ko, kd)] += 1
    return [{"from": a, "to": b, "weight": w} for (a, b), w in
            sorted(weight.items(), key=lambda kv: -kv[1])]


DESPACHO = "· dispatch ·"


def from_surface(project, surface: str):
    """Where a user enters, and what opens up when the agent chooses by name.

    Returns (entries, reachable, error). `reachable` is what the user CAN walk, and that
    includes crossing the dispatch seam: measured, from `web chat` the call graph reaches 48
    of `mcp_tools/`'s 738 symbols — the rest is chosen by the agent by name, and a map that
    omits them answers "what gets called without going through the agent", which is not the
    question.

    The seam is crossed only if it is DECLARED (`[dispatch]`), and it shows up in the drawing
    as a node of its own. No edge is invented: what is stated is where the system stops
    resolving by call.
    """
    import locks as _cand

    cfg = project.cfg
    targets = cfg.surfaces.get(surface)
    if not targets:
        return set(), set(), (f"«{surface}» is not declared. Surfaces: "
                              f"{', '.join(sorted(cfg.surfaces)) or '(ninguna)'}")
    entries: set[str] = set()
    for o in targets:
        ids, err = _cand._resolve(project, o)
        if err:
            return set(), set(), err
        entries |= ids

    alcanzable = set(depths(project, entries))
    by_call = set(alcanzable)
    puerta_ids: set[str] = set()
    puerta = cfg.dispatch.get("at")
    abre = cfg.dispatch.get("opens", "")
    if puerta and abre.startswith("decorator:"):
        ids, err = _cand._resolve(project, puerta)
        # The door only opens if the user REACHES it. Opening it always would make every
        # surface reach everything, which is the inflation this map avoids.
        if not err and (ids & alcanzable):
            puerta_ids = ids & alcanzable
            reason = abre.split(":", 1)[1]
            tools = project.roots_by_reason.get(reason, set())
            alcanzable |= set(depths(project, tools)) | tools
    # What is on the map ONLY because the agent chooses by name. Distinguishing it is the
    # difference between "the user can get here" and "the user gets here by calling":
    # without the mark, the tools are drawn as if the path were made of calls and the map
    # asserts something the graph never proved.
    seam = {"puerta": puerta_ids, "via": alcanzable - by_call}
    return entries, alcanzable, None, seam


def build(project, rank: dict[str, float], statuses: dict[str, str],
              roots: set[str], only: set[str] | None = None,
              seam: dict | None = None, eje: str = "layer") -> dict:
    """The complete model, at all three levels. The renderer computes nothing.

    That separation is what lets the drawing change —2D today, something else later— without
    touching the measurement again, and what allows `--json` to hand over exactly what is on
    screen.
    """
    prof = depths(project, roots)
    cfg = project.cfg
    # With a surface, the map is NOT the repo: it is what that door reaches. Filtering here
    # —and not at draw time— makes layers, columns and mass be computed over the slice, which
    # is what you want to see; against the whole universe the slice ends up flattened by the
    # large modules that do not participate.
    if only is not None:
        prof = {k: v for k, v in prof.items() if k in only}

    inside = (lambda sid: True) if only is None else (lambda sid: sid in only)
    claves = {
        MODULO: lambda sid, s: cfg.module_of(s.file) if inside(sid) else None,
        ARCHIVO: lambda sid, s: s.file if inside(sid) else None,
        SIMBOLO: lambda sid, s: sid if inside(sid) else None,
    }
    parents = {
        MODULO: lambda k: None,
        ARCHIVO: lambda k: cfg.module_of(k),
        SIMBOLO: lambda k: project.symbols[k].file,
    }

    levels = {}
    for level, clave in claves.items():
        nodes = {k: _close(v) for k, v in _group(project, rank, prof, clave).items()}
        for k, n in nodes.items():
            n["parent"] = parents[level](k)
            n["level"] = level
            # In the weave the id comes prefixed by project; the per-repository color
            # is what lets you see where one ends and the next begins.
            if "▸" in k:
                n["project"] = k.split("▸")[0]
            if level == SIMBOLO:
                s = project.symbols[k]
                n["name"], n["loc"] = s.name, s.loc
                n["status"] = statuses.get(k, "")
            else:
                n["name"] = k
        levels[level] = {"nodes": list(nodes.values()),
                          "edges": _edges(project, clave, nodes)}

    # Status is aggregated upward from the symbols: a module has no liveness level of its
    # own, it has a composition.
    por_clave = {ARCHIVO: lambda s: s.file, MODULO: lambda s: cfg.module_of(s.file)}
    for level, f in por_clave.items():
        count: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for sid, s in project.symbols.items():
            if only is not None and sid not in only:
                continue
            count[f(s)][statuses.get(sid, "")] += 1
        for n in levels[level]["nodes"]:
            n["statuses"] = dict(count.get(n["id"], {}))

    # The DISPATCH node: where the system stops resolving by call. It goes in as a node of
    # its own rather than as loose edges because what has to be seen is the DOOR — "here the
    # agent chooses by name"— and not a tangle of lines toward 168 tools.
    if seam and seam.get("via"):
        for level, clave in claves.items():
            nodes = {n["id"]: n for n in levels[level]["nodes"]}
            grupo = {}
            for cual in ("puerta", "via"):
                grupo[cual] = {k for sid in seam[cual]
                               if (s := project.symbols.get(sid)) is not None
                               and (k := clave(sid, s)) is not None and k in nodes}
            # A group with symbols on both sides is NOT "via dispatch": it is reached by
            # call as well as through the agent, and marking it whole would hide that.
            solo_via = {k for k in grupo["via"] - grupo["puerta"]
                        if not any(clave(sid, s) == k for sid, s in project.symbols.items()
                                   if sid in (only or set()) and sid not in seam["via"])}
            for k in solo_via:
                nodes[k]["via_despacho"] = True
            if not solo_via:
                continue
            levels[level]["nodes"].append({
                "id": DESPACHO, "name": DESPACHO, "level": level, "parent": None,
                "dispatch": True, "hidden": sorted(solo_via), "pct": 0.0,
                "symbols": len(seam["via"]), "statuses": {}, "depth": SUELTO,
                "sueltos": 0, "mass": 0.0})
            levels[level]["edges"] += (
                [{"from": k, "to": DESPACHO, "weight": 3, "seam": True}
                 for k in sorted(grupo["puerta"])] +
                [{"from": DESPACHO, "to": k, "weight": 3, "seam": True}
                 for k in sorted(solo_via)])

    total = sum(n["mass"] for n in levels[MODULO]["nodes"]) or 1.0
    for level in levels.values():
        for n in level["nodes"]:
            n["pct"] = round(n["mass"] / total * 100, 3)
            del n["mass"]

    # The position, computed here: the renderer draws and does not decide.
    for level, datos in levels.items():
        ids = [n["id"] for n in datos["nodes"]]
        pct = {n["id"]: n["pct"] for n in datos["nodes"]}
        # Between two SYMBOLS one reference is the unit, not noise: demanding 3 leaves the
        # graph without edges and everything falls into the same layer. The accident cut is a
        # notion about aggregates —modules and files—, not about the elementary edge.
        if eje == "depth":
            # In a ROUTE the axis is the distance to the origin, not dependency: there is ONE
            # origin, so depth orders things again (which is what did not happen in the
            # global map, with 402 roots spread across 20 of 36 modules). It is inverted
            # because the canvas draws layer 0 at the bottom, and a route is read from the
            # entry hacia el fondo.
            depth = max((n["depth"] for n in datos["nodes"]), default=0)
            layer = {n["id"]: max(0, depth - max(0, n["depth"]))
                    for n in datos["nodes"]}
        else:
            layer = layers(ids, datos["edges"], 1 if level == SIMBOLO else PESO_MINIMO)
        col = sort_rows(layer, datos["edges"], pct)
        for n in datos["nodes"]:
            n["layer"], n["col"] = layer[n["id"]], col[n["id"]]
        datos["layers"] = max(layer.values(), default=0) + 1

    # A symbol is not an aggregate: it has no status composition and no child count, and its
    # `id` already says file, line and name. Loading it with the aggregate's fields is 2 MB
    # of zeros in the page — the symbol level is 90% of the model's weight.
    for n in levels[SIMBOLO]["nodes"]:
        for campo in ("symbols", "statuses", "sueltos", "level", "loc"):
            n.pop(campo, None)

    return {
        "project": cfg.name,
        "levels": levels,
        "max_depth": max(prof.values(), default=0),
        "sueltos": sum(1 for s in project.symbols if s not in prof),
        "symbols": len(only) if only is not None else len(project.symbols),
    }
