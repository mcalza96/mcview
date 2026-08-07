#!/usr/bin/env python3
"""Does an INDEPENDENT extractor see the same code this one does?

Every other lock here checks mcview against itself: a fixture it wrote, a golden it recorded,
an invariant it believes. That is circular in one specific way — a parser bug that is
consistent with itself passes all of them. This one asks a second implementation, written by
somebody else, in another language, over the same files.

The oracle is any pre-indexed code graph that leaves a SQLite database behind
(`.codegraph/codegraph.db` — codegraph, MIT, https://github.com/colbymchenry/codegraph). It is
never a runtime dependency: mcview works with no index present, and this lock SKIPS, loudly.

TWO CHECKS, and what each one can actually catch:

  A · INVENTORY   symbols one has and the other does not.
                  Catches mcview losing or inventing SYMBOLS while parsing.
                  Measured on CIRE backend: 6,168 vs 6,186 — 0.3% apart. Two extractors,
                  two implementation languages, the same census. That agreement is the
                  evidence that makes the disagreement meaningful.

  B · RECALL      calls the index RESOLVED that mcview does not have.
                  Catches holes in mcview's resolution. Measured: 117 of 6,944 (1.7%).

WHAT THIS CANNOT DO, and it was measured rather than assumed. It does not catch mcview
INVENTING an edge. The obvious check —same file, same line, different target— was built and
discarded: reintroducing a real precision bug (comprehension and lambda targets not binding,
which fabricated strong edges) moved it by ZERO, twice, under two definitions of
contradiction. The reason is structural: the index resolves ~38% of references, so a
fabricated edge lands where it resolved nothing; and where the site does coincide, mcview
ADDS a false target while keeping the true one, so the intersection never empties. A
conservative index cannot be the precision oracle of an exhaustive one — it is missing the
case, not the criterion. Precision stays with `check_reach` and its fixtures, which is what
actually rejected that bug.

WHAT IT DOES CATCH, seeded and measured: breaking attribute resolution (`x.method()`) takes
`missing_calls` from 117 to 2,997. Its teeth are for a whole resolution CLASS going dark, not
for a narrow scope bug — the same seeding showed a scope over-suppression moving it by zero,
because the edges that one removes are mostly the fabricated ones the index never had either.

Baselines are pinned per project, in `golden/external_index.json`, because divergence is a
property of THIS pair of tools over THIS repo — a round number would be a threshold nobody
measured. The lock fails when divergence GROWS.

A pinned difference has to be EXPLAINED before it is pinned, or the baseline just freezes a
bug. The two live here:

  python      0.0–0.2% apart across four projects, up to 38,769 symbols. Nothing to explain.
  typescript  33.8% apart, and it decomposes: 22% is vocabulary (a React component written
              `const Panel = memo(...)` is a symbol here and a `constant` there), and the
              rest is nesting — mcview indexes a function-valued `const` and an inline
              `type` DECLARED INSIDE another function, which the index does not. Verified by
              reading them: `cleanup` and `onClientAbort` in `app/api/hermes/chat/route.ts`
              are nested arrow functions. Counting them is deliberate; `ALIVE_BY_NESTING`
              exists because a callback is passed by reference and never called by name.

    mcview/selfcheck/check_external_index.py            # 0 = pass
    mcview/selfcheck/check_external_index.py --record   # pin today's numbers
"""
from __future__ import annotations

import collections
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config    # noqa: E402
import factory as _factory  # noqa: E402

AQUI = os.path.dirname(os.path.abspath(__file__))
BASELINE = os.path.join(AQUI, "golden", "external_index.json")

# The kinds an external index uses for what mcview calls a symbol. The vocabulary is not the
# same on both sides and it differs BY LANGUAGE, which is why the divergence is pinned per
# project instead of held to a single threshold: on TypeScript, a React component declared
# `const Panel = memo(...)` is a symbol for mcview and a `constant` for the index. `variable`
# and `constant` stay out — counting every configuration constant would inflate the
# difference with noise that is not a disagreement about the code.
KINDS = ("function", "method", "class", "interface")


def _find_db(start: str) -> str | None:
    """Walk up looking for an index. It belongs to the REPOSITORY, not to the project, so a
    monorepo has one at the root while mcview measures a subdirectory."""
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, ".codegraph", "codegraph.db")
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _theirs(db_path: str, repo_root: str, project_root: str, cfg):
    """Their symbols and their resolved calls, in mcview's coordinates.

    Paths come out relative to the REPO; mcview speaks relative to the PROJECT. Getting this
    wrong does not fail — it reports a 100% disagreement, which reads like a catastrophic
    parser bug and is a path bug.

    Their side is filtered through THIS config's exclusions, and that is not a detail: without
    it, `mcview.hermes-prod.toml` —which excludes tests, scripts and docs— reported 8,876
    symbols against 38,769, a 336% disagreement that was entirely the lock comparing a scoped
    project against an unscoped index. A lock that fabricates a catastrophe is worse than no
    lock: it trains you to ignore it.
    """
    prefix = os.path.relpath(project_root, repo_root)
    prefix = "" if prefix == "." else prefix.replace(os.sep, "/") + "/"
    rel = (lambda p: p[len(prefix):]) if prefix else (lambda p: p)
    ignored = set(cfg.ignored_dirs)

    def mine_too(path: str) -> bool:
        r = rel(path)
        parts = r.split("/")
        return not (cfg.excluded(r) or any(x in ignored or x.startswith(".") for x in parts[:-1]))

    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    marca = (f"select id,name,file_path from nodes where kind in {KINDS} "
             "and file_path like ?", (prefix + "%",))
    symbols = {(rel(f), n) for _, n, f in db.execute(*marca) if mine_too(f)}

    calls = set()
    for af, an, bf, bn in db.execute(
            "select a.file_path,a.name,b.file_path,b.name from edges e "
            "join nodes a on a.id=e.source join nodes b on b.id=e.target "
            "where e.kind='calls' and a.file_path like ? and b.file_path like ? "
            f"and a.kind in {KINDS} and b.kind in {KINDS}", (prefix + "%", prefix + "%")):
        if mine_too(af) and mine_too(bf):
            calls.add(((rel(af), an), (rel(bf), bn)))
    db.close()
    return symbols, calls


def compare(cfg_path: str) -> dict | None:
    """Returns the divergence, or None if there is no index — and None is NOT an empty dict.

    That distinction is not pedantry: a sibling lock printed `typescript 5/5` right after
    saying `TypeScript skipped`, because the skip returned an empty list of failures and
    "did not run" is indistinguishable from "ran and passed" once it is one.
    """
    cfg = _config.load(cfg_path)
    db_path = _find_db(cfg.root)
    if not db_path:
        return None
    repo_root = os.path.dirname(os.path.dirname(db_path))

    p = _factory.make_project(cfg)
    # Compared by (file, name) and not by line: a decorator puts the index's line and
    # mcview's `def` several lines apart, and comparing those would report as disagreement
    # what is a convention about where a symbol begins.
    mine = {(s.file, s.name) for s in p.symbols.values()}
    mine_edges = set()
    for o, ds in p.edges.items():
        so = p.symbols.get(o)
        if not so:
            continue
        for d in ds:
            sd = p.symbols.get(d)
            if sd:
                mine_edges.add(((so.file, so.name), (sd.file, sd.name)))

    # THE TREE, stamped with the numbers. This lock pins a baseline and the baseline ages
    # against a repository somebody else is working in: measured, it fired on a project this
    # session never touched while a `.tsx` was being edited, and reported it as a regression.
    # Third time a lock here mistook a moving tree for one — `check_determinism` got the same
    # guard for the same reason. A lock that fabricates a catastrophe trains you to ignore it.
    import hashlib as _h
    huella = _h.sha256()
    for dirpath, dirnames, filenames in os.walk(cfg.root):
        dirnames[:] = sorted(d for d in dirnames if d not in cfg.ignored_dirs)
        for nombre in sorted(filenames):
            try:
                st = os.stat(os.path.join(dirpath, nombre))
            except OSError:
                continue
            huella.update(f"{nombre}:{st.st_mtime_ns}:{st.st_size}".encode())

    theirs, their_calls = _theirs(db_path, repo_root, cfg.root, cfg)
    # Only edges whose BOTH ends exist in mcview's inventory. An edge toward a symbol mcview
    # never saw is an inventory difference (check A) and counting it here too would report
    # the same defect twice, in a check that is supposed to isolate resolution.
    comparable = {e for e in their_calls if e[0] in mine and e[1] in mine}
    return {
        "index": os.path.relpath(db_path, repo_root),
        "mine_symbols": len(mine), "their_symbols": len(theirs),
        "only_mine": len(mine - theirs), "only_theirs": len(theirs - mine),
        "comparable_calls": len(comparable),
        "missing_calls": len(comparable - mine_edges),
        "tree": huella.hexdigest()[:16],
    }


def main() -> int:
    record = "--record" in sys.argv
    root = os.path.dirname(AQUI)
    configs = sorted(f for f in os.listdir(os.path.dirname(root))
                     if f.startswith("mcview") and f.endswith(".toml")
                     and not f.startswith("mcview.workspace"))
    base = {}
    if os.path.exists(BASELINE):
        base = json.load(open(BASELINE, encoding="utf-8"))

    failures, results, skipped = [], {}, []
    for name in configs:
        path = os.path.join(os.path.dirname(root), name)
        try:
            r = compare(path)
        except SystemExit as e:            # optional parser missing: BaseException, not Exception
            skipped.append(f"{name} (no parser: {str(e).splitlines()[0]})")
            continue
        if r is None:
            skipped.append(f"{name} (no external index found)")
            continue
        results[name] = r
        b = base.get(name)
        if not b:
            skipped.append(f"{name} (no baseline — run --record)")
            continue
        if b.get("tree") and b["tree"] != r["tree"]:
            skipped.append(f"{name} (the tree changed since the baseline — any difference is "
                           f"unattributable; re-record on a quiet tree)")
            continue
        for k, label in (("only_mine", "symbols only mcview has"),
                         ("only_theirs", "symbols only the index has"),
                         ("missing_calls", "resolved calls mcview lacks")):
            if r[k] > b[k]:
                failures.append(f"{name}: {label} grew {b[k]} → {r[k]}. Either mcview "
                                f"regressed, or the index did — read the diff before "
                                f"re-recording.")

    if record:
        os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
        json.dump(results, open(BASELINE, "w", encoding="utf-8"), indent=2, sort_keys=True)
        print(f"  recorded {len(results)} project(s) → {os.path.relpath(BASELINE, root)}")
        return 0

    for f in failures:
        print(f"  ✗ {f}")
    for name, r in results.items():
        pct = 100 * (r["only_mine"] + r["only_theirs"]) / max(r["mine_symbols"], 1)
        print(f"  · {name}: {r['mine_symbols']} vs {r['their_symbols']} symbols "
              f"({pct:.1f}% apart) · {r['missing_calls']}/{r['comparable_calls']} "
              f"resolved calls missing")
    for s in skipped:
        print(f"  ~ SKIPPED {s}")
    if not failures:
        # It says how many it compared AND how many it skipped, on the same line, because a
        # green that covered nothing is the failure mode this whole directory exists against.
        print(f"  ✓ external index: {len(results)} compared · {len(skipped)} skipped")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
