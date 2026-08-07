#!/usr/bin/env python3
"""Does the duplicate detector still see the duplication NOBODY extracted?

A regression lock over `core.blocks`. It exists because the detector had, measured, a blind
spot with a known direction: it compared FUNCTION bodies, so it only saw a clone after
somebody had bothered to pull it into its own function. CIRE's ingestion subsystem had the
same error-translation pattern in 9 units and the detector reported 2 — exactly the 2 already
extracted. It presented the tip of the iceberg as if it were the finding, and the bias points
at the worse side: it is blind precisely to the duplication nobody has started fixing.

WHY A FIXTURE OF ITS OWN AND NOT THE REAL REPO
--------------------------------------------
Measuring against CIRE's real sites looks more honest and is exactly the opposite: the day
somebody unifies those `except` blocks, the lock would start failing **because the bug got
fixed**. A test that breaks when the code improves protects nothing. The fixture is synthetic,
minimal and never changes.

WHAT IT TESTS, PRECISELY
--------------------------
1. Two blocks with the same shape inside different functions are found.
2. The same pair is still NOT found with `with_blocks` off — i.e. what finds it is this layer
   and nothing else.
3. A block is not reported against the function containing it (double counting).
4. A nested function's blocks are emitted ONCE, not once per ancestor.

    mcview/selfcheck/check_blocks.py        # 0 = pass
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config      # noqa: E402
import duplicates as _dup     # noqa: E402
import factory as _factory    # noqa: E402

# Two functions with nothing in common EXCEPT the error-handling block. Comparing function
# bodies, they look nothing alike; the clone is inside.
FIXTURE = '''
def batch_addition(payload):
    total = 0
    for item in payload:
        total += item
    try:
        return {"ok": total}
    except ValueError as e:
        detail = str(e)
        if "TENANT_MISMATCH" in detail:
            raise ApiError(status_code=400, code="TENANT_MISMATCH", details=detail)
        raise ApiError(status_code=400, code="INVALID_REQUEST", details=detail)


def batch_deletion(identificador, cascada):
    name = identificador.strip().lower()
    registro = search(name, cascada)
    try:
        return registro.delete()
    except ValueError as e:
        detail = str(e)
        if "COLLECTION_SEALED" in detail:
            raise ApiError(status_code=409, code="COLLECTION_SEALED", details=detail)
        raise ApiError(status_code=400, code="INVALID_REQUEST", details=detail)


def with_nested(x):
    def internal(y):
        if y > 0:
            a = y + 1
            b = a * 2
            c = b - 3
            return c
        return 0
    return internal(x)
'''

TOML = '''
[project]
name = "fixture"
root = "."

[roots]
dirs = ["."]
product_dirs = ["."]
'''


def _analyze(directorio: str, with_blocks: bool):
    cfg = _config.load(os.path.join(directorio, "mcview.toml"))
    project = _factory.make_project(cfg)
    return project, _dup.analyze(project, with_blocks=with_blocks)


def _block_pairs(res) -> list[tuple[str, str]]:
    out = []
    for grupo in res["type12"]:
        symbols = grupo["symbols"]
        if any(getattr(s, "kind", "") == "block" for s in symbols):
            out.append(tuple(sorted(s.name for s in symbols)))
    for pair in res["type3"]:
        if any(getattr(s, "kind", "") == "block" for s in (pair["a"], pair["b"])):
            out.append(tuple(sorted((pair["a"].name, pair["b"].name))))
    return out


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "mcview.toml"), "w").write(TOML)
        open(os.path.join(d, "module.py"), "w").write(FIXTURE)

        project, on = _analyze(d, with_blocks=True)
        _, off = _analyze(d, with_blocks=False)

        pairs = _block_pairs(on)
        esperado = ("batch_addition/except", "batch_deletion/except")
        if esperado not in pairs:
            failures.append(f"1. the clone between `except` blocks was not found — pairs: {pairs}")

        if _block_pairs(off):
            failures.append("2. blocks showed up with with_blocks=False")
        if off["blocks"] != 0:
            failures.append(f"2. with_blocks=False still computed {off['blocks']} fingerprints")

        # 3 — a block is never compared against the function containing it
        for pair in on["type3"]:
            a, b = pair["a"], pair["b"]
            if a.file == b.file and {getattr(a, "kind", ""), getattr(b, "kind", "")} == {
                    "block", "function"} and a.name.split("/")[0] == b.name.split("/")[0]:
                failures.append(f"3. block comparado contra su container: {a.loc} ↔ {b.loc}")

        # 4 — the nested function emits its blocks exactly once
        anidada = [s for s in project.symbols.values() if s.name == "internal"][0]
        externa = [s for s in project.symbols.values() if s.name == "with_nested"][0]
        if project.blocks(externa, 3):
            failures.append("4. the outer one emitted blocks from the nested function")
        if len(project.blocks(anidada, 3)) != 1:
            failures.append(f"4. the nested one emitted {len(project.blocks(anidada, 3))} blocks, not 1")

    for f in failures:
        print(f"  ✗ {f}")
    if not failures:
        print("  ✓ nested blocks: 4/4")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
