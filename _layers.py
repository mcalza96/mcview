"""Layers are DIRECTORIES, not Python packages.

The tool's promise is "copy the directory and write one `.toml`": no build step, no
`pip install`, and the CLI is invoked by path (`mcview/mcview.py`, which is what both
hooks run and what `check_portability` copies). A real package —with `__init__.py` and
relative imports— would force `python -m mcview` and break that promise.

So the layers are appended to `sys.path` and **the imports stay flat**: `import core`
works whether core lives at the root or under `extraction/`. Splitting the tree did not
touch a single import — the special case disappears instead of being handled at the 35
sites that import a sibling.

The price, stated up front: module names are global, so two layers cannot hold a file
with the same name. Today all 25 are unique, and `selfcheck/check_portability.py`
measures that rather than trusting it.

    import _layers   # this is all the entrypoints do
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LAYERS = ("", "extraction", "graph", "views", "render")


def mount(root: str = ROOT) -> None:
    for layer in LAYERS:
        d = os.path.join(root, layer)
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)


def collisions(root: str = ROOT) -> dict[str, list[str]]:
    """Modules sharing a name across two layers: the flat `sys.path` would let one win
    silently, and which one wins depends on ordering. It is the single failure mode this
    design adds, so it gets measured."""
    seen: dict[str, list[str]] = {}
    for layer in LAYERS:
        d = os.path.join(root, layer)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.endswith(".py") and not f.startswith("_"):
                seen.setdefault(f[:-3], []).append(layer or ".")
    return {n: c for n, c in seen.items() if len(c) > 1}


mount()
