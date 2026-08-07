"""The three repositories as ONE graph, presenting the `Project` contract.

The whole trick is that there is no new view here. `Weave` exposes exactly what `Project`
exposes —`symbols`, `strong_edges`, `product_roots`, `cfg`— with every project's symbols
under a prefix, and with the SEAMS turned into real edges. Since every view works against
that contract, `contracts`, `atlas`, `paths` and `locks` start crossing repositories without
a single line of them being touched.

That includes what motivated all of this: a lock on connections can now state *"every
Telegram entry crosses the backend's tenant resolver"*, which is a claim about two repos and
until now there was no way to write it.

THE SEAM BECOMES AN EDGE, BUT IT DOES NOT DISGUISE ITSELF. The catalog in `seams.py` gives
`file:line` for both ends, and `Symbol` has `line`/`end`, so the symbol containing each end
resolves exactly — not by name, which would be guessing. Edges created this way are recorded
in `applied_seams`: a call proven by the AST and a string that matches across two repos are
not the same evidence, and whoever draws or rules has to be able to tell them apart.

Tables and RPCs are NOT woven. Two projects writing `content_chunks` are coupled —tightly—
but neither calls the other, so the edge would have an invented direction. They are reported
separately, as shared state.
"""
from __future__ import annotations

import copy
from collections import defaultdict

import config as _config
import seams as _seams
import factory as _factory

SEP = "▸"
CALL_KINDS = ("path", "tool")


class _WeaveConfig:
    """The `cfg` the views see. Every query is dispatched to the `.toml` of the matching
    project, read off the path prefix. Without this, `module_of` would classify a gateway
    file using the backend's lines of work."""

    def __init__(self, cfgs: dict[str, object], name: str):
        self._cfgs = cfgs
        self.name = name
        self.modules = {f"{e}{SEP}{m}": v for e, c in cfgs.items()
                        for m, v in c.modules.items()}
        self.root = ""

    def _split(self, rel: str) -> tuple[object | None, str]:
        label, _, rest = rel.partition(SEP)
        return self._cfgs.get(label), rest

    def module_of(self, rel: str) -> str:
        cfg, rest = self._split(rel)
        return f"{rel.split(SEP)[0]}{SEP}{cfg.module_of(rest)}" if cfg else rel

    def area_of(self, rel: str) -> str:
        cfg, rest = self._split(rel)
        return cfg.area_of(rest) if cfg else "core"

    def is_product_dir(self, rel: str) -> bool:
        cfg, rest = self._split(rel)
        return cfg.is_product_dir(rest) if cfg else True

    def is_root_dir(self, rel: str) -> bool:
        cfg, rest = self._split(rel)
        return cfg.is_root_dir(rest) if cfg else False

    def excluded_from_duplicates(self, rel: str) -> bool:
        cfg, rest = self._split(rel)
        return cfg.excluded_from_duplicates(rest) if cfg else False


class Weave:
    """Presents the `Project` contract. Everything else in the tool consumes it."""

    def __init__(self, projects: dict[str, object], cfgs: dict[str, object]):
        self._projects = projects
        self.cfg = _WeaveConfig(cfgs, " + ".join(sorted(projects)))
        self.symbols: dict[str, object] = {}
        self.strong_edges: dict[str, set[str]] = defaultdict(set)
        self.edges: dict[str, set[str]] = defaultdict(set)
        self.product_roots: set[str] = set()
        self.roots_by_reason: dict[str, set[str]] = defaultdict(set)
        # `weights` is the quota split PageRank uses. It is carried over prefixed rather
        # than recomputed: a symbol's mass inside its own project does not change because
        # two other repos joined the graph.
        self.weights: dict[tuple[str, str], float] = defaultdict(float)
        self.call_order: dict[str, list[tuple[int, str]]] = defaultdict(list)
        self.branches: dict[str, str] = {}
        self.applied_seams: list[dict] = []
        self._levels: dict[str, set[str]] = defaultdict(set)

        for label, p in projects.items():
            pre = f"{label}{SEP}"
            for sid, s in p.symbols.items():
                # Copy with the file prefixed: a file's id has to be unique across the
                # weave, or two repos with `api/v1/routers/` collapse into one node.
                s2 = copy.copy(s)
                s2.file = pre + s.file
                s2.id = pre + sid
                self.symbols[pre + sid] = s2
            for origin, targets in p.strong_edges.items():
                self.strong_edges[pre + origin] |= {pre + d for d in targets}
            for origin, targets in p.edges.items():
                self.edges[pre + origin] |= {pre + d for d in targets}
            self.product_roots |= {pre + r for r in p.product_roots}
            for (o, d), w in p.weights.items():
                self.weights[(pre + o, pre + d)] += w
            for o, calls in getattr(p, "call_order", {}).items():
                self.call_order[pre + o] = [(ln, pre + d) for ln, d in calls]
            for k, v in getattr(p, "branches", {}).items():
                self.branches[pre + k] = v
            for reason, ids in getattr(p, "roots_by_reason", {}).items():
                self.roots_by_reason[reason] |= {pre + i for i in ids}
            for level, ids in p.levels().items():
                self._levels[level] |= {pre + i for i in ids}

        self.by_file: dict[str, list] = defaultdict(list)
        for s in self.symbols.values():
            self.by_file[s.file].append(s)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        for sid, s in self.symbols.items():
            self.by_name[s.name].append(sid)

    def levels(self) -> dict[str, set[str]]:
        return dict(self._levels)

    def resolve(self, target: str) -> tuple[set[str], str | None]:
        """`project▸target`. The target is resolved by the PROJECT's own resolver — which
        already knows about modules, paths, symbols and seam literals — and the result is
        prefixed. Reimplementing it here would be a second truth about what a name means,
        and the first time the two diverged nobody would notice."""
        import locks as _locks

        label, sep, rest = target.partition(SEP)
        if not sep or label not in self._projects:
            return set(), (f"«{target}» must be «project{SEP}target». "
                           f"Projects: {', '.join(sorted(self._projects))}")
        ids, err = _locks._resolve(self._projects[label], rest)
        if err:
            return set(), err
        return {f"{label}{SEP}{i}" for i in ids}, None


def _symbol_at(project, loc: str) -> str | None:
    """The symbol CONTAINING a line. The innermost one wins: a call inside a nested method
    belongs to the method, not to the class wrapping it."""
    file, _, line = loc.partition(":")
    try:
        n = int(line)
    except ValueError:
        return None
    best, best_start = None, -1
    for sid, s in project.symbols.items():
        if s.file == file and s.line <= n <= s.end and s.line > best_start:
            best, best_start = sid, s.line
    return best


def build(configs: dict[str, str]) -> Weave:
    """`{label: path to the .toml}` → the weave. De-duplicates configs over the same tree."""
    loaded = {e: _config.load(r) for e, r in configs.items()}
    # The one that DECLARES THE MOST SEAMS wins, not the alphabetically first: that
    # criterion looked deterministic and was arbitrary — `hermes-prod` sorts before
    # `hermes` and won, so the variant without `[seams]` took over and the gateway ended
    # up with no junctions at all.
    chosen: dict[str, str] = {}
    for label in sorted(loaded, key=lambda e: (-len(loaded[e].seams), e)):
        chosen.setdefault(loaded[label].root, label)
    kept = {e: loaded[e] for e in sorted(chosen.values())}

    projects = {e: _factory.make_project(c) for e, c in kept.items()}
    weave = Weave(projects, kept)

    catalogs = {e: _seams.detect(p) for e, p in projects.items()}
    for consumer, cat in catalogs.items():
        for kind in CALL_KINDS:
            for literal, locs in cat.get("consumes", {}).get(kind, {}).items():
                for producer, other in catalogs.items():
                    if producer == consumer:
                        continue
                    sink = other.get("exports", {}).get(kind, {}).get(literal)
                    if not sink:
                        continue
                    for lc in locs:
                        a = _symbol_at(projects[consumer], lc)
                        if a is None:
                            continue
                        for ld in sink:
                            b = _symbol_at(projects[producer], ld)
                            if b is None:
                                continue
                            ia = f"{consumer}{SEP}{a}"
                            ib = f"{producer}{SEP}{b}"
                            weave.strong_edges[ia].add(ib)
                            weave.edges[ia].add(ib)
                            # Without a quota the other repo ends up with zero mass: the
                            # walker crosses the seam but carries nothing with it.
                            weave.weights[(ia, ib)] += 1.0
                            # The seam enters the call ORDER at its real line: the HTTP
                            # call happens where it is written, and in the sequence it has
                            # to appear between the calls surrounding it, not at the end.
                            weave.call_order[ia].append((int(lc.split(":")[1]), ib))
                            weave.applied_seams.append(
                                {"kind": kind, "literal": literal,
                                 "from": ia, "to": ib})
    return weave


def shared_resources(configs: dict[str, str]) -> list[dict]:
    """Tables and RPCs touched by two or more projects. They are not edges —nobody calls
    anybody— but they are coupling, and whoever reads the map has to know they exist."""
    loaded = {e: _config.load(r) for e, r in configs.items()}
    cats = {e: _seams.detect(_factory.make_project(c)) for e, c in loaded.items()}
    out = []
    for kind in ("table", "rpc"):
        by_literal: dict[str, set[str]] = defaultdict(set)
        for label, cat in cats.items():
            for literal in cat.get("touches", {}).get(kind, {}):
                by_literal[literal].add(label)
        out += [{"kind": kind, "literal": lit, "projects": sorted(q)}
                for lit, q in sorted(by_literal.items()) if len(q) > 1]
    return out
