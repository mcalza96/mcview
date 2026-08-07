#!/usr/bin/env python3
"""Lock: every key in a `.toml` has a reader in the code.

It exists because of the worst failure mode this tool can have — the one that **does not
crash**. When a config key and the code that reads it drift apart, nothing raises: the
reader gets its default, the view runs, and it returns an empty list. And an empty list from
a detector reads exactly like "there is nothing here", which is a finding.

It happened for real while translating the tool to English. `[[recorridos]]` became
`[[routes]]` in the `.toml` while the reader kept asking for `get("recorridos")`, and
`--route` answered *"declared routes: "* — the shape of a legitimately empty config. The
seam detectors drifted the same way and `--seams` would have reported zero junctions between
repositories.

WHAT IT CHECKS, and what it deliberately does not. A key is "read" if it appears as a string
literal anywhere in the code. That is coarse on purpose: matching each key against its exact
reader would need a model of how the config is destructured, and that model would be one
more thing that can drift. The coarse version catches the whole class at zero cost.

VALUES ARE NOT KEYS. `[modules]` maps declared names ("Retrieval") to paths, and those names
belong to whoever writes the config — no code will ever mention them. The same goes for
`[services]`, `[surfaces]` and `[areas]`. Their keys are skipped by name, which is why that
list lives here and not in a heuristic.
"""
from __future__ import annotations

import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

# Sections whose KEYS are user-declared values, not part of the tool's contract.
VALUE_SECTIONS = {"modules", "services", "surfaces", "areas"}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _keys(d: dict, section: str | None = None) -> set[str]:
    out: set[str] = set()
    for k, v in d.items():
        if section in VALUE_SECTIONS:
            continue                      # the key here is a name the owner chose
        out.add(k)
        if isinstance(v, dict):
            out |= _keys(v, k)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, dict):
                    out |= _keys(x, k)
    return out


def _source() -> str:
    tool = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = []
    for dirpath, dirnames, filenames in os.walk(tool):
        dirnames[:] = [d for d in dirnames
                       if d not in ("vendor", "__pycache__", "golden")]
        for f in filenames:
            if f.endswith(".py"):
                src.append(open(os.path.join(dirpath, f), encoding="utf-8").read())
    return "\n".join(src)


def main() -> int:
    tomls = sorted(glob.glob(os.path.join(ROOT, "mcview*.toml")))
    if not tomls:
        print("  · no mcview*.toml at the root — nothing to check")
        return 0

    src = _source()
    failures = []
    for p in tomls:
        with open(p, "rb") as fh:
            for k in sorted(_keys(tomllib.load(fh))):
                if f'"{k}"' not in src and f"'{k}'" not in src:
                    failures.append(f"{os.path.basename(p)}: `{k}` has no reader "
                                    f"in the code — the view will silently return empty")

    if failures:
        for f in failures:
            print(f"  ✗ {f}")
        return 1
    print(f"  ✓ config keys: every key in {len(tomls)} .toml files has a reader")
    return 0


if __name__ == "__main__":
    sys.exit(main())
