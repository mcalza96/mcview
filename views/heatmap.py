"""Heat map — where the most-used code is, WITHOUT executing the system.

The question is not binary ("is this dead?") but continuous: **how much weight does each file
carry in the project's real usage?**

Model: a random walker starts at the declared entry points (routes, tools, commands) and
follows references. With probability `1-d` it teleports back to an entry. The stationary
distribution of that Markov chain is the fraction of time the walker spends in each symbol:
**an estimate of usage frequency derived from structure, not from traffic.**

It is personalized PageRank, and the personalization is what makes it correct here. Classic
PageRank teleports to any node — it models somebody who can start browsing on any page. A
program does not: **it always starts at an entry.** Seeding the jump at the roots is what
turns generic centrality into "how much this gets used when the system runs".

Two properties a reference count does not have:

* **Transitivity.** A helper called once, but from the heart of the system, weighs more than
  one called twenty times from a cold corner. A flat count says the opposite.
* **Mass distribution.** An ambiguous reference (homonyms) splits its mass across the
  candidates instead of counting as certainty for all of them.

IT DOES NOT PREDICT EXECUTION, AND THAT WAS MEASURED
----------------------------------------
This used to say "it does not replace the runtime census: it predicts it". That is false:
against the probe, the AUC of mass as a predictor of "it ran" comes out at **0.506** —0.50 is
predicting nothing— and the deciles are not even monotonic (the 7th runs 30%, the 1st 20.5%).
Ver `validar_heatmap.py`.

The claim above holds and this one does not, because they are different: mass **is**, by
definition, the fraction of time the walker spends in each symbol. That is true by
construction, like an average. "It predicts what will run" was an extra promise nobody needed
and the tool does not keep.

Practical consequence: mass orders by **structural centrality**, not by importance and not by
real frequency. A file at the top of the ranking is one that many paths from the roots go
through — which is exactly what it says, and nothing more.
"""
from __future__ import annotations

from collections import defaultdict

AMORTIGUACION = 0.85     # d — probability of following a reference
ITERACIONES = 60
TOLERANCIA = 1e-9


def _is_product(project, file: str) -> bool:
    """A root directory that is NOT product (tests, loose scripts) stays OUT of the map. They
    are consumers of the system, not part of its usage structure — and through homonyms they
    absorbed mass until they topped the ranking."""
    cfg = project.cfg
    if cfg.is_root_dir(file) and not cfg.is_product_dir(file):
        return False
    return True


def pagerank(project, d: float = AMORTIGUACION, solo_producto: bool = True) -> dict[str, float]:
    """Stationary distribution seeded at the project roots."""
    nodes = [n for n in project.symbols
             if not solo_producto or _is_product(project, project.symbols[n].file)]
    idx = {n: i for i, n in enumerate(nodes)}
    N = len(nodes)
    if not N:
        return {}

    # weighted outgoing edges; anything that is not a project symbol is ignored
    outgoing: list[list[tuple[int, float]]] = [[] for _ in range(N)]
    for (origin, target_node), w in project.weights.items():
        i, j = idx.get(origin), idx.get(target_node)
        if i is None or j is None or i == j:
            continue
        outgoing[i].append((j, float(w)))
    for i, lst in enumerate(outgoing):
        total = sum(w for _, w in lst)
        if total:
            outgoing[i] = [(j, w / total) for j, w in lst]

    # personalization vector: the walker ALWAYS reappears at an entry
    roots = [idx[r] for r in project.product_roots if r in idx]
    if not roots:
        roots = [idx[r] for r in project.roots if r in idx] or list(range(N))
    p = [0.0] * N
    for i in roots:
        p[i] = 1.0 / len(roots)

    rank = list(p)
    for _ in range(ITERACIONES):
        nuevo = [0.0] * N
        colgante = 0.0
        for i, r in enumerate(rank):
            if not r:
                continue
            if outgoing[i]:
                for j, w in outgoing[i]:
                    nuevo[j] += d * r * w
            else:
                colgante += r          # no outgoing edges: its mass returns to the entries
        fuga = (1.0 - d) + d * colgante
        for i in range(N):
            nuevo[i] += fuga * p[i]
        delta = sum(abs(nuevo[i] - rank[i]) for i in range(N))
        rank = nuevo
        if delta < TOLERANCIA:
            break

    return {nodes[i]: rank[i] for i in range(N)}


def by_file(project, rank: dict[str, float]) -> list[dict]:
    """Aggregates mass at file level — the unit that gets read and deleted."""
    mass: dict[str, float] = defaultdict(float)
    count: dict[str, int] = defaultdict(int)
    frios: dict[str, int] = defaultdict(int)
    for sid, r in rank.items():
        s = project.symbols[sid]
        mass[s.file] += r
        count[s.file] += 1
        if r <= 1e-12:
            frios[s.file] += 1

    total = sum(mass.values()) or 1.0
    rows = [{
        "file": a,
        "mass": m,
        "pct": 100.0 * m / total,
        "symbols": count[a],
        "frios": frios[a],
    } for a, m in mass.items()]
    rows.sort(key=lambda f: -f["mass"])
    return rows


def concentration(rows: list[dict]) -> dict:
    """How uneven the split is: how many files concentrate half the usage."""
    acumulado, mitad, ochenta = 0.0, None, None
    for i, f in enumerate(rows, 1):
        acumulado += f["pct"]
        if mitad is None and acumulado >= 50:
            mitad = i
        if ochenta is None and acumulado >= 80:
            ochenta = i
            break
    return {"archivos_50pct": mitad, "archivos_80pct": ochenta, "total": len(rows)}


def by_module(project, rank: dict[str, float]) -> list[dict]:
    """Aggregates mass per LINE OF WORK. A module lives in several directories:
    "retrieval" touches store/, api/v1/mcp_tools/ and api/v1/routers/ at once."""
    cfg = project.cfg
    mass, simb, arch, frios = (defaultdict(float), defaultdict(int),
                               defaultdict(set), defaultdict(int))
    for sid, r in rank.items():
        s = project.symbols[sid]
        m = cfg.module_of(s.file)
        mass[m] += r
        simb[m] += 1
        arch[m].add(s.file)
        if r <= 1e-12:
            frios[m] += 1
    total = sum(mass.values()) or 1.0
    rows = [{"module": m, "pct": 100.0 * v / total, "symbols": simb[m],
              "files": len(arch[m]), "frios": frios[m],
              "area": cfg.area_of(sorted(arch[m])[0])} for m, v in mass.items()]
    rows.sort(key=lambda f: -f["pct"])
    return rows


def deletion_risk(project, dead, rank) -> list[dict]:
    """Orders the dead candidates from SAFEST to RISKIEST to delete.

    One candidate is not worth the same as another. Two signals, both from the usage map:

      surroundings  LIVE mass of the file it lives in
      outgoing      mass of what the symbol INVOKES

    WHAT IT MEASURES, precisely: **impact if the verdict is wrong**, not the probability that
    it is. A dead symbol surrounded by hot code, if we are wrong, breaks something heavily
    used; one in a cold file breaks nothing. Risk = probability × impact, and this is the
    second factor.

    The original hypothesis was the other one —"dead in a hot file = more likely a false
    positive"— and it was REFUTED by hand-checking the four worst
    rankeados: `set_role` (0 usos), `reset_async_supabase_client` (0),
    `timer` (1 mention, in a comment), `rotate_master_key` (2, both in comments). Four out of
    four genuinely dead. A small sample, but unanimously against.

    Both are normalized to [0,1] before combining: raw, the outgoing one is two orders of
    magnitude larger and the score collapses to a single term.

    It does NOT change the verdict — a DEAD_CANDIDATE remains a hypothesis. It changes the ORDER
    in which they are worth attacking.
    """
    from collections import defaultdict
    total = sum(rank.values()) or 1.0
    live_mass, alive, todos = defaultdict(float), defaultdict(int), defaultdict(int)
    for sid, s in project.symbols.items():
        todos[s.file] += 1
        if sid not in dead:
            alive[s.file] += 1
            live_mass[s.file] += rank.get(sid, 0.0)

    rows = []
    for sid in dead:
        s = project.symbols[sid]
        rows.append({
            "name": s.name, "kind": s.kind, "loc": s.loc, "file": s.file,
            "surroundings": live_mass[s.file] / total,
            "outgoing": sum(rank.get(t, 0.0) for t in project.edges.get(sid, ())) / total,
            "dead_frac": (todos[s.file] - alive[s.file]) / max(todos[s.file], 1),
        })
    for key in ("surroundings", "outgoing"):
        mx = max((f[key] for f in rows), default=0.0) or 1.0
        for f in rows:
            f[key + "_n"] = f[key] / mx
    for f in rows:
        f["risk"] = round(0.5 * f["surroundings_n"] * (1 - f["dead_frac"])
                            + 0.5 * f["outgoing_n"], 4)
    rows.sort(key=lambda f: f["risk"])
    return rows
