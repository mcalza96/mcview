"""What happens, and in what order. Not what is reachable.

Every other view in this tool answers over a graph, and a graph has no before and after: it
knows the handler calls `get_tenant_id` and `assess_complexity`, not that the tenant is
resolved first. To understand a TURN that is not enough — "the user sends a message, the
tenant is resolved, the agent assesses the intent" is a sequence, and a sequence cannot be
deduced from a set of edges.

The data existed and was being thrown away. Inside a body the calls ARE ordered: it is in the
AST, and `core._refer` already received the line. Keeping it turns the same graph into a
sequence diagram with nothing declared and nothing executed.

WHAT IT IS NOT. It is not a trace: it is the WRITTEN order, not the one that happened. A call
inside an `if` shows up here even if a real turn never executes it, and one coming out of
dynamic dispatch does not show up even if it always executes. That is why the next step is to
contrast against runtime — what is written orders the narrative, what executed corrects it.

IT RECURSES BY MASS, NOT OVER EVERYTHING. A real turn touches thousands of symbols and a
thousand-step narrative cannot be read. It descends through the heaviest call at each level
and records how many branches were left unopened: a cut that is declared is a cut; one that
stays quiet reads as if that were everything that happens.
"""
from __future__ import annotations

TOPE_POR_NIVEL = 8
HONDO = 4


def _step(weave, sid: str, rank: dict[str, float], depth: int,
          seen: set[str], top: int, inside: set[str] | None = None,
          obs: dict[str, int] | None = None) -> dict:
    s = weave.symbols[sid]
    node = {"id": sid, "name": s.name, "loc": s.loc, "steps": [], "pruned": 0}
    # IT CONFIRMS, IT DOES NOT RULE OUT. An unmarked step is not a false step: it may not
    # have run inside the observed window, or sit behind an `if`, or run in a process where
    # nobody turned the probe on. Same rule as the liveness census.
    if obs is not None:
        node["ejecutado"] = sid in obs
    if depth <= 0 or sid in seen:
        # A cycle is not an error: `run_turn` can call itself again. It is cut and marked,
        # instead of recursing forever or omitting it as if it did not exist.
        node["repeats"] = sid in seen
        return node
    seen = seen | {sid}

    calls = sorted(weave.call_order.get(sid, ()), key=lambda x: x[0])
    vistos_destino: set[str] = set()
    ordered = []
    for line, target_node in calls:
        if target_node in vistos_destino or target_node == sid:
            continue          # the same function called three times is ONE step of the narrative
        vistos_destino.add(target_node)
        ordered.append((line, target_node))

    if inside is not None:
        # With a target, relevance is not decided by mass: it descends through whatever is ON
        # some path to the target, and through all of it. A route step pruned for "weighing
        # little" is exactly the one needed to understand how the answer gets assembled.
        chosen = [(ln, d) for ln, d in ordered if d in inside]
        node["pruned"] = 0
        node["off_path"] = len(ordered) - len(chosen)
    else:
        chosen = sorted(ordered, key=lambda x: -rank.get(x[1], 0.0))[:top]
        node["pruned"] = len(ordered) - len(chosen)
    # They are chosen by mass but NARRATED by line: the narrative has to follow the code's
    # order, not the ranking's.
    for line, target_node in sorted(chosen, key=lambda x: x[0]):
        child = _step(weave, target_node, rank, depth - 1, seen, top, inside, obs)
        child["line"] = line
        node["steps"].append(child)
    return node


def trace(weave, entry: str, rank: dict[str, float],
           depth: int = HONDO, top: int = TOPE_POR_NIVEL,
           dst: str | None = None, obs: dict[str, int] | None = None) -> dict:
    ids, err = (weave.resolve(entry) if hasattr(weave, "resolve")
                else _resolver_simple(weave, entry))
    if err:
        return {"error": err}
    # The entry is ONE symbol: a sequence starts at a point, not at an area. If the target
    # resolved to an area, the heaviest one is taken and named.
    sid = max(ids, key=lambda s: rank.get(s, 0.0))

    inside = None
    if dst:
        import route as _rec
        r = _rec.trace(weave, entry, dst) if hasattr(weave, "resolve") else None
        if r is None:
            return {"error": "«--to» needs the workspace weave"}
        if "error" in r:
            return r
        inside = r["inside"]
    tree = _step(weave, sid, rank, depth, set(), top, inside, obs)
    before = _count_leaves(tree)
    tree = collapse(tree)
    out = {"entry": entry, "steps_before_collapse": before,
             "steps": _count_leaves(tree), "dst": dst, "starts_at": weave.symbols[sid].loc,
             "of_candidates": len(ids), "tree": tree}
    if inside is not None:
        out["en_algun_camino"] = len(inside)
    if obs is not None:
        out["runtime"] = {"observados_en_el_relato": _count(tree),
                            "regla": "confirma, no descarta"}
    return out


def _collect_ids(n: dict, out: set[str]) -> None:
    """The ids the narrative actually reached. Used to measure its own cut."""
    out.add(n["id"])
    for p in n["steps"]:
        _collect_ids(p, out)


def _count(n: dict) -> tuple[int, int]:
    seen = 1 if n.get("ejecutado") else 0
    total = 1
    for p in n["steps"]:
        v, t_ = _count(p)
        seen += v
        total += t_
    return seen, total


def _resolver_simple(project, target: str):
    import locks as _cand
    return _cand._resolve(project, target)


def _lane(weave, sid: str) -> str:
    return weave.cfg.module_of(weave.symbols[sid].file)


def report(weave, r: dict) -> str:
    if "error" in r:
        return f"\n  {r['error']}\n"
    f = [f"\n  SEQUENCE — {r['entry']}",
         f"  {r['steps']} steps (of {r['steps_before_collapse']} before collapsing repetition)",
         f"  starts at {r['starts_at']}"
         + (f"  (the heaviest of {r['of_candidates']} symbols)"
            if r["of_candidates"] > 1 else "") + "\n",
         "  the order is the WRITTEN one, not the executed one: a call inside an `if`",
         "  shows up anyway, and a dynamically dispatched one does not\n"]
    # R3: never degrade in silence. When the entry was not declared, the walk starts at the
    # heaviest symbol — and mass is *measured* not to predict execution (AUC 0.506), so the
    # origin is an inference, not an entry point. Everything downstream, the expected visits
    # included, is conditioned on it. Saying so costs two lines; not saying so makes a guess
    # read like a fact.
    if r["of_candidates"] > 1 and not getattr(weave.cfg, "surfaces", None):
        f += ["  \u26a0 no [surfaces] declared: this origin was CHOSEN BY MASS, not by a door.",
              "    Naming the real entry points in the .toml changes where this walk begins.\n"]

    def descend(n: dict, depth_lvl: int):
        indent = "   " + "  " * depth_lvl
        for p in n["steps"]:
            mark = "↻ " if p.get("repeats") else ""
            # `·` is not "it did not happen": it is "not observed". The difference is the whole point.
            run = "" if "ejecutado" not in p else ("✓ " if p["ejecutado"] else "· ")
            times = f"  ×{p['times']}" if p.get("times") else ""
            echo_note = (f"  ↑ already told at {p['already_told']} ({p['hidden']} steps)"
                   if p.get("already_told") else "")
            f.append(f"{indent}{run}{mark}{p['name']:<34s} {p['loc']}   "
                     f"[{_lane(weave, p['id'])}]{times}{echo_note}")
            descend(p, depth_lvl + 1)
        if n.get("off_path"):
            f.append(f"{indent}({n['off_path']} calls from {n['name']} that do not "
                     f"llevan al target_node)")
        if n["pruned"]:
            f.append(f"{indent}… {n['pruned']} more calls from {n['name']}, "
                     f"not expanded (it descends through the heaviest)")

    descend(r["tree"], 0)
    return "\n".join(f) + "\n"


def mermaid(weave, r: dict) -> str:
    """A sequence diagram with lanes. The lane is the line of work, which is the unit you think
    a turn in — not the file."""
    if "error" in r:
        return r["error"]
    lines, lanes = [], []
    messages = []

    def descend(n: dict):
        c_parent = _lane(weave, n["id"])
        if c_parent not in lanes:
            lanes.append(c_parent)
        for p in n["steps"]:
            c = _lane(weave, p["id"])
            if c not in lanes:
                lanes.append(c)
            messages.append((c_parent, c, p["name"], p.get("repeats")))
            descend(p)

    descend(r["tree"])
    lines.append("sequenceDiagram")
    for c in lanes:
        lines.append(f"  participant {_id(c)} as {c}")
    for frm, to, what, repeats in messages:
        arrow = "-->>" if repeats else "->>"
        lines.append(f"  {_id(frm)}{arrow}{_id(to)}: {what}")
    return "\n".join(lines)


def _id(name: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in name)[:24]


def signature(n: dict) -> tuple:
    """The SHAPE of a subtree: its name and its children's, recursively. Two steps with the same
    signature tell the same story even if they happen in different places."""
    return (n["name"], tuple(signature(p) for p in n["steps"]))


def collapse(n: dict, already_told: dict | None = None) -> dict:
    """Compresses what repeats, with the counter in view.

    A 661-message diagram is correct and unreadable, and the problem is not visual: it is that
    the same story is told many times. It collapses along two routes, and both LEAVE THE
    NUMBER — «×20» is not a footnote, it is the finding: it says there is a loop there, which
    is exactly what you want to know about a turn.

        consecutive siblings with the same shape  →  just one, with «×N»
        a shape already narrated above           →  referenced, not repeated

    The second matters more than it looks: `get_async_supabase_client` appears under eight
    different parents and drags its subtree along each time. Counting it once and referencing
    it afterwards loses no information —the subtree is the same— and removes most of the
    height.
    """
    already_told = {} if already_told is None else already_told
    output = []
    for p in n["steps"]:
        f = signature(p)
        if f in already_told and p["steps"]:
            output.append({**p, "steps": [], "already_told": already_told[f],
                           "hidden": _count_leaves(p)})
            continue
        if p["steps"]:
            already_told[f] = p["loc"]
        output.append(collapse(p, already_told))

    # Consecutive siblings with the same shape: one, with the counter.
    compressed = []
    for p in output:
        if compressed and signature(compressed[-1]) == signature(p):
            compressed[-1]["times"] = compressed[-1].get("times", 1) + 1
        else:
            compressed.append(p)
    return {**n, "steps": compressed}


def _count_leaves(n: dict) -> int:
    return 1 + sum(_count_leaves(p) for p in n["steps"])


# ------------------------------------------------------- the exhaustive mode
# The narrative above answers "what happens, in what order" and pays for it by pruning: it
# descends the heaviest call and counts what it left shut. That is the right trade for reading,
# and the wrong one for "which edges can this flow take at all" — a question about a SET, not
# about an order.
#
# It is NOT solved by ranking. Mass is what does the pruning here, and mass is *measured* not
# to predict execution (AUC 0.506): ordering the edges by centrality would say which are
# structurally central, never which the flow can traverse. The set is reachability, which the
# liveness census already computes; the weight of each branch is the absorbing chain, which
# `--decisions` already computes. Neither needed inventing — what was missing is an output.
def reach_all(weave, entry: str, rank: dict[str, float], obs: dict[str, int] | None = None,
              narrated: set[str] | None = None) -> dict:
    """Everything reachable from an entry, grouped by line of work and weighted by the chain.

    ALL the resolved symbols are entries, not the heaviest one. `--sequence` takes a single
    origin because a narrative starts at a point; a reach set does not, and `expected_visits`
    already accepts a set. For a surface declaring three router files, those three files ARE
    the door — collapsing them to the heaviest would answer about one third of it.
    """
    ids, err = (weave.resolve(entry) if hasattr(weave, "resolve")
                else _resolver_simple(weave, entry))
    if err:
        return {"error": err}

    def clausura(aristas) -> set[str]:
        frontier, vistos = set(ids), set(ids)
        while frontier:
            siguiente: set[str] = set()
            for sid in frontier:
                for d in aristas.get(sid, ()):
                    if d not in vistos and d in weave.symbols:
                        vistos.add(d)
                        siguiente.add(d)
            frontier = siguiente
        return vistos

    # TWO closures, and the difference is the finding. The complete graph resolves a reference
    # by name even when several symbols share it, so a reach set built on it drags in whatever
    # happens to be a homonym: measured from `Ingesta`, 553 symbols of `tests/unit` came out
    # reachable carrying 22% of the expected visits, which is not the suite being called by the
    # ingestion path — it is `get`, `run`, `main` resolving to the nearest namesake.
    # The strong closure only follows names that belong to ONE symbol. Reporting both keeps the
    # same grade-of-evidence contract the liveness census uses: the wide number fails open, and
    # the narrow one says how much of it you can actually stand on.
    alcanzables = clausura(weave.edges)
    inequivocos = clausura(weave.strong_edges)

    aristas = sum(1 for s in alcanzables for d in weave.edges.get(s, ()) if d in alcanzables)

    visitas: dict[str, float] = {}
    try:
        import markov as _markov
        P = _markov.transitions(weave, alcanzables)
        visitas = _markov.expected_visits(P, set(ids))
    except Exception:  # noqa: BLE001
        # The weight is optional and the SET is not. Both run on the bare stdlib —
        # `expected_visits` iterates the front instead of inverting the fundamental matrix
        # precisely so that it does not need numpy — so this branch is not about a missing
        # dependency; it is there so that an unforeseen failure in the chain costs the column
        # and not the answer. When it fires the report says the set is unweighted rather than
        # printing a column of zeros, which would read as "no flow goes there".
        visitas = {}

    total = sum(visitas.values()) or 1.0
    por_linea: dict[str, dict] = {}
    for sid in alcanzables:
        linea = _lane(weave, sid)
        fila = por_linea.setdefault(linea, {"line": linea, "symbols": 0, "unambiguous": 0,
                                            "share": 0.0, "executed": 0})
        fila["symbols"] += 1
        if sid in inequivocos:
            fila["unambiguous"] += 1
        fila["share"] += visitas.get(sid, 0.0) / total
        if obs is not None and sid in obs:
            fila["executed"] += 1

    filas = sorted(por_linea.values(), key=lambda x: (-x["share"], -x["symbols"]))
    out = {"entry": entry, "entries": len(ids), "reachable": len(alcanzables),
           "unambiguous": len(inequivocos),
           "edges": aristas, "of_project": len(weave.symbols),
           "weighted": bool(visitas), "lines": filas}
    if obs is not None:
        out["executed"] = sum(1 for s in alcanzables if s in obs)
    if narrated is not None:
        out["narrated"] = len(narrated & alcanzables)
    return out


def report_reach(weave, r: dict) -> str:
    if "error" in r:
        return f"\n  {r['error']}\n"
    pct = 100 * r["reachable"] / max(r["of_project"], 1)
    f = [f"\n  REACHABLE FROM — {r['entry']}   ({r['entries']} entry symbol(s))",
         f"  {r['reachable']} symbols · {r['edges']} edges · {pct:.0f}% of the project",
         f"  {r['unambiguous']} of them through UNAMBIGUOUS names "
         f"({100*r['unambiguous']/max(r['reachable'],1):.0f}%) — the rest arrive only through "
         f"a name\n  several symbols share, which is reach you cannot stand on\n"]
    if r.get("narrated") is not None:
        f.append(f"  the narrative (`--sequence` without `--all`) shows {r['narrated']} of "
                 f"them — {100*r['narrated']/max(r['reachable'],1):.1f}%\n")
    ancho = max((len(x["line"]) for x in r["lines"]), default=10)
    cab = "  share" if r["weighted"] else ""
    f.append(f"  {'line of work':{ancho}}  {'symbols':>8}  {'unamb':>6}{cab}"
             + ("  executed" if "executed" in r else ""))
    f.append("  " + "-" * (ancho + 26))
    for x in r["lines"][:20]:
        share = f"  {100*x['share']:5.1f}%" if r["weighted"] else ""
        vis = f"  {x['executed']:8}" if "executed" in r else ""
        f.append(f"  {x['line'][:ancho]:{ancho}}  {x['symbols']:8}  "
                 f"{x['unambiguous']:6}{share}{vis}")
    if len(r["lines"]) > 20:
        f.append(f"  … and {len(r['lines']) - 20} more lines of work")

    f += ["",
          "  This is what the flow CAN traverse, not what it does. The set is reachability",
          "  over the WRITTEN call graph: a call inside an `if` is in here, and one made by",
          "  dynamic dispatch is not."]
    if not r["weighted"]:
        f.append("  No share column: the chain could not be built. The set above is "
                 "complete — it is the weighting that is missing, not the reach.")
    if "executed" in r:
        f.append(f"  {r['executed']} of them were seen executing — that CONFIRMS, it never "
                 f"rules out.")
    return "\n".join(f) + "\n"
