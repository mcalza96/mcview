# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""FOCUSED ORIENTATION — a task's context, computed rather than written.

Every other `mcview` view is GLOBAL: the heat map lists 334 files, `--modules` lists 25 lines
of work. To get oriented before touching ONE area, 90% of that is noise — and context paid
for in tokens and never used is exactly the waste this tool exists to avoid.

This view answers a different question:

    I am about to work on X. What do I need to know about the structure, and only about X?

WHAT IT REPLACES AND WHAT IT DOES NOT
-----------------------
It replaces the STRUCTURAL prose —who calls what, what is dead, where the system goes— which
is precisely the half of documentation that rots. It is computed from today's AST, so it
cannot be out of date by construction.

It does NOT replace the DECISIONS: why something was chosen, what was measured, what was
refuted. No Markov chain recovers "this view was tried and added nothing". That still lives
in memory, and this view does not pretend to replace it.

ORDERING IS BY MASS, NOT BY COUNT
------------------------------------
Neighbors are ordered by the mass of the file on the other side, not by how many times it
references. A helper called once from the heart of the system matters more than one called
twenty times from a cold corner; a flat count says the opposite. It is the same property that
makes the heat map correct (`heatmap.py`).

THE COHESION HERE IS NOT THE ONE FROM `--hierarchy`
---------------------------------------------
It is computed over the core's weights, with the COMPLETE graph. `--hierarchy` computes it
over the adjacency without the top 1% of hubs, because 21 symbols concentrate 47% of the
edges. The two numbers answer the same question and are NOT interchangeable — which is why
the output says where this one comes from.
"""
from __future__ import annotations

from collections import defaultdict

FRIO = 1e-12          # same threshold as heatmap.by_file
COHESION_MINIMA = 0.15  # below this it is not a module: it is crosscutting infrastructure


# ------------------------------------------------------------------ resolve
def resolve(project, target: str) -> dict:
    """A target can be a declared module, a path, or a symbol name.

    They are tried in that order and the first that resolves wins. Nothing is guessed: if
    nothing resolves, the candidates are returned so the asker can choose. A target silently
    resolved wrong would produce a brief about something else, which is worse than producing
    none.
    """
    cfg = project.cfg
    obj = target.strip().rstrip("/")
    plegado = obj.casefold()

    # 0 — DECLARED SURFACE, and it goes first because it is the most specific thing anybody
    # said about this project: a module is where code lives, a surface is where a USER comes
    # in. Until this existed, declaring `[surfaces]` changed nothing about where a flow began
    # — the walk still started at the heaviest symbol, and the warning that told you to name
    # your doors was promising something the tool did not do. Measured: asking for a surface
    # by name matched a module by substring instead and anchored the narrative 58 symbols away
    # from any door.
    for name, targets in (getattr(cfg, "surfaces", {}) or {}).items():
        if name.casefold() != plegado:
            continue
        archivos: set[str] = set()
        for t in targets:
            d = resolve(project, t)
            if "error" not in d:
                archivos |= set(d.get("files", ()))
        if archivos:
            # The SAME shape the other resolvers return —`kind`, `name`, `files`— and not one
            # of my own invention: the consumers read `name`, and a fourth shape crashed
            # `--orient` with a KeyError the moment a surface was asked for by name.
            return {"kind": "surface", "name": name, "files": sorted(archivos)}

    # 1 — declared module (exact, then by prefix)
    for name in cfg.modules:
        if name.casefold() == plegado:
            return _by_module(project, name)
    coincidencias = [n for n in cfg.modules if plegado in n.casefold()]
    if len(coincidencias) == 1:
        return _by_module(project, coincidencias[0])

    # 2 — path: file or directory, relative to the project root
    files = sorted(a for a in project.by_file
                      if a == obj or a.startswith(obj + "/"))
    if files:
        return {"kind": "path", "name": obj, "files": files}

    # 3 — symbol name: it orients on the file where it lives
    if obj in project.by_name:
        files = sorted({project.symbols[s].file for s in project.by_name[obj]})
        return {"kind": "symbol", "name": obj, "files": files}

    # 4 — a seam LITERAL: a table, an RPC, a route, a tool.
    # It is not a symbol, which is why until now this came out as "did not resolve" —
    # measured: a session investigating access went blind on `platform_access_grants` and
    # fell back to grep. The target is not a function, it is a RESOURCE, and what you want to
    # know is who touches it.
    import seams as _seams
    findings = _seams.search(_seams.detect(project), obj)
    if findings:
        files = sorted({loc.split(":")[0] for _, _, locs in findings for loc in locs})
        return {"kind": "seam", "name": obj, "files": files,
                "seam": [{"side": l, "kind": t, "where": locs} for l, t, locs in findings]}

    return {"error": f"did not resolve: {target}",
            "modules": sorted(cfg.modules),
            "coincidencias": coincidencias}


def _by_module(project, name: str) -> dict:
    cfg = project.cfg
    files = sorted(a for a in project.by_file if cfg.module_of(a) == name)
    return {"kind": "module", "name": name, "files": files}


# ------------------------------------------------------------------- neighbors
def neighbors(project, inside: set[str], files: set[str],
            file_mass: dict[str, float]) -> dict:
    """Who enters the target and where it exits to, aggregated per file.

    Ordered by the mass of the file on the OTHER side: the useful question before touching
    something is not how many call it but whether something the system goes through calls it.

    An edge's origin can be a file rather than a symbol —module-level code executes on import
    and its references count— so membership in the target is decided per file in both cases.
    Without that, an import of the target itself would count as coming from outside.

    ONLY WHAT HAS AT LEAST ONE UNAMBIGUOUS REFERENCE IS LISTED. Ordering by mass alone let in
    neighbors with `0.0 refs`: an attribute reference split across homonyms weighs 0.06, and
    because the file on the other side was hot it topped the list anyway. That is exactly the
    evidence the core calls weak (`ALIVE_PRODUCT_WEAK`), and presenting it as a dependency
    claims too much. The ambiguous ones do not disappear: they are counted separately, because
    knowing they are there is information.
    """
    incoming: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    outgoing: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    fuertes = getattr(project, "strong_edges", {})
    strong_module = getattr(project, "strong_module_refs", {})

    for (origin, target_node), weight in project.weights.items():
        o_dentro = origin in inside or project.file_of(origin) in files
        d_inside = target_node in inside
        if o_dentro == d_inside:
            continue                      # interno, o ajeno al target
        unambiguous = (target_node in fuertes.get(origin, ())
                      or target_node in strong_module.get(origin, ()))
        side = incoming if d_inside else outgoing
        other = project.file_of(origin if d_inside else target_node)
        side[other][0] += weight
        side[other][1] += weight if unambiguous else 0.0

    def _rows(agregado):
        rows = [{"file": a, "refs": round(p, 1),
                  "mass_pct": 100.0 * file_mass.get(a, 0.0)}
                 for a, (p, f) in agregado.items() if f > 0]
        rows.sort(key=lambda f: (-f["mass_pct"], -f["refs"]))
        return rows, sum(1 for p, f in agregado.values() if f <= 0)

    inbound, ent_amb = _rows(incoming)
    outbound, sal_amb = _rows(outgoing)
    return {"incoming": inbound, "outgoing": outbound,
            "incoming_ambiguous": ent_amb, "outgoing_ambiguous": sal_amb}


def cohesion(project, inside: set[str]) -> float:
    """The fraction of the target's references that stay inside it.

    Over the complete graph (see the header: `--hierarchy` measures it without hubs). Below
    COHESION_MINIMA the target is not a unit: it is crosscutting.
    """
    internal = total = 0.0
    for (origin, target_node), weight in project.weights.items():
        if origin not in inside:
            continue
        total += weight
        if target_node in inside:
            internal += weight
    return internal / total if total else 0.0


# -------------------------------------------------------------------- armado
def orient(project, rank: dict[str, float], levels: dict[str, set[str]],
             dups: dict | None, target: str, top: int = 8) -> dict:
    """The complete brief for a target. Everything expensive (rank, levels, duplicates) arrives
    precomputed: this view composes, it does not recompute."""
    target_node = resolve(project, target)
    if "error" in target_node:
        return target_node

    files = set(target_node["files"])
    inside = {sid for sid, s in project.symbols.items() if s.file in files}
    if not inside:
        return {"error": f"{target_node['name']} has no analyzable symbols"}

    total_mass = sum(rank.values()) or 1.0
    file_mass: dict[str, float] = defaultdict(float)
    for sid, r in rank.items():
        file_mass[project.symbols[sid].file] += r / total_mass

    target_mass = sum(file_mass[a] for a in files)

    # temperature: how liveness is distributed inside the target
    temperatura = {status: len(inside & sids) for status, sids in levels.items()}
    frios = sum(1 for sid in inside if rank.get(sid, 0.0) <= FRIO)

    calientes = sorted(
        ({"symbol": project.symbols[sid].name,
          "loc": project.symbols[sid].loc,
          "mass_pct": 100.0 * rank[sid] / total_mass}
         for sid in inside if rank.get(sid, 0.0) > FRIO),
        key=lambda f: (-f["mass_pct"], f["loc"]))[:top]

    v = neighbors(project, inside, files, file_mass)
    cfg = project.cfg

    out = {
        "target": target_node["name"],
        "kind": target_node["kind"],
        "seam": target_node.get("seam"),
        "files": sorted(files),
        "symbols": len(inside),
        "mass_pct": 100.0 * target_mass,
        "cohesion": round(cohesion(project, inside), 3),
        "transversal_declarado": target_node["name"] in cfg.crosscutting_modules,
        "temperatura": temperatura,
        "frios": frios,
        "calientes": calientes,
        "incoming": v["incoming"][:top],
        "outgoing": v["outgoing"][:top],
        "incoming_total": len(v["incoming"]),
        "outgoing_total": len(v["outgoing"]),
        "incoming_ambiguous": v["incoming_ambiguous"],
        "outgoing_ambiguous": v["outgoing_ambiguous"],
        "duplicates": _duplicates_of_target(dups, files, top) if dups else [],
    }
    return out


def _duplicates_of_target(dups: dict, files: set[str], top: int) -> list[dict]:
    """The twins that TOUCH the target — the "this already exists" before writing."""
    out = []
    for grupo in dups.get("type12", []):
        symbols = grupo["symbols"]
        if any(s.file in files for s in symbols):
            out.append({"kind": "identical", "jaccard": 1.0,
                          "what": sorted({s.name for s in symbols})[0],
                          "where": [s.loc for s in symbols]})
    for pair in dups.get("type3", []):
        a, b = pair["a"], pair["b"]
        if a.file in files or b.file in files:
            out.append({"kind": "casi", "jaccard": round(pair["jaccard"], 2),
                          "what": a.name, "where": [a.loc, b.loc]})
    return out[:top]


# -------------------------------------------------------------------- printing
def print_rows(r: dict):
    if "error" in r:
        print(f"\n  {r['error']}")
        if r.get("coincidencias"):
            print("  ambiguous between: " + ", ".join(r["coincidencias"]))
        elif r.get("modules"):
            print("  declared modules: " + ", ".join(r["modules"]))
        print()
        return

    print(f"\n  ORIENTATION — {r['target']}   ({r['kind']})")
    if r.get("seam"):
        print("  not a symbol: a RESOURCE. Who touches it:")
        for c in r["seam"]:
            print(f"    {c['side']}/{c['kind']}  ×{len(c['where'])}")
            for d in c["where"][:6]:
                print(f"        {d}")
            if len(c["where"]) > 6:
                print(f"        … and {len(c['where']) - 6} more")
    print(f"  {len(r['files'])} files · {r['symbols']} symbols · "
          f"{r['mass_pct']:.2f}% of the project's mass\n")

    coh = r["cohesion"]
    note = ""
    if coh < COHESION_MINIMA:
        note = ("  ← below 0.15: not a unit, this is crosscutting infrastructure"
                if not r["transversal_declarado"] else "  ← crosscutting, already declared as such")
    print(f"  cohesion {coh:.2f}{note}")
    print("  (complete graph; --hierarchy measures it without hubs — not interchangeable)\n")

    print("  ── TEMPERATURE ────────────────────────────────────────────")
    for status, n in sorted(r["temperatura"].items(), key=lambda kv: -kv[1]):
        if n:
            print(f"    {status:22s} {n:4d}")
    print(f"    {'cold (mass ~0)':22s} {r['frios']:4d}   "
          f"referenced, but the system does not go through them")

    if r["calientes"]:
        print("\n  ── WHERE IT GOES, INSIDE ──────────────────────────────────")
        for c in r["calientes"]:
            print(f"    {c['mass_pct']:6.2f}%  {c['symbol']:32s} {c['loc']}")

    for etq, key in (("WHO USES IT", "incoming"), ("WHAT IT DEPENDS ON", "outgoing")):
        rows = r[key]
        if not rows:
            continue
        ambiguous = r[key + "_ambiguous"]
        print(f"\n  ── {etq} ── ordered by the mass of the other side "
              f"({len(rows)} of {r[key + '_total']}) ──")
        for f in rows:
            print(f"    {f['mass_pct']:6.2f}%  {f['file']:52s} {f['refs']:6.1f} refs")
        if ambiguous:
            print(f"    (+{ambiguous} files linked ONLY by an ambiguous name — "
                  f"weak evidence, not listed)")

    if r["duplicates"]:
        print("\n  ── ALREADY EXISTS ─────────────────────────────────────────")
        for d in r["duplicates"]:
            print(f"    {d['kind']:9s} ({d['jaccard']:.2f})  ×{len(d['where'])}  {d['what']}")
            for where in d["where"]:
                print(f"                          {where}")
    print()
