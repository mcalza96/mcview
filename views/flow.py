# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""THE ROUTE — where the system goes to reach a subsystem, and where it continues.

`--orient` gives an area's heat map: how much it weighs, who uses it, what is cold. That is
a CENSUS, not a ROUTE. To avoid duplicating a component, knowing a file is hot is not
enough: you have to see that the request already crosses a tenant resolver before arriving,
and that writing a new one would be the second.

ZERO CONFIGURATION, AND THAT IS THE DESIGN DECISION
----------------------------------------------------
The earlier tracers declared their roots, their tools and their sinks by hand. They work,
but only for the flow somebody already sat down to declare — useless for a session opening a
subsystem for the first time, which is exactly when it is needed. They are still alive and
complementary: they live in `scripts/flow-cire.py` and `scripts/flow-telegram.py`, OUTSIDE
the tool, because their value is a SEMANTIC taxonomy of sinks —"talks to the model", "writes
to the database"— which this does not derive and which belongs to this project.

Here the target IS the sink. The roots are already declared in the `.toml` (the same ones the
whole tool uses) and the output sinks are DISCOVERED. That way, getting oriented in a new
area costs no declaration.

FOUR QUESTIONS, THREE OF THEM OVER THE SAME SET OF PATHS
---------------------------------------------------------
    how you ENTER      · which target symbols the roots reach, and through which door
    where it GOES      · nodes present in the largest fraction of those paths
    what PROTECTS it   · nodes the paths CALL without being on them
                         (`paths.discovered_guards`)
    where it REACHES   · forward reachability from the target, aggregated per file

The third is not a variant of the second. A guard is not ON the path: it is called before, as
a precondition with an early return, so in the graph it is a SIBLING. Confusing the two
produced 64 false bypasses the first time it was attempted — it is documented in `paths.py`,
and that is why this reuses that function instead of reimplementing the count.

WHAT THIS IS NOT
----------------
It is not a profiler: it is structure, not execution. A path that exists in the graph may
never be walked in production — that is what the probe is for. And a path ABSENT from the
graph may exist anyway (dynamic dispatch, plugins by name); the bias runs toward the false
negative, never toward inventing a path that is not there.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import paths as _paths

PATH_CAP = 12           # hops; beyond this it stops reading as evidence
STEP_THRESHOLD = 0.30   # fraction of paths for something to count as "on the path"


class _UnambiguousOnly:
    """The project graph restricted to UNAMBIGUOUS-name edges.

    A PATH IS A STRONGER CLAIM THAN A REFERENCE, and it needs stronger evidence. Over CIRE's
    complete graph there are 124,531 edges against 8,058 unambiguous ones —15× inflation from
    homonyms— and with that everything reaches everything: this view's first attempt reported
    that 351 of 402 roots "reach" Ingestion, and listed `client` and `get` from test files as
    what the flow crosses first. That is not a flow, it is noise shaped like a flow, and it
    is worse than showing nothing because it reads as a finding.

    It presents the same contract as `Project` for the only things `paths.py` consumes
    (`edges`, `symbols`), so the path engine is reused untouched.
    """

    def __init__(self, project):
        self._p = project
        self.edges = project.strong_edges
        self.symbols = project.symbols

    def __getattr__(self, n):
        return getattr(self._p, n)


def _raices_de_producto(project) -> set[str]:
    from heatmap import _is_product
    return {s for s in project.product_roots
            if _is_product(project, project.symbols[s].file)}


def gates(project, inside: set[str]) -> set[str]:
    """The target symbols that are reached FROM OUTSIDE.

    Taking the whole target as the sink adds noise: the paths would end at any internal
    helper reachable on the rebound. The boundary —what somebody outside calls— is what
    actually works as the subsystem's entry door.
    """
    out: set[str] = set()
    for origin, targets in project.edges.items():
        if origin in inside:
            continue
        out |= targets & inside
    return out


def common_steps(paths: list[list[str]], project, threshold: float = STEP_THRESHOLD) -> list[dict]:
    """Nodes present ON the paths, by the fraction of paths crossing them.

    Different from `paths.discovered_guards`, which counts what the paths CALL without being
    on them. The root and the door are excluded: they are there by construction.
    """
    if not paths:
        return []
    count: Counter = Counter()
    for c in paths:
        count.update(set(c[1:-1]))
    total = len(paths)
    out = [{"name": project.symbols[n].name, "loc": project.symbols[n].loc,
              "fraccion": v / total, "en": v, "from": total}
             for n, v in count.items() if v / total >= threshold]
    return sorted(out, key=lambda x: (-x["fraccion"], x["loc"]))


def branchings(paths: list[list[str]], project, top: int = 5) -> list[dict]:
    """Where the flow DECIDES: the path nodes with the most distinct outputs.

    A node with twenty outputs is a dispatcher; reading those first explains the subsystem
    faster than reading the twenty targets.
    """
    seen = {n for c in paths for n in c}
    rows = [{"name": project.symbols[n].name, "loc": project.symbols[n].loc,
              "outputs": len(project.edges.get(n, ()))}
             for n in seen]
    return sorted((f for f in rows if f["outputs"] > 1),
                  key=lambda f: (-f["outputs"], f["loc"]))[:top]


def targets(project, inside: set[str], rank: dict[str, float], top: int = 8) -> list[dict]:
    """Where the flow continues: forward reachability, aggregated PER FILE.

    Per file and not per symbol because the question is "which subsystems does this talk
    to?", and a list of forty functions does not answer it. The TERMINALS are marked —what is
    reached and calls nothing further— because that is where the flow actually ends.
    """
    seen, queue = set(inside), list(inside)
    while queue:
        for d in project.edges.get(queue.pop(), ()):
            if d not in seen:
                seen.add(d)
                queue.append(d)
    afuera = seen - inside
    total = sum(rank.values()) or 1.0
    por_arch: dict[str, dict] = defaultdict(lambda: {"n": 0, "terminales": 0, "mass": 0.0})
    # SORTED: `afuera` is a set and the masses below are ACCUMULATED. Floating-point addition
    # is not associative, so the same set summed in a different order gave 0.023309784847592552
    # against ...555 — a difference in the last bits, invisible on screen, enough to change the
    # hash and enough to flip a rounded percentage sitting on a boundary.
    for sid in sorted(afuera):
        s = project.symbols[sid]
        e = por_arch[s.file]
        e["n"] += 1
        e["mass"] += rank.get(sid, 0.0) / total
        if not project.edges.get(sid):
            e["terminales"] += 1
    rows = [{"file": a, **v, "mass_pct": 100 * v["mass"]} for a, v in por_arch.items()]
    return sorted(rows, key=lambda f: (-f["mass_pct"], f["file"]))[:top], len(afuera)


def _for_sequence(project, paths: list[list[str]], rank: dict[str, float],
                    puertas_tope: int = 5, por_puerta: int = 3) -> list[list[str]]:
    """Which paths deserve to enter the sequence diagram.

    Two criteria, and the second is the one that matters: the doors with the most MASS are
    taken, and SEVERAL paths from each, not one. Keeping one per door looks cleaner and
    erases exactly what you want to see — CONVERGENCE: three different benchmark roots
    entering through the same `_enqueue_or_run` is the finding, and with one path per door it
    disappears. Within each door the LONG paths are preferred: a single hop does not show
    ninguna chain.
    """
    por_g: dict[str, list[list[str]]] = defaultdict(list)
    for c in paths:
        por_g[c[-1]].append(c)
    out = []
    for gate in sorted(por_g, key=lambda g: -rank.get(g, 0.0))[:puertas_tope]:
        for c in sorted(por_g[gate], key=len, reverse=True)[:por_puerta]:
            out.append([project.symbols[n].name for n in c])
    return out


def trace(project, inside: set[str], rank: dict[str, float], top: int = 6) -> dict:
    """The target's complete route. It reuses `paths.py`; it does not reimplement the graph."""
    view = _UnambiguousOnly(project)
    entries = gates(view, inside)
    if not entries:
        return {"error": "nothing from outside enters this target through an unambiguous "
                         "reference — not enough evidence to trace a flow"}

    # A root INSIDE the target produces a one-hop path that explains nothing:
    # the subsystem calling itself is not "how you get in".
    roots = _raices_de_producto(project) - inside
    paths = _paths.paths_to(view, entries, roots, top=PATH_CAP)
    guards = _paths.discovered_guards(paths, view, STEP_THRESHOLD)
    output, alcanzados = targets(view, inside, rank, top)

    # DECLARED ROOTS FIRST, then by mass. Measured over 5 subsystems: ordering by mass
    # alone, only 5 of the first 15 positions were a declared entry point; putting the roots
    # first, 12 of 15. And counting roots-that-reach (the original criterion) was worse
    # still: it rewarded the most-called leaves, so Ingestion's "entries" came out as
    # `get_source_by_id` and `fetch_next_job` — the database helpers.
    #
    # This is not a new heuristic: in this codebase an entry point IS something the framework
    # calls on its own —an MCP tool, a route, a worker handler— and that is already declared
    # in the `.toml`. The tool was using that data to seed PageRank and ignoring it here.
    # The ENTIRE BOUNDARY is ordered, not the path endpoints. `paths_to` excludes as an
    # origin the roots that live INSIDE the target (otherwise it produces one-hop paths that
    # explain nothing), so a declared entry of the subsystem itself —an MCP tool living
    # inside— never showed up as an endpoint. The header said "22 declared entries" and the
    # list showed one: they were counting different sets.
    declaradas = getattr(project, "product_roots", set())
    por_puerta: Counter = Counter(c[-1] for c in paths)
    # `entries` is a set, so two gates that are both declared and both weigh the same came out
    # in whatever order the process happened to hash them. The id closes the tie.
    gate_order = sorted(entries,
                           key=lambda p: (p not in declaradas, -rank.get(p, 0.0), p))
    # The example path is the LONGEST, not the shortest. `paths_to` returns the shortest per
    # root because for "does this root arrive without crossing a guard?" one is enough; here
    # the question is different —showing the chain— and a two-node path shows none.
    ejemplo = max(paths, key=lambda c: (len(c), c)) if paths else None
    return {
        "raices_que_llegan": len(paths),
        "gates": [{"name": project.symbols[p].name,
                     "loc": project.symbols[p].loc, "roots": por_puerta[p],
                     "declarada": p in declaradas,
                     "mass_pct": 100.0 * rank.get(p, 0.0) / (sum(rank.values()) or 1.0)}
                    for p in gate_order[:top]],
        "gates_total": len(entries),
        "puertas_declaradas": len(entries & set(declaradas)),
        "steps": common_steps(paths, view)[:top],
        "guards": guards[:top],
        "ramifica": branchings(paths, view, top),
        "targets": output,
        "alcanzados": alcanzados,
        "camino_ejemplo": [project.symbols[n].name for n in ejemplo] if ejemplo else [],
        "paths": _for_sequence(project, paths, rank),
    }


def _nickname(text: str, longest: int = 26) -> str:
    """A Mermaid-safe label: no quotes, no brackets, and truncated."""
    t = text.replace('"', "'").replace("[", "(").replace("]", ")")
    return t if len(t) <= longest else t[:longest - 1] + "…"


def neighbors_by_module(project, inside: set[str], files: set[str]) -> tuple[list, list]:
    """Who uses the target and what it depends on, aggregated per LINE OF WORK.

    Altitude matters: at symbol level, a subsystem's "doors" end up being its database
    helpers, because those are the most called. `Worker and scheduling → Ingestion →
    Persistence` says something about the architecture; `fetch_next_job` does not.

    Tests and scripts are excluded: they are CONSUMERS of the system, not part of its
    structure. Without that filter `tests/unit` tops the list with 165 references and buries
    the real modules.
    """
    from heatmap import _is_product
    cfg = project.cfg
    inbound: dict[str, float] = defaultdict(float)
    outbound: dict[str, float] = defaultdict(float)
    fuertes = getattr(project, "strong_edges", {})
    fuertes_mod = getattr(project, "strong_module_refs", {})

    for (origin, target_node), weight in project.weights.items():
        o_dentro = origin in inside or project.file_of(origin) in files
        d_inside = target_node in inside
        if o_dentro == d_inside:
            continue
        if not (target_node in fuertes.get(origin, ()) or target_node in fuertes_mod.get(origin, ())):
            continue
        other = project.file_of(origin if d_inside else target_node)
        if not _is_product(project, other):
            continue
        (inbound if d_inside else outbound)[cfg.module_of(other)] += weight

    call_order = lambda d: sorted(({"module": m, "refs": round(v, 1)} for m, v in d.items()),
                             key=lambda f: (-f["refs"], f["module"]))
    return call_order(inbound), call_order(outbound)


def _internal_parts(files: set[str], top: int = 5) -> list[dict]:
    """The target's pieces, grouped by directory. `ingest/`, `api/v1/routers/…`:
    the subsystem's internal shape without listing 31 files."""
    grupos: dict[str, int] = defaultdict(int)
    for a in sorted(files):
        parts = a.split("/")
        grupos["/".join(parts[:-1]) + "/" if len(parts) > 1 else parts[0]] += 1
    rows = [{"dir": d, "n": n} for d, n in grupos.items()]
    return sorted(rows, key=lambda f: (-f["n"], f["dir"]))[:top]


def mermaid_sequence(r: dict, target: str, tope_caminos: int = 9) -> str:
    """The real paths, merged into a DAG: who TRIGGERS, through which STEPS, and where it
    enters the subsystem.

    It is a genuine flow diagram and not a box map, because the paths already exist —
    `paths.paths_to` returns one per root— and they **converge**: three different benchmark
    roots enter Ingestion through the same `_enqueue_or_run → _enqueue_benchmark`. That
    convergence is the information: it is where the system decides once for many origins, and
    it is what to look at before adding a fourth origin.

    Here function names ARE the right unit, unlike in the module map: a step in a sequence is
    a function. What was wrong before was not using symbols, it was presenting database
    leaves as if they were entries.

    Paths are chosen by the MASS of their door and deduplicated per door: showing all 57
    would fill the screen with variants of the same route.
    """
    if "error" in r or not r.get("paths"):
        return f"flowchart LR\n  err[\"{_nickname(r.get('error', 'no paths to trace'), 60)}\"]"

    paths = r["paths"][:tope_caminos]
    ids: dict[str, str] = {}
    L = ["flowchart LR"]
    edges: set[tuple[str, str]] = set()
    roots = {path[0] for path in paths}
    puertas_ = {path[-1] for path in paths}

    for path in paths:
        for name in path:
            if name in ids:
                continue
            n = f"N{len(ids)}"
            ids[name] = n
            if name in roots:
                # stadium = a declared trigger point (a root from the .toml)
                L.append(f'  {n}(["{_nickname(name, 28)}"])')
            elif name in puertas_:
                L.append(f'  {n}["<b>{_nickname(name, 28)}</b>"]')
            else:
                L.append(f'  {n}["{_nickname(name, 28)}"]')
        for a, b in zip(path, path[1:]):
            edges.add((ids[a], ids[b]))

    L += [f"  {a} --> {b}" for a, b in sorted(edges)]
    L.append(f'  subgraph DENTRO["{_nickname(target, 26)}"]')
    L += [f"    {ids[n]}" for n in sorted(puertas_)]
    L.append("  end")

    if r.get("guards"):
        g = " · ".join(f'{x["name"]} {100*x["fraccion"]:.0f}%' for x in r["guards"][:3])
        L.append(f'  GUARD["crosses first:<br/>{_nickname(g, 70)}"]')
        L.append(f"  DENTRO -.-> GUARD")
        L.append("  style GUARD stroke-dasharray:4 4")

    # The crossing into another project is drawn with a THICK edge: it is not a local call,
    # it is a process hop over the network. Seeing it like an internal call is exactly the
    # mistake that hides the expensive failure modes.
    c = r.get("crossings") or {}
    for i, x in enumerate((c.get("entra") or [])[:4]):
        L.append(f'  IN{i}(["{_nickname(x["project"], 20)}<br/><i>{_nickname(x["literal"], 30)}</i>"])')
        L.append(f"  IN{i} ==> DENTRO")
    for i, x in enumerate((c.get("sale") or [])[:4]):
        L.append(f'  OUT{i}(["{_nickname(x["project"], 20)}<br/><i>{_nickname(x["literal"], 30)}</i>"])')
        L.append(f"  DENTRO ==> OUT{i}")
    return "\n".join(L)


def mermaid(r: dict, target: str, arriba: list, abajo: list, parts: list) -> str:
    """The subsystem as a map: who uses it, what it contains, what it depends on.

    AT SUBSYSTEM ALTITUDE, not symbol altitude. The previous version drew function names and
    was useless: Ingestion's "doors" came out as `get_source_by_id` and `fetch_next_job`
    —the database helpers— because they were ordered by how many roots reach them, and that
    rewards the most-called leaves, which are precisely the ones
    menos explican.

    Guards stay as functions because there the name IS the information: "it already crosses a
    tenant resolver" is what stops you writing the second one. They go in a single note, not
    one box each.

    Text and not an image on purpose: it fits in a markdown file, a commit or an agent's
    prompt, it is versioned and it diffs.
    """
    if "error" in r:
        return f"flowchart LR\n  err[\"{_nickname(r['error'], 60)}\"]"

    # `flowchart TB` with the groups STACKED, not `LR` with `direction TB` inside: Mermaid
    # does not reliably honor nested direction, and the 15 nodes ended up in a single
    # 3,566 px row — illegible in any reading column. Measured, not assumed.
    L = ["flowchart TB"]

    if arriba:
        L.append('  subgraph USA["who uses it"]')
        for i, m in enumerate(arriba[:5]):
            L.append(f'    U{i}["{_nickname(m["module"], 24)}<br/><i>{m["refs"]:.0f} refs</i>"]')
        L.append("  end")

    L.append(f'  subgraph OBJ["{_nickname(target, 28)}"]')
    for i, p in enumerate(parts):
        L.append(f'    P{i}["{_nickname(p["dir"], 30)}<br/><i>{p["n"]} arch</i>"]')
    L.append("  end")

    if abajo:
        L.append('  subgraph DEP["what it depends on"]')
        for i, m in enumerate(abajo[:5]):
            L.append(f'    D{i}["{_nickname(m["module"], 24)}<br/><i>{m["refs"]:.0f} refs</i>"]')
        L.append("  end")

    for i in range(len(arriba[:5])):
        L.append(f"  U{i} --> OBJ")
    for i in range(len(abajo[:5])):
        L.append(f"  OBJ --> D{i}")

    if r.get("guards"):
        guardias = " · ".join(f'{g["name"]} {100*g["fraccion"]:.0f}%'
                              for g in r["guards"][:3])
        L.append(f'  GUARD["crosses first:<br/>{_nickname(guardias, 70)}"]')
        L.append("  OBJ -.-> GUARD")          # sibling of the path, not a step
        L.append("  style GUARD stroke-dasharray:4 4")

    L.append("  style OBJ stroke-width:3px")
    return "\n".join(L)


def print_rows(r: dict):
    if "error" in r:
        print(f"\n  ── FLOW ── {r['error']}\n")
        return

    serv = r.get("services") or {}
    if serv:
        # Before touching anything: which processes this runs in. A change to shared code
        # forces restarting EVERY process that reaches it, and the one not restarted keeps
        # the old code in memory without signalling it.
        tot = r.get("files_total") or max(serv.values())
        print(f"\n  ── WHICH PROCESSES IT RUNS IN ── of the target's {tot} files ──")
        for s, n in sorted(serv.items(), key=lambda kv: -kv[1]):
            print(f"    {s:12s} {n:4d}/{tot}")
        if len(serv) > 1:
            print(f"    ⚠ {r.get('compartidos', 0)}/{tot} run in MORE THAN ONE: touching them "
                  f"forces restarting every process that reaches them")

    if r.get("usan") or r.get("depende"):
        # AT SUBSYSTEM ALTITUDE. Above, `orient` already listed neighbors per FILE; this is
        # the same relation one altitude up, which is where architecture is read.
        print("\n  ── ON THE MAP ── lines of work around it (no tests, no scripts) ──")
        for m in (r.get("usan") or [])[:5]:
            print(f"    {m['module']:28s} ──{m['refs']:6.0f} refs──▶  ({r['target']})")
        for m in (r.get("depende") or [])[:5]:
            print(f"    {'(' + r['target'] + ')':28s} ──{m['refs']:6.0f} refs──▶  {m['module']}")

    # A "door" is a symbol called from outside. That is the subsystem BOUNDARY, and only
    # part of it are real ENTRIES: in Ingestion, 2 of 79. Saying so keeps a list of database
    # accessors from being read as where the system is entered.
    print(f"\n  ── HOW YOU GET IN ── {r.get('puertas_declaradas', 0)} declared entries "
          f"of {r['gates_total']} symbols on the boundary · {r['raices_que_llegan']} roots ──")
    for p in r["gates"]:
        mark = "▶" if p.get("declarada") else " "
        print(f"   {mark} {p['mass_pct']:5.2f}%  {p['name']:32s} {p['loc']}")
    print("     ▶ = a declared entry point (tool, route, handler). The rest is boundary:")
    print("       they are called from outside, but that is not how you get in.")

    if r["steps"]:
        print("\n  ── WHERE IT GOES ── nodes ON the path ──")
        for p in r["steps"]:
            print(f"    {100*p['fraccion']:5.0f}%  {p['name']:34s} {p['loc']}")

    if r["guards"]:
        print("\n  ── WHAT IT CROSSES FIRST ── what the path CALLS without being on it ──")
        for p in r["guards"]:
            print(f"    {100*p['fraccion']:5.0f}%  {p['name']:34s} {p['loc']}")

    if r["ramifica"]:
        print("\n  ── WHERE IT DECIDES ── reading these first explains the subsystem ──")
        for p in r["ramifica"]:
            print(f"    {p['outputs']:3d} outputs  {p['name']:32s} {p['loc']}")

    if r["targets"]:
        print(f"\n  ── WHERE IT REACHES ── {r['alcanzados']} symbols reached ──")
        for d in r["targets"]:
            end = f" · {d['terminales']} end there" if d["terminales"] else ""
            print(f"    {d['mass_pct']:6.2f}%  {d['file']:48s} {d['n']:3d} sym{end}")

    if r["camino_ejemplo"]:
        print("\n  ── ONE CONCRETE PATH ── the longest, to verify by reading ──")
        print("    " + " → ".join(r["camino_ejemplo"]))
    print()
