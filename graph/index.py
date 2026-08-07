"""Cached index — the "does this already exist?" query in milliseconds.

The full sweep takes seconds; a pre-write gate cannot cost that. This index is built once,
cached on disk, and rebuilt **only for the files that changed** (content hash per file).

It keeps three things per function:

    name          for exact and subtoken collisions
    fingerprint   hash of the anonymized skeleton   → Type-1/2 clones
    signature     bottom-k MinHash of its n-grams   → Type-3 clones

The signature exists because storing the complete n-grams of thousands of functions would
make the cache enormous. With the k smallest fingerprints, Jaccard is estimated without
storing the whole set.

This is the SAME primitive as the sweep, at the other moment: "does this already exist?"
before writing is the same question as "is this duplicated?" afterwards.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import time

import duplicates as _dup
from core import _Anonymizer

VERSION = 1
SIGNATURE_K = 48      # how many hashes the sketch keeps per function
MIN_STATEMENTS = 4


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


def skeleton_of(node: ast.AST, min_statements: int = MIN_STATEMENTS) -> str | None:
    body = [x for x in node.body
            if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
    if len(body) < min_statements:
        return None
    try:
        copy = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
    except (SyntaxError, ValueError, RecursionError):
        return None
    return ast.dump(_Anonymizer().visit(copy), annotate_fields=False)


def signature_of(skel: str, k: int = SIGNATURE_K) -> list[int]:
    """Bottom-k MinHash: the k smallest fingerprints of its n-grams."""
    hs = sorted({_h(g) for g in _dup._ngrams(skel)})
    return hs[:k]


def jaccard(a: list[int], b: list[int]) -> float:
    """Estimate from two bottom-k sketches."""
    if not a or not b:
        return 0.0
    sa, sb = set(a), set(b)
    union = sorted(sa | sb)[:min(len(a), len(b))]
    if not union:
        return 0.0
    return len(set(union) & sa & sb) / len(union)


def _analyze_source(src: str, rel: str) -> list[dict]:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        d = {"n": n.name, "f": rel, "l": n.lineno,
             "c": "class" if isinstance(n, ast.ClassDef) else "function"}
        if not isinstance(n, ast.ClassDef):
            skel = skeleton_of(n)
            if skel:
                d["h"] = hashlib.blake2b(skel.encode(), digest_size=8).hexdigest()
                d["s"] = signature_of(skel)
        out.append(d)
    return out


def build(cfg, cache_path: str | None = None, force: bool = False) -> dict:
    """Builds or updates the index. It only re-parses what changed."""
    cache_path = cache_path or os.path.join(cfg.root, ".mcview", "index.json")
    prev = {}
    if os.path.exists(cache_path) and not force:
        try:
            prev = json.load(open(cache_path, encoding="utf-8"))
            if prev.get("version") != VERSION:
                prev = {}
        except (ValueError, OSError):
            prev = {}

    prev_hashes = prev.get("hashes", {})
    prev_symbols = prev.get("files", {})

    hashes, files = {}, {}
    reparsed = 0
    for dirpath, dirnames, filenames in os.walk(cfg.root):
        dirnames[:] = [d for d in dirnames if d not in cfg.ignored_dirs]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            abs_p = os.path.join(dirpath, fn)
            rel = os.path.relpath(abs_p, cfg.root)
            if cfg.excluded(rel):
                continue
            try:
                src = open(abs_p, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            hh = hashlib.blake2b(src.encode(), digest_size=8).hexdigest()
            hashes[rel] = hh
            if prev_hashes.get(rel) == hh and rel in prev_symbols:
                files[rel] = prev_symbols[rel]      # unchanged: reuse
            else:
                files[rel] = _analyze_source(src, rel)
                reparsed += 1

    idx = {"version": VERSION, "project": cfg.name, "root": cfg.root,
           "generated": int(time.time()), "hashes": hashes, "files": files,
           "reparsed": reparsed}
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(idx, f)
    os.replace(tmp, cache_path)
    return idx


def load(cfg, cache_path: str | None = None) -> dict | None:
    cache_path = cache_path or os.path.join(cfg.root, ".mcview", "index.json")
    if not os.path.exists(cache_path):
        return None
    try:
        idx = json.load(open(cache_path, encoding="utf-8"))
        return idx if idx.get("version") == VERSION else None
    except (ValueError, OSError):
        return None


def query(idx: dict, src: str, rel: str, threshold: float = 0.75) -> dict:
    """Does what I am about to write already exist?

    Returns matches by NAME and by SHAPE. It blocks nothing and judges nothing: two
    functions with the same shape can be duplication or two legitimate faces of an API.
    The one who decides is the one reading.
    """
    new = _analyze_source(src, rel)
    if not new:
        return {"new": 0, "by_name": [], "by_shape": []}

    by_name, by_fingerprint = {}, {}
    for file, syms in idx["files"].items():
        if file == rel:
            continue                       # do not compare against itself
        for s in syms:
            by_name.setdefault(s["n"], []).append(s)
            if "h" in s:
                by_fingerprint.setdefault(s["h"], []).append(s)

    name_match, shape_match = [], []
    for s in new:
        for old in by_name.get(s["n"], [])[:3]:
            name_match.append({"name": s["n"], "kind": s["c"],
                               "already_in": f"{old['f']}:{old['l']}"})
        if "h" not in s:
            continue
        exact = by_fingerprint.get(s["h"], [])
        if exact:
            shape_match.append({"name": s["n"], "jaccard": 1.0, "kind": "identical",
                                "already_in": f"{exact[0]['f']}:{exact[0]['l']}"})
            continue
        best, where = 0.0, None
        for file, syms in idx["files"].items():
            if file == rel:
                continue
            for old in syms:
                if "s" not in old:
                    continue
                j = jaccard(s["s"], old["s"])
                if j > best:
                    best, where = j, old
        if best >= threshold and where:
            shape_match.append({"name": s["n"], "jaccard": round(best, 2),
                                "kind": "similar",
                                "already_in": f"{where['f']}:{where['l']}"})
    return {"new": len(new), "by_name": name_match, "by_shape": shape_match}
