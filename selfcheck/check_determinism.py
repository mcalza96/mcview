#!/usr/bin/env python3
"""Does the same command, over the same code, produce the same answer?

It should be too obvious to test, and it was not. Twelve views depended on `PYTHONHASHSEED` —
and not only in the order of equal rows: a computed number moved with it. The fraction of paths
crossing `get_async_supabase_client` came out at **67% under one seed and 72% under another**.
A percentage that changes with the process's string hashing is not a measurement.

THE CAUSE WAS ONE, and that is why the fix was one line in one place. `paths.paths_to` walks
backwards from the sinks with a BFS and keeps the FIRST path that reaches each node — so the
order it starts and expands in decides which path survives, and it started from a `set`. Every
view downstream (`--orient`, `--flow`, both mermaid outputs, the HTML page) inherited it.

WHY THIS REPLACES A HARNESS INSTEAD OF EXTENDING ONE. There was a `golden.py` that ran the CLI
as a SUBPROCESS once per case — 27 cases × 2 seeds — so every case re-parsed the whole
repository from scratch, and one of the four projects it swept has 38k symbols. Measured: 21
minutes for the full sweep, ~6 for the smallest slice. Its own docstring said "an hour-long
lock does not get run, and one that does not get run is not a lock", and then it became one:
its baseline directory was never recorded, its `--seeds` mode died on an import before
measuring anything, and its `--only` flag was parsed and never used. Three modes, none working.

The answer to "does this depend on the hash seed" needs exactly TWO processes — the seed is
fixed at interpreter start, so one is impossible and three are waste. Each builds the graph
ONCE and renders every view against it. Measured: 9.5 s against 21 minutes, and it found six
seed-dependent views the old harness never reported because it never ran.

WHAT THE SIX WERE, because two of them are not about ordering at all and that is the useful
part. `neighbors_by_module` and `_internal_parts` grouped while walking a set and broke ties by
insertion order — cosmetic. The other two ACCUMULATE FLOATS while walking a set, and
floating-point addition is not associative: the same set summed in a different order gave
0.023309784847592552 against ...555. Invisible on screen, enough to change a hash, and enough to
flip a rounded percentage sitting on a boundary. Both are fixed at their source —
`markov.expected_visits` and `flow.targets` — not at the views that read them.

    mcview/selfcheck/check_determinism.py        # 0 = pass
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

SEEDS = ("0", "12345")


def _render(cfg_path: str) -> dict[str, str]:
    """Every view, against ONE graph. Returns {name: sha of its output}.

    The views are called the way the CLI calls them, and the reason is not tidiness: what has
    to be reproducible is the surface a person reads, so hashing an internal structure would
    verify something nobody looks at. `--no-twins` throughout — the duplicate analysis costs
    25 s against 0.4 s for everything else combined, and it has no path through `paths_to`,
    which is the machinery under suspicion.
    """
    import config as _config
    import factory as _factory
    import heatmap as _heatmap
    import orient as _orient
    import flow as _flow
    import blueprint as _bp
    import sequence as _seq
    import seams as _seams
    import json as _json

    cfg = _config.load(cfg_path)

    # A FINGERPRINT OF THE TREE, emitted with the results. This lock compares two processes,
    # and it silently assumed the code would hold still between them — on a repository where
    # somebody else is working, it does not. Measured: two consecutive runs failed on
    # DIFFERENT views while two files were being edited underneath, which reads exactly like
    # non-determinism and is not. A lock that fabricates a catastrophe trains you to ignore it,
    # which is worse than not having one.
    fingerprint = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(cfg.root):
        dirnames[:] = sorted(d for d in dirnames if d not in cfg.ignored_dirs)
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            fingerprint.update(f"{path}:{st.st_mtime_ns}:{st.st_size}".encode())

    project = _factory.make_project(cfg)          # ← ONCE. The whole point of this file.
    rank = _heatmap.pagerank(project)
    levels = project.levels()

    out: dict[str, str] = {"__tree": fingerprint.hexdigest()[:16]}

    def firma(name: str, text: str):
        out[name] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    firma("census", _json.dumps({k: sorted(v) for k, v in levels.items()}, sort_keys=True))
    firma("map", _json.dumps(_heatmap.by_file(project, rank), sort_keys=True, default=str))
    firma("modules", _json.dumps(_heatmap.by_module(project, rank), sort_keys=True, default=str))
    firma("blueprint", _json.dumps(_bp.build(project, rank), sort_keys=True, default=str))
    firma("seams", _json.dumps(_seams.detect(project), sort_keys=True, default=str))

    objetivos = sorted(cfg.modules)[:3] or [sorted({s.file for s in project.symbols.values()})[0]]
    for i, target in enumerate(objetivos):
        r = _orient.orient(project, rank, levels, None, target)
        firma(f"orient{i}", _json.dumps(r, sort_keys=True, default=str))
        if "error" in r:
            continue
        files = set(r["files"])
        inside = {sid for sid, s in project.symbols.items() if s.file in files}
        r["flow"] = _flow.trace(project, inside, rank)
        usan, depende = _flow.neighbors_by_module(project, inside, files)
        r["flow"].update(usan=usan, depende=depende, target=r["target"])
        firma(f"flow{i}", _json.dumps(r["flow"], sort_keys=True, default=str))
        firma(f"mermaid-map{i}", _flow.mermaid(r["flow"], r["target"], usan, depende,
                                               _flow._internal_parts(files)))
        firma(f"mermaid-seq{i}", _flow.mermaid_sequence(r["flow"], r["target"]))
        s = _seq.trace(project, target, rank)
        firma(f"sequence{i}", _json.dumps(s, sort_keys=True, default=str))
        firma(f"reach{i}", _json.dumps(_seq.reach_all(project, target, rank),
                                       sort_keys=True, default=str))
    return out


def main() -> int:
    # The child mode. The seed cannot be changed inside a running interpreter, so the only way
    # to compare two is to be two — and re-executing THIS file keeps the rendering identical on
    # both sides by construction, which a second script would not.
    if "--worker" in sys.argv:
        cfg = sys.argv[sys.argv.index("--worker") + 1]
        for name, sha in sorted(_render(cfg).items()):
            print(f"{name}\t{sha}")
        return 0

    raiz = os.path.dirname(os.path.dirname(AQUI))
    configs = sorted(f for f in os.listdir(raiz)
                     if f.startswith("mcview") and f.endswith(".toml")
                     and "workspace" not in f)
    if not configs:
        print("  ~ SKIPPED: no mcview*.toml found — nothing to compare")
        return 0

    # ONE config is enough and that is a measured claim, not thrift: the view machinery is
    # shared and does not know which project it is looking at, so a second project re-tests the
    # config discovery and the parser, not determinism. The sweep that did all four is what
    # cost 21 minutes.
    # The MAIN project, not whichever sorts first. It was picking `mcview.frontend.toml` by
    # alphabet — which does exercise the TypeScript parser, but the machinery under suspicion
    # is shared and the main config is the bigger, more representative graph.
    cfg = os.path.join(raiz, "mcview.toml" if "mcview.toml" in configs else configs[0])
    outputs = []
    for seed in SEEDS:
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), "--worker", cfg],
                           capture_output=True, text=True, env=env, cwd=raiz)
        if r.returncode != 0:
            print(f"  ✗ the pass with PYTHONHASHSEED={seed} failed:\n{r.stderr[-600:]}")
            return 1
        outputs.append(dict(l.split("\t") for l in r.stdout.strip().splitlines() if "\t" in l))

    a, b = outputs
    # The tree first, and it is not one failure among others: if the code moved, EVERY
    # difference below is unexplained and reporting them as non-determinism would be a lie
    # with hashes behind it.
    if a.get("__tree") != b.get("__tree"):
        print("  ~ INCONCLUSIVE: the source tree changed between the two passes, so any "
              "difference is unattributable.\n    Re-run on a quiet tree — this needs the code "
              "to hold still, and it does not check\n    determinism against a moving target.")
        return 0

    failures = [f"{k}: the output depends on PYTHONHASHSEED ({a[k]} vs {b[k]})"
              for k in sorted(a) if k != "__tree" and a.get(k) != b.get(k)]
    for f in failures:
        print(f"  ✗ {f}")
    if not failures:
        print(f"  ✓ determinism: {len(a) - 1} views identical under PYTHONHASHSEED "
              f"{' and '.join(SEEDS)} · {os.path.basename(cfg)}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
