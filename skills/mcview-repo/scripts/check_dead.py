#!/usr/bin/env python3
"""Checks in ONE pass whether a set of candidates is really dead.

It replaces symbol-by-symbol verification. With 30 candidates, four greps each is 120 passes
over the tree; here the tree is read once and every symbol is looked up at the same time.
Measured: from minutes to seconds.

It does not just count: **it classifies each match**, which is what decides the verdict. A
`grep` says "1 use" both for a real call and for a homonymous Pydantic field, a mention in a
comment or a name inside a string.

    code       a real reference → the symbol is NOT dead
    string     inside quotes: mock.patch, importlib, dispatch from config
               → INVISIBLE to AST analysis, and it may be a real use
    comment    prose → counts as zero
    definition its own declaration

Uso:
    python3 check_dead.py --root backend --symbols a,b,c
    python3 mcview/mcview.py --status DEAD_CANDIDATE --limit 200 --json \\
      | python3 check_dead.py --root backend --json-stdin
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

EXT = {".py", ".pyi", ".md", ".yml", ".yaml", ".json", ".toml", ".sql", ".sh",
       ".ts", ".tsx", ".js", ".env", ".cfg", ".ini", ".txt"}
IGNORED = {"__pycache__", ".venv", "venv", "node_modules", ".git", ".mcview",
           ".codegraph", "build", "dist", ".mypy_cache", ".pytest_cache",
           # JS/TS build output. The bundles hold the COMPILED code, so every symbol
           # appears there and the verdict comes out "ALIVE" for EVERYTHING. Measured: 238
           # matches for `Filters` in .next, none of them evidence. Generated code
           # is never evidence — it is a copy of what you are evaluating.
           ".next", ".turbo", ".vercel", "out", "coverage", ".svelte-kit"}


CODE_EXT = {".py", ".pyi", ".ts", ".tsx", ".js", ".sql", ".sh"}


def clasificar(line: str, col: int, name: str, ext: str = ".py") -> str:
    """What this match IS. The distinction decides the verdict: a grep says "1 use" both for a
    real call and for a homonymous Pydantic field or a
    mention en prosa."""
    if ext not in CODE_EXT:
        return "doc"
    before = line[:col]
    # `name: type = ...` at class level is a homonymous DECLARATION, not a use
    if re.match(rf"\s+{re.escape(name)}\s*:\s*\S", line):
        return "declaracion"
    if re.search(r"^\s*(#|//|\*)", line) or "#" in before.split('"')[0].split("'")[0]:
        return "comentario"
    if re.match(rf"\s*(async\s+)?(def|class)\s+{re.escape(name)}\b", line):
        return "definition"
    # unclosed quotes before the position → we are inside a string
    if (before.count('"') - before.count('\\"')) % 2 or (before.count("'") - before.count("\\'")) % 2:
        return "string"
    return "code"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--symbols", help="comma-separated list")
    ap.add_argument("--json-stdin", action="store_true",
                    help="read_rows la output de `mcview.py --status ... --json`")
    ap.add_argument("--git", action="store_true",
                    help="also date each symbol with git log -S (slower)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.json_stdin:
        datos = json.load(sys.stdin)
        target = {d["name"]: d.get("loc", "") for d in datos}
    elif args.symbols:
        target = {s.strip(): "" for s in args.symbols.split(",") if s.strip()}
    else:
        sys.exit("faltan --symbols o --json-stdin")
    if not target:
        sys.exit("nothing to verify")

    patron = re.compile(r"\b(" + "|".join(re.escape(n) for n in target) + r")\b")
    findings = defaultdict(lambda: defaultdict(list))
    dinamicos = []

    # ONE pass over the tree, every symbol at once
    for dirpath, dirnames, filenames in os.walk(args.root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED]
        for fn in filenames:
            if os.path.splitext(fn)[1] not in EXT:
                continue
            path = os.path.join(dirpath, fn)
            try:
                text = open(path, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            if not patron.search(text):
                continue
            for i, line in enumerate(text.split("\n"), 1):
                if "importlib" in line or "__import__" in line or "getattr(" in line:
                    if patron.search(line):
                        dinamicos.append(f"{path}:{i}")
                for m in patron.finditer(line):
                    name = m.group(1)
                    findings[name][clasificar(line, m.start(), name,
                                                os.path.splitext(fn)[1])].append(
                        f"{path}:{i}")

    rows = []
    for name, loc in target.items():
        h = findings.get(name, {})
        propio = loc.split(":")[0] if loc else None
        # code in ANOTHER file = a real use; in its own, it may be mutually dead
        code_elsewhere = [x for x in h.get("code", [])
                        if not propio or propio not in x]
        rows.append({
            "name": name, "loc": loc,
            "codigo_externo": len(code_elsewhere),
            "string": len(h.get("string", [])),
            "doc": len(h.get("doc", [])),
            "homonimo": len(h.get("declaracion", [])),
            "comentario": len(h.get("comentario", [])),
            "verdict": ("ALIVE — real reference" if code_elsewhere
                          else "REVIEW — only in strings" if h.get("string")
                          else "no references (mentions in docs/homonyms)"
                          if h.get("doc") or h.get("declaracion")
                          else "no references"),
            "evidencia": (code_elsewhere or h.get("string", []) or
                          h.get("doc", []) or h.get("declaracion", []))[:3],
        })

    if args.git:
        for f in rows:
            try:
                out = subprocess.run(
                    ["git", "log", "--oneline", "-1", "--reverse", "-S", f["name"]],
                    capture_output=True, text=True, timeout=25).stdout.strip()
                f["nacio_en"] = out.split("\n")[0][:60] if out else ""
            except (subprocess.SubprocessError, OSError):
                f["nacio_en"] = ""

    call_order = {"ALIVE — real reference": 0, "REVIEW — only in strings": 1,
             "no references (mentions in docs/homonyms)": 2, "no references": 3}
    rows.sort(key=lambda f: (call_order[f["verdict"]], f["name"]))

    if args.json:
        print(json.dumps({"symbols": rows, "importacion_dinamica": dinamicos},
                         ensure_ascii=False, indent=2))
        return

    print(f"\n  {len(rows)} candidates verified in ONE pass\n")
    print(f"  {'symbol':32s} {'code':>4s} {'str':>4s} {'doc':>4s} {'hom':>4s}  verdict")
    print("  " + "-" * 78)
    for f in rows:
        print(f"  {f['name'][:32]:32s} {f['codigo_externo']:4d} {f['string']:4d} "
              f"{f['doc']:4d} {f['homonimo']:4d}  {f['verdict']}")
        if f["verdict"].startswith(("VIVO", "REVISAR")):
            for e in f["evidencia"]:
                print(f"       ↳ {e}")
    if dinamicos:
        print(f"\n  ⚠ dynamic import near these names:")
        for d in dinamicos[:8]:
            print(f"       {d}")
    n = sum(1 for f in rows if f["verdict"].startswith("no references"))
    print(f"\n  {n}/{len(rows)} with no real reference at all.")
    print(f"  The rest are NOT deletable: review the evidence above.\n")


if __name__ == "__main__":
    main()
