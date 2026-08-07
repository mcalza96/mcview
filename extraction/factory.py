# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""Picks the parser according to the language declared in the `.toml`.

It lives in its own file —and not inside `core`— so the core does NOT import the TypeScript
side. If it did, a Python project would load tree-sitter at startup and an optional dependency
would become mandatory; worse, any error in the new parser would break the old path. Here the
import is lazy: the Python side never executes it.
"""
from __future__ import annotations

import core as _nucleo


def make_project(cfg):
    if getattr(cfg, "language", "python") == "typescript":
        from ts import TSProject

        return TSProject(cfg)
    return _nucleo.Project(cfg)
