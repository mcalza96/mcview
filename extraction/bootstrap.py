# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""`--init`: derive a starter `mcview.toml` from what the project already declares.

Declaring the roots is half the work and it is the only mandatory part — without them,
reachability declares the entire project dead. But that does not mean it has to be done from
memory: **the project already says how it starts**, in `[project.scripts]`, in the Dockerfile's
`CMD`, in the decorators that register into a dispatch dict, in the single `uvicorn.run`.

Until now that procedure lived in a skill — which is to say, in a prompt somebody had to read,
remember and not get wrong. This module moves it into the tool. It is the same trade the whole
project is built on: given two designs, the one that moves a guarantee out of the prompt and
into the construction wins.

IT PROPOSES, IT DOES NOT RULE — and the output says so line by line.

Every root it writes carries **where it came from**, as a comment, because a config whose roots
came out of `[project.scripts]` can be audited and one that came out of a heuristic cannot. Six
months from now that comment is the difference between knowing why a directory is declared and
guessing.

THE EXPENSIVE MISTAKE IS DECLARING DIRECTORIES, so this prefers real roots and only falls back
to `dirs` when it found nothing else — loudly. Measured on a 448-file project: declaring
directories gave 649 roots and the flow stopped saying anything; declaring what actually starts
—eight files— and it began to answer. A `--init` that quietly emitted `dirs = ["src/"]` would
produce a config that runs, reports numbers, and measures nothing.

WHAT IT DOES NOT DO. It does not name the lines of work (`[modules]`), it does not declare the
seams, and it does not guess the surfaces. Those are statements about what the project *is*, not
about how it starts, and nothing in the file system knows them.
"""
from __future__ import annotations

import ast
import os
import re

from config import DEFAULT_IGNORED
from core import _decorator_name

# Decorators that wrap a function without REGISTERING it anywhere. A registry decorator makes
# its target reachable by name; these only change how it is called. Treating them as roots
# would mark half the codebase as an entry point.
NOT_A_ROOT = frozenset({
    "property", "staticmethod", "classmethod", "abstractmethod", "cached_property",
    "dataclass", "wraps", "lru_cache", "cache", "override", "overload", "contextmanager",
    "asynccontextmanager", "singledispatch", "total_ordering", "final", "runtime_checkable",
    # Test registries ARE registries, but their targets are tests: they belong in `dirs`, not
    # in `[roots] decorators`, or the census counts the suite as product.
    "fixture", "pytest.fixture", "parametrize", "pytest.mark.parametrize",
})

# Names that look like an HTTP verb on a router/app object: `@router.get(...)`.
HTTP_METHODS = frozenset({
    "get", "post", "put", "patch", "delete", "head", "options", "trace",
    "route", "api_route", "websocket", "add_api_route",
})

TEST_DIRS = ("tests", "test", "__tests__", "spec", "specs", "e2e")
AUX_DIRS = ("scripts", "tools", "bench", "benchmarks", "eval", "evals", "examples")
SRC_DIRS = ("src", "app", "lib", "source")


def _walk(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in DEFAULT_IGNORED and not d.startswith(".")]
        yield dirpath, filenames


def _is_aux(rel: str) -> bool:
    """A path belonging to the suite, to tooling, or to a scratch pad.

    They are not product: their entrypoints do not start the system and their decorators
    register tests. They still become `dirs` —otherwise everything only they touch comes out
    dead— but never `product_dirs`, and never a root reason.
    """
    parts = rel.replace(os.sep, "/").split("/")
    return any(p in TEST_DIRS or p in AUX_DIRS or p.startswith("scratch") for p in parts)


def _read(path: str) -> str:
    try:
        return open(path, encoding="utf-8").read()
    except (OSError, UnicodeDecodeError):
        return ""


def detect(root: str) -> dict:
    """Everything the project already says about how it starts.

    Returns findings with PROVENANCE attached — each one carries the file that stated it, so
    `render` can write the comment. A finding without its source is a heuristic wearing the
    costume of a declaration.
    """
    py: list[str] = []
    ts: list[str] = []
    for dirpath, filenames in _walk(root):
        for f in filenames:
            p = os.path.join(dirpath, f)
            if f.endswith(".py"):
                py.append(p)
            elif f.endswith((".ts", ".tsx")):
                ts.append(p)

    out: dict = {
        "language": "typescript" if len(ts) > len(py) else "python",
        "n_py": len(py), "n_ts": len(ts),
        "decorators": [], "maybe_decorators": [], "route_methods": [], "route_objects": [],
        "maybe_route_objects": [],
        "entrypoints": [], "test_dirs": [], "aux_dirs": [], "scratch_dirs": [],
        "src_root": ".",
        "notes": [],
    }

    # -- where the source lives -------------------------------------------------
    # Only if it is a REAL container: a `src/` holding two files while the root holds two
    # hundred is not the source root, and getting this wrong scopes every later number.
    files = py or ts
    for cand in SRC_DIRS:
        d = os.path.join(root, cand)
        if not os.path.isdir(d):
            continue
        inside = sum(1 for f in files if f.startswith(d + os.sep))
        if inside >= max(3, len(files) * 0.5):
            out["src_root"] = cand
            out["notes"].append(f"`{cand}/` holds {inside} of {len(files)} source files")
            break

    # -- the directories that exist ---------------------------------------------
    base = os.path.join(root, out["src_root"]) if out["src_root"] != "." else root
    for dirpath, _ in _walk(root):
        name = os.path.basename(dirpath)
        rel = os.path.relpath(dirpath, base)
        if rel.startswith(".."):
            rel = os.path.relpath(dirpath, root)
        if name.startswith("scratch") and rel not in out["scratch_dirs"]:
            out["scratch_dirs"].append(rel)
        elif name in TEST_DIRS and rel not in out["test_dirs"]:
            out["test_dirs"].append(rel)
        elif name in AUX_DIRS and rel not in out["aux_dirs"]:
            out["aux_dirs"].append(rel)

    if out["language"] == "typescript":
        _detect_ts(root, out)
        return out
    _detect_py(root, py, out)
    return out


def _detect_py(root: str, py: list[str], out: dict) -> None:
    """Registration decorators and entrypoints, from the AST and from what declares startup."""
    from collections import Counter, defaultdict

    bare: Counter = Counter()
    where: defaultdict = defaultdict(set)
    objs: Counter = Counter()
    methods: Counter = Counter()
    proto: Counter = Counter()

    for p in py:
        rel = os.path.relpath(p, root)
        if _is_aux(rel):
            continue                      # a decorator used only by the suite registers tests
        try:
            tree = ast.parse(_read(p))
        except (SyntaxError, ValueError):
            continue
        # MODULE LEVEL ONLY, and this is the discriminator that matters — not a denylist.
        # A registry decorator makes a module-level function reachable by name from a dispatch
        # dict; `@field_validator` decorates a METHOD and registers it on its own class, which
        # is scoped and reaches nothing. Measured here: scanning every node made
        # `field_validator` and `model_validator` (20 uses) look like registries, and declaring
        # them as roots would have marked every Pydantic model method as an entry point —
        # reachability stops discriminating, which is the same failure as declaring whole
        # directories in a different costume.
        for n in tree.body:
            if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for d in n.decorator_list:
                name = _decorator_name(d)
                if not name or name.split(".")[-1] in NOT_A_ROOT or name in NOT_A_ROOT:
                    continue
                if "." in name:
                    obj, _, meth = name.rpartition(".")
                    if meth in HTTP_METHODS:
                        objs[obj] += 1
                        methods[meth] += 1
                    else:
                        # `@mcp_server.call_tool()` — the object is a registry but the method
                        # is not an HTTP verb: it is a PROTOCOL handler, which `config
                        # .root_reason` already knows how to classify once the object is
                        # declared. It is reported and not declared, because "an object with a
                        # decorator method" also describes `@app.middleware` and a dozen
                        # things that are not roots.
                        proto[obj] += 1
                    continue
                bare[name] += 1
                where[name].add(rel)

    # A REGISTRY is used across many files; a local helper decorator is used in one. The
    # threshold is on FILES and not on uses, because a decorator applied 40 times inside one
    # module is that module's plumbing, not the framework's registry.
    for name, n in bare.most_common():
        row = (name, n, len(where[name]), sorted(where[name])[0])
        if len(where[name]) >= 2:
            out["decorators"].append(row)
        else:
            # One file is not enough evidence to DECLARE a registry — but it is enough to say
            # it exists. Measured here: `mcp_prompt` and `mcp_resource` are real registries
            # used in exactly one file each, and a threshold that hides them silently is the
            # same class of error as one that declares a validator. They go out as candidates.
            out["maybe_decorators"].append(row)
    out["route_methods"] = [m for m, _ in methods.most_common()]
    out["route_objects"] = [o for o, _ in objs.most_common()]
    out["maybe_route_objects"] = [(o, n) for o, n in proto.most_common()
                                  if o not in objs and n >= 2]

    # -- what actually starts a process -----------------------------------------
    seen: set[str] = set()

    def add(rel: str, why: str) -> None:
        if rel not in seen:
            seen.add(rel)
            out["entrypoints"].append((rel, why))

    pyproject = os.path.join(root, "pyproject.toml")
    if os.path.exists(pyproject):
        src = _read(pyproject)
        block = re.search(r"\[project\.scripts\](.*?)(\n\[|\Z)", src, re.S)
        if block:
            for target in re.findall(r'=\s*"([\w.]+):', block.group(1)):
                rel = target.replace(".", os.sep) + ".py"
                if os.path.exists(os.path.join(root, rel)):
                    add(rel, "declared in [project.scripts]")

    for name in ("Dockerfile", "Procfile", "docker-compose.yml", "docker-compose.yaml"):
        p = os.path.join(root, name)
        if not os.path.exists(p):
            continue
        for m in re.finditer(r"([\w/]+\.py)", _read(p)):
            rel = m.group(1)
            if os.path.exists(os.path.join(root, rel)):
                add(rel, f"runs in {name}")

    for p in py:
        rel = os.path.relpath(p, root)
        # An `if __name__ == "__main__"` inside a test or a scratch file is not a process
        # entrypoint. Measured on a real backend: 158 files matched and 155 were tests,
        # scratch and scripts. Emitting all of them is the "649 roots" failure again — when
        # everything is an entrance, "how do you get in" has no answer.
        if _is_aux(rel):
            continue
        src = _read(p)
        if "uvicorn.run(" in src or re.search(r"\.run_forever\(|\.serve_forever\(", src):
            add(rel, "starts a server (uvicorn.run / serve_forever)")
        elif '__name__ == "__main__"' in src or "__name__ == '__main__'" in src:
            add(rel, "has an `if __name__ == \"__main__\"` block")


def _detect_ts(root: str, out: dict) -> None:
    """In a filesystem-routed framework the roots are free: the framework loads by FILE NAME.

    There is nothing to hunt here — no decorator escapes, unlike a Python backend where one
    did and only turned up with a runtime probe.
    """
    conv = []
    for dirpath, filenames in _walk(root):
        for f in filenames:
            if f in ("route.ts", "route.tsx", "page.tsx", "layout.tsx", "middleware.ts"):
                conv.append(os.path.relpath(os.path.join(dirpath, f), root))
    if conv:
        out["convention_roots"] = conv
        out["notes"].append(
            f"{len(conv)} files loaded by framework convention (route/page/layout) — those "
            f"are the roots, and `ts.py` already declares them: nothing to write here")
    pkg = os.path.join(root, "package.json")
    if os.path.exists(pkg):
        for m in re.finditer(r'"(?:main|module|bin)"\s*:\s*"([^"]+)"', _read(pkg)):
            out["entrypoints"].append((m.group(1), "declared in package.json"))


# ---------------------------------------------------------------------- render
def render(root: str, findings: dict) -> str:
    """The `.toml`, with the provenance of every root written next to it."""
    name = os.path.basename(os.path.abspath(root)) or "project"
    L = [
        "# Generated by `mcview --init`. It is a PROPOSAL, not a verdict — review it.",
        "#",
        "# Every root below says where it came from. That comment is the point: a config whose",
        "# roots came out of `[project.scripts]` can be audited; one that came out of somebody's",
        "# judgement cannot, and in six months nobody knows whether a line is there for a reason.",
        "#",
        "# Before believing any number this produces, run the four checks in the `mcview-install`",
        "# skill — above all the first: if the root count approaches the file count, the roots",
        "# are wrong and every later measurement is noise wearing the shape of data.",
        "",
        "[project]",
        f'name = "{name}"',
        f'root = "{findings["src_root"]}"',
    ]
    if findings["language"] != "python":
        L.append(f'language = "{findings["language"]}"')
    for n in findings["notes"]:
        L.append(f"# {n}")

    L += ["", "[roots]"]
    wrote_real_root = False

    if findings["decorators"]:
        L.append("# Decorators that REGISTER into a dispatch dict: their target is reachable by")
        L.append("# name and no call graph edge points at it. Each one below is used across")
        L.append("# several files, which is what tells a registry from a local helper.")
        for dec, uses, nfiles, example in findings["decorators"][:8]:
            L.append(f"#   {dec}: {uses} uses in {nfiles} files (e.g. {example})")
        names = ", ".join(f'"{d[0]}"' for d in findings["decorators"][:8])
        L.append(f"decorators = [{names}]")
        wrote_real_root = True

    if findings["route_methods"]:
        L.append("# HTTP routes: `@<object>.<method>(...)`. The framework calls these; nothing")
        L.append("# in the code does.")
        L.append("route_methods = [" + ", ".join(f'"{m}"' for m in findings["route_methods"]) + "]")
        L.append("route_objects = [" + ", ".join(f'"{o}"' for o in findings["route_objects"][:6]) + "]")
        wrote_real_root = True

    for dec, uses, nfiles, example in findings.get("maybe_decorators", [])[:6]:
        L.append(f"#   candidate — `{dec}`: {uses} uses but only in {nfiles} file "
                 f"({example}). One file is not enough to declare a registry; look at it.")
    for obj, n in findings.get("maybe_route_objects", [])[:4]:
        L.append(f"#   candidate — `{obj}` is decorated on with a NON-http method {n} times: "
                 f"if it registers protocol handlers, add it to route_objects.")

    if findings["entrypoints"]:
        L.append("# Processes that actually start. These are files, not directories — which is")
        L.append("# what keeps reachability able to discriminate.")
        for rel, why in findings["entrypoints"][:10]:
            L.append(f"#   {rel} — {why}")
        wrote_real_root = True

    # THE ENTRYPOINT FILES, not their parent directory. `dirs` matches by prefix, so a file
    # path works — and that difference is the whole point. Deriving the parent looked tidier
    # and produced `dirs = ["src/"]` on a flat project, which makes EVERY module in the source
    # root a root: measured on a 3-symbol fixture, dead code came out ALIVE_PRODUCT. It is the
    # exact mistake this module's own header warns about, committed by this module.
    dirs = [rel for rel, _ in findings["entrypoints"][:10]]
    product = list(dirs)
    for t in findings["test_dirs"]:
        if t + "/" not in dirs:
            dirs.append(t + "/")          # tests are roots, but NOT product

    if findings.get("convention_roots"):
        # A filesystem-routed framework HAS declared its roots — they are the file names, and
        # `ts.py` walks from them without any help from this file. Emitting the "nothing was
        # found" panic here was false, and the config it produced was worse than false: the
        # fallback declared the source directory, whose files become roots but not product,
        # so everything reachable came out off-product. Both sides of that were fixed; what
        # `dirs` adds here is the code the framework does NOT load by name.
        wrote_real_root = True
        L += [
            "#",
            f"# {len(findings['convention_roots'])} files are loaded BY NAME by the framework",
            "#   (page/layout/route/middleware). They are roots and they are product, and they",
            "#   are found by convention — nothing to declare. `dirs` below is the rest of the",
            "#   source: it is a root so that what only it touches is not read as dead, and it",
            "#   is product so it is not read as tests.",
        ]
        dirs = [findings["src_root"] + "/"] if findings["src_root"] != "." else ["./"]
        product = list(dirs)

    if not wrote_real_root:
        L += [
            "#",
            "# ⚠ NOTHING REAL WAS FOUND: no registration decorators, no HTTP routes, no process",
            "#   entrypoint. Falling back to whole directories, which is the EXPENSIVE mistake —",
            "#   measured on a 448-file project it gave 649 roots and the flow stopped saying",
            "#   anything, because when everything is an entrance there is no 'how do you get in'.",
            "#   Find what really starts this project and replace this line. See `mcview-install`.",
        ]
        dirs = [findings["src_root"] + "/"] if findings["src_root"] != "." else ["./"]
        product = list(dirs)

    if dirs:
        L.append("dirs = [" + ", ".join(f'"{d}"' for d in dirs) + "]")
    if product:
        L.append("# …of those, the ones that are NOT tests. Without this second list the heat map")
        L.append("# and the paths fill up with tests and bury the real system.")
        L.append("product_dirs = [" + ", ".join(f'"{d}"' for d in product) + "]")

    if findings.get("scratch_dirs"):
        L += ["", "# A scratch pad is not the system: it is where things get tried. Measured",
              "# here, leaving it in added 33 symbols to the inventory and diluted every",
              "# percentage computed over it.", "[exclude]",
              "patterns = [" + ", ".join(f'"^{d}/"' for d in findings["scratch_dirs"]) + "]"]

    if findings["test_dirs"] or findings["aux_dirs"]:
        L += ["", "# An auxiliary directory is cold BY DESIGN: tooling, benchmarks, evaluation.",
              "# Without declaring it, the map reads it as dead periphery.", "[areas]"]
        if findings["aux_dirs"]:
            L.append("auxiliary = [" + ", ".join(f'"{d}/"' for d in findings["aux_dirs"]) + "]")
        if findings["test_dirs"]:
            L.append("test = [" + ", ".join(f'"{d}/"' for d in findings["test_dirs"]) + "]")

    if findings["test_dirs"]:
        L += ["", "[duplicates]",
              "# Tests MUST be roots (or everything only they touch comes out dead), but their",
              "# internal duplication is noise: two near-identical tests are normal, not debt.",
              "exclude = [" + ", ".join(f'"{d}/"' for d in findings["test_dirs"]) + "]"]

    # These two used to sit in the "nothing in the file system knows them" list below, and for
    # one of them that was simply false: a service IS its entrypoint, and the entrypoints were
    # already found, with their reason, a few lines up. The cost of not writing them was not
    # cosmetic — `--services` prints "no [services] in the .toml — nothing to derive" and the
    # whole view is dark on every freshly initialised project, with the data sitting right here.
    if findings["entrypoints"]:
        L += ["", "# One entry per process that starts. What each service REACHES is derived from",
              "# the graph, not declared — that is why a file can belong to several at once,",
              "# which is the truth about a shared `services/` directory.",
              "[services]"]
        for rel, why in findings["entrypoints"][:10]:
            svc = os.path.splitext(os.path.basename(rel))[0]
            L.append(f'{svc} = "{rel}"'.ljust(46) + f"# {why}")

    if findings["decorators"]:
        L += ["", "# A registration decorator is also a SEAM: whoever consumes this project by",
              "# name comes in through the id it registers. Derived from the same finding that",
              "# produced `[roots] decorators` — the rest of the section cannot be derived.",
              "[seams]",
              "exports_tool = [" + ", ".join(f'"{d[0]}"' for d in findings["decorators"][:8]) + "]"]

    L += [
        "",
        "# NOT written here, and not by omission — nothing in the file system knows them:",
        "#   [modules]   the lines of work. A module is NOT a directory: 'retrieval' can live",
        "#               in three at once. Declaring them by responsibility is what makes the",
        "#               map readable; declaring them by folder measures physical proximity.",
        "#               Not derivable, and this was MEASURED, not assumed: MCL over the call",
        "#               graph covers 33% of the symbols in groups of at most 40, which are",
        "#               SUB-modules. Proposing them gave 61 lines covering 16% of the files —",
        "#               worse than the directory fallback, which at least covers all of it.",
        "#               `mcview --modules` uses those groups for what they do measure: whether",
        "#               a line you declared is really one thing (SPLIT) or two names for one",
        "#               (MERGED).",
        "#   [seams]     the rest of it: the tables, the routes and the literals through which",
        "#               this project joins others.",
        "#   [surfaces]  the doors a user enters through.",
        "#   [[locks]]   the contracts over connections.",
        "# See the `mcview-install` skill.",
        "",
    ]
    return "\n".join(L)

