#!/usr/bin/env python3
"""Does a warm rebuild tell the truth?

The per-file facts cache (`Project(file_cache=...)`) exists so the rebuild an agent
triggers by editing one file re-parses one file instead of 725 — measured 3.0 s → 82 ms
on the reference backend. That speed buys a NEW class of bug: a cache entry that
survives a change it should not have survived. An index that lies is worse than a slow
one, because it lies with confidence.

WHAT IT PROVES
--------------
Four scenarios over a synthetic two-file project, each compared against a COLD build of
the same tree — the cold build is the definition of truth here:

  · warm with no change    → identical graph, and the second build must not re-extract
  · warm after a body edit → identical to cold (lines shift, so every Symbol.id in the
    edited file moves — the cheap thing to get wrong)
  · warm after adding a HOMONYM in file B → file A's strong edge must DEGRADE, even
    though A's cached facts never changed. This is the case that separates sound
    incremental (resolution re-runs globally) from a stale index (it does not).
  · warm after deleting the file → the entry must not linger.

The homonym scenario also asserts the semantic change actually happened (the strong
edge existed before and is gone after), so the lock cannot pass vacuously by comparing
two empty graphs.

    mcview/selfcheck/check_incremental.py        # 0 = pass
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import _layers  # noqa: F401,E402
import config as _config      # noqa: E402
import factory as _factory    # noqa: E402

PROYECTO = {
    "app/a.py": '''
def helper():
    return 1


def caller():
    return helper()
''',
    "app/b.py": '''
def other():
    return 2
''',
    "mcview.toml": '''
[project]
name = "incremental test"
root = "."

[roots]
dirs = ["app/"]
product_dirs = ["app/"]
''',
}


def _digest(p) -> str:
    def canon(d):
        return {k: sorted(v) for k, v in sorted(d.items())}
    payload = {
        "symbols": sorted(p.symbols),
        "edges": canon(p.edges), "strong": canon(p.strong_edges),
        "weights": sorted((f"{a}->{b}", round(w, 9)) for (a, b), w in p.weights.items()),
        "order": {k: v for k, v in sorted(p.call_order.items())},
        "branches": dict(sorted(p.branches.items())),
        "roots": sorted(p.roots), "product": sorted(p.product_roots),
        "locales": {k: sorted(v) for k, v in sorted(p._locales.items())},
        "modrefs": canon(p.module_refs),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def main() -> int:
    fallas = []
    with tempfile.TemporaryDirectory() as tmp:
        for rel, contenido in PROYECTO.items():
            path = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            open(path, "w").write(contenido)
        cfg_path = os.path.join(tmp, "mcview.toml")

        def cold():
            return _factory.make_project(_config.load(cfg_path))

        def warm(cache):
            return _factory.make_project(_config.load(cfg_path), file_cache=cache)

        cache: dict = {}
        d0 = _digest(warm(cache))
        if d0 != _digest(cold()):
            fallas.append("the FIRST cache-aware build already differs from a cold one")

        # 1 — no change: identical, and served from the cache
        # held by REFERENCE, not by id(): a re-extracted object can reuse a freed address
        antes = {rel: v[1] for rel, v in cache.items()}
        if _digest(warm(cache)) != d0:
            fallas.append("warm rebuild with no change differs from itself")
        if any(cache[rel][1] is not antes[rel] for rel in antes):
            fallas.append("no change, yet a facts entry was re-extracted (cache never hits)")

        # 2 — body edit: every line in a.py shifts, so every Symbol.id in it moves
        a_py = os.path.join(tmp, "app/a.py")
        open(a_py, "w").write("# desplaza todo una linea\n" + PROYECTO["app/a.py"])
        if _digest(warm(cache)) != _digest(cold()):
            fallas.append("warm after a body edit differs from cold (shifted ids linger)")

        # 3 — homonym added in the OTHER file: a.py's facts are still cached and still
        # valid, but `helper` stops being unambiguous, so caller's STRONG edge must go
        strong_antes = any("helper" in t for ts in warm(cache).strong_edges.values() for t in ts)
        b_py = os.path.join(tmp, "app/b.py")
        open(b_py, "a").write("\n\ndef helper():\n    return 3\n")
        p_tibio = warm(cache)
        strong_despues = any("helper" in t for ts in p_tibio.strong_edges.values() for t in ts)
        if not strong_antes:
            fallas.append("vacuous: the strong edge to `helper` never existed")
        if strong_despues:
            fallas.append("a homonym in b.py did not degrade a.py's strong edge: "
                          "resolution is reading stale state")
        if _digest(p_tibio) != _digest(cold()):
            fallas.append("warm after adding a homonym differs from cold")

        # 4 — deletion: the entry must not linger
        os.remove(b_py)
        if _digest(warm(cache)) != _digest(cold()):
            fallas.append("warm after deleting b.py differs from cold (entry lingers)")
        if any("b.py" in rel for rel in cache):
            fallas.append("deleted file still has a facts entry in the cache")

    if fallas:
        print("  ✗ incremental:")
        for f in fallas:
            print(f"      {f}")
        return 1
    print("  ✓ incremental: warm rebuild = cold build under no-change, body edit, "
          "cross-file homonym and deletion")
    return 0


if __name__ == "__main__":
    sys.exit(main())
