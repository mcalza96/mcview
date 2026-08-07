"""DISCOVERED lines of work — the same Markov chain, a different question.

The heat map asks *where the walker spends time*. A module is something else: a region the
walker **struggles to leave**. That does not have to be declared — it can be discovered from
the same graph.

Method: Markov Clustering (MCL). Two operations alternate over the transition matrix:

    expansion  (M @ M)   — the walker takes two steps: it flows where there is a path
    inflation  (M ** r)   — differences get exaggerated: strong paths reinforce, weak ones
                            evaporate

Iterating, the flow concentrates in densely connected regions and is cut off
between them. The resulting groups are the modules.

**Inflation is the granularity knob, and that is why sub-lines come for free:** a low `r`
produces a few coarse lines; a high one splits them into sub-lines. No separate algorithm is
needed per level — it is the same one, more inflated.

What this does NOT do: name them. The groups come out as sets of symbols. Naming them is a
job for a human or an LLM (last and narrow).

And the most useful part is not the result but the **disagreement with what was declared**:
if a module you declared splits in two, the name hides two things; if two you declared merge,
they are one.
"""
from __future__ import annotations

from collections import defaultdict


def nodes_of(project, solo_producto=True, solo_nucleo=True, quitar_hubs=0.01):
    """The set of symbols clustering runs over. Shared by every view: if each used different
    nodes, the matrices would not be addable."""
    from heatmap import _is_product
    cfg = project.cfg
    nodes = [n for n in project.symbols
             if (not solo_producto or _is_product(project, project.symbols[n].file))
             and (not solo_nucleo or cfg.area_of(project.symbols[n].file) == "core")]
    if quitar_hubs:
        grado = defaultdict(float)
        for (o, d), w in project.weights.items():
            grado[o] += w
            grado[d] += w
        ranking = sorted(nodes, key=lambda n: -grado.get(n, 0.0))
        hubs = set(ranking[:max(1, int(len(ranking) * quitar_hubs))])
        nodes = [n for n in nodes if n not in hubs]
    return nodes


def adjacency(project, nodes):
    """STRUCTURAL view: who references whom, symmetrized."""
    import numpy as np
    import scipy.sparse as sp
    idx = {n: i for i, n in enumerate(nodes)}
    fi, co, va = [], [], []
    for (o, d), w in project.weights.items():
        i, j = idx.get(o), idx.get(d)
        if i is None or j is None or i == j:
            continue
        fi += [i, j]
        co += [j, i]
        va += [float(w), float(w)]
    A = sp.csr_matrix((va, (fi, co)), shape=(len(nodes), len(nodes)), dtype=np.float32)
    A.sum_duplicates()
    return A


def cluster(project, inflation: float = 1.8, iteraciones: int = 24,
                poda: float = 1e-5, solo_producto: bool = True,
                solo_nucleo: bool = True, quitar_hubs: float = 0.01):
    """MCL over the reference graph. Returns a list of id sets."""
    import numpy as np

    from heatmap import _is_product

    cfg = project.cfg
    nodes = [n for n in project.symbols
             if (not solo_producto or _is_product(project, project.symbols[n].file))
             and (not solo_nucleo or cfg.area_of(project.symbols[n].file) == "core")]

    # HUBS OUT. Common infra (`get`, `ApiError`, `get_tenant_id`) touches everything and
    # GLUES the modules into a single block: without this, one group took 1,169
    # symbols and 79.6% of the mass. Removing connectors is standard practice in
    # community detection — they belong to no module, they belong to all of them.
    if quitar_hubs:
        grado = defaultdict(float)
        for (o, d), w in project.weights.items():
            grado[o] += w
            grado[d] += w
        ranking = sorted(nodes, key=lambda n: -grado.get(n, 0.0))
        corte = max(1, int(len(ranking) * quitar_hubs))
        hubs = set(ranking[:corte])
        nodes = [n for n in nodes if n not in hubs]
    idx = {n: i for i, n in enumerate(nodes)}
    N = len(nodes)
    if N == 0:
        return []

    # SPARSE, not dense. The N×N matrix was an implementation choice, not a requirement
    # of the method: the Markov chain only needs the edges that
    # EXIST. Measured on CIRE's core: 2.76% density — 36× more memory, and in a repo of
    # 40k symbols the dense one is simply unworkable.
    import scipy.sparse as sp

    fi, co, va = [], [], []
    for (o, d), w in project.weights.items():
        i, j = idx.get(o), idx.get(d)
        if i is None or j is None:
            continue
        # symmetric: for clustering, what matters is that they are related, not the direction
        fi.append(i); co.append(j); va.append(float(w))
        fi.append(j); co.append(i); va.append(float(w))
    M = sp.csr_matrix((va, (fi, co)), shape=(N, N), dtype=np.float32)
    M.sum_duplicates()
    M.setdiag(np.asarray(M.max(axis=1).todense()).ravel())   # self-loop: it stabilizes

    def normalize(X):
        s = np.asarray(X.sum(axis=0)).ravel()
        s[s == 0] = 1.0
        return X @ sp.diags(1.0 / s)

    def prune(X, top_k=40):
        """Without pruning, expansion densifies the matrix and the advantage is lost."""
        X = X.tocsc()
        X.data[X.data < poda] = 0.0
        X.eliminate_zeros()
        if top_k:
            X = X.tocsc()
            for c in range(X.shape[1]):
                ini, end = X.indptr[c], X.indptr[c + 1]
                if end - ini > top_k:
                    tramo = X.data[ini:end]
                    corte = np.partition(tramo, -top_k)[-top_k]
                    tramo[tramo < corte] = 0.0
            X.eliminate_zeros()
        return X.tocsr()

    M = normalize(M)
    for _ in range(iteraciones):
        M = M @ M                                   # expansion
        M.data **= inflation                        # inflation
        M = normalize(prune(M))

    grupos: dict[int, set] = defaultdict(set)
    Mc = M.tocsc()
    for j in range(N):
        ini, end = Mc.indptr[j], Mc.indptr[j + 1]
        if end == ini:
            continue
        owner = int(Mc.indices[ini + int(np.argmax(Mc.data[ini:end]))])
        grupos[owner].add(nodes[j])
    return sorted(grupos.values(), key=len, reverse=True)


def describe(project, grupo, rank=None) -> dict:
    """Summarizes a group by its files and its dominant declared module."""
    cfg = project.cfg
    arch, mods = defaultdict(int), defaultdict(int)
    for sid in grupo:
        s = project.symbols[sid]
        arch[s.file] += 1
        mods[cfg.module_of(s.file)] += 1
    mass = sum(rank.get(sid, 0.0) for sid in grupo) if rank else 0.0
    return {
        "symbols": len(grupo),
        "files": len(arch),
        "mass": mass,
        # Ties broken BY NAME, not by the randomness of the walk. `grupo` is a set, so the
        # order in which `mods`/`arch` get filled changes between processes (string hashing
        # is randomized); sorting by count alone leaves ties at its mercy and the SAME run
        # produced different lists. It changes no number — it changes whether the report is
        # comparable with itself, which is the premise of `--diff`.
        "declarados": sorted(mods.items(), key=lambda x: (-x[1], x[0])),
        "top_files": sorted(arch.items(), key=lambda x: (-x[1], x[0]))[:4],
    }


def contrast(project, grupos, min_grupo: int = 5, min_symbols: int = 20) -> dict:
    """Disagreement between what is DECLARED and what is DISCOVERED — the real diagnosis.

    · a declared module spread across many groups → the name hides several things
    · a group absorbing several declared modules → those modules are one
    """
    # SIGNIFICANT groups only. With all of them, MCL leaves dozens of 1-2 symbol fragments
    # and EVERY module comes out "split" — the signal fires always and discriminates nothing
    # (measured: 18 of 18 modules flagged).
    cfg = project.cfg
    grupo_de = {}
    for g, grupo in enumerate(grupos):
        if len(grupo) < min_grupo:
            continue
        for sid in grupo:
            grupo_de[sid] = g

    reparto = defaultdict(lambda: defaultdict(int))
    for sid, s in project.symbols.items():
        g = grupo_de.get(sid)
        if g is None:
            continue
        reparto[cfg.module_of(s.file)][g] += 1

    partidos, fundidos = [], defaultdict(list)
    for mod, gs in reparto.items():
        total = sum(gs.values())
        if total < min_symbols:
            continue
        principal = max(gs.values())
        if principal / total < 0.5:
            partidos.append({"module": mod, "grupos": len(gs),
                             "symbols": total,
                             "concentration": round(principal / total, 2)})
        dominante = max(gs.items(), key=lambda x: x[1])[0]
        fundidos[dominante].append(mod)

    return {
        "partidos": sorted(partidos, key=lambda x: x["concentration"]),
        "fundidos": [{"grupo": g, "modules": m} for g, m in fundidos.items() if len(m) > 1],
    }


# ---------------------------------------------------------------- modularity
def _matrix(project):
    """Symmetric adjacency of the product core. The basis for Q."""
    import numpy as np
    from heatmap import _is_product
    cfg = project.cfg
    nodes = [n for n in project.symbols
             if _is_product(project, project.symbols[n].file)
             and cfg.area_of(project.symbols[n].file) == "core"]
    idx = {n: i for i, n in enumerate(nodes)}
    A = np.zeros((len(nodes), len(nodes)), dtype=np.float32)
    for (o, d), w in project.weights.items():
        i, j = idx.get(o), idx.get(d)
        if i is None or j is None or i == j:
            continue
        A[i, j] += w
        A[j, i] += w
    return nodes, idx, A


def modularity(particion, idx, A) -> float:
    """Newman's Q: density INSIDE the groups minus what chance would predict.

    Q > 0.3 se considera estructura de communities clara; Q < 0.3, acoplamiento
    high. It serves two different purposes: scoring a DECLARED partition and finding the
    graph's natural k.

    Known limit (Fortunato-Barthelemy): maximizing Q tends to MERGE small communities and the
    optimum depends on the graph's size. The k that comes out is an order of magnitude, not
    an exact number.
    """
    import numpy as np
    m2 = A.sum()
    if not m2:
        return 0.0
    k = A.sum(axis=1)
    q = 0.0
    for grupo in particion:
        ii = [idx[s] for s in grupo if s in idx]
        if len(ii) < 2:
            continue
        q += A[np.ix_(ii, ii)].sum() / m2 - (k[ii].sum() / m2) ** 2
    return float(q)


def sweep_k(project, inflaciones=(1.15, 1.2, 1.25, 1.3, 1.4, 1.6, 1.8, 2.0, 2.5)):
    """Looks for the graph's natural k by maximizing Q.

    **Both partitions are scored over the SAME graph**, the one MCL saw. That was not the case
    before: the matrix came from `_matrix` (the whole product core) and the groups from
    `cluster` (which removes the top 1% of hubs). The hubs stayed inside the declared
    partition and outside every discovered community, so their degree term penalized the
    discovered one without
    castigar a la declarada.

    It is not a detail: in the frontend those 13 nodes concentrated **16.7% of the graph's
    total degree**, and the headline "you capture X% of the reachable modularity" came out
    inflated because the denominator ran with a handicap the numerator did not have. Comparing
    two partitions scored over different graphs measures nothing.
    """
    nodes = nodes_of(project)
    idx = {n: i for i, n in enumerate(nodes)}
    A = adjacency(project, nodes).toarray()
    rows = []
    for infl in inflaciones:
        grupos = cluster(project, inflation=infl)
        rows.append({"inflation": infl,
                      "k": len([g for g in grupos if len(g) >= 5]),
                      "Q": round(modularity(grupos, idx, A), 3)})
    cfg = project.cfg
    decl = defaultdict(set)
    for sid, s in project.symbols.items():
        if sid in idx:
            decl[cfg.module_of(s.file)].add(sid)
    best = max(rows, key=lambda f: f["Q"])
    return {
        "symbols": len(nodes),
        "barrido": rows,
        "declarada": {"k": len(decl),
                      "Q": round(modularity(list(decl.values()), idx, A), 3)},
        "optima": best,
    }


# -------------------------------------------------- hierarchy: split or merge
def submodules(project, inflaciones=(1.2, 1.4, 1.7, 2.0), min_symbols=25):
    """k_sub per module: how many pieces each line of work wants to be.

    RECURSION is needed, the global optimum is not enough: maximizing Q over the whole graph
    has a resolution limit and is blind to small communities inside a large one. Treating each
    module as its own graph makes that bias disappear — the subgraph is small and its internal
    Q does see its structure.

    High Q_int = the module has internal communities → splitting is worth it.
    Q_int baja = es cohesivo → dejarlo en paz.
    """
    import numpy as np
    nodes, idx, A = _matrix(project)
    cfg = project.cfg

    porm = defaultdict(list)
    for sid in nodes:
        porm[cfg.module_of(project.symbols[sid].file)].append(sid)

    out = []
    for mod, miembros in porm.items():
        if len(miembros) < min_symbols:
            continue
        ii = [idx[s] for s in miembros]
        sub = A[np.ix_(ii, ii)]
        if sub.sum() == 0:
            continue
        sub_idx = {s: n for n, s in enumerate(miembros)}
        best = {"Q_int": 0.0, "k_sub": 1}
        for infl in inflaciones:
            parts = _mcl_on(sub, miembros, infl)
            q = modularity(parts, sub_idx, sub)
            k = len([g for g in parts if len(g) >= 4])
            if q > best["Q_int"]:
                best = {"Q_int": round(q, 3), "k_sub": k, "inflation": infl}
        # COHESION: what fraction of the module's references stays INSIDE.
        # Q_int alone is no good as a criterion: in a sparsely connected subgraph it comes
        # out high by construction and flags "split" on 100% of the modules. Cohesion does
        # not have that bias and is directly interpretable.
        internal = float(sub.sum())
        total = float(A[ii, :].sum())
        cohesion = internal / total if total else 0.0
        out.append({"module": mod, "symbols": len(miembros),
                      "cohesion": round(cohesion, 3),
                      "transversal": mod in cfg.crosscutting_modules, **best})
    return sorted(out, key=lambda x: -x["Q_int"])


def _mcl_on(A, nodes, inflation, iteraciones=20, threshold=1e-5, top_k=30):
    """MCL over an already-built adjacency (a subgraph)."""
    import numpy as np
    import scipy.sparse as sp
    M = sp.csr_matrix(A, dtype=np.float32)
    M.setdiag(np.asarray(M.max(axis=1).todense()).ravel())

    def norm(X):
        s = np.asarray(X.sum(axis=0)).ravel()
        s[s == 0] = 1.0
        return X @ sp.diags(1.0 / s)

    M = norm(M)
    for _ in range(iteraciones):
        M = M @ M
        M.data **= inflation
        M.data[M.data < threshold] = 0.0
        M.eliminate_zeros()
        M = norm(M)
    grupos = defaultdict(set)
    Mc = M.tocsc()
    for j in range(Mc.shape[1]):
        a, b = Mc.indptr[j], Mc.indptr[j + 1]
        if b > a:
            grupos[int(Mc.indices[a + int(np.argmax(Mc.data[a:b]))])].add(nodes[j])
    return sorted(grupos.values(), key=len, reverse=True)


def merges(project, min_symbols=15):
    """ΔQ of merging each pair of declared modules.

    ΔQ > 0 means there are MORE edges between those two modules than chance predicts: the code
    does not tell them apart and merging them improves modularity. It is Newman's
    agglomeration step, applied to the declared partition instead of to the algorithm's own
    result.
    """
    import numpy as np
    nodes, idx, A = _matrix(project)
    cfg = project.cfg
    m2 = A.sum()
    if not m2:
        return []
    k = A.sum(axis=1)

    porm = defaultdict(list)
    for sid in nodes:
        porm[cfg.module_of(project.symbols[sid].file)].append(idx[sid])
    mods = [(m, ii) for m, ii in porm.items() if len(ii) >= min_symbols]

    pairs = []
    for a in range(len(mods)):
        for b in range(a + 1, len(mods)):
            (ma, ia), (mb, ib) = mods[a], mods[b]
            between = A[np.ix_(ia, ib)].sum()
            if between == 0:
                continue
            dq = 2 * between / m2 - 2 * (k[ia].sum() / m2) * (k[ib].sum() / m2)
            pairs.append({"a": ma, "b": mb, "delta_Q": round(float(dq), 4)})
    return sorted(pairs, key=lambda x: -x["delta_Q"])


# ---------------------------------------------------------------- islands
def islands(project, min_symbols: int = 10) -> list[dict]:
    """Connected components INSIDE each file — where to cut, and whether it is worth it.

    Size is NOT a splitting criterion. Measured in this repo: the largest file (1,794 lines,
    67 symbols) has 76% of its symbols in ONE connected island — it is one big thing, cutting
    it would be arbitrary. And a 518-line file has eight islands with the largest at 19%: that
    is not a file, it is a folder.

    What decides is FRAGMENTATION, and the islands also say WHERE to cut: each component
    already comes with its members. You do not have to choose how many parts — you have to
    count them.
    """
    import numpy as np
    from collections import deque

    nodes, idx, A = _matrix(project)
    por_arch = defaultdict(list)
    for s in nodes:
        por_arch[project.symbols[s].file].append(s)

    out = []
    for arch, ms in por_arch.items():
        if len(ms) < min_symbols:
            continue
        ii = [idx[s] for s in ms]
        sub = A[np.ix_(ii, ii)]
        total = A[ii, :].sum()

        ady = defaultdict(set)
        for a in range(len(ms)):
            for b in range(a + 1, len(ms)):
                if sub[a, b] > 0:
                    ady[a].add(b)
                    ady[b].add(a)
        seen, comps = set(), []
        for a in range(len(ms)):
            if a in seen:
                continue
            c, q = set(), deque([a])
            seen.add(a)
            while q:
                x = q.popleft()
                c.add(x)
                for y in ady.get(x, ()):
                    if y not in seen:
                        seen.add(y)
                        q.append(y)
            comps.append(c)
        comps.sort(key=len, reverse=True)
        mayor = len(comps[0]) / len(ms)
        coh = float(sub.sum() / total) if total else 0.0

        # ORDER matters: a dominant island wins over low cohesion. A file with 100% of its
        # symbols connected is ONE thing even if it calls almost everything outward (a
        # coordinator). The other way around, the verdict
        # se contradecia only: "mayor 100%" + "replantear".
        n_islands = len([c for c in comps if len(c) >= 2])
        if mayor >= 0.60:
            verdict = "one big thing — do not split"
        elif coh < 0.15:
            verdict = "NOT cohesive — rethink it, do not split"
        elif n_islands >= 3:
            verdict = f"SPLIT along the islands ({n_islands})"
        else:
            verdict = "no clear signal"

        out.append({
            "file": arch, "symbols": len(ms),
            "cohesion": round(coh, 2), "mayor_pct": round(mayor, 2),
            "islands": len([c for c in comps if len(c) >= 2]),
            "verdict": verdict,
            "cortes": [sorted(project.symbols[ms[i]].name for i in c)
                       for c in comps if len(c) >= 2],
        })
    call_order = {"SPLIT": 0, "NOT cohesive": 1, "no clear": 2, "one big": 3}
    out.sort(key=lambda f: (next(v for k, v in call_order.items()
                                   if f["verdict"].startswith(k)), f["mayor_pct"]))
    return out
