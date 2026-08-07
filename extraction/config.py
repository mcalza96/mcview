"""Per-project configuration — `mcview.toml`.

EVERYTHING project-specific lives here. The core knows no framework: it knows there are
decorators that mark roots, but not which ones.

Declaring the roots is half the work and it is not optional: a reachability analysis with
no roots declares the entire project dead. It is exactly where the mature tools in this
space concentrate their advantage.

Minimal example:

    [project]
    name = "my-api"
    root = "src"

    [roots]
    decorators    = ["task", "command"]     # @task(...) marks a root
    route_methods = ["get", "post"]         # @router.get(...) / @app.post(...)
    route_objects = ["router", "app"]
    dirs          = ["src/cli/", "tests/"]  # every module in here is a root
    product_dirs  = ["src/cli/"]            # of those, which ones are NOT tests

    [exclude]
    patterns = ["migrations/", "_pb2.py$"]
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_IGNORED = {
    "__pycache__", ".venv", "venv", "node_modules", ".git", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "build", "dist", ".mcview", ".codegraph",
    # Build output of JS/TS projects. `.next` generates a validator.ts with thousands of
    # synthetic types (`__Check`, `__Unused`) referenced by nobody: they made up 90% of the
    # "dead" symbols in the frontend's first run and would have been the entire finding if
    # nobody had looked at the list. Generated code is NEVER evidence.
    ".next", ".turbo", ".vercel", "out", "coverage", ".svelte-kit",
}


@dataclass
class Config:
    name: str
    root: str
    # Which parser builds the graph. "python" (ast, the default) or "typescript"
    # (tree-sitter). The factory picks it; the rest of the module never looks at it.
    language: str = "python"
    root_decorators: set[str] = field(default_factory=set)
    route_methods: set[str] = field(default_factory=set)
    route_objects: set[str] = field(default_factory=set)
    route_object_prefixes: tuple[str, ...] = ()
    root_dirs: tuple[str, ...] = ()
    product_dirs: tuple[str, ...] = ()
    excluded_patterns: tuple[re.Pattern, ...] = ()
    ignored_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_IGNORED))
    # An auxiliary directory (tooling, evaluation) is cold BY DESIGN. Without declaring it,
    # the map reads it as dead periphery and the judgement turns into noise: 48 eval files
    # with 0.75% of the mass are not entropy, they are eval.
    areas: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Lines of work. The file is the wrong unit for seeing what a project is about:
    # "retrieval" lives in 4 different directories.
    modules: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # Modules that are PLUMBING by nature: they instrument everyone and belong to nobody.
    # Judging them by the cohesion yardstick always returns "SCATTERED", and that is a
    # category error — there is nothing to fix there.
    crosscutting_modules: tuple[str, ...] = ()
    exclude_duplicates: tuple[str, ...] = ()
    # SEAM detectors: the literals through which this project joins others. Optional and
    # declared, like the roots. Without this, `seams.detect` returns nothing.
    seams: dict = field(default_factory=dict)
    # service → entrypoint. Each process's reach is COMPUTED from the graph; declaring it
    # per directory would be a lie, because `services/` runs in the api and in the worker.
    services: dict = field(default_factory=dict)
    # Modules that only WATCH: logs, metrics, audit, traces. A symbol whose only readers
    # live in here is computed and GOVERNS NOTHING — see `consumption.py`. It is declared
    # because "what counts as observability" belongs to the project: in one it is
    # `telemetry.py`, in another `obs/`.
    observability: tuple[str, ...] = ()
    # Modules that only TRANSPORT: they serialize a value into a header, a queue, a payload.
    # Reading in order to send is not consuming either; the consumer is on the other side
    # and may not exist.
    transport: tuple[str, ...] = ()
    # Contracts over CONNECTIONS. They are declared like the roots —by hand, with the tool
    # proposing them— because an auto-discovered lock locks accidents, not intentions.
    locks: tuple = ()
    # Where a user ENTERS. These are not the roots: roots are everything that starts a path
    # (402 in CIRE, which is why the depth axis flattens); a surface is a door a person
    # walks through, and there are three or four.
    surfaces: dict = field(default_factory=dict)
    # Where the agent picks a tool BY NAME. It is a seam made of strings and no graph edge
    # crosses it, so it gets declared: without this, the map from Telegram reaches 48 of
    # mcp_tools' 738 symbols and reads as if the rest did not exist.
    dispatch: dict = field(default_factory=dict)
    min_statements: int = 4
    # A nested block is smaller than a function by construction: demanding the same minimum
    # leaves it out almost always. The number comes from measuring, not from choosing — see
    # the header of `core.blocks`.
    min_statements_block: int = 3
    jaccard_threshold: float = 0.80

    # -- queries the core makes --------------------------------------------
    def module_of(self, rel: str) -> str:
        """Line of work. With no declaration, it falls back to the 2-level directory."""
        best, longest = None, -1
        for name, prefixes in self.modules.items():
            for p in prefixes:
                if rel.startswith(p) and len(p) > longest:
                    best, longest = name, len(p)
        if best:
            return best
        parts = rel.split("/")
        return "/".join(parts[:2]) if len(parts) > 2 else parts[0]

    def area_of(self, rel: str) -> str:
        """core | auxiliary | test — whatever is not declared is core."""
        best, longest = "core", -1
        for name, prefixes in self.areas.items():
            for p in prefixes:
                if rel.startswith(p) and len(p) > longest:
                    best, longest = name, len(p)
        return best

    def excluded_from_duplicates(self, rel: str) -> bool:
        return rel.startswith(self.exclude_duplicates) if self.exclude_duplicates else False

    def excluded(self, rel: str) -> bool:
        return any(p.search(rel) for p in self.excluded_patterns)

    def is_root_dir(self, rel: str) -> bool:
        return rel.startswith(self.root_dirs) if self.root_dirs else False

    def is_product_dir(self, rel: str) -> bool:
        return rel.startswith(self.product_dirs) if self.product_dirs else False

    def root_reason(self, decorator: str) -> str | None:
        """Returns why this decorator marks a root, or None."""
        if not decorator:
            return None
        if decorator in self.root_decorators:
            return decorator
        if "." in decorator:
            base, _, method = decorator.rpartition(".")
            if method in self.route_methods and (
                    base in self.route_objects
                    or any(base.endswith(p) for p in self.route_object_prefixes)):
                return "http_route"
            if base in self.route_objects and method not in self.route_methods:
                # e.g. @mcp_server.call_tool() — a protocol handler
                return "protocol_handler"
        return None


def discover(name: str | None = None, src: str | None = None) -> str | None:
    """Finds the config by walking up from the current directory.

    THE CONFIG DOES NOT LIVE INSIDE THE TOOL, and this is what makes that true. While
    `mcview.toml` sat inside `mcview/`, extracting the module into another repository
    carried this project's configuration with it: the promise that "everything specific
    lives in a `.toml`" was true on paper and false in the file tree.

    Convention, at the project root:

        mcview.toml            the default project
        mcview.<name>.toml     the others, if there is more than one

    A new project copies `mcview/` and writes ONE `mcview.toml`. Nothing else.
    """
    file = f"mcview.{name}.toml" if name else "mcview.toml"
    current = os.path.abspath(src or os.getcwd())
    while True:
        cand = os.path.join(current, file)
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def load(toml_path: str) -> Config:
    with open(toml_path, "rb") as f:
        d = tomllib.load(f)

    p = d.get("project", {})
    r = d.get("roots", {})
    e = d.get("exclude", {})
    base = os.path.dirname(os.path.abspath(toml_path))

    return Config(
        name=p.get("name", os.path.basename(base)),
        root=os.path.normpath(os.path.join(base, p.get("root", "."))),
        language=p.get("language", "python"),
        root_decorators=set(r.get("decorators", [])),
        route_methods=set(r.get("route_methods", [])),
        route_objects=set(r.get("route_objects", [])),
        route_object_prefixes=tuple(r.get("route_object_suffixes", [])),
        root_dirs=tuple(r.get("dirs", [])),
        product_dirs=tuple(r.get("product_dirs", [])),
        excluded_patterns=tuple(re.compile(x) for x in e.get("patterns", [])),
        ignored_dirs=set(DEFAULT_IGNORED) | set(e.get("dirs", [])),
        areas={k: tuple(v) for k, v in d.get("areas", {}).items()},
        modules={k: tuple(v) for k, v in d.get("modules", {}).items()},
        crosscutting_modules=tuple(d.get("crosscutting_modules", [])),
        exclude_duplicates=tuple(d.get("duplicates", {}).get("exclude", [])),
        locks=tuple(d.get("locks", [])),
        surfaces={k: tuple(v) if isinstance(v, list) else (v,)
                  for k, v in d.get("surfaces", {}).items()},
        dispatch=d.get("dispatch", {}),
        observability=tuple(d.get("consumption", {}).get("observability", [])),
        transport=tuple(d.get("consumption", {}).get("transport", [])),
        seams=d.get("seams", {}),
        services=d.get("services", {}),
        min_statements=int(d.get("duplicates", {}).get("min_statements", 4)),
        min_statements_block=int(d.get("duplicates", {}).get("min_statements_block", 3)),
        jaccard_threshold=float(d.get("duplicates", {}).get("jaccard_threshold", 0.80)),
    )
