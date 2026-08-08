#!/usr/bin/env python3
"""mcview — a repository entropy census.

It answers three questions about a project, with evidence and without guessing:

    what code is unused?        → reachability from declared roots
    what code is duplicated?    → structural fingerprint of the AST
    what actually runs?         → runtime census (the probe, optional)

Usage:
    mcview/mcview.py                       # summary of the default project
    mcview/mcview.py --config other/mcview.toml
    mcview/mcview.py --json                # for consumption by an agent
    mcview/mcview.py --status DEAD_CANDIDATE --limit 50

Safety contract: `DEAD_CANDIDATE` **is not a deletion order**. It is a hypothesis
with no static evidence of use. Confirming it requires runtime or manual
verification. The guarantee lives in what this tool returns, not in the prompt of
whoever invokes it.
"""
from __future__ import annotations

import argparse
import glob
import json as _json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config          # noqa: E402
import duplicates as _duplicates  # noqa: E402
import communities as _com        # noqa: E402
import views as _views          # noqa: E402
import diff as _dif        # noqa: E402
import index as _index          # noqa: E402
import heatmap as _heatmap              # noqa: E402
import factory as _factory        # noqa: E402

import orient as _orient  # noqa: E402

_CFG = [""]

ORDEN = ["ALIVE_PRODUCT", "ALIVE_PRODUCT_WEAK", "ALIVE_NOT_PRODUCT",
         "ALIVE_BY_NESTING", "DEAD_CANDIDATE"]

GLOSA = {
    "ALIVE_PRODUCT": "reachable from a real root, by an unambiguous name",
    "ALIVE_PRODUCT_WEAK": "reachable ONLY via an ambiguous name (homonyms)",
    "ALIVE_NOT_PRODUCT": "reachable, but never from a product root",
    "ALIVE_BY_NESTING": "alive only through nesting (its own, or its only caller's)",
    "DEAD_CANDIDATE": "unreachable from every root — a hypothesis, NOT a deletion order",
}


def require_algebra(view: str):
    """`numpy` and `scipy` are OPTIONAL: only the community family asks for them.

    The check lives here, at the dispatch, and not at the 16 sites where they are
    imported: whoever needs the message is whoever chose the view, and that way the core
    —the census, the map, the gate, `--orient` and `--flow`— keeps running on the bare
    stdlib. Verified by blocking the modules, not by reading the imports.
    """
    try:
        import numpy  # noqa: F401
        import scipy.sparse  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            f"`{view}` needs numpy and scipy, which are optional. Install them with:\n"
            "    pip install numpy scipy\n"
            "The rest of the tool (census, --map, --orient, --flow, the gate) does "
            f"not need them.\n({e})"
        ) from e


_workspace_configs = _config.workspace_configs


def CACHE_WEAVE():
    """The weave, for a walkthrough whose stages cross repositories."""
    import weave as _tej
    return _tej.build(_workspace_configs(os.path.dirname(os.path.abspath(_CFG[0]))))


def main():
    ap = argparse.ArgumentParser(description="a repository entropy census")
    ap.add_argument("--config", help="path to a .toml; by default `mcview.toml` is discovered "
                                     "by walking up from the current directory")
    ap.add_argument("--project", help="shortcut: uses `mcview.<name>.toml` from the root")
    ap.add_argument("--json", action="store_true", help="structured output")
    ap.add_argument("--mcp", action="store_true",
                    help="run as an MCP server over stdio (JSON-RPC 2.0)")
    ap.add_argument("--init", action="store_true",
                    help="derive a starter mcview.toml from what the project already "
                         "declares (scripts, Dockerfile, registration decorators, routes)")
    ap.add_argument("--force", action="store_true",
                    help="with --init: overwrite an existing mcview.toml")
    ap.add_argument("--status", help="list one specific status")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--no-duplicates", action="store_true")
    ap.add_argument("--diff", metavar="REF",
                    help="what the working tree did to the repo relative to REF")
    ap.add_argument("--risk", action="store_true",
                    help="dead candidates, from safest to riskiest")
    ap.add_argument("--reindex", action="store_true",
                    help="build/update the cached index")
    ap.add_argument("--exists", metavar="FILE",
                    help="does what is in FILE (or stdin) already exist?")
    ap.add_argument("--views", action="store_true",
                    help="combine structural + lexical + evolutionary views")
    ap.add_argument("--weights", default="1,0.5,0.3",
                    help="view weights (structural,lexical,evolutionary)")
    ap.add_argument("--islands", action="store_true",
                    help="which files to split and WHERE (internal components)")
    ap.add_argument("--hierarchy", action="store_true",
                    help="k_sub per module (split) and merge ΔQ (join)")
    ap.add_argument("--k", action="store_true",
                    help="the graph's natural k by Newman modularity")
    ap.add_argument("--modules", action="store_true",
                    help="declared vs discovered lines of work (MCL)")
    ap.add_argument("--inflation", type=float, default=1.4,
                    help="granularity: 1.4 lines of work · 2.0 sub-lines")
    ap.add_argument("--locks", action="store_true",
                    help="run the connection contracts declared in the .toml")
    ap.add_argument("--propose", nargs=2, metavar=("FROM", "TO"),
                    help="what is worth locking between two parts; emits the TOML block")
    ap.add_argument("--no-collapse", action="store_true",
                    help="with --decisions: one node per symbol, without condensing chains")
    ap.add_argument("--decisions", action="store_true",
                    help="with --sequence --to: the turn's network as a decision tree, "
                         "with P(branch) from the Markov chain")
    ap.add_argument("--sequence", metavar="TARGET",
                    help="what happens and IN WHAT ORDER from an entry point "
                         "(«project\u25b8target» to cross repos)")
    ap.add_argument("--depth", type=int, default=4, help="with --sequence: depth levels")
    ap.add_argument("--to", dest="to", metavar="TARGET",
                    help="with --sequence: narrate EVERYTHING leading to the target, without "
                         "pruning by mass")
    ap.add_argument("--walkthrough", metavar="SPEC",
                    help="a JOURNEY as a figure from a .toml of lanes and stages: verifies "
                         "every stage resolves, draws the cuts as cuts, prints the caveats. "
                         "SVG to stdout; add --png to also rasterise if a converter exists")
    ap.add_argument("--png", metavar="FILE", help="with --walkthrough: also write a PNG")
    ap.add_argument("--blueprint", action="store_true",
                    help="the skeleton of a conceptual diagram: nodes, edges with their grade "
                         "of evidence, doors and CUTS — everything except what each one is "
                         "FOR, which is the one part no measurement gives")
    ap.add_argument("--all", dest="todas", action="store_true",
                    help="with --sequence: every edge the flow CAN traverse (a set, not a "
                         "narrative) — grouped by line of work and weighted by the chain")
    ap.add_argument("--runtime", action="store_true",
                    help="mark which steps were seen executing (it confirms, it never rules out)")
    ap.add_argument("--route", metavar="NAME",
                    help="everything traversable between two points of the workspace "
                         "(those declared in [[routes]] of mcview.workspace.toml)")
    ap.add_argument("--workshop", action="store_true",
                    help="with --atlas: EVERY project in the workspace and their seams")
    ap.add_argument("--from", dest="origin", metavar="SURFACE",
                    help="with --atlas: the map of what ONE user door reaches "
                         "(those declared in [surfaces])")
    ap.add_argument("--atlas", action="store_true",
                    help="the territory: an interactive 2D map of how everything connects "
                         "(redirigir a un .html y abrirlo)")
    ap.add_argument("--map", action="store_true",
                    help="heat map: how much weight each file carries in usage")
    ap.add_argument("--services", action="store_true",
                    help="what code each process can execute, and what is shared")
    ap.add_argument("--no-consumer", action="store_true",
                    help="what gets computed and GOVERNS nothing (only logs or transport read it)")
    ap.add_argument("--bridges", action="store_true",
                    help="joins the catalogs of EVERY mcview*.toml in the workspace")
    ap.add_argument("--seams", action="store_true",
                    help="the literals through which this project joins others")
    ap.add_argument("--reach", action="store_true",
                    help="EXPORTED literals nobody can select: orphans (nobody writes "
                         "that name) and inert-only (docs/tests write it, which does not make "
                         "it selectable). It is `--no-consumer` in the plane of strings, "
                         "where dispatch by name makes the edge invisible to the graph")
    ap.add_argument("--orient", metavar="TARGET",
                    help="structural brief for ONE area (module, path or symbol)")
    ap.add_argument("--no-twins", action="store_true",
                    help="with --orient: skip the duplicate analysis")
    ap.add_argument("--flow", action="store_true",
                    help="with --orient: the ROUTE — how you get in, where it goes, where it reaches")
    ap.add_argument("--cross", action="store_true",
                    help="with --flow: follow the path into the workspace's other projects")
    ap.add_argument("--html", action="store_true",
                    help="with --flow: the complete page (redirect to a .html and open it)")
    ap.add_argument("--mermaid", nargs="?", const="sequence", choices=["sequence", "map"],
                    help="with --flow: a Mermaid diagram. 'sequence' (default) = the real "
                         "paths merged; 'map' = the lines of work around it")
    args = ap.parse_args()

    # --mcp runs before everything: the server resolves its own config per call, because a
    # long-lived server can be asked about several projects in one session.
    if args.mcp:
        import mcp_server
        sys.exit(mcp_server.serve())

    # --init runs BEFORE config discovery, which is the whole point: it exists for the repo
    # that does not have one yet. Every other path exits here with "could not find
    # mcview.toml", and that message is where a first-time user currently stops.
    if args.init:
        import bootstrap as _boot
        root = os.getcwd()
        target = os.path.join(root, "mcview.toml")
        findings = _boot.detect(root)
        # `--json` inspects without writing, so the overwrite guard does not apply to it:
        # gating a read-only path behind a write guard makes the tool refuse to answer a
        # question it can answer perfectly well.
        if args.json:
            print(_json.dumps(findings, ensure_ascii=False, indent=2))
            return
        if os.path.exists(target) and not args.force:
            sys.exit(f"  {target} already exists. Read it before replacing it — it may carry "
                     f"roots that were added because of a real false positive. "
                     f"Use --force to overwrite, or --json to see what it would derive.")
        open(target, "w", encoding="utf-8").write(_boot.render(root, findings))
        n_dec = len(findings["decorators"])
        n_ent = len(findings["entrypoints"])
        print(f"\n  wrote {target}")
        print(f"  {findings['language']} · {findings['n_py']} .py · {findings['n_ts']} .ts/.tsx")
        n_conv = len(findings.get("convention_roots") or ())
        print(f"  {n_dec} registration decorator(s) · {len(findings['route_methods'])} route "
              f"method(s) · {n_ent} entrypoint(s)"
              + (f" · {n_conv} loaded by framework CONVENTION" if n_conv else ""))
        # The convention roots count. Leaving them out of this test told a project whose roots
        # are ALL conventional —a filesystem-routed frontend, 31 of them— that "nothing real was
        # found", and pointed it at the expensive mistake it had just avoided. The file it had
        # written said the opposite two lines up. A summary that contradicts its own output is
        # worse than no summary: the file is right and nobody reads past the warning.
        if not (n_dec or n_ent or n_conv or findings["route_methods"]):
            print("\n  ⚠ nothing real was found: it fell back to whole directories, which is")
            print("    the expensive mistake. Open the file — it says what to do instead.")
        else:
            print("\n  Every root says where it came from. Read it before believing a number:")
            print("    mcview --map          does the mass look like your system?")
            print("    mcview --orient <X>   ask it something whose answer you already know")

        print()
        return

    # The config is DISCOVERED; it does not live inside the tool. See `config.discover`.
    if not args.config:
        args.config = _config.discover(args.project)
    _CFG[0] = args.config or ""
    if not args.config or not os.path.exists(args.config):
        which = f"mcview.{args.project}.toml" if args.project else "mcview.toml"
        sys.exit(f"could not find {which} walking up from {os.getcwd()}.\n"
                 f"Declaring the roots is mandatory: write a {which} at the project "
                 f"root, or pass --config <path>.")

    if args.diff:
        import subprocess
        repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
        before = _dif.snapshot_of(repo, args.diff, args.config)
        after = _dif.snapshot_of(repo, None, args.config)
        d = _dif.compare(before, after)
        v, signals = _dif.verdict(d)
        if args.json:
            print(_json.dumps({"verdict": v, "signals": signals, **d},
                              ensure_ascii=False, indent=2, default=str))
            return
        print(f"\n  DIFF vs {args.diff} — {v.upper()}\n")
        for s in signals:
            print(f"    · {s}")
        if not signals:
            print("    no signals")
        print(f"\n  net symbols per area:")
        for k, n in sorted(d["net_symbols"].items()):
            if n:
                print(f"    {k:16s} {n:+d}")
        print(f"\n  files touched: {d['files_touched']}   "
              f"mass they represent: {d['change_heat_pct']}%")
        print(f"  concentration (files = 50% of usage): "
              f"{d['concentration']['before']} → {d['concentration']['after']}")
        for h in d["duplicacion_introducida"][:8]:
            print(f"\n    ⚠ structural twin: {h['name']}  {h['file']}  [{h['area']}]")
        print()
        return

    if args.reindex:
        cfg = _config.load(args.config)
        t = time.time()
        idx = _index.build(cfg)
        n = sum(len(v) for v in idx["files"].values())
        print(f"  index: {n} symbols · {len(idx['files'])} files · "
              f"{idx['reparsed']} reparsed · {time.time()-t:.2f}s")
        return

    if args.exists:
        cfg = _config.load(args.config)
        idx = _index.load(cfg) or _index.build(cfg)
        if args.exists == "-":
            src, rel = sys.stdin.read(), "<stdin>"
        else:
            src, rel = open(args.exists, encoding="utf-8").read(), args.exists
        r = _index.query(idx, src, rel)
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return
        if not r["by_shape"] and not r["by_name"]:
            print(f"  nothing similar among the {r['new']} symbols analyzed")
            return
        for c in r["by_shape"]:
            print(f"  ⚠ {c['name']}: {c['kind']} shape (jaccard {c['jaccard']}) "
                  f"to {c['already_in']}")
        for c in r["by_name"]:
            print(f"  · {c['name']}: there is already a {c['kind']} with that name "
                  f"in {c['already_in']}")
        return

    t0 = time.time()
    cfg = _config.load(args.config)
    project = _factory.make_project(cfg)
    levels = project.levels()
    # ONE reader for the probe census. There used to be a second one here that globbed only
    # `.mcview/` and stripped a hardcoded `/app/` prefix, while `graph/runtime.py` reads
    # `.mcview/` AND `.salud/` and trims by the longest known suffix. They drifted, and the
    # symptom was silent: this view printed "no census" with 177 symbols confirmed on disk.
    # Deleting the duplicate is the fix — a second reader cannot drift if it does not exist.
    import runtime as _rt
    obs = _rt.observed(project, cfg.root)
    proven = set(obs)
    window = _rt.summary(project, obs)["window_s"]

    if args.views:
        require_algebra("--views")
        import subprocess

        import scipy.sparse as sp
        repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
        nodes = _com.nodes_of(project)
        E = _com.adjacency(project, nodes)
        L = _views.lexical_view(project, nodes)
        V = _views.evolution_view(project, nodes, repo)
        vacia = sp.csr_matrix(E.shape, dtype=E.dtype)
        we, wl, wv = (float(x) for x in args.weights.split(","))

        combos = [("structure only", (1, 0, 0)), ("+ lexical", (1, wl, 0)),
                  ("+ evolution", (1, 0, wv)), ("all three", (we, wl, wv))]
        rows = []
        for etq, (a, b, c) in combos:
            S = _views.combine(E, L if b else vacia, V if c else vacia, weights=(a, b, c))
            best = None
            for infl in (1.2, 1.3, 1.4, 1.6):
                gs = _com._mcl_on(S, nodes, infl)
                m = _views.nmi(gs, project)
                if best is None or m > best["NMI"]:
                    best = {"view": etq, "inflation": infl,
                             "k": len([g for g in gs if len(g) >= 5]),
                             "purity": round(_views.purity(gs, nodes, project), 3),
                             "NMI": round(m, 3)}
            rows.append(best)

        if args.json:
            print(_json.dumps({"project": cfg.name, "symbols": len(nodes),
                               "nnz": {"estructural": int(E.nnz), "lexica": int(L.nnz),
                                       "evolutiva": int(V.nnz)},
                               "resultados": rows}, ensure_ascii=False, indent=2))
            return

        print(f"\n  MULTIPLE VIEWS — {cfg.name}   ({len(nodes)} symbols)")
        print(f"  topology says who calls whom, not what each thing is about\n")
        print(f"    structural nnz={E.nnz}   lexical nnz={L.nnz}   evolutionary nnz={V.nnz}\n")
        print(f"  {'view':20s} {'infl':>5s} {'k':>4s} {'purity':>8s} {'NMI':>7s}")
        base = rows[0]["NMI"]
        for f in rows:
            d = f["NMI"] - base
            mark = f"   {d:+.3f}" if d else ""
            print(f"  {f['view']:20s} {f['inflation']:5.1f} {f['k']:4d} "
                  f"{f['purity']:8.3f} {f['NMI']:7.3f}{mark}")
        print(f"\n  NMI = agreement with YOUR declared partition, penalizing")
        print(f"  fragmentation. Purity is NO good for comparing: it grows with k by")
        print(f"  construction (single-symbol groups give purity 1.0).")
        print(f"\n  The weights {args.weights} are a declared choice, not an optimum.")
        print(f"  And the declared partition as a yardstick is partly circular: it rewards")
        print(f"  agreeing with whoever wrote it, not with an external truth.\n")
        return

    if args.orient:
        rank = _heatmap.pagerank(project)
        dups = None if args.no_twins else _duplicates.analyze(project)
        r = _orient.orient(project, rank, levels, dups, args.orient)
        if args.flow and "error" not in r:
            import flow as _flow
            files = set(r["files"])
            inside = {sid for sid, s in project.symbols.items() if s.file in files}
            r["flow"] = _flow.trace(project, inside, rank)
            usan, depende = _flow.neighbors_by_module(project, inside, files)
            r["flow"].update(usan=usan, depende=depende, target=r["target"])
            import services as _serv
            _m = _serv.reach(project)
            if _m:
                r["flow"]["services"] = _serv.from_files(_m, files)
                r["flow"]["compartidos"] = len(files & _serv.shared(_m))
                r["flow"]["files_total"] = len(files)
            if args.cross:
                import seams as _cost
                otros = _cost.workspace_catalogs(args.config, excepto=cfg.name)
                r["flow"]["crossings"] = _cost.crossings(
                    _cost.detect(project), files, otros)
        if args.html and "flow" in r:
            import flow as _flow
            import page as _page
            files = set(r["files"])
            inside = {s for s, x in project.symbols.items() if x.file in files}
            arriba, abajo = _flow.neighbors_by_module(project, inside, files)
            print(_page.render(
                r,
                _flow.mermaid_sequence(r["flow"], r["target"]),
                _flow.mermaid(r["flow"], r["target"], arriba, abajo,
                               _flow._internal_parts(files)),
                " ".join(sys.argv)))
            return

        if args.mermaid and "flow" in r:
            import flow as _flow
            files = set(r["files"])
            inside = {s for s, x in project.symbols.items() if x.file in files}
            if args.mermaid == "map":
                arriba, abajo = _flow.neighbors_by_module(project, inside, files)
                print(_flow.mermaid(r["flow"], r["target"], arriba, abajo,
                                     _flow._internal_parts(files)))
            else:
                print(_flow.mermaid_sequence(r["flow"], r["target"]))
            return
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return
        _orient.print_rows(r)
        if "flow" in r:
            import flow as _flow
            _flow.print_rows(r["flow"])
            if r["flow"].get("crossings"):
                import seams as _cost
                _cost.print_crossings(r["flow"]["crossings"])
        return

    if args.no_consumer:
        import consumption as _cons
        declarado = bool(getattr(cfg, "observability", ()) or getattr(cfg, "transport", ()))
        h = _cons.no_consumer(project)
        if args.json:
            print(_json.dumps(h, ensure_ascii=False, indent=2))
            return
        _cons.print_rows(h, cfg.name, declarado)
        return

    if args.services:
        import services as _serv
        m = _serv.reach(project)
        bound = _serv.reach(project, strong=False)      # conservative lower bound
        if args.json:
            print(_json.dumps({k: sorted(v) for k, v in m.items()},
                              ensure_ascii=False, indent=2))
            return
        _serv.print_rows(m, cfg.name, bound)
        return

    if args.bridges:
        import glob as _glob
        import seams as _seams
        ws_root = os.path.dirname(os.path.abspath(args.config))
        cats = {}
        for tm in sorted(_glob.glob(os.path.join(ws_root, 'mcview*.toml'))):
            c2 = _config.load(tm)
            if not getattr(c2, 'seams', None):
                continue
            cats[c2.name] = _seams.detect(_factory.make_project(c2))
        bridges = _seams.join(cats)
        if args.html:
            import page as _page
            print(_page.render_bridges(bridges, cats, ' '.join(sys.argv)))
            return
        if args.json:
            print(_json.dumps(bridges, ensure_ascii=False, indent=2))
            return
        _seams.print_bridges(bridges, cats)
        return

    if args.walkthrough:
        import walkthrough as _wt
        import blueprint as _bp
        base = project
        spec = _wt.load(args.walkthrough)
        if any("▸" in (st.get("verify") or "") for st in spec.get("stage", [])):
            base = CACHE_WEAVE()
        fallas = _wt.verify(base, spec)
        if fallas:
            # It refuses instead of drawing what it could. A figure with one invented box is
            # worse than none: its reader is by construction someone who will not check it.
            sys.exit("  the walkthrough does not check out:\n    " + "\n    ".join(fallas))
        r = _bp.build(base, _heatmap.pagerank(base))
        svg = _wt.draw(spec, r["cuts"], r["caveats"])
        if args.png:
            hecho = _wt.to_png(svg, args.png)
            print(f"  wrote {hecho}" if hecho else
                  "  no converter (rsvg-convert / cairosvg): PNG skipped, SVG below")
            if hecho:
                return
        print(svg)
        return

    if args.blueprint:
        import blueprint as _bp
        obs = None
        if args.runtime:
            import runtime as _rt
            obs = _rt.observed(project, cfg.root)
        r = _bp.build(project, _heatmap.pagerank(project), obs=obs)
        print(_json.dumps(r, ensure_ascii=False, indent=2) if args.json else _bp.report(r))
        return

    if args.reach:
        import seams as _seams
        cat = _seams.detect(project)
        lits = {l for t, m in cat.get("exports", {}).items() if t == "tool" for l in m}
        mentions = _seams.scan_mentions(lits, [cfg.root], cfg.ignored_dirs)
        rows = _seams.reachability(cat, mentions,
                                         inert=tuple(cfg.seams.get("inert", ())),
                                         selectors=tuple(cfg.seams.get("selectors", ())))
        if args.json:
            print(_json.dumps(rows, ensure_ascii=False, indent=2))
            return
        _seams.print_reach(rows, args.limit)
        return

    if args.seams:
        import seams as _seams
        cat = _seams.detect(project)
        if args.json:
            print(_json.dumps(cat, ensure_ascii=False, indent=2))
            return
        _seams.print_rows(cat, cfg.name)
        return

    if args.risk:
        rank = _heatmap.pagerank(project)
        rows = _heatmap.deletion_risk(project, levels["DEAD_CANDIDATE"], rank)
        if args.json:
            print(_json.dumps(rows[:args.limit], ensure_ascii=False, indent=2))
            return
        from collections import defaultdict as _dd
        pa = _dd(list)
        for f in rows:
            pa[f["file"]].append(f)
        res = sorted(({"file": a, "n": len(v),
                       "risk": sum(x["risk"] for x in v) / len(v),
                       "frac": v[0]["dead_frac"]}
                      for a, v in pa.items()), key=lambda x: x["risk"])
        print(f"\n  DELETION RISK — {len(rows)} candidates across {len(res)} files")
        print(f"  from SAFEST to RISKIEST. It does not change the verdict, it changes the order.\n")
        print(f"  {'file':46s} {'dead':>7s} {'%file':>6s} {'risk':>7s}")
        for r in res[:12]:
            print(f"  {r['file'][:46]:46s} {r['n']:7d} {100*r['frac']:5.0f}% {r['risk']:7.3f}")
        print(f"  {'…':46s}")
        for r in res[-5:]:
            print(f"  {r['file'][:46]:46s} {r['n']:7d} {100*r['frac']:5.0f}% {r['risk']:7.3f}")
        print(f"\n  It ranks by IMPACT if the verdict is wrong, NOT by the probability")
        print(f"  that it is: a dead symbol in a hot zone breaks more when deleted.")
        print(f"  (The hypothesis 'hot zone = more false positives' was refuted:")
        print(f"   the 4 worst-ranked turned out to be genuinely dead.)\n")
        return

    if args.islands:
        require_algebra("--islands")
        r = _com.islands(project)
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return
        print(f"\n  ISLANDS — {cfg.name}")
        print(f"  size is NOT a splitting criterion; fragmentation is\n")
        print(f"  {'file':44s} {'sym':>5s} {'coh':>5s} {'largest':>6s} {'islands':>6s}")
        print("  " + "-" * 76)
        for f in r[:16]:
            print(f"  {f['file'][:44]:44s} {f['symbols']:5d} {f['cohesion']:5.2f} "
                  f"{f['mayor_pct']:5.0%} {f['islands']:6d}   {f['verdict']}")
        aDividir = [f for f in r if f["verdict"].startswith("DIVIDIR")]
        if aDividir:
            f = aDividir[0]
            print(f"\n  Where to cut {f['file']} — each island is a file:")
            for c in f["cortes"][:6]:
                print(f"    [{len(c):2d}] {', '.join(c[:6])}")
        print(f"\n  largest≥60% = one big thing, do not split even at 2,000 lines.")
        print(f"  largest<30% with ≥3 islands = several things cohabiting.")
        print(f"  cohesion<0.15 = it is not even cohesive; splitting does not fix it.\n")
        return

    if args.hierarchy:
        require_algebra("--hierarchy")
        subs = _com.submodules(project)
        merges = _com.merges(project)
        if args.json:
            print(_json.dumps({"project": cfg.name, "submodules": subs,
                               "merges": merges}, ensure_ascii=False, indent=2))
            return

        def verdict(c, k, transversal=False):
            if transversal:
                return "crosscutting — plumbing, not applicable"
            if c >= 0.40:
                return "cohesive — leave it"
            if c >= 0.15:
                return f"split into {k}"
            return "SCATTERED — not a module"

        print(f"\n  HIERARCHY — {cfg.name}")
        print(f"  the same Markov chain, run INSIDE each module\n")
        print(f"  ── SPLIT ──────────────────────────────────────────────────")
        print(f"  cohesion = fraction of the module's references that stay inside\n")
        print(f"  {'module':26s} {'sym':>5s} {'cohes':>6s} {'k_sub':>6s}   verdict")
        for f in sorted(subs, key=lambda x: -x["cohesion"]):
            print(f"  {f['module'][:26]:26s} {f['symbols']:5d} {f['cohesion']:6.2f} "
                  f"{f['k_sub']:6d}   {verdict(f['cohesion'], f['k_sub'], f.get('transversal'))}")

        print(f"\n  ── MERGE ──────────────────────────────────────────────────")
        positives = [x for x in merges if x["delta_Q"] > 0]
        print(f"  ΔQ>0 = there are more edges between those two modules than "
              f"chance predicts\n")
        for x in merges[:8]:
            print(f"    {x['delta_Q']:+8.4f}  {x['a'][:24]:24s} + {x['b'][:24]}")
        if positives:
            largest = positives[0]["delta_Q"]
            print(f"\n    {len(positives)} pairs with ΔQ>0 out of {len(merges)}.")
            print(f"    The largest is {largest:.4f} — judge the MAGNITUDE, not the sign:")
            print(f"    a merge that moves less than 5% of total Q changes nothing.")
        print()
        return

    if args.k:
        require_algebra("--k")
        r = _com.sweep_k(project)
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return
        print(f"\n  NATURAL K — {cfg.name}   ({r['symbols']} core symbols)")
        print(f"  Newman modularity: internal density minus what chance would predict\n")
        print(f"    {'inflation':>10s} {'k':>5s} {'Q':>8s}")
        for f in r["barrido"]:
            mark = "  ←" if f["Q"] == r["optima"]["Q"] else ""
            print(f"    {f['inflation']:10.2f} {f['k']:5d} {f['Q']:8.3f}{mark}")
        d, o = r["declarada"], r["optima"]
        print(f"\n    declared by you:   k={d['k']:3d}   Q={d['Q']:.3f}")
        print(f"    graph optimum:     k={o['k']:3d}   Q={o['Q']:.3f}")
        if d["Q"] > 0:
            print(f"    → your partition captures {100*d['Q']/o['Q']:.0f}% of the "
                  f"reachable modularity")
        print(f"\n    Q>0.3 = clear modular structure · Q<0.3 = high coupling")
        print(f"    Careful: maximizing Q has a resolution limit — k is an order of")
        print(f"    magnitude, not an exact number.\n")
        return

    if args.modules:
        require_algebra("--modules")
        rank = _heatmap.pagerank(project)
        grupos = _com.cluster(project, inflation=args.inflation)
        c = _com.contrast(project, grupos)
        rows = _heatmap.by_module(project, rank)
        if args.json:
            print(_json.dumps({"project": cfg.name, "inflation": args.inflation,
                               "declarados": rows, "contrast": c,
                               "grupos": [_com.describe(project, g, rank)
                                          for g in grupos if len(g) >= 6]},
                              ensure_ascii=False, indent=2, default=str))
            return

        # R3 of this project: never degrade in silence. Without `[modules]` the grouping
        # falls back to the 2-level directory, and the table looks exactly the same — same
        # columns, same percentages, a name in every row. What changed is WHAT IS BEING
        # MEASURED: physical proximity instead of responsibility. Measured here, and this is
        # why it is not derived instead: MCL over the call graph groups 33%% of the symbols
        # into clusters of at most 40, which are sub-modules — proposing them covered 16%% of
        # the files, worse than the fallback that at least covers all of them.
        if not cfg.modules:
            print("\n  \u26a0 no [modules] in the .toml: grouping by DIRECTORY. Every row below")
            print("    is a folder, so this measures proximity, not lines of work. Declaring")
            print("    them by responsibility is what makes this table mean something.")
        print(f"\n  LINES OF WORK — {cfg.name}   (inflation {args.inflation})")
        print(f"  declared by you vs discovered by the walker\n")
        print(f"  {'declared line':26s} {'mass':>7s} {'sym':>5s} {'cold':>6s} {'sym/%mass':>11s}")
        print("  " + "-" * 62)
        for f in rows:
            if f["symbols"] < 12:
                continue
            print(f"  {f['module'][:26]:26s} {f['pct']:6.2f}% {f['symbols']:5d} "
                  f"{100*f['frios']/f['symbols']:5.0f}% {f['symbols']/max(f['pct'],0.01):11.0f}")

        print(f"\n  ── DISAGREEMENT ───────────────────────────────────────────")
        if c["partidos"]:
            print(f"\n  SPLIT — the name hides more than one thing:")
            for x in c["partidos"]:
                print(f"    {x['module'][:28]:28s} {x['symbols']:4d} sym across "
                      f"{x['grupos']:2d} groups · {x['concentration']:.0%} in the largest")
        else:
            print("\n  SPLIT: none — every declared line is coherent")
        if c["fundidos"]:
            print(f"\n  MERGED — the code does not tell them apart:")
            for x in c["fundidos"][:8]:
                print(f"    {' + '.join(m[:22] for m in x['modules'][:3])}")
        else:
            print("\n  MERGED: none")

        large = [g for g in grupos if len(g) >= 8]
        print(f"\n  ── DISCOVERED GROUPS ({len(large)} with ≥8 symbols) ──")
        for g in large[:10]:
            d = _com.describe(project, g, rank)
            dec = ", ".join(f"{m}({n})" for m, n in d["declarados"][:2])
            purity = d["declarados"][0][1] / d["symbols"]
            print(f"\n    {d['symbols']:4d} sym · {d['files']:3d} files · "
                  f"purity {purity:.0%}")
            print(f"         {dec}")
            print(f"         {d['top_files'][0][0]}")
        print()
        return

    if args.locks or args.propose:
        import locks as _cand
        if args.propose:
            r = _cand.propose(project, _heatmap.pagerank(project), *args.propose)
        else:
            r = _cand.verify(project, cfg)
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
            return
        if "error" in r:
            print(f"\n  {r['error']}\n")
            return
        if args.propose:
            print(f"\n  CANDIDATES — {r['src']} → {r['dst']}\n")
            if r.get("no_candidates"):
                print(f"    {r['no_candidates']}\n")
                for step in r.get("direct_path", [])[:6]:
                    print(f"      ↳ {step}")
                print()
                return
            for c in r["candidates"]:
                print(f"    {c['mass_pct']:6.2f}%  {c['kind']:12s} {c['guarantee']:34s} {c['loc']}")
            print(f"\n  To lock it, paste into the .toml:\n\n{r['toml']}")
            return
        print(f"\n  LOCKS ON CONNECTIONS — {r['project']}\n")
        for c in r["locks"]:
            print(f"    {c['verdict']:9s} {c['name']}")
            if c.get("why"):
                print(f"              {c['why']}")
            for step in c.get("path", [])[:6]:
                print(f"              ↳ {step}")
        print(f"\n  {r['count']}\n")
        return

    if args.sequence and args.decisions:
        import weave as _tej, decisions as _dec
        # `--decisions` needs a destination: a decision tree without a leaf is a walk. Without
        # this, `--to` defaulted to "" and the weave's resolver reported «» must be
        # «project▸target» — a message that blames the format of the argument you DID pass for
        # the absence of the one you did not, and sends you to fix the wrong thing.
        if not args.to:
            sys.exit("  --decisions needs --to: the tree is built between an entry and a "
                     "destination.\n  e.g. --sequence 'principal▸Ingesta' "
                     "--to 'principal▸services/enrichment_service.py'")
        weave = _tej.build(_workspace_configs(
            os.path.dirname(os.path.abspath(args.config))))
        status_map = {s: e for e, ss in weave.levels().items() for s in ss}
        obs = None
        if args.runtime:
            import runtime as _rt
            obs = _rt.observed(weave, cfg.root)
        m = _dec.build(weave, args.sequence, args.to or "", status_map, obs,
                           collapse=not args.no_collapse)
        if args.json:
            print(_json.dumps(m, ensure_ascii=False, indent=2))
        elif args.html:
            import canvas as _canvas
            print(_canvas.page(m))
        else:
            print(_dec.report(m))
        return

    if args.sequence:
        import sequence as _sec
        if "\u25b8" in args.sequence:
            import weave as _tej
            base = _tej.build(_workspace_configs(
                os.path.dirname(os.path.abspath(args.config))))
        else:
            base = project
        obs = None
        if args.runtime:
            import runtime as _rt
            obs = _rt.observed(base, cfg.root)
            if not obs:
                print("  no runtime census in .mcview/ or .salud/ — the steps go unmarked "
                      "(absence of evidence, not evidence of absence)\n")
        if args.todas:
            # The narrative is computed anyway, and cheaply, so the exhaustive view can say
            # what FRACTION of the reach it shows. A cut whose size is unknown is the one
            # that reads as if it were everything.
            narrado = _sec.trace(base, args.sequence, _heatmap.pagerank(base),
                                 depth=args.depth, obs=obs)
            vistos = set()
            if "tree" in narrado:
                _sec._collect_ids(narrado["tree"], vistos)
            r = _sec.reach_all(base, args.sequence, _heatmap.pagerank(base), obs=obs,
                               narrated=vistos)
            if args.json:
                print(_json.dumps(r, ensure_ascii=False, indent=2))
            else:
                print(_sec.report_reach(base, r))
            return
        r = _sec.trace(base, args.sequence, _heatmap.pagerank(base), depth=args.depth,
                        dst=args.to, obs=obs)
        if args.json:
            print(_json.dumps(r, ensure_ascii=False, indent=2))
        elif args.html:
            import page as _page
            print(_page.render_sequence(base, r, " ".join(sys.argv), _sec._lane))
        elif args.mermaid:
            print(_sec.mermaid(base, r))
        else:
            print(_sec.report(base, r))
        return

    if args.route:
        import weave as _tej, route as _rec
        ws_root = os.path.dirname(os.path.abspath(args.config))
        ws = os.path.join(ws_root, "mcview.workspace.toml")
        if not os.path.exists(ws):
            sys.exit(f"  {ws} is missing — that is where [[routes]] are declared")
        with open(ws, "rb") as fh:
            decl = _config.tomllib.load(fh).get("routes", [])
        elegido = next((d for d in decl if d.get("name") == args.route), None)
        if not elegido:
            sys.exit("  declared routes: " +
                     ", ".join(repr(d.get("name")) for d in decl))
        cfgs = _workspace_configs(ws_root)
        weave = _tej.build(cfgs)
        r = _rec.trace(weave, elegido["src"], elegido["dst"])
        if args.json:
            print(_json.dumps({k: (sorted(v) if isinstance(v, set) else v)
                               for k, v in r.items()}, ensure_ascii=False, indent=2))
            return
        if args.html and "error" not in r:
            import atlas as _atlas, canvas as _canvas
            rank = _heatmap.pagerank(weave)
            status_map = {s: e for e, ss in weave.levels().items() for s in ss}
            # `only` = the DAG of paths: a route's map is not the repo cropped at draw
            # time, it is the slice — layers, columns and mass are computed over it.
            modelo = _atlas.build(weave, rank, status_map, r["origin"], only=r["inside"],
                                      eje="depth")
            modelo["project"] = f"{elegido['name']}: {r['src']} → {r['dst']}"
            print(_canvas.page(modelo))
            return
        print(_rec.report(weave, r))
        return

    if args.atlas and args.workshop:
        import workshop as _workshop
        cfgs = _workspace_configs(os.path.dirname(os.path.abspath(args.config)))
        modelo = _workshop.combine(cfgs)
        if args.json:
            print(_json.dumps(modelo, ensure_ascii=False, separators=(",", ":")))
            return
        import canvas as _canvas
        print(_canvas.page(modelo))
        return

    if args.atlas:
        import atlas as _atlas
        rank = _heatmap.pagerank(project)
        status_map = {s: e for e, ss in levels.items() for s in ss}
        roots = {s for s in project.product_roots
                  if _heatmap._is_product(project, project.symbols[s].file)}
        only = None
        if args.origin:
            entries, only, err, seam = _atlas.from_surface(project, args.origin)
            if err:
                sys.exit(f"  {err}")
            roots = entries
        modelo = _atlas.build(project, rank, status_map, roots, only=only,
                                  seam=seam if args.origin else None)
        modelo["surface"] = args.origin
        if args.json:
            print(_json.dumps(modelo, ensure_ascii=False, separators=(",", ":")))
            return
        import canvas as _canvas
        print(_canvas.page(modelo))
        return

    if args.map:
        rank = _heatmap.pagerank(project)
        rows = _heatmap.by_file(project, rank)
        conc = _heatmap.concentration(rows)
        if args.json:
            print(_json.dumps({"project": cfg.name, "concentration": conc,
                               "files": [{k: v for k, v in f.items() if k != "mass"}
                                            for f in rows]},
                              ensure_ascii=False, indent=2))
            return
        # R3 of this project: never degrade in silence. Without `[modules]` the grouping
        # falls back to the 2-level directory, and the table looks exactly the same — same
        # columns, same percentages, a name in every row. What changed is WHAT IS BEING
        # MEASURED: physical proximity instead of responsibility. Measured here, and this is
        # why it is not derived instead: MCL over the call graph groups 33%% of the symbols
        # into clusters of at most 40, which are sub-modules — proposing them covered 16%% of
        # the files, worse than the fallback that at least covers all of them.
        if not cfg.modules:
            print("\n  \u26a0 no [modules] in the .toml: grouping by DIRECTORY. Every row below")
            print("    is a folder, so this measures proximity, not lines of work. Declaring")
            print("    them by responsibility is what makes this table mean something.")
        print(f"\n  HEAT MAP — {cfg.name}")
        print(f"  expected usage mass, derived from structure (without executing anything)")
        print(f"\n  {conc['archivos_50pct']} files concentrate 50% of usage · "
              f"{conc['archivos_80pct']} hold 80%   (of {conc['total']})\n")
        ancho = 42
        for f in rows[:30]:
            barra = "█" * max(1, int(f["pct"] / max(rows[0]["pct"], 1e-9) * ancho))
            print(f"  {f['pct']:5.2f}% {barra:<{ancho}} {f['file']}")
        cold = [f for f in rows if f["pct"] < 0.01]
        print(f"\n  {len(cold)} product files with mass < 0.01% — cold periphery.")
        print(f"  They are not DEAD_CANDIDATE: they are referenced, but the system")
        print(f"  barely goes through them. It is where entropy piles up unsignalled.\n")
        return

    dup = None if args.no_duplicates else _duplicates.analyze(project)
    elapsed = time.time() - t0

    # ------------------------------------------------------------ un status
    if args.status:
        chosen = sorted(levels.get(args.status, ()),
                          key=lambda sid: project.symbols[sid].file)
        if args.json:
            print(_json.dumps([{
                "name": project.symbols[s].name,
                "kind": project.symbols[s].kind,
                "loc": project.symbols[s].loc,
                "status": "ALIVE_PROVEN" if s in proven else args.status,
            } for s in chosen[:args.limit]], ensure_ascii=False, indent=2))
        else:
            print(f"{args.status} — {GLOSA.get(args.status, '')}")
            print(f"  {len(chosen)} symbols\n")
            for sid in chosen[:args.limit]:
                s = project.symbols[sid]
                mark = "  [EXECUTED]" if sid in proven else ""
                print(f"  {s.kind:8s} {s.name:34s} {s.loc}{mark}")
        return

    # -------------------------------------------------------------- summary
    if args.json:
        output = {
            "project": cfg.name,
            "symbols": len(project.symbols),
            "seconds": round(elapsed, 2),
            "roots": dict(project.reasons),
            "runtime_window_min": window // 60,
            "levels": {k: {"n": len(levels[k]), "runtime_proven": len(levels[k] & proven)}
                        for k in ORDEN},
            "duplicates": None if dup is None else {
                "type12_grupos": len(dup["type12"]),
                "type3_pares": len(dup["type3"]),
            },
        }
        print(_json.dumps(output, ensure_ascii=False, indent=2))
        return

    print(f"\n{'='*66}\n  MCVIEW — {cfg.name}\n{'='*66}")
    print(f"  {len(project.symbols)} symbols · {len(project.by_file)} files "
          f"· {elapsed:.1f}s")

    print(f"\n  DECLARED ROOTS")
    for k, v in sorted(project.reasons.items(), key=lambda x: -x[1]):
        print(f"    {k:24s} {v}")
    if not project.reasons:
        print("    none — check [roots] in the .toml; with no roots everything looks dead")

    print(f"\n  LIVENESS LEVELS")
    for k in ORDEN:
        n = len(levels[k])
        pr = len(levels[k] & proven)
        extra = f"   ({pr} proven at runtime)" if pr else ""
        print(f"    {k:20s} {n:5d}{extra}")
        print(f"    {'':20s}       {GLOSA[k]}")

    if window:
        print(f"\n  RUNTIME: {len(proven)} symbols executed "
              f"(window {window//60} min)")
        contradicting = levels["DEAD_CANDIDATE"] & proven
        if contradicting:
            print(f"    ⚠ {len(contradicting)} DEAD_CANDIDATE symbols EXECUTED "
                  f"— the static analysis was wrong, check the roots:")
            for sid in list(contradicting)[:5]:
                print(f"        {project.symbols[sid].name} "
                      f"{project.symbols[sid].loc}")
    else:
        print(f"\n  RUNTIME: no census — the candidates are NOT deletable yet")

    if dup:
        print(f"\n  REDUNDANCY ({dup['analizadas']} fingerprints: functions with "
              f"≥{cfg.min_statements} statements + {dup['blocks']} nested "
              f"blocks with ≥{cfg.min_statements_block})")
        print(f"    Type-1/2 (identical skeleton): {len(dup['type12'])} groups")
        for g in dup["type12"][:6]:
            names = ", ".join(sorted({s.name for s in g["symbols"]}))
            print(f"      ×{len(g['symbols'])}  {names[:60]}")
            for s in g["symbols"][:3]:
                print(f"            {s.loc}")
        print(f"    Type-3 (similar shape): {len(dup['type3'])} pairs")
        for p in dup["type3"][:6]:
            print(f"      {p['jaccard']:.2f}  ~{p['tokens']} tok  "
                  f"{p['a'].name} ~ {p['b'].name}")
            print(f"            {p['a'].loc}")
            print(f"            {p['b'].loc}")

    print(f"\n  Detail: --status <STATUS> [--limit N] [--json]\n")


if __name__ == "__main__":
    main()
