#!/usr/bin/env python3
"""Does the graph respect Python SCOPE, or does it go back to fabricating edges?

A lock over `core._own_bound` + `_map_reach`. It exists because a local variable whose name
matched a unique function in another file fabricated an edge —and fabricated it with the
STRONGEST evidence the tool can give, because `strong_edges` means "only one symbol has this
name", not "this is a real call".

Measured before the fix on CIRE: 502 of 8,001 strong edges (6.3%) were of this kind. Over an
8-hop path that is a ~40% chance of containing an invented link, which is why `Evaluation`'s
flow reported 166 roots where there are 20.

FIVE CASES, AND FOUR OF THEM ARE "DO NOT SUPPRESS"
----------------------------------------
The risk of the fix is not under-suppressing: it is over-suppressing, because that ERASES
real edges and kills live symbols by cascade. It happened: counting a nested function's name
as a "shadowing local" killed 38 symbols, `_audit_slice` among them, the heart of the parallel
audit. The new-DEAD_CANDIDATE check caught it, not reading by eye — which is why four of the
five cases here are negative.

    mcview/selfcheck/check_reach.py        # 0 = pass
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config    # noqa: E402
import factory as _factory  # noqa: E402

FIXTURE_OBJETIVO = '''
def docs_read(document_id):
    """The real function: a UNIQUE name in the project, so it resolves unambiguously."""
    return {"id": document_id}


def helper_called(x):
    return x + 1


def helper_by_attribute(y):
    return y
'''

FIXTURE_USOS = '''
import target_module


def local_shadow(audit):
    """`docs_read` here is a LOCAL. It does not reference the homonymous function."""
    docs_read = audit.get("documents_read_count") or 0
    other = docs_read + 1
    return other


def is_real_call(v):
    """No local binding: this IS a reference."""
    return helper_called(v)


def by_attribute(obj):
    """A local does NOT shadow an attribute: `obj.helper_by_attribute` is not the bare name."""
    helper_by_attribute = 0
    return obj.helper_by_attribute + helper_by_attribute


def with_nested(items):
    """The nested `def` BINDS its name here, but that binding IS the symbol: referencing it from
    a comprehension is legitimate. Counting it as a shadow killed 38 symbols once."""
    def _internal(s):
        return s * 2
    return [_internal(i) for i in items]


def declares_global(v):
    """With `global`, the assignment does NOT create a local: the read still refers to the symbol."""
    global helper_called
    helper_called = v
    return helper_called


def uses_comprehension(xs):
    """In py3 a comprehension has ITS OWN scope: `helper_called` as a comprehension variable does
    not make the name local in the rest of the function."""
    _ = [helper_called for helper_called in xs]
    return helper_called(1)
'''

# `dirs` is compared with `str.startswith` against the relative path, so "." matches nothing
# and the project would end up with NO roots — which makes everything come out DEAD_CANDIDATE
# and the liveness check would measure the fixture's config, not the filter. Hence the sources
# live in `app/`.
TOML = '''
[project]
name = "fixture-reach"
root = "."

[roots]
dirs = ["app/"]
product_dirs = ["app/"]
'''


def _edges_by_name(project):
    out = set()
    for origin, targets in project.edges.items():
        s = project.symbols.get(origin)
        if not s:
            continue
        for d in targets:
            out.add((s.name, project.symbols[d].name))
    return out


FIXTURE_TS_OBJETIVO = '''
export function docsRead(id: string) { return { id } }
export function helperLlamado(x: number) { return x + 1 }
export function helperPorAtributo(y: number) { return y }
export const PanelCompartido = () => null
'''

FIXTURE_TS_USOS = '''
import { docsRead, helperLlamado, helperPorAtributo, PanelCompartido } from "./target"

export function sombraLocal(audit: any) {
  const docsRead = audit.count ?? 0
  return docsRead + 1
}

export function isRealCall(v: number) {
  return helperLlamado(v)
}

export function porAtributo(obj: any) {
  const helperPorAtributo = 0
  return obj.helperPorAtributo + helperPorAtributo
}

export function conVariableFuncional(items: number[]) {
  const _internal = (s: number) => s * 2
  return items.map(_internal)
}

export function sombraDeParametro(PanelCompartido: number) {
  return PanelCompartido + 1
}
'''

TOML_TS = '''
[project]
name = "fixture-reach-ts"
root = "."
language = "typescript"

[roots]
dirs = ["app/"]
product_dirs = ["app/"]
'''


def _ts_phase() -> list[str]:
    """Same contract as the Python phase. It is skipped if tree-sitter is missing: the lock must
    not become an environment blocker for somebody working only on the Python side."""
    try:
        import ts  # noqa: F401
        ts._Parser.create()
    except Exception as e:                                   # noqa: BLE001
        print(f"  · TypeScript skipped (no parser: {type(e).__name__})")
        return []

    failures = []
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, "app"))
        open(os.path.join(d, "mcview.toml"), "w").write(TOML_TS)
        open(os.path.join(d, "app", "target.ts"), "w").write(FIXTURE_TS_OBJETIVO)
        open(os.path.join(d, "app", "usos.ts"), "w").write(FIXTURE_TS_USOS)
        cfg = _config.load(os.path.join(d, "mcview.toml"))
        p = _factory.make_project(cfg)
        edges = _edges_by_name(p)

        cases = [
            ("sombraLocal", "docsRead", False,
             "a `const` shadowing the name does not reference the homonymous symbol"),
            ("isRealCall", "helperLlamado", True,
             "with no local binding, the read IS a reference"),
            ("porAtributo", "helperPorAtributo", True,
             "a local does not shadow an ATTRIBUTE (`obj.x` is not the bare name)"),
            ("conVariableFuncional", "_internal", True,
             "`const f = () => {}` IS a symbol, not a shadow — killing it killed "
             "`getCookie` and `handleAction` while they were called from their own file"),
            ("sombraDeParametro", "PanelCompartido", False,
             "a parameter also binds the name"),
        ]
        for origin, target_node, must, why in cases:
            present = (origin, target_node) in edges
            if present != must:
                failures.append(f"[ts] {origin} → {target_node}: "
                              f"{'should not exist' if present else 'should exist'} — {why}")

        dead = {p.symbols[s].name for s in p.levels()["DEAD_CANDIDATE"]}
        for vivo in ("helperLlamado", "_internal", "helperPorAtributo"):
            if vivo in dead:
                failures.append(f"[ts] {vivo} became DEAD_CANDIDATE — a real edge was erased")
    return failures


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as d:
        os.mkdir(os.path.join(d, "app"))
        open(os.path.join(d, "mcview.toml"), "w").write(TOML)
        open(os.path.join(d, "app", "target_module.py"), "w").write(FIXTURE_OBJETIVO)
        open(os.path.join(d, "app", "usos.py"), "w").write(FIXTURE_USOS)
        cfg = _config.load(os.path.join(d, "mcview.toml"))
        p = _factory.make_project(cfg)
        edges = _edges_by_name(p)

        cases = [
            # (origin, target_node, must_exist, why)
            ("local_shadow", "docs_read", False,
             "a local shadowing the name does NOT reference the homonymous symbol"),
            ("is_real_call", "helper_called", True,
             "with no local binding, the read IS a reference"),
            ("by_attribute", "helper_by_attribute", True,
             "a local does not shadow an ATTRIBUTE: `obj.x` is not the bare name"),
            ("with_nested", "_internal", True,
             "a nested function's name IS the symbol, not a shadow"),
            ("declares_global", "helper_called", True,
             "with `global`, the assignment does not create a local"),
            ("uses_comprehension", "helper_called", True,
             "the comprehension variable has its own scope in py3"),
        ]
        for origin, target_node, must, why in cases:
            present = (origin, target_node) in edges
            if present != must:
                failures.append(f"{origin} → {target_node}: "
                              f"{'should not exist' if present else 'should exist'} — {why}")

        # No live symbol may be left dead by the filter.
        levels = p.levels()
        dead = {p.symbols[s].name for s in levels["DEAD_CANDIDATE"]}
        for vivo in ("helper_called", "_internal", "helper_by_attribute"):
            if vivo in dead:
                failures.append(f"{vivo} became DEAD_CANDIDATE — the filter erased a real edge")

    failures += _ts_phase()

    for f in failures:
        print(f"  ✗ {f}")
    if not failures:
        print("  ✓ lexical scope: python 6/6 · typescript 5/5 · live symbols intact")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
