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
    unicos = [v[0] for v in by_fingerprint.values()]
    index, grams = defaultdict(list), {}
    for i, (s, esq) in enumerate(unicos):
        g = _ngrams(esq)
        grams[i] = g
        for ng in g:
            index[ng].append(i)

    pairs = []
    for i, (s_i, esq_i) in enumerate(unicos):
        candidatos = defaultdict(int)
        for ng in grams[i]:
            for j in index[ng]:
                if j > i:
                    candidatos[j] += 1
        for j, comunes in candidatos.items():
            if comunes < 3:
                continue
            union = len(grams[i] | grams[j])
            if not union:
                continue
            jac = comunes / union
            if jac >= cfg.jaccard_threshold:
                s_j, esq_j = unicos[j]
                pairs.append({
                    "jaccard": jac, "a": s_i, "b": s_j,
                    "tokens": min(len(esq_i), len(esq_j)) // 10,
                })

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
