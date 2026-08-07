"""Multiple views — structure, semantics and evolution.

Pure topology is not enough to recover CONCEPTUAL modules: the dependency graph says who calls
whom, not what each thing is about. The remodularization literature has it measured —
combining structural, semantic and evolutionary signals improves the clustering; each one
alone does not.

Three views, each a similarity matrix over the same symbols:

    structural    who references whom       (the graph we already had)
    lexical       which words they share    (identifiers + docstrings)
    evolutionary  what changes together     (git co-change)

The lexical one is deliberately TF-IDF over subtokens, not neural embeddings: it is what the
classic work uses (LSI over identifiers), it costs no API calls, and it covers 100% of the
symbols instead of only those that happen to have been embedded.

The evolutionary one was discarded BEFORE on its own —co-change is a weak predictor— and is
picked up here for the exact reason the literature gives: it contributes *in combination*.

The combination weights are a CHOICE, not a truth. That is why the evaluation function
exists: it measures whether adding views brings the discovered groups closer to the partition
declared by the human, which is the only proxy we have for "conceptual module".
"""
from __future__ import annotations

import math
import re
import subprocess
from collections import Counter, defaultdict

_PALABRA = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _subtokens(name: str) -> list[str]:
    """`get_tenant_id` / `getTenantId` → [get, tenant, id]"""
    parts = []
    for trozo in name.split("_"):
        parts += re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]*|[a-z]+|\d+", trozo)
    return [p.lower() for p in parts if len(p) > 2]


def lexical_view(project, nodes, top_k=30):
    """TF-IDF over name + docstring + body names. Cosine, pruned."""
    import numpy as np
    import scipy.sparse as sp

    docs = []
    for sid in nodes:
        s = project.symbols[sid]
        toks = _subtokens(s.name) + _subtokens(s.file.rsplit("/", 1)[-1][:-3])
        src = project.sources.get(s.file, "")
        if src:
            lines = src.split("\n")[s.line - 1:min(s.end, s.line + 60)]
            for w in _PALABRA.findall("\n".join(lines))[:200]:
                toks += _subtokens(w)
        docs.append(Counter(toks))

    df = Counter()
    for d in docs:
        df.update(d.keys())
    N = len(docs)
    vocab = {t: i for i, t in enumerate(t for t, c in df.items() if 1 < c < N * 0.4)}
    if not vocab:
        return sp.csr_matrix((N, N), dtype=np.float32)

    fi, co, va = [], [], []
    for i, d in enumerate(docs):
        for t, c in d.items():
            j = vocab.get(t)
            if j is None:
                continue
            fi.append(i); co.append(j)
            va.append((1 + math.log(c)) * math.log(N / df[t]))
    X = sp.csr_matrix((va, (fi, co)), shape=(N, len(vocab)), dtype=np.float32)
    norma = np.sqrt(X.multiply(X).sum(axis=1)).A.ravel()
    norma[norma == 0] = 1.0
    X = sp.diags(1.0 / norma) @ X

    S = (X @ X.T).tocsr()
    S.setdiag(0.0)
    S.eliminate_zeros()
    return _prune_rows(S, top_k)


def evolution_view(project, nodes, repo, commits=400, top_k=30):
    """Git co-change, at file level, propagated to the symbols."""
    import numpy as np
    import scipy.sparse as sp

    root_rel = project.cfg.root.replace(repo + "/", "")
    try:
        output = subprocess.run(
            ["git", "-C", repo, "log", f"-{commits}", "--name-only",
             "--pretty=format:%H", "--", root_rel],
            capture_output=True, text=True, check=True, timeout=120).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return sp.csr_matrix((len(nodes), len(nodes)), dtype=np.float32)

    files_of = defaultdict(list)
    for i, sid in enumerate(nodes):
        files_of[project.symbols[sid].file].append(i)

    pairs = Counter()
    veces = Counter()
    current = []
    for line in output.split("\n") + [""]:
        line = line.strip()
        if not line or len(line) == 40 and " " not in line:
            touched = [a for a in current if a in files_of]
            if 1 < len(touched) <= 25:       # commits gigantes no informan
                for a in touched:
                    veces[a] += 1
                for x in range(len(touched)):
                    for y in range(x + 1, len(touched)):
                        pairs[tuple(sorted((touched[x], touched[y])))] += 1
            current = []
            continue
        rel = line.replace(root_rel + "/", "", 1)
        if rel.endswith(".py"):
            current.append(rel)

    fi, co, va = [], [], []
    for (a, b), n in pairs.items():
        # Jaccard over commits: it normalizes how often each file changes
        j = n / (veces[a] + veces[b] - n)
        if j < 0.15:
            continue
        for i in files_of[a]:
            for k in files_of[b]:
                fi.append(i); co.append(k); va.append(j)
                fi.append(k); co.append(i); va.append(j)
    S = sp.csr_matrix((va, (fi, co)), shape=(len(nodes), len(nodes)), dtype=np.float32)
    S.sum_duplicates()
    return _prune_rows(S, top_k)


def _prune_rows(S, top_k):
    import numpy as np
    S = S.tocsr()
    for r in range(S.shape[0]):
        a, b = S.indptr[r], S.indptr[r + 1]
        if b - a > top_k:
            tramo = S.data[a:b]
            corte = np.partition(tramo, -top_k)[-top_k]
            tramo[tramo < corte] = 0.0
    S.eliminate_zeros()
    return S


def _normalize(S):
    m = S.max()
    return S / m if m else S


def combine(estructural, lexica, evolutiva, weights=(1.0, 0.5, 0.3)):
    """Weighted sum of the three views, each normalized to [0,1].

    The weights are a declared choice, not a result. `evaluate` measures whether they move
    anything.
    """
    we, wl, wv = weights
    S = we * _normalize(estructural)
    if wl and lexica.nnz:
        S = S + wl * _normalize(lexica)
    if wv and evolutiva.nnz:
        S = S + wv * _normalize(evolutiva)
    return S.tocsr()


def purity(grupos, nodes, project, min_grupo=5):
    """Agreement with the DECLARED partition — our proxy for "conceptual".

    For each discovered group, what fraction falls into its dominant declared module. A
    size-weighted average. If adding views RAISES purity, those views are bringing topology
    closer to concept.
    """
    cfg = project.cfg
    total, acum = 0, 0.0
    for g in grupos:
        if len(g) < min_grupo:
            continue
        c = Counter(cfg.module_of(project.symbols[s].file) for s in g)
        acum += max(c.values())
        total += len(g)
    return (acum / total) if total else 0.0


def nmi(grupos, project, min_grupo=3):
    """Informacion mutua normalizada contra la particion declarada.

    PURITY is no good for comparing views: it grows with k by construction —in the limit,
    single-symbol groups give purity 1.0— and the views produce very different k. NMI
    penalizes fragmentation and is therefore comparable.
    """
    import math
    cfg = project.cfg
    pairs = []
    for gi, g in enumerate(grupos):
        if len(g) < min_grupo:
            continue
        for sid in g:
            pairs.append((gi, cfg.module_of(project.symbols[sid].file)))
    if not pairs:
        return 0.0
    n = len(pairs)
    cx, cy, cxy = Counter(), Counter(), Counter()
    for x, y in pairs:
        cx[x] += 1; cy[y] += 1; cxy[(x, y)] += 1
    hx = -sum(c / n * math.log(c / n) for c in cx.values())
    hy = -sum(c / n * math.log(c / n) for c in cy.values())
    i = sum(c / n * math.log((c / n) / (cx[x] / n * cy[y] / n))
            for (x, y), c in cxy.items())
    return 2 * i / (hx + hy) if (hx + hy) else 0.0
