"""Redundancia estructural — clones Type-1/2/3.

The CHEAP and WIDE layer of the funnel. No LLM, no embeddings, no threshold to justify: two
functions with the same skeleton (AST with identifiers, attributes and literals erased) are
the same code under different names.

Type-4 —same responsibility, divergent code— is invisible here by definition: if the code
diverges, so does the skeleton. That layer needs embeddings, and even they do not rule: they
order a queue an LLM adjudicates.

This module proposes deleting NOTHING. Two functions with the same shape can be real
duplication or two deliberately symmetric faces of an API.
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict

import core as _core

N_GRAMA = 5


def _ngrams(s: str) -> set[str]:
    toks = s.replace("(", " ( ").replace(")", " ) ").replace(",", " ").split()
    return {" ".join(toks[i:i + N_GRAMA]) for i in range(max(0, len(toks) - N_GRAMA + 1))}


def analyze(project, with_blocks: bool = True) -> dict:
    cfg = project.cfg
    fingerprints = []
    blocks = 0
    for s in project.symbols.values():
        if s.kind != "function" or cfg.excluded_from_duplicates(s.file):
            continue
        esq = project.skeleton(s, cfg.min_statements)
        if esq:
            fingerprints.append((s, esq, hashlib.blake2b(esq.encode(), digest_size=16).hexdigest()))
        if not with_blocks:
            continue
        # NESTED blocks enter the same queue: comparing only function bodies leaves
        # the tool blind to the duplication nobody has extracted yet. A block presents
        # the same contract as a symbol (`core.Fragment`), so neither the ranking nor
        # the consumers need to know which is which.
        for line, label, esq_b in project.blocks(s, cfg.min_statements_block):
            frag = _core.Fragment(f"{s.name}/{label}", s.file, line)
            fingerprints.append((frag, esq_b,
                            hashlib.blake2b(esq_b.encode(), digest_size=16).hexdigest()))
            blocks += 1

    # -- Type-1/2: identical fingerprint --
    by_fingerprint = defaultdict(list)
    for s, esq, h in fingerprints:
        by_fingerprint[h].append((s, esq))
    exact = {h: v for h, v in by_fingerprint.items() if len(v) > 1}

    # -- Type-3: skeleton n-grams, one representative per fingerprint --
    #
    # NOT the naive inverted index. Measured on a 6.3k-symbol repo: n-grams like
    # `Call ( Name` appear in 2113 of 2116 skeletons, so walking every posting costs
    # ~324M dict increments to feed a threshold that then discards almost everything.
    # Prefix filtering (AllPairs) is EXACT for a Jaccard threshold t: if jac(a,b) >= t
    # then |a∩b| >= t·|b|, so b's prefix — its |b| - ceil(t·|b|) + 1 globally RAREST
    # grams — must contain at least one gram of a. Index only prefixes (short postings
    # by construction), probe with the full set, verify survivors with the exact
    # C-level intersection. Same output, measured 22.3s → under a second.
    unicos = [v[0] for v in by_fingerprint.values()]
    t = cfg.jaccard_threshold

    ids: dict[str, int] = {}
    grams = [{ids.setdefault(ng, len(ids)) for ng in _ngrams(esq)} for _, esq in unicos]

    freq = defaultdict(int)
    for g in grams:
        for ng in g:
            freq[ng] += 1

    index = defaultdict(list)
    pairs = []
    for i, (s_i, esq_i) in enumerate(unicos):
        g_i = grams[i]
        candidatos = set()
        for ng in g_i:
            candidatos.update(index[ng])
        for j in candidatos:
            g_j = grams[j]
            # size filter, O(1) and exact: jac >= t forces t·|a| <= |b| <= |a|/t.
            # Measured on 928k prefix candidates: discards 77% before touching the sets.
            if not (t * len(g_i) <= len(g_j) <= len(g_i) / t):
                continue
            comunes = len(g_i & g_j)
            if comunes < 3:
                continue
            union = len(g_i) + len(g_j) - comunes
            if union and comunes / union >= t:
                s_j, esq_j = unicos[j]
                pairs.append({
                    "jaccard": comunes / union, "a": s_j, "b": s_i,
                    "tokens": min(len(esq_i), len(esq_j)) // 10,
                })
        # the 1e-9 leans the rounding toward a LONGER prefix: a float ceil that lands
        # one too high would silently drop true pairs, one too low only costs probes
        prefijo = len(g_i) - math.ceil(t * len(g_i) - 1e-9) + 1
        for ng in sorted(g_i, key=lambda x: (freq[x], x))[:max(prefijo, 0)]:
            index[ng].append(i)

    # Rank by duplicated VOLUME, not by similarity: 1.00 over a 10-token `main` is not
    # worth what 0.85 over a 400-line function is.
    pairs.sort(key=lambda p: -(p["jaccard"] * p["tokens"]))

    return {
        "analizadas": len(fingerprints),
        "blocks": blocks,
        "type12": [{"fingerprint": h[:8], "symbols": [s for s, _ in v]}
                   for h, v in sorted(exact.items(), key=lambda x: -len(x[1]))],
        "type3": pairs,
    }
