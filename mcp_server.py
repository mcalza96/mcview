#!/usr/bin/env python3
"""MCP server — the same measurements, delivered as tools instead of as a manual.

    mcview --mcp          # stdio, JSON-RPC 2.0

WHY THIS EXISTS, AND WHAT IT REPLACES
--------------------------------------
The consumer of this tool is an agent orienting itself before writing code. Until now it
reached the tool through a SKILL: prose telling it which command to run. A skill is a prompt —
something that has to be read, remembered and not gotten wrong. A tool schema is construction:
it cannot be invoked wrong.

That is the whole trade this project is built on, applied to its own interface.

THE RULE THAT MAKES THIS SAFE, AND IT IS NOT OPTIONAL
------------------------------------------------------
**Every result carries its own caveat, as a field.**

Today each number is printed next to what it does NOT claim, and that qualifier lives in two
places: the skills and the printed output. A tool returning bare JSON would strip it — and a
number without its caveat is precisely what this tool exists not to produce. `mass: 16.42`
with no `caveat` reads as importance; it is structural centrality, and it is *measured* not to
predict execution (AUC 0.506).

So `caveat` is as mandatory as the payload. Hand a model a number with no qualifier and it
will supply one of its own.

ZERO DEPENDENCIES, LIKE THE REST
---------------------------------
MCP stdio is newline-delimited JSON-RPC 2.0. The surface a tools-only server needs is three
methods, so it is written against the stdlib instead of pulling in an SDK — the tool has to
stay a directory you copy, and a server that only works after `pip install` would break that
for the primary install model.

WHAT IS DELIBERATELY *NOT* A TOOL
-----------------------------------
The expensive views: full duplicate analysis, `--k`, `--hierarchy`, `--islands`, `--views`.
Measured, they run in minutes on a large repo, and a tool call that blocks for minutes is a
tool nobody calls twice. They stay on the CLI, where a minute is a fair price. `--map`,
`--orient` and the rest measure ~2.5 s on a 6k-symbol repo, which is why they are here.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import config as _config          # noqa: E402
import factory as _factory        # noqa: E402
import heatmap as _heatmap        # noqa: E402
import orient as _orient          # noqa: E402

PROTOCOL = "2024-11-05"
VERSION = "1.0.0"

# --------------------------------------------------------------- the caveats
# Each one is the shortest true statement of what the number does NOT say. They are not
# disclaimers: every one of them was written after a measurement contradicted a reading
# somebody had already made.
CAVEAT = {
    "mass": ("mass is STRUCTURAL CENTRALITY, not importance and not real frequency. Measured "
             "against a runtime probe it does NOT predict execution (AUC 0.506). A file at the "
             "top is one that many paths from the roots cross — plumbing, usually."),
    "dead": ("DEAD_CANDIDATE is a HYPOTHESIS, not a deletion order: it means no static evidence "
             "of use. Names reached only through a string (a registry, mock.patch, config "
             "dispatch) are invisible to it. Confirm with runtime or by hand before deleting."),
    "flow": ("This is STRUCTURE, not execution: a path here may never be walked, and one that "
             "is absent may exist anyway through dynamic dispatch. The bias is toward the false "
             "negative — it never invents a path. It runs on unambiguous edges only."),
    "order": ("The order is the WRITTEN one, not the executed one. A call inside an `if` shows "
              "up even if it never runs; a dynamically dispatched one does not show up even if "
              "it always runs."),
    "locks": ("The verdict is exact —proven by removal, not sampled— but it only sees REACHING "
              "the sink without crossing the guard. It does NOT see 'crossed the guard and "
              "forgot the tenant filter': that is an argument, not an edge."),
    "seams": ("Seams are declared, not inferred: if the literal does not match there is no "
              "bridge. A dynamically built literal is invisible. And a route match by suffix is "
              "a candidate to verify, not a proven edge."),
    "twins": ("Same shape is not the same responsibility. Two functions with one skeleton can "
              "be real duplication or two deliberately symmetric faces of an API — the tool "
              "proposes, the reader decides. Ask what would happen if ONE copy diverged."),
    "diff": ("Typed signals, never a single score: a composite number is unfalsifiable. Only "
             "`net_symbols` is validated against history; change heat and concentration are "
             "NOT validated. A 0 can also mean 'not measured' if the change touches an "
             "excluded area."),
    "cohesion": ("Cohesion below 0.15 does not mean 'split it': it means it is not a unit, it "
                 "is crosscutting infrastructure. It is computed over the complete graph; "
                 "`--hierarchy` measures it without hubs and gives a different number."),
}

INSTRUCTIONS = """\
# mcview — structural understanding, computed from today's AST

## What this is for, and what it is not

**It exists to orient YOU while you work.** You are about to touch a repository you do not
hold in your head. mcview tells you what is there, computed from the code as it is right
now — so you build and audit with more discipline and less flailing, and you do it faster
than by reading twenty files to find the three that matter.

That is the whole purpose. In particular:

- **It does not run a health check on the repo.** It has no opinion about quality. It
  reports mass, reachability, duplication and cohesion; whether any of that is a *problem*
  depends on what the project is for, and it does not know that.
- **It does not decide anything, and it never authorises a change.** `DEAD_CANDIDATE` is a
  hypothesis, not a deletion order. A duplicate is a shape, not debt. No output of this tool
  is grounds for deleting, refactoring or approving on its own.
- **It does not replace reading the code.** It tells you WHICH code to read. Every view ends
  by pointing at a concrete path precisely so you go and verify it.

The decisions stay with the user and the reading stays with you. What moves here is the
COST of being disciplined: what used to require holding the repo in your head, or trusting
documentation that drifted, is now a measurement you can take in one call and cite.

## Use it ALONGSIDE a code index

This is not a retrieval engine and it is not your only tool. If you need to find a symbol,
read its source, or follow a call chain across many languages, use a pre-indexed graph —
codegraph or any equivalent. It is faster at that than anything here, and it is the right
tool for it.

    ask the index    where is it, what does it say, who calls it
    ask mcview       what shape is this, what is dead, what is duplicated, what is central

Do NOT cross the two. Measured on the same 6.2k-symbol repository: the inventories agree to
within 0.3%, but 62% of symbols have no incoming edge in the index against the 1% mcview
reports as dead. Reading a retrieval index's missing edge as evidence of dead code turns 70
hypotheses into 3,810. If you have both, cite each for what it measures.

Every answer is computed from today's AST, so it cannot be stale. Use it BEFORE writing
code, not to explain code you already read.

## Where to start

`mcview_orient` is the primary tool. Given a module, a path or a symbol it returns: mass,
cohesion, the grades of liveness, who uses it, what it depends on, how you get in, what the
paths cross first (the guards), and one concrete path to verify by reading three functions.

If the project has no config yet, every tool fails the same way and tells you to call
`mcview_init` first — that derives a starter config from what the project already declares.

## Reading the results, and this is the part that matters

**Every result carries a `caveat` field. It is not boilerplate — read it and carry it into
whatever you report.** Each one exists because a measurement once contradicted a reading:

- `mass` is structural centrality. It is *measured* NOT to predict execution (AUC 0.506).
  Never report it as "the most important code".
- `DEAD_CANDIDATE` is a hypothesis, never a deletion order.
- Anything about flow is structure, not execution.
- "Not observed" at runtime is not "does not happen".

Reporting a number from here without its caveat is the failure this tool was built to
prevent.

## `ask_the_user`: stop, do not compose around it

Some results carry a top-level **`ask_the_user`**. It is not a caveat and it is not advice: it
means the measurement rests on something nobody declared, and the tool has put the question and
the candidate answers right there so you can ask instead of guess.

**When you see it, stop and ask the user before reporting anything built on that result.**

This exists because of a measured failure, not a hypothetical one: an agent was shown a warning
that a flow's starting point had been inferred from mass, continued anyway, produced an analysis
whose entry point turned out to be the OUTPUT formatter, and mentioned the caveat at the end.
The warning was true and changed nothing. A flow that begins in the wrong place is not a partial
answer — it is a wrong one, and the person reading it cannot tell.

## What is not here

Full duplicate analysis, `--k`, `--hierarchy`, `--islands` and the multi-view comparison run
in minutes on a large repo and stay on the CLI (`mcview --k`, etc.). Ask the user to run them
rather than blocking on a tool call.
"""


# ------------------------------------------------------------------- the graph
class _Cache:
    """One process, many calls: rebuilding the graph per call would cost ~2.5 s every time.

    Cached by config path, invalidated by the newest mtime in the tree. A long-lived server
    over code that changes underneath it is exactly how an index starts lying — and here the
    check is a stat walk, which is cheap enough that there is no reason to skip it.
    """

    def __init__(self):
        self._by_cfg: dict[str, tuple[float, object, object]] = {}
        self._weaves: dict[str, tuple[float, object]] = {}
        # {cfg_path: {rel: (mtime_ns, FileFacts | None)}} — per-FILE facts that survive a
        # full-project invalidation. The stamp above answers "did ANYTHING change?"; this
        # answers "which file?", so the rebuild the agent triggers by editing one file
        # re-parses one file instead of 725. Facts are text-pure (no config in them), so a
        # config edit rebuilds the project but keeps every entry. In-process only, dies
        # with the server: mcview keeps ZERO state on disk — the persistent index with a
        # watcher is codegraph's identity, not ours.
        self._facts: dict[str, dict] = {}

    @staticmethod
    def _newest(root: str, ignored: set) -> float:
        newest = 0.0
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in ignored]
            for f in filenames:
                # `.toml` too: before this, the stamp only watched source files, so editing
                # mcview.toml left a long-lived server answering with the old roots until
                # some .py file happened to change
                if f.endswith((".py", ".ts", ".tsx", ".toml")):
                    try:
                        newest = max(newest, os.stat(os.path.join(dirpath, f)).st_mtime)
                    except OSError:
                        pass
        return newest

    def get(self, cfg_path: str):
        cfg = _config.load(cfg_path)
        stamp = self._newest(cfg.root, cfg.ignored_dirs)
        hit = self._by_cfg.get(cfg_path)
        if hit and hit[0] == stamp:
            return hit[1], hit[2]
        project = _factory.make_project(cfg, file_cache=self._facts.setdefault(cfg_path, {}))
        self._by_cfg[cfg_path] = (stamp, cfg, project)
        return cfg, project

    def weave(self, ws_root: str):
        """The three repositories as one graph — and it MUST be cached.

        Measured without it: 21.9 s on the first cross-repo call and 20.8 s on the second,
        because the weave parses every project from scratch each time. A tool that costs 20 s
        every call is a tool nobody calls twice, and the second measurement is the one that
        says so — a slow first call is a cold cache, a slow second call is no cache.
        """
        import weave as _weave
        cfgs = _workspace_configs(ws_root)
        stamp = 0.0
        for path in cfgs.values():
            c = _config.load(path)
            stamp = max(stamp, self._newest(c.root, c.ignored_dirs))
        hit = self._weaves.get(ws_root)
        if hit and hit[0] == stamp:
            return hit[1]
        w = _weave.build(cfgs)
        self._weaves[ws_root] = (stamp, w)
        return w


CACHE = _Cache()


def _resolve_config(project_name: str | None, project_path: str | None = None) -> str:
    """Find the config, walking up from `project_path` or from the process cwd.

    `projectPath` is not a convenience: a server installed GLOBALLY is one process serving
    many repositories, and without it every answer depends on which directory the client
    happened to launch it from. Measured: the same call returns 6,186 symbols from the project
    root and "no mcview.toml" from `/tmp`. Same name as codegraph's parameter on purpose —
    the agent already knows it, and a familiar schema is one less thing to guess.
    """
    src = os.path.abspath(os.path.expanduser(project_path)) if project_path else None
    path = _config.discover(project_name, src)
    if not path:
        which = f"mcview.{project_name}.toml" if project_name else "mcview.toml"
        raise _Missing(
            f"No {which} found walking up from {src or os.getcwd()}. Declaring the roots is "
            f"mandatory — without them reachability declares the whole project dead. "
            f"Call `mcview_init` to derive a starter config from what this project already "
            f"declares, then read what it wrote before believing any number."
        )
    return path


class _Missing(Exception):
    """No config. It is the one error with a specific next step, so it gets its own type."""


# ------------------------------------------------------------------- the tools
def _t(name, desc, props, required=()):
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props,
                            "required": list(required)}}


_PROJECT = {"type": "string",
            "description": "Workspace project to measure (uses mcview.<name>.toml). "
                           "Omit for the default."}
_PATH = {"type": "string",
         "description": "Absolute path to the repository to measure. Omit to use the "
                        "directory the server was started in — pass it explicitly when the "
                        "server is installed globally and serves more than one repo."}
_LIMIT = {"type": "number", "description": "Max rows to return.", "default": 25}

TOOLS = [
    _t("mcview_orient",
       "PRIMARY TOOL — call FIRST when you need to understand an area before touching it. "
       "Given a module, a path or a symbol it returns mass, cohesion, grades of liveness, who "
       "uses it, what it depends on, how you get in, what the paths cross first (the guards), "
       "where it reaches, and one concrete path you can verify by reading three functions. "
       "Answers 'how is X built', 'what do I touch if I change X', 'does this already exist'.",
       {"target": {"type": "string",
                   "description": "A declared module, a file/directory path, a symbol name, "
                                  "or a seam literal (a table, an RPC, a route, a tool name)."},
        "flow": {"type": "boolean", "default": True,
                 "description": "Include the route: how you get in, what it crosses, where it "
                                "reaches. Turn off for a faster census-only brief."},
        "twins": {"type": "boolean", "default": False,
                  "description": "Include structural twins ('does this already exist'). Costs "
                                 "an order of magnitude more — turn on when about to WRITE."},
        "project": _PROJECT, "projectPath": _PATH},
       ["target"]),

    _t("mcview_process",
       "What happens and IN WHAT ORDER from an entry point — the narrative of a turn, step by "
       "step. Use it for process questions ('what happens when a user sends a message', 'how "
       "is the answer assembled') rather than place questions. A graph has no before and "
       "after; this reads the call order the AST keeps.",
       {"target": {"type": "string", "description": "Entry point. Use «project▸target» to "
                                                    "cross repositories."},
        "to": {"type": "string",
               "description": "Destination. With it, nothing on a path to the destination is "
                              "pruned by mass — which is usually the step that explains how "
                              "the result is assembled."},
        "runtime": {"type": "boolean", "default": False,
                    "description": "Mark which steps were SEEN executing, from the probe "
                                   "census. It confirms; it never rules out."},
        "depth": {"type": "number", "default": 4},
        "project": _PROJECT, "projectPath": _PATH},
       ["target"]),

    _t("mcview_route",
       "Everything a message can traverse between two points of the WORKSPACE, across "
       "repositories. Returns the DAG that contains every path (not a sample), the exact "
       "chokepoints (proven by removal), and where it crosses from one repo to another.",
       {"name": {"type": "string",
                 "description": "A route declared in [[routes]] of mcview.workspace.toml. "
                                "Omit to list the declared ones."},
        "projectPath": _PATH},
       []),

    _t("mcview_exists",
       "Does this already exist? Checks a snippet or a file against the index by NAME and by "
       "SHAPE. Call it BEFORE writing a new function or module — this is the anti-duplication "
       "question, and it is the cheapest one here (milliseconds).",
       {"content": {"type": "string", "description": "The code about to be written."},
        "path": {"type": "string", "description": "Where it would live (for context)."},
        "project": _PROJECT, "projectPath": _PATH},
       ["content"]),

    _t("mcview_blueprint",
       "THE SKELETON OF A CONCEPTUAL DIAGRAM — call this when you have to DRAW how the system "
       "works for somebody who is not going to read the code. It returns the nodes (lines of "
       "work), the edges between them with TWO counts, the doors a user enters through, and "
       "the CUTS where the graph provably stops. It deliberately leaves `responsibility` empty "
       "on every node: that is your job, and it is the only part of the drawing no measurement "
       "gives.\n"
       "THE CONTRACT, and it is not advice: do NOT add a node or an edge that is not in this "
       "output. Whoever reads your diagram is not going to check it against the code — an "
       "invented connection is worse for them than no diagram at all. An edge with "
       "`unambiguous: 0` resolved only through a shared name (measured on a real repo: 208 "
       "references between two modules, all of them the word `get`) — draw it dashed or leave "
       "it out. And draw the cuts AS CUTS: past a dispatch the target is chosen by name, and "
       "an arrow across it invents a call that does not happen.",
       {"project": _PROJECT, "projectPath": _PATH}, []),

    _t("mcview_map",
       "Where the system goes: usage mass per file, computed as a random walk seeded at the "
       "declared entry points. Answers 'what is central here'. Read the caveat — this is "
       "centrality, not importance, and it is measured NOT to predict execution.",
       {"limit": _LIMIT, "project": _PROJECT, "projectPath": _PATH}, []),

    _t("mcview_status",
       "Symbols at one grade of liveness. 'Alive' is not a boolean: ALIVE_PRODUCT_WEAK (alive "
       "only through an ambiguous name) and ALIVE_NOT_PRODUCT (reachable, but never from a product root — a test, a script, or a directory declared in `dirs` and left out of `product_dirs`) "
       "are where entropy lives. DEAD_CANDIDATE is a hypothesis, never a deletion order.",
       {"level": {"type": "string",
                  "enum": ["ALIVE_PRODUCT", "ALIVE_PRODUCT_WEAK", "ALIVE_NOT_PRODUCT",
                           "ALIVE_BY_NESTING", "DEAD_CANDIDATE"],
                  "description": "Omit for the census summary of all levels."},
        "limit": _LIMIT, "project": _PROJECT, "projectPath": _PATH},
       []),

    _t("mcview_locks",
       "Connection contracts. A component is protected by a test; a connection is not — "
       "'every request crosses the tenant resolver' is a property of every path. Without "
       "arguments it runs the contracts declared in the .toml. With from/to it PROPOSES where "
       "a lock is worth putting, and emits the TOML block.",
       {"from": {"type": "string", "description": "Propose mode: the origin."},
        "to": {"type": "string", "description": "Propose mode: the sink."},
        "project": _PROJECT, "projectPath": _PATH},
       []),

    _t("mcview_seams",
       "The literals through which this project joins others — routes, tool names, tables, "
       "RPCs. The seam between projects is made of STRINGS, so no call graph crosses it and "
       "no single-repo tool sees it. With workspace=true it joins every project's catalog and "
       "also reports SHARED STATE: two projects touching one table without ever calling each "
       "other, which is usually where the authorization surface lives.",
       {"workspace": {"type": "boolean", "default": False},
        "limit": _LIMIT, "project": _PROJECT, "projectPath": _PATH},
       []),

    _t("mcview_diff",
       "What a change did to the repository, against a git ref. Returns typed signals — never "
       "a single score, because a composite number is unfalsifiable and the moment it becomes "
       "a gate the number gets optimized instead of the code.",
       {"ref": {"type": "string", "description": "Git ref to compare against (e.g. HEAD, "
                                                 "HEAD~1, a branch)."},
        "project": _PROJECT, "projectPath": _PATH},
       ["ref"]),

    _t("mcview_init",
       "Derive a starter mcview.toml from what the project ALREADY declares: [project.scripts], "
       "the Dockerfile CMD, the decorators that register into a dispatch dict, the single "
       "uvicorn.run. Call it when another tool says there is no config. It PROPOSES with the "
       "provenance of every root written next to it — the human reviews before believing "
       "numbers. It never overwrites an existing config unless force=true.",
       {"projectPath": _PATH,
        "write": {"type": "boolean", "default": False,
                  "description": "Write mcview.toml. With false it only returns what it would "
                                 "derive, which is the safe default for an agent."},
        "force": {"type": "boolean", "default": False}},
       []),
]


# ----------------------------------------------------------------- dispatch
def call(name: str, a: dict) -> dict:
    if name == "mcview_init":
        import bootstrap as _boot
        root = (os.path.abspath(os.path.expanduser(a["projectPath"]))
                if a.get("projectPath") else os.getcwd())
        findings = _boot.detect(root)
        text = _boot.render(root, findings)
        out = {
            "root": root,
            "language": findings["language"],
            "declared_roots": {
                "decorators": [d[0] for d in findings["decorators"]],
                "route_methods": findings["route_methods"],
                "route_objects": findings["route_objects"],
                "entrypoints": [{"file": r, "why": w} for r, w in findings["entrypoints"]],
            },
            "candidates_to_review": {
                "decorators": [{"name": d[0], "uses": d[1], "files": d[2], "example": d[3]}
                               for d in findings.get("maybe_decorators", [])],
                "route_objects": [{"name": o, "uses": n}
                                  for o, n in findings.get("maybe_route_objects", [])],
            },
            "toml": text,
            "written": False,
        }
        target = os.path.join(root, "mcview.toml")
        if a.get("write"):
            if os.path.exists(target) and not a.get("force"):
                out["error"] = (f"{target} already exists — it may carry roots added because "
                                f"of a real false positive. Read it first; pass force=true to "
                                f"replace it.")
            else:
                open(target, "w", encoding="utf-8").write(text)
                out["written"] = True
        found = bool(findings["decorators"] or findings["entrypoints"]
                     or findings["route_methods"])
        out["caveat"] = (
            "A PROPOSAL, not a verdict. Every root says where it came from — read them before "
            "believing any number. Which entry points matter is a statement about the project, "
            "not about the file system, so this cannot decide it for you."
            if found else
            "NOTHING REAL WAS FOUND: no registration decorators, no HTTP routes, no process "
            "entrypoint. It fell back to whole directories, which is the expensive mistake — "
            "when everything is an entrance, 'how do you get in' has no answer. Find what "
            "actually starts this project and write the roots by hand.")
        return out

    cfg_path = _resolve_config(a.get("project"), a.get("projectPath"))
    cfg, project = CACHE.get(cfg_path)

    if name == "mcview_orient":
        import duplicates as _dup
        rank = _heatmap.pagerank(project)
        levels = project.levels()
        dups = _dup.analyze(project) if a.get("twins") else None
        r = _orient.orient(project, rank, levels, dups, a["target"])
        if "error" in r:
            return {**r, "caveat": "The target did not resolve, and nothing was guessed: a "
                                   "silently mis-resolved target returns a brief about "
                                   "something else."}
        r["caveat"] = CAVEAT["mass"] + " " + CAVEAT["cohesion"]
        if a.get("flow", True):
            import flow as _flow
            import services as _serv
            files = set(r["files"])
            inside = {s for s, x in project.symbols.items() if x.file in files}
            r["flow"] = _flow.trace(project, inside, rank)
            usan, dep = _flow.neighbors_by_module(project, inside, files)
            r["flow"].update(usan=usan, depende=dep, target=r["target"])
            m = _serv.reach(project)
            if m:
                r["flow"]["services"] = _serv.from_files(m, files)
            r["flow"]["caveat"] = CAVEAT["flow"]
        if dups is not None:
            r["twins_caveat"] = CAVEAT["twins"]
        return r

    if name == "mcview_process":
        import sequence as _seq
        base = project
        if "▸" in a["target"]:
            base = CACHE.weave(os.path.dirname(cfg_path))
        obs = None
        if a.get("runtime"):
            import runtime as _rt
            obs = _rt.observed(base, cfg.root)
        r = _seq.trace(base, a["target"], _heatmap.pagerank(base),
                       depth=int(a.get("depth", 4)), dst=a.get("to"), obs=obs)
        r["caveat"] = CAVEAT["order"]
        # A BLOCKING FIELD, not another caveat, and the difference is measured. An agent
        # tracing a flow was shown "no [surfaces] declared: the origin was CHOSEN BY MASS",
        # continued, produced an analysis whose entry point turned out to be the OUTPUT
        # formatter, and mentioned the warning at the end — where it protects nobody. Prose
        # in a skill did not stop it. A named top-level field carrying the question and the
        # candidates leaves nothing to compose and nothing to skip.
        if r.get("of_candidates", 0) > 1 and not getattr(base.cfg, "surfaces", None):
            import blueprint as _bp
            cands, pregunta = _bp.door_candidates(base)
            r["ask_the_user"] = {
                "why": "This walk began at the heaviest symbol, not at a declared door — an "
                       "inference, and everything below is conditioned on it.",
                "question": pregunta,
                "candidates": cands,
                "do_not": "Do not report this flow as an answer before asking. A flow that "
                          "starts in the wrong place is not a partial answer, it is a wrong "
                          "one.",
            }
        if a.get("runtime"):
            r["runtime_caveat"] = (
                "The probe CONFIRMS, it never rules out. A step with no mark may sit behind an "
                "`if`, fall outside the measured window, or run in a process with no probe. "
                "Absence of evidence is not evidence of absence."
                if obs else
                "No runtime census found — the steps carry no marks. That is 'not measured', "
                "not 'did not run'.")
        return r

    if name == "mcview_route":
        import route as _route
        ws = os.path.join(os.path.dirname(cfg_path), "mcview.workspace.toml")
        if not os.path.exists(ws):
            return {"error": f"{ws} is missing — that is where [[routes]] are declared."}
        with open(ws, "rb") as fh:
            declared = _config.tomllib.load(fh).get("routes", [])
        if not a.get("name"):
            return {"declared_routes": [d.get("name") for d in declared],
                    "caveat": "Pick one by name. Routes are declared because the junctions "
                              "between repositories are strings, not calls."}
        chosen = next((d for d in declared if d.get("name") == a["name"]), None)
        if not chosen:
            return {"error": "unknown route",
                    "declared_routes": [d.get("name") for d in declared]}
        weave = CACHE.weave(os.path.dirname(cfg_path))
        r = _route.trace(weave, chosen["src"], chosen["dst"])
        for k in ("inside", "origin", "sink"):
            r.pop(k, None)
        r["chokepoints"] = [weave.symbols[s].loc for s in r.get("chokepoints", [])]
        r["shortest_path"] = [weave.symbols[s].loc for s in (r.get("shortest_path") or [])]
        r["caveat"] = (CAVEAT["flow"] + " Chokepoints ARE exact — proven by removal, not "
                       "sampled. If there are none, there is no mandatory step to put a "
                       "guarantee on: building one is design, not cleanup.")
        return r

    if name == "mcview_exists":
        import index as _index
        idx = _index.load(cfg) or _index.build(cfg)
        r = _index.query(idx, a["content"], a.get("path", "<new>"))
        r["caveat"] = CAVEAT["twins"]
        return r

    if name == "mcview_blueprint":
        import blueprint as _bp
        return _bp.build(project, _heatmap.pagerank(project))

    if name == "mcview_map":
        rank = _heatmap.pagerank(project)
        rows = _heatmap.by_file(project, rank)
        lim = int(a.get("limit", 25))
        return {"project": cfg.name,
                "concentration": _heatmap.concentration(rows),
                "files": [{k: v for k, v in f.items() if k != "mass"} for f in rows[:lim]],
                "caveat": CAVEAT["mass"]}

    if name == "mcview_status":
        levels = project.levels()
        if not a.get("level"):
            return {"project": cfg.name, "symbols": len(project.symbols),
                    "roots": dict(project.reasons),
                    "levels": {k: len(v) for k, v in levels.items()},
                    "caveat": CAVEAT["dead"]}
        lim = int(a.get("limit", 25))
        chosen = sorted(levels.get(a["level"], ()),
                        key=lambda s: project.symbols[s].file)
        return {"level": a["level"], "total": len(chosen),
                "symbols": [{"name": project.symbols[s].name,
                             "kind": project.symbols[s].kind,
                             "loc": project.symbols[s].loc} for s in chosen[:lim]],
                "caveat": CAVEAT["dead"]}

    if name == "mcview_locks":
        import locks as _locks
        if a.get("from") and a.get("to"):
            r = _locks.propose(project, _heatmap.pagerank(project), a["from"], a["to"])
            r["caveat"] = (CAVEAT["locks"] + " An empty candidate list is NOT 'found nothing': "
                           "it is 'nothing is interposed'. The chokepoint to put a guarantee "
                           "on does not exist yet.")
            return r
        r = _locks.verify(project, cfg)
        r["caveat"] = CAVEAT["locks"]
        return r

    if name == "mcview_seams":
        import seams as _seams
        if a.get("workspace"):
            import glob as _glob
            cats = {}
            for tm in sorted(_glob.glob(os.path.join(os.path.dirname(cfg_path),
                                                     "mcview*.toml"))):
                c2 = _config.load(tm)
                if getattr(c2, "seams", None):
                    cats[c2.name] = _seams.detect(_factory.make_project(c2))
            bridges = _seams.join(cats)
            return {"projects": sorted(cats), **bridges, "caveat": CAVEAT["seams"]}
        return {"project": cfg.name, "catalog": _seams.detect(project),
                "caveat": CAVEAT["seams"]}

    if name == "mcview_diff":
        import subprocess

        import diff as _diff
        repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                              capture_output=True, text=True, check=True).stdout.strip()
        before = _diff.snapshot_of(repo, a["ref"], cfg_path)
        after = _diff.snapshot_of(repo, None, cfg_path)
        d = _diff.compare(before, after)
        verdict, signals = _diff.verdict(d)
        return {"verdict": verdict, "signals": signals,
                "net_symbols": d["net_symbols"], "files_touched": d["files_touched"],
                "caveat": CAVEAT["diff"]}

    return {"error": f"unknown tool: {name}"}


def _workspace_configs(root: str) -> dict:
    import glob as _glob
    out = {}
    for f in sorted(_glob.glob(os.path.join(root, "mcview*.toml"))):
        b = os.path.basename(f)[:-5]
        label = b.split(".", 1)[1] if "." in b else "principal"
        if label != "workspace":
            out[label] = f
    return out


# ---------------------------------------------------------------- the protocol
def _send(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def _text(payload) -> dict:
    return {"content": [{"type": "text",
                         "text": json.dumps(payload, ensure_ascii=False,
                                            indent=2, default=str)}]}


def serve() -> int:
    """Newline-delimited JSON-RPC 2.0 on stdin/stdout.

    Anything printed to stdout that is not a response corrupts the stream, so every view that
    prints —and several do— is never called from here: the tools use the functions that RETURN
    structures, which is the same split `--json` already relies on.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method, mid = msg.get("method"), msg.get("id")

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mcview", "version": VERSION},
                "instructions": INSTRUCTIONS}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params") or {}
            t0 = time.time()
            try:
                out = call(p.get("name", ""), p.get("arguments") or {})
                out["_seconds"] = round(time.time() - t0, 2)
                _send({"jsonrpc": "2.0", "id": mid, "result": _text(out)})
            except _Missing as e:
                # Not an exception the model should have to interpret: it is the one error
                # with an exact next step, so it comes back as a normal result carrying it.
                _send({"jsonrpc": "2.0", "id": mid,
                       "result": _text({"error": str(e), "next": "mcview_init"})})
            except SystemExit as e:
                # `SystemExit` and NOT `Exception`, because it inherits from `BaseException`
                # and a bare `except Exception` lets it through — which KILLS THE SERVER.
                # The optional parsers exit rather than raise, because for a CLI user
                # "install this and exit" is the right UX; for a long-lived server it is the
                # worst possible one: the client loses the connection, every later call fails,
                # and the reason is invisible. Measured on a global install with no
                # tree-sitter: one call against a TypeScript project and the process was gone
                # with exit code 1.
                #
                # It is the same bug, in the same shape, that once made `check_reach` die
                # instead of skipping. Third time this class shows up — hence catching it
                # here, at the one place every tool call passes through, rather than at each
                # site that can raise it.
                _send({"jsonrpc": "2.0", "id": mid, "result": _text({
                    "error": str(e) or "the tool exited",
                    "caveat": "This is a MISSING OPTIONAL DEPENDENCY, not a fact about the "
                              "code being measured. Nothing was analyzed — do not read this "
                              "as an empty result."})})
            except Exception as e:                                   # noqa: BLE001
                _send({"jsonrpc": "2.0", "id": mid, "result": {
                    "isError": True,
                    "content": [{"type": "text",
                                 "text": f"{type(e).__name__}: {e}\n"
                                         f"{traceback.format_exc()[-800:]}"}]}})
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(serve())
