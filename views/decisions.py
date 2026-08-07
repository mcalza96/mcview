"""The turn as a DECISION TREE: a network, with the probability on each branch.

The lane journey answers "in what order". This view answers the other half: **where the system
chooses**, and where the flow goes when it does. They are different questions, which is why
they are two views and not one with a toggle.

The node is a symbol, the edge is a transition, and both visible things come from the Markov
chain the tool already built and only used to extract a single figure per
node:

    node size        expected visits from the entry — how much flow goes through it
    width and label  the reference SPLIT from i to j (see the warning in markov.py: it is not
                     a branch probability while the AST cannot say which branch of which
                     conditional each call falls in)
    depth            hops from the entry — here the axis is correct because there is ONE origin

The difference from the global map is not cosmetic. There the size is the PROJECT's mass —how
central a symbol is across the whole repo— and here it is how much of THIS route's flow goes
through it. A symbol can be the heart of the system and take no part in the turn.

It is restricted to the route's subgraph before normalizing, and that matters: a branch's
probability depends on what it competes with. Normalizing over the whole graph would give
percentages that do not add up to what is on screen.
"""
from __future__ import annotations

import atlas as _atlas
import markov as _markov
import route as _route

# Below this the branch is an exception, not a decision, and labelling it fills the drawing
# with numbers that change no reading.
MINIMO_ROTULO = 0.08


def build(weave, src: str, dst: str, statuses: dict[str, str],
              obs: dict[str, int] | None = None, collapse: bool = True) -> dict:
    r = _route.trace(weave, src, dst)
    if "error" in r:
        return r

    inside = r["inside"]
    seams = {(c["from"], c["to"]) for c in getattr(weave, "applied_seams", ())}
    P = _markov.transitions(weave, inside, seams)
    visitas = _markov.expected_visits(P, r["origin"])
    decide = {d["id"]: d for d in _markov.decisions(P, visitas)}
    # The ones that can be PROVEN: calls in different branches of the same conditional. The
    # reparto de referencias ordena candidatos; esto afirma.
    bifurca = _markov.forks(weave, inside)
    if obs is not None:
        bifurca = _markov.annotate_with_runtime(bifurca, obs)
    ids_bifurca = {b["id"] for b in bifurca}

    # TWO names, and they used to be one. `depth` held the per-symbol dict and was then
    # overwritten with its maximum, so every later `depth.get(...)` was a dict method on an
    # int and this view crashed on every call — it had never run. Same class as a local
    # shadowing a builtin: the collision is invisible until the second use.
    profundidad = _atlas.depths(weave, r["origin"])
    mas_honda = max((profundidad.get(s, 0) for s in inside), default=0)

    nodes = []
    total = sum(visitas.values()) or 1.0
    for sid in sorted(inside):
        s = weave.symbols[sid]
        lane = weave.cfg.module_of(s.file)
        n = {
            "id": sid, "name": s.name, "loc": s.loc, "parent": None,
            "level": "symbol", "pct": round(visitas.get(sid, 0.0) / total * 100, 3),
            "visitas": round(visitas.get(sid, 0.0), 4),
            "status": statuses.get(sid, ""),
            "project": lane.split("▸")[0] if "▸" in lane else "",
            "lane": lane,
            # The axis: inverted because the canvas draws layer 0 at the bottom and a decision
            # tree is read from the entry toward the leaves.
            "layer": max(0, mas_honda - profundidad.get(sid, mas_honda)),
            "symbols": 1, "statuses": {}, "sueltos": 0, "depth": profundidad.get(sid, -1),
        }
        if sid in r["origin"]:
            n["entry"] = True
        if sid in ids_bifurca:
            n["bifurca"] = True
        elif sid in decide:
            n["decide"] = round(1.0 - decide[sid]["largest"], 3)
        if obs is not None:
            n["ejecutado"] = sid in obs
        nodes.append(n)

    # Seams ARE DRAWN —they are the crossing between repos, which is what has to be seen—
    # but they carry NO probability: they are not branches of the flow, they are mentions of
    # a name.
    edges = [{"from": a, "to": b, "weight": 3, "seam": True}
               for (a, b) in sorted(seams) if a in inside and b in inside]
    for i, branches in P.items():
        for j, p in branches:
            a = {"from": i, "to": j, "weight": max(1, round(p * 10))}
            # Only labelled where the number changes a reading: at a node that decides, and
            # only if the branch is not an exception.
            if i in decide and p >= MINIMO_ROTULO:
                a["p"] = round(p * 100)
            edges.append(a)

    # A layer with 40 nodes comes out as a horizontal strip the framing shrinks until it is
    # unreadable. It is the global map's problem in reverse: there, too many layers with one
    # node; here, too few layers and too many nodes. Each wide layer is split into sub-rows,
    # preserving the order — depth still rules, things are only stacked inside.
    _ancho = max(4, round(len(nodes) ** 0.5))
    _por_capa: dict[int, list[dict]] = {}
    for n in nodes:
        _por_capa.setdefault(n["layer"], []).append(n)
    _nueva = 0
    for c in sorted(_por_capa):
        row = sorted(_por_capa[c], key=lambda n: (-n["pct"], n["id"]))
        for k, n in enumerate(row):
            n["layer"] = _nueva + k // _ancho
        _nueva += max(1, -(-len(row) // _ancho))
    depth = _nueva - 1

    ids = {n["id"] for n in nodes}
    edges = [a for a in edges if a["from"] in ids and a["to"] in ids]

    crudos = len(nodes)
    if collapse:
        import blocks as _blocks
        lane = {n["id"]: n["lane"] for n in nodes}
        nodes, edges = _blocks.condense(
            nodes, edges, lambda i: lane.get(i, ""), ids_bifurca)
        # Layers are recomputed over the BLOCKS: inheriting the head's layer leaves gaps
        # where the chains were and the drawing comes out with empty rows.
        for n in nodes:
            n["layer"] = n.get("layer", 0)
        vistos_capa = sorted({n["layer"] for n in nodes})
        remap = {c: k for k, c in enumerate(vistos_capa)}
        for n in nodes:
            n["layer"] = remap[n["layer"]]
        depth = len(vistos_capa) - 1
    pct = {n["id"]: n["pct"] for n in nodes}
    col = _atlas.sort_rows({n["id"]: n["layer"] for n in nodes}, edges, pct)
    for n in nodes:
        n["col"] = col[n["id"]]

    return {
        "project": f"decisions: {src} → {dst}",
        "levels": {"module": {"nodes": nodes, "edges": edges,
                               "layers": depth + 1}},
        "symbols": crudos,
        "blocks": len(nodes),
        "forks": [
            {"name": weave.symbols[b["id"]].name, "conditional": b["conditional"],
             "runtime": b.get("runtime"),
             "options": [{"branch": o["branch"],
                           "targets": [weave.symbols[d].name for d in o["targets"]]}
                          for o in b["options"]]}
            for b in bifurca],
        "decisions": [
            {"name": weave.symbols[d["id"]].name, "loc": weave.symbols[d["id"]].loc,
             "largest": round(d["largest"] * 100),
             "branches": [{"to": weave.symbols[j].name, "p": round(p * 100)}
                       for j, p in d["branches"][:4]]}
            for d in sorted(decide.values(), key=lambda x: -x["weight"])[:12]],
    }


def report(m: dict) -> str:
    if "error" in m:
        return f"\n  {m['error']}\n"
    f = [f"\n  {m['project'].upper()}",
         f"  {m['symbols']} symbols → {m.get('blocks', m['symbols'])} blocks "
         f"(cadenas lineales colapsadas) · "
         f"{len(m['decisions'])} nodes where the flow splits\n",
         "  ⚠️ the number is the REFERENCE SPLIT, not a branch probability: the AST cannot",
         "  tell a call inside an `if` from the one on the next line. Two consecutive",
         "  calls give 50/50 and there is no choice at all. It ranks candidates; it does",
         "  not rule. SEAMS are left out of the computation — they are mentions of a",
         "  name, and with equal weight they manufactured a 50/50 that did not exist.\n"]
    f.append(f"  ── PROVEN FORKS ── calls in different branches of the SAME "
             f"condicional: {len(m['forks'])} ──")
    if not m["forks"]:
        f.append("     none. In this route static analysis cannot prove")
        f.append("     a single choice: the ones that exist are made by the LLM or by the data.")
    for b in m["forks"]:
        f.append(f"     {b['name']}  —  {b['conditional']}")
        if b.get("runtime"):
            f.append(f"        runtime: {b['runtime']}")
        for o in b["options"]:
            f.append(f"        {o['branch']:6s} → {', '.join(o['targets'][:4])}")
    f.append(f"\n  ── candidates by reference split (NOT proven) ──")
    for d in m["decisions"]:
        f.append(f"    {d['name']:32s} {d['loc']}")
        for r in d["branches"]:
            f.append(f"       {r['p']:3d}%  → {r['to']}")
    return "\n".join(f) + "\n"
