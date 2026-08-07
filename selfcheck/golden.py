#!/usr/bin/env python3
"""Regression lock: the tool says THE SAME THING before and after being moved.

The other four `check_*` scripts prove the CLI **runs**. That is not enough for a migration:
renaming the package, splitting the tree into layers and moving printing out of `main` must
not change a single number, and "nothing changed" read off the diff is exactly the
evidence-free claim this tool exists in order not to accept.

It runs the CLI **as a subprocess** —like `check_portability`, and for the same reason: what
gets frozen is the surface a user sees, not the internal state of some imports— over every
workspace config and every view, normalizes what legitimately varies, and compares against
`golden/`.

    mcview/selfcheck/golden.py --record     # capture the baseline (once, while green)
    mcview/selfcheck/golden.py              # verify: empty diff or failure
    mcview/selfcheck/golden.py --full   # + the expensive views (see below)
    mcview/selfcheck/golden.py --seeds   # does the output depend on PYTHONHASHSEED?

TWO LEVELS, and the reason is measured: the census takes **4.8 s without duplicates and over
5 min with them** on `hermes/hermes-agent`, the tree two configs share. An hour-long lock does
not get run, and one that does not get run is not a lock.

    fast (default)  every view, duplicates only where they are cheap → per commit
    --full      + duplicates across all 4 projects                → per phase

The fast level does NOT cover hermes' duplication, and it says so at the end instead of
letting the green be read as full coverage.

WHAT GETS NORMALIZED, and why each one:

  · times ("2.0s", "1.4 s")        — they measure the machine, not the code
  · absolute repo paths            — portability is already tested elsewhere
  · the TOOL NAME                  — `mcview` → `<TOOL>`. It is what lets the rename be
                                     VERIFIED instead of asserted: if the only change is
                                     what it is called, the golden does not move. PROJECT
                                     names are left alone.

What does NOT go in: `--diff`, which compares against the working tree and changes with every
commit of the migration itself. Measuring that here would freeze the noise.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

# The layers, mounted like every other lock does. Without this `_targets` raised
# ModuleNotFoundError on `config` and `--seeds` — the check written to catch output that
# depends on PYTHONHASHSEED — had never run. It was found by a non-determinism it would have
# caught: the same command produced two different evidence samples in `--blueprint`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401

HERE = os.path.dirname(os.path.abspath(__file__))
MCVIEW = os.path.dirname(HERE)
REPO = os.path.dirname(MCVIEW)
CLI = os.path.join(MCVIEW, os.path.basename(MCVIEW) + ".py")
if not os.path.exists(CLI):                      # before the rename the CLI is mcview.py
    CLI = os.path.join(HERE, "mcview.py")
GOLDEN = os.path.join(HERE, "golden")

# Outputs longer than this are frozen by hash: the HTML page weighs ~1.2 MB and versioning it
# whole would put the embedded renderer inside the lock.
TOPE_LITERAL = 120_000


def _configs() -> dict[str, str]:
    """The per-project `.toml` files, by short name. The file name itself changes with the
    tool's name, so it is discovered by suffix and not by literal.

    `mcview.workspace.toml` is NOT one of them: it describes the junctions between projects,
    not a repository, and it has no `[project] root` to walk. Treating it as a project made
    the focused views pick a target out of the workspace root — the same distinction
    `mcview.py::_workspace_configs` already makes.
    """
    out = {}
    for f in sorted(os.listdir(REPO)):
        m = re.fullmatch(r"mcview(?:\.([\w-]+))?\.toml", f)
        if m and m.group(1) != "workspace":
            out[m.group(1) or "principal"] = os.path.join(REPO, f)
    return out


# WHERE COVERAGE IS PAID FOR, measured and not chosen: the view machinery is ONE and does not
# depend on the project, so running all 23 views four times buys repetition, not coverage.
# What a second project does buy is that config DISCOVERY and the TypeScript parser keep
# working — and a handful of views test that.
#
#   principal (backend, ~6k symbols)    all 23 views          ~90 s
#   the other three                     the smoke test (5)    ~60 s
#
# The timings behind it: census with duplicates over `hermes/hermes-agent` >5 min (4.8 s
# without them), and `--views` over the same tree >8 min because it walks git history.
PRINCIPAL = "principal"
HUMO = {"census", "map", "modules", "seams", "services"}

# (name, arguments). The name is the golden file's, so it does not carry the tool's name
# inside. Only the census reaches `duplicates.analyze`; the other views return earlier, so
# there the flag changes nothing.
VISTAS_GLOBALES = [
    ("census", []),
    ("census-json", ["--json"]),
    ("risk", ["--risk"]),
    ("map", ["--map"]),
    ("map-json", ["--map", "--json"]),
    ("modules", ["--modules"]),
    ("k", ["--k"]),
    ("hierarchy", ["--hierarchy"]),
    ("islands", ["--islands"]),
    ("combinadas", ["--views"]),
    ("no-consumer", ["--no-consumer"]),
    ("seams", ["--seams"]),
    ("reach", ["--reach"]),
    ("services", ["--services"]),
]

# Focused views: the target depends on the project, so it CANNOT be a literal. Hardcoding it
# is the same mistake as putting the config inside the tool — it worked here and would have
# skipped every focused view in any other repository, which is indistinguishable from a lock
# that passes. They are DERIVED from the config: the declared modules with the most files,
# which are the ones that exercise the path tracer (a cold area does not).
N_OBJETIVOS = 3


def _targets(toml_path: str, how_many: int) -> list[str]:
    """The project's largest areas, computed. Same criterion as `check_view._largest_target`.

    It is deliberately cheap: it reads the config and counts files on disk instead of building
    the graph, because this runs once per project before any view does.
    """
    import os as _os
    from collections import Counter

    import config as _cfg
    cfg = _cfg.load(toml_path)
    counts: Counter = Counter()
    for dirpath, dirnames, filenames in _os.walk(cfg.root):
        dirnames[:] = [d for d in dirnames if d not in cfg.ignored_dirs]
        for f in filenames:
            if not f.endswith((".py", ".ts", ".tsx")):
                continue
            rel = _os.path.relpath(_os.path.join(dirpath, f), cfg.root)
            if not cfg.excluded(rel) and cfg.is_product_dir(rel) or not cfg.product_dirs:
                counts[cfg.module_of(rel)] += 1
    # A declared module beats a directory fallback: it is the unit the owner thinks in.
    declared = [m for m, _ in counts.most_common() if m in cfg.modules]
    return (declared or [m for m, _ in counts.most_common()])[:how_many]


def _cases(full: bool, only: str | None = None):
    """`only` was PARSED and never passed here. The flag was documented in the module header,
    accepted on the command line, and did nothing — so `--only principal`, advertised at ~90 s,
    silently ran all four projects and took as long as the full sweep. Found while waiting for
    it. Same class as a config key with no reader: the caller believes the scope was narrowed.
    """
    for project, cfg in _configs().items():
        if only and not project.startswith(only):
            continue
        principal = project == PRINCIPAL
        for name, args in VISTAS_GLOBALES:
            if not (principal or full or name in HUMO):
                continue
            # Duplicates are only computed by the census; the other views return earlier,
            # so there the flag would change nothing.
            if name.startswith("census") and not (principal or full):
                args = args + ["--no-duplicates"]
            yield f"{project}.{name}", cfg, args
        targets = _targets(cfg, N_OBJETIVOS if principal or full else 1)
        for i, obj in enumerate(targets):
            base = ["--orient", obj, "--no-twins"]
            yield f"{project}.orient{i}", cfg, base
            yield f"{project}.flow{i}", cfg, base + ["--flow"]
            yield f"{project}.flow{i}-json", cfg, base + ["--flow", "--json"]
            if i == 0:
                yield f"{project}.mermaid-sec", cfg, base + ["--flow", "--mermaid"]
                yield f"{project}.mermaid-map", cfg, base + ["--flow", "--mermaid", "map"]
                yield f"{project}.html", cfg, base + ["--flow", "--html"]
    yield "workspace.bridges", None, ["--bridges"]


_TIEMPO = re.compile(r"\d+[.,]\d+\s?s\b")
_HERRAMIENTA = re.compile(r"\b(mcview|mcview|MCVIEW|MCVIEW)\b")


def normalize(txt: str) -> str:
    txt = txt.replace(REPO, "<REPO>")
    txt = _TIEMPO.sub("<T>", txt)
    txt = _HERRAMIENTA.sub("<TOOL>", txt)
    # `Ns` with no decimals appears in the index and in the HTML.
    txt = re.sub(r"\b\d+ms\b", "<T>", txt)
    return txt


def run(cfg: str | None, args: list[str], seed: str = "0") -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    cmd = [sys.executable, CLI] + (["--config", cfg] if cfg else []) + args
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO, env=env, timeout=900)
    output = normalize(r.stdout + ("\n[STDERR]\n" + r.stderr if r.stderr.strip() else ""))
    if len(output) > TOPE_LITERAL:
        cab = "\n".join(output.splitlines()[:80])
        return f"{cab}\n…[{len(output)} chars]\nsha256={hashlib.sha256(output.encode()).hexdigest()}\n"
    return f"$ <TOOL> {' '.join(args)}\nexit={r.returncode}\n\n{output}"


def main():
    record = "--record" in sys.argv
    seeds = "--seeds" in sys.argv
    full = "--full" in sys.argv
    # `--only <prefix>` runs one slice. The view machinery is ONE and does not depend on the
    # project, so `--only principal` (23 views, ~90 s) covers the risk of a structural change;
    # the other three projects test config discovery and the TypeScript parser, which moving
    # files does not touch.
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    os.makedirs(GOLDEN, exist_ok=True)
    failures, n = [], 0

    for name, cfg, args in _cases(full, only):
        n += 1
        got = run(cfg, args)
        target_node = os.path.join(GOLDEN, name + ".txt")
        if record:
            with open(target_node, "w", encoding="utf-8") as fh:
                fh.write(got)
            print(f"  ▸ {name}")
            continue
        if seeds:
            other = run(cfg, args, seed="12345")
            if other != got:
                failures.append(f"{name}: THE OUTPUT DEPENDS ON PYTHONHASHSEED")
            continue
        if not os.path.exists(target_node):
            failures.append(f"{name}: no baseline — run --record")
            continue
        esperado = open(target_node, encoding="utf-8").read()
        if esperado != got:
            d = next((i for i, (a, b) in enumerate(zip(esperado.splitlines(),
                                                       got.splitlines())) if a != b), 0)
            e = esperado.splitlines()
            o = got.splitlines()
            failures.append(f"{name}: differs at line {d+1}\n"
                          f"      esperado: {e[d] if d < len(e) else '<end>'}\n"
                          f"      got: {o[d] if d < len(o) else '<end>'}")

    # What the fast level does NOT cover is stated here. A green that stays quiet about its
    # reach reads as "it covers everything", which is the claim this file exists not to make.
    caveat = "" if full else (
        f"\n  ⚠ fast level: all 23 views only over '{PRINCIPAL}'; in the other "
        f"projects {len(HUMO)} smoke views and no duplicates — "
        f"run --full before closing a phase")

    if record:
        print(f"\n  ✓ baseline recorded: {n} views in {GOLDEN}{caveat}")
        return 0
    if failures:
        print(f"\n  ✗ {len(failures)} de {n} views cambiaron:\n")
        for f in failures:
            print(f"    · {f}")
        return 1
    print(f"  ✓ golden: {n} identical views"
          f"{' bajo dos PYTHONHASHSEED' if seeds else ''}{caveat}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
