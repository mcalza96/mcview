"""The SKELETON of a conceptual diagram — everything a drawing needs except the meaning.

Somebody who is not reading the code line by line wants a picture: the user comes in HERE, it
goes through THIS which is responsible for THAT, and from there it can go to these others. That
picture is worth having and this tool cannot draw it, because half of it is a statement about
responsibility and nothing in an AST knows what a module is FOR.

So the work is split where the evidence splits:

    computed here      the nodes, the edges, their weight and their grade of evidence, the
                       doors, and the CUTS — where the graph provably cannot continue
    supplied by whoever draws it   what each node is responsible for, in one line

That split is the whole point, and it is not a division of labour: it is a SAFETY property.
The reader of this diagram is, by construction, someone who is not going to verify it against
the code. For that reader an invented edge is worse than no diagram at all — it looks
authoritative, it is the only thing they will look at, and they have no way to check it. By
emitting the skeleton already correct, whoever labels it CANNOT invent a connection. The worst
they can do is misname a node, which is visible and cheap.

Every id here is stable and checkable: a drawing that mentions a node or an edge absent from
this output is fabricated, and that can be tested rather than trusted.

AGGREGATED BY LINE OF WORK, which is where the honesty lives. `[modules]` is a declaration —
"retrieval" is three directories at once — and without it the grouping falls back to the
2-level directory, which measures physical proximity and not responsibility. That fallback is
REPORTED (`grouping: "directory"`), because a diagram of folders labelled as responsibilities
is exactly the confident-and-wrong artifact this whole file exists to avoid.
"""
from __future__ import annotations

from collections import defaultdict

CAVEATS = {
    "mass": "structural centrality, MEASURED not to predict execution (AUC 0.506). It says "
            "where the system passes through, never what is most important.",
    "edges": "the WRITTEN call graph. A call inside an `if` is here; one made by dynamic "
             "dispatch is not.",
    "unambiguous": "an edge is `unambiguous` when the name it resolves through belongs to a "
                   "single symbol. The rest may be homonyms — reach you cannot stand on.",
    "cuts": "where the graph provably stops. A diagram must show the cut, not bridge it: on "
            "the other side something chooses by name, and no static edge crosses that.",
    "dead": "DEAD_CANDIDATE is a hypothesis with no static evidence of use, never a deletion "
            "order.",
}


def build(project, rank: dict[str, float], obs: dict[str, int] | None = None) -> dict:
    """The conceptual graph of the whole system, at the level of lines of work."""
    cfg = project.cfg
    levels = project.levels()
    nivel_de = {s: lv for lv, ss in levels.items() for s in ss}

    # -- nodes ----------------------------------------------------------------
    masa, simbolos, archivos, frios = (defaultdict(float), defaultdict(int),
                                       defaultdict(set), defaultdict(int))
    por_nivel: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    ejecutados: dict[str, int] = defaultdict(int)
    for sid, r in rank.items():
        s = project.symbols[sid]
        m = cfg.module_of(s.file)
        masa[m] += r
        simbolos[m] += 1
        archivos[m].add(s.file)
        if r <= 1e-12:
            frios[m] += 1
        por_nivel[m][nivel_de.get(sid, "")] += 1
        if obs is not None and sid in obs:
            ejecutados[m] += 1
    total = sum(masa.values()) or 1.0

    nodes = []
    for m in sorted(masa, key=lambda x: -masa[x]):
        n = {
            "id": m,
            # Deliberately EMPTY. It is the one field this module cannot fill, and leaving it
            # named and blank is what turns "we did not compute it" into a visible hole rather
            # than an absence nobody notices.
            "responsibility": None,
            "symbols": simbolos[m], "files": len(archivos[m]),
            "mass_pct": round(100.0 * masa[m] / total, 2),
            "cold": frios[m],
            "levels": {k: v for k, v in por_nivel[m].items() if k},
            "area": cfg.area_of(sorted(archivos[m])[0]),
        }
        if obs is not None:
            n["seen_running"] = ejecutados[m]
        nodes.append(n)
    conocidos = {n["id"] for n in nodes}

    # -- edges ----------------------------------------------------------------
    # TWO counts per edge and not one, for the same reason the reach set reports two closures:
    # a module pair joined only through a shared name is not joined. Measured elsewhere in this
    # tool, that difference was 553 reachable symbols against 1 that held up.
    refs: dict[tuple[str, str], int] = defaultdict(int)
    fuertes: dict[tuple[str, str], int] = defaultdict(int)
    muestra: dict[tuple[str, str], list[str]] = defaultdict(list)
    for o, ds in project.edges.items():
        so = project.symbols.get(o)
        if not so:
            continue
        a = cfg.module_of(so.file)
        firmes = project.strong_edges.get(o, ())
        for d in ds:
            sd = project.symbols.get(d)
            if not sd:
                continue
            b = cfg.module_of(sd.file)
            if a == b:
                continue                 # inside a node; the diagram is between nodes
            refs[(a, b)] += 1
            if d in firmes:
                fuertes[(a, b)] += 1
                if len(muestra[(a, b)]) < 3:
                    # Concrete evidence, so a reader can go and check ONE line instead of
                    # believing the arrow.
                    muestra[(a, b)].append(f"{so.file}:{so.line} {so.name} → "
                                           f"{sd.file}:{sd.line} {sd.name}")

    edges = [{"from": a, "to": b, "refs": n, "unambiguous": fuertes[(a, b)],
              "evidence": muestra[(a, b)]}
             for (a, b), n in sorted(refs.items(), key=lambda x: -x[1])
             if a in conocidos and b in conocidos]

    # -- doors ----------------------------------------------------------------
    import locks as _locks

    doors = []
    for nombre, objetivos in (getattr(cfg, "surfaces", {}) or {}).items():
        alcanza: set[str] = set()
        for o in objetivos:
            ids, err = _locks._resolve(project, o)
            if not err:
                alcanza |= {cfg.module_of(project.symbols[i].file)
                            for i in ids if i in project.symbols}
        doors.append({"id": nombre, "declared": list(objetivos),
                      "enters": sorted(alcanza)})

    # -- cuts -----------------------------------------------------------------
    # The most important thing on the drawing, and the easiest to leave out. A diagram that
    # joins both sides of a dispatch is telling the reader a call happens where in fact
    # something picks a name out of a table.
    cuts = []
    disp = getattr(cfg, "dispatch", {}) or {}
    if disp:
        cuts.append({"kind": "dispatch", "at": disp.get("at"), "opens": disp.get("opens"),
                     "note": "beyond this point the target is chosen BY NAME. No edge in this "
                             "graph crosses it — draw it as a cut, never as an arrow."})
    for etiqueta, lits in (getattr(cfg, "seams", {}) or {}).items():
        if etiqueta in ("inert", "selectors") or not lits:
            continue
        cuts.append({"kind": "seam", "id": etiqueta, "literals": list(lits)[:8],
                     "note": "the join to another repository travels as a literal, not as a "
                             "call."})

    return {
        "project": cfg.name,
        "grouping": "declared" if cfg.modules else "directory",
        "grouping_note": (None if cfg.modules else
                          "no [modules] in the .toml: these nodes are DIRECTORIES, which "
                          "measure physical proximity and not responsibility. Label them as "
                          "folders or declare the lines of work first."),
        "nodes": nodes, "edges": edges, "doors": doors, "cuts": cuts,
        "caveats": CAVEATS,
        "for_whoever_draws_it": [
            "Fill `responsibility` on each node: one line, what it is FOR.",
            "Do NOT add nodes or edges. Every id you draw must appear above; anything else "
            "is fabricated and the reader has no way to notice.",
            "Draw `cuts` as cuts. Joining both sides of a dispatch invents a call.",
            "An edge with `unambiguous: 0` is weak evidence — draw it dashed or leave it out.",
            "If you cannot name a node, say so. An unnamed node is honest; a guessed one is "
            "the failure this output exists to prevent.",
        ],
    }


def report(r: dict) -> str:
    f = [f"\n  BLUEPRINT — {r['project']}",
         f"  {len(r['nodes'])} nodes · {len(r['edges'])} edges · {len(r['doors'])} doors · "
         f"{len(r['cuts'])} cuts    (grouping: {r['grouping']})\n"]
    if r["grouping_note"]:
        f += [f"  ⚠ {r['grouping_note']}\n"]
    ancho = max((len(n["id"]) for n in r["nodes"]), default=8)
    f.append(f"  {'node':{ancho}}  {'sym':>5} {'mass':>7} {'cold':>5}   responsibility")
    f.append("  " + "-" * (ancho + 34))
    for n in r["nodes"][:25]:
        f.append(f"  {n['id'][:ancho]:{ancho}}  {n['symbols']:5} {n['mass_pct']:6.2f}% "
                 f"{n['cold']:5}   {n['responsibility'] or '— to be named'}")
    if len(r["nodes"]) > 25:
        f.append(f"  … and {len(r['nodes']) - 25} more nodes")

    f.append(f"\n  EDGES (refs · unambiguous)")
    for e in r["edges"][:15]:
        f.append(f"  {e['from'][:24]:24} → {e['to'][:24]:24} {e['refs']:5} · "
                 f"{e['unambiguous']}")
    if len(r["edges"]) > 15:
        f.append(f"  … and {len(r['edges']) - 15} more edges")

    if r["doors"]:
        f.append("\n  DOORS")
        for d in r["doors"]:
            entra = ", ".join(d["enters"][:4]) or "(resolves to nothing)"
            f.append(f"  {d['id'][:24]:24} → {entra}")
    if r["cuts"]:
        f.append("\n  CUTS — the graph stops here; do not draw an arrow across")
        for c in r["cuts"]:
            f.append(f"  {c['kind']}: {c.get('at') or c.get('id')}")
    f.append("\n  --json gives the whole thing, with per-edge evidence and the caveats.")
    return "\n".join(f) + "\n"
