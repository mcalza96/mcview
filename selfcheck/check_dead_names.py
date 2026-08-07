#!/usr/bin/env python3
"""A name assigned and never read — the shape of work that does not happen.

The dominant defect in this codebase is not a wrong computation. It is a DECLARATION WITH NO
READER: something written, accepted, documented, and consumed by nobody. Six of them turned up
in a single session, and they share one property — nothing crashes, so the only signal is the
absence of an effect nobody was measuring:

    a config key the TypeScript path never read
    a `--only` flag parsed, assigned, and never passed to the function it was scoping
    a `--seeds` mode that died on an import before measuring anything
    a view that had never once run, because one name held two different values
    a `[surfaces]` block the weave dropped when the question crossed repositories
    one declaration with TWO readers that understood it differently

There is already a lock for the first shape (`check_config_keys`). This one covers the second,
which is the cheapest to detect and was the most expensive to find by hand: `--only` was
advertised at ~90 s, silently ran the full 21-minute sweep, and was only noticed while waiting
for it.

WHAT IT CHECKS, and the boundary is deliberate. Only "assigned and never read anywhere in its
function", which on this repository fires with ZERO false positives — verified against the
commit that still had the `--only` bug, where it names the line exactly.

WHAT IT DELIBERATELY DOES NOT CHECK. "Reassigned before its first value was ever read" catches
a real bug of the same family —the one that kept `--decisions` broken for its whole life, a name
holding a dict and then its maximum— but a line-order approximation of it flags every
accumulator and every loop variable: measured, 4 false positives in one file against 1 true
one. A check that cries wolf four times per file is a check people learn to skip, which is worse
than not having it. Doing it properly needs control flow, and until then it is not here.

    mcview/selfcheck/check_dead_names.py        # 0 = pass
"""
from __future__ import annotations

import ast
import glob
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(AQUI)

# A leading underscore is the language's own way of saying "deliberately unused" — an ignored
# tuple element, a signature that has to match. Flagging it would be arguing with a convention.
def _exempt(name: str) -> bool:
    return name.startswith("_") or name in {"self", "cls"}


def dead_names(src: str, label: str) -> list[str]:
    out = []
    tree = ast.parse(src)
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        # PLAIN ASSIGNMENT ONLY. A `for name, targets in d.items()` that uses only the second
        # element is idiomatic and harmless; counting it turned 1 real finding into 7 rows, and
        # a check with six harmless rows is one nobody reads. What is left is the exact shape
        # that matters: a value COMPUTED and then dropped.
        stored: dict[str, int] = {}
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        stored.setdefault(t.id, t.lineno)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.value:
                stored.setdefault(n.target.id, n.target.lineno)
        read = {n.id for n in ast.walk(fn)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        # `global`/`nonlocal` names leave the function: their reader is somewhere else.
        outer = {x for n in ast.walk(fn) if isinstance(n, (ast.Global, ast.Nonlocal))
                 for x in n.names}
        for name, line in sorted(stored.items(), key=lambda kv: kv[1]):
            if _exempt(name) or name in read or name in outer:
                continue
            out.append(f"{label}:{line}  `{name}` in {fn.name}(): assigned and never read")
    return out


def main() -> int:
    failures = []
    for path in sorted(glob.glob(os.path.join(RAIZ, "**", "*.py"), recursive=True)):
        rel = os.path.relpath(path, RAIZ)
        if "__pycache__" in rel or rel.startswith("build/") or rel.startswith("vendor/"):
            continue
        try:
            failures += dead_names(open(path, encoding="utf-8").read(), rel)
        except SyntaxError as e:
            failures.append(f"{rel}: does not parse — {e}")

    for f in failures:
        print(f"  ✗ {f}")
    if not failures:
        print("  ✓ dead names: no value is computed and then dropped")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
