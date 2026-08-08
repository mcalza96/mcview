"""mcview's analysis core — inventory, references and reachability.

Project-agnostic: EVERYTHING specific (what a root is, what gets excluded, where
the code lives) comes from `mcview.toml`. There is not a single framework name in
this file.

Design decisions, each one bought with a measurement:

* **The AST is parsed directly, with no external index.** A code index can have
  silent holes —calls that show up neither as resolved nor as unresolved— and a
  silent hole is indistinguishable from "unused". Measured against a real index:
  112,476 of our own edges vs 9,770 of theirs (11.5×).

* **Fail-open all the way down.** When in doubt, ALIVE. False "dead" is the failure
  mode that hurts: code in use gets deleted. False "alive" only costs a review.

* **"Alive" is not a boolean but a grade of evidence.** A symbol reachable only
  through a homonym, or only from a test, is not alive in the same way as one
  reachable from an HTTP route. Collapsing that into a boolean overestimated
  liveness by a factor of eight in the first project measured.
"""
from __future__ import annotations

import ast
import builtins
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field

BUILTINS = set(dir(builtins))

# What an attribute reference is worth against a name reference. It is a modelling
# choice, not a truth: raising it moves the map toward a flat count; lowering it
# trusts only the lexical binding.
ATTRIBUTE_WEIGHT = 0.25


# Methods of the builtin types. They are COMPUTED from the interpreter rather than
# written by hand: a written list ages with every Python version, and the one that
# matters is the version actually running.
BUILTIN_METHODS = frozenset(
    m for kind in (str, bytes, dict, list, set, frozenset, tuple, int, float, bool)
    for m in dir(kind) if not m.startswith("__"))


# ----------------------------------------------------------------- inventory
@dataclass
class Symbol:
    name: str
    kind: str          # function | class
    file: str          # relative to the project root
    line: int
    end: int
    id: str = field(init=False)

    def __post_init__(self):
        self.id = f"{self.file}:{self.line}:{self.name}"

    @property
    def loc(self) -> str:
        return f"{self.file}:{self.line}"


@dataclass
class FileFacts:
    """Everything a build derives from ONE file's text — and nothing else.

    The boundary is deliberate: no field here may depend on the config or on another file,
    because that is what makes an entry reusable across builds. The config is applied later
    (root reasons, product dirs) and the cross-file work — resolving names against
    `by_name` — is the ONLY part a warm rebuild pays. Measured on the reference backend:
    94% of construction time lives on this side of the line."""
    src: str
    tree: ast.AST
    symbols: list          # (name, kind, line, end) in walk order
    locales: dict          # (line, name) → names bound in that function's scope
    alias: dict            # alias → real name (aliased imports)
    branches: dict         # line → "cond#branch" mark, file-relative
    ref_sites: list        # (line, name, fuerza, lexico) in walk order
    decorators: dict       # (line, name) → decorator names, for every def/class


_MISS = object()          # cache sentinel: `None` is a legitimate value (a file that does not parse)


def _extract(src: str, tree: ast.AST) -> FileFacts:
    """One file's text → its facts. Pure on purpose: no config, no `self`, no other file."""
    # inventory
    symbols = [(n.name, "class" if isinstance(n, ast.ClassDef) else "function",
                n.lineno, getattr(n, "end_lineno", n.lineno))
               for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]

    # lexical scope per function. The enclosing functions' scope is INHERITED: if the outer
    # one binds `foo`, the inner one reading `foo` sees the closure, not the global. Without
    # inheritance, a nested function would re-fabricate the very edge the enclosing one
    # already avoided.
    locales: dict[tuple[int, str], set[str]] = {}

    def visit(node, heredados: set[str]):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own_names = heredados | _own_bound(child)
                locales[(child.lineno, child.name)] = own_names
                visit(child, own_names)
            else:
                # a class contributes no scope to its methods: a name bound in the class
                # body is NOT visible as a local inside a method.
                visit(child, heredados)

    visit(tree, set())

    # ALIASED IMPORTS, in their own pass and before collecting sites, because a use can
    # appear earlier in the walk than the import that explains it.
    #
    # `from x import iniciar as _iniciar_sonda` makes the call site read `_iniciar_sonda()`,
    # a name no symbol in the project carries — so the reference resolved to nothing and the
    # edge simply did not exist. It is not a homonym problem, it is the opposite: an alias is
    # an UNAMBIGUOUS binding to one real symbol, and it was being thrown away.
    # Measured on the reference project: 111 aliased imports and 324 uses of them.
    alias: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                if al.asname and al.asname != al.name:
                    alias[al.asname] = al.name.rsplit(".", 1)[-1]

    # which lines live in each branch of each conditional. The INNERMOST wins: a call
    # inside an `if` nested in a `try` belongs to the `if`. Only `If`, `Try` and `Match` —
    # those are the ones offering ALTERNATIVES. The body of a `for` or a `while` is not an
    # alternative: it is repetition, and counting it as a branch would say the system
    # chooses where it actually iterates.
    branches: dict[int, str] = {}

    def descend(node, mark):
        marked_children = {}
        if isinstance(node, ast.If):
            marked_children = {id(x): f"{node.lineno}#si" for x in node.body}
            marked_children.update({id(x): f"{node.lineno}#no" for x in node.orelse})
        elif isinstance(node, ast.Try):
            marked_children = {id(x): f"{node.lineno}#try" for x in node.body}
            for k, h in enumerate(node.handlers):
                marked_children.update({id(x): f"{node.lineno}#exc{k}" for x in h.body})
            marked_children.update({id(x): f"{node.lineno}#else" for x in node.orelse})
        elif isinstance(node, getattr(ast, "Match", ())):
            for k, caso in enumerate(getattr(node, "cases", [])):
                marked_children.update({id(x): f"{node.lineno}#caso{k}" for x in caso.body})
        for child in ast.iter_child_nodes(node):
            sub = marked_children.get(id(child), mark)
            if sub and getattr(child, "lineno", None):
                for ln in range(child.lineno, getattr(child, "end_lineno", child.lineno) + 1):
                    branches[ln] = sub
            descend(child, sub)

    descend(tree, None)

    # reference SITES and decorator names — what `_resolve` will judge later, once it can
    # see the whole project (`by_name`) and the config (root reasons)
    ref_sites: list[tuple[int, str, float, bool]] = []
    decorators: dict[tuple[int, str], list[str]] = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            decorators[(n.lineno, n.name)] = [
                _decorator_name(d) for d in getattr(n, "decorator_list", [])]

        # an import alias references the ORIGINAL name
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for al in n.names:
                ref_sites.append((n.lineno, al.name.rsplit(".", 1)[-1], 1.0, True))
            continue

        name, fuerza, lexico = None, 1.0, True
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            name = n.id
        elif isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Load):
            # `x.foo()` binds to the TYPE OF x at runtime, which we do not know;
            # `foo()` binds lexically. Weaker evidence, lower weight.
            name, fuerza, lexico = n.attr, ATTRIBUTE_WEIGHT, False
        if name and name not in BUILTINS:
            ref_sites.append((getattr(n, "lineno", 0), name, fuerza, lexico))

    return FileFacts(src, tree, symbols, locales, alias, branches, ref_sites, decorators)


@dataclass
class Fragment:
    """A block inside a function. It presents the SAME contract as `Symbol`
    —`file`, `name`, `line`, `loc`— so the consumers of duplicates do not have to know
    whether what reached them is a function or a block."""
    name: str
    file: str
    line: int
    kind: str = "block"

    @property
    def loc(self) -> str:
        return f"{self.file}:{self.line}"


# Control constructs whose body is an extractable unit. The value is the set of fields
# holding statement lists; a `try`'s `handlers` are walked separately because they are nodes,
# not statements.
_COMPUESTOS = {
    ast.If: (("body", "if"), ("orelse", "else")),
    ast.For: (("body", "for"), ("orelse", "for-else")),
    ast.AsyncFor: (("body", "for"), ("orelse", "for-else")),
    ast.While: (("body", "while"), ("orelse", "while-else")),
    ast.With: (("body", "with"),),
    ast.AsyncWith: (("body", "with"),),
    ast.Try: (("body", "try"), ("orelse", "try-else"), ("finalbody", "finally")),
    ast.ExceptHandler: (("body", "except"),),
}


def _nested_bodies(root):
    """(node, label, statements) for each control block inside `root`.

    An explicit walk and not `ast.walk`, because it has to PRUNE: on reaching a nested `def`
    or `class` it cuts. If it descended, the inner function's blocks would be emitted twice
    —once per ancestor— and a clone would be over-counted.
    """
    stack = list(root.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        campos = _COMPUESTOS.get(type(n))
        if not campos:
            continue
        for campo, label in campos:
            body = getattr(n, campo, None)
            if body:
                yield n, label, body
                stack.extend(body)
        stack.extend(getattr(n, "handlers", ()))


class _Anonymizer(ast.NodeTransformer):
    """Erases identity, keeps shape. For the structural fingerprint."""

    def visit_Name(self, n):
        return ast.copy_location(ast.Name(id="_", ctx=n.ctx), n)

    def visit_arg(self, n):
        n.arg, n.annotation = "_", None
        return n

    def visit_Attribute(self, n):
        self.generic_visit(n)
        n.attr = "_"
        return n

    def visit_Constant(self, n):
        return ast.copy_location(ast.Constant(value="_"), n)

    def visit_keyword(self, n):
        self.generic_visit(n)
        n.arg = "_"
        return n


def _bound_only_inside(fn) -> set[str]:
    """Names a comprehension or a lambda binds, whose EVERY read lies inside one of them.

    The cheap way to tell a throwaway loop variable from a name that also refers to something
    real in the same function. Line spans, not scopes: a comprehension is a single expression,
    so its span is exact and there is nothing to model.

    ALL the binders of a name at once, and that is the whole point. The first version asked
    "is it read outside THIS comprehension?", which is the same question asked once per
    comprehension — and a function with several of them defeats it, because the reads inside
    comprehension #2 are outside comprehension #1. Measured in this very file: `_mark_branches`
    has five dict comprehensions over `x`, so none of them bound it and every `x` resolved to a
    one-letter function in another layer, with the STRONGEST evidence the tool can give. The
    diagram showed `extraction` depending on `render`, which is how it was found.

    A name with no reads at all comes out bound: `all()` over nothing is true, and an unused
    target is exactly the throwaway case.
    """
    spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for n in ast.walk(fn):
        if not isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp,
                              ast.GeneratorExp, ast.Lambda)):
            continue                  # not every AST node carries a line (`arguments` does not)
        span = (n.lineno, getattr(n, "end_lineno", None) or n.lineno)
        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for g in n.generators:
                for t in ast.walk(g.target):
                    if isinstance(t, ast.Name):
                        spans[t.id].append(span)
        elif isinstance(n, ast.Lambda):
            a = n.args
            for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg):
                if x:
                    spans[x.arg].append(span)
    if not spans:
        return set()

    reads: dict[str, list[int]] = defaultdict(list)
    for x in ast.walk(fn):
        if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load) and x.id in spans:
            reads[x.id].append(x.lineno)
    return {name for name, sp in spans.items()
            if all(any(lo <= r <= hi for lo, hi in sp) for r in reads.get(name, ()))}


def _own_bound(node) -> set[str]:
    """Names a function binds IN ITS OWN scope.

    It does not descend into nested functions or classes: their bindings are theirs, not this
    one's. And it does NOT record their NAMES, even though `def inner()` binds `inner` in this
    scope: that binding IS the project's symbol, so a read of `inner` is a legitimate
    reference, not a shadow. Counting it killed 38 symbols by cascade —`_audit_slice` among
    them, the heart of the parallel audit, called from a comprehension on line 1303 of
    `audit_tools.py`— and the new-DEAD_CANDIDATE check caught it, not a manual review.

    Anything declared `global`/`nonlocal` is excluded: there the assignment does NOT create a
    local, and a read of that name really does refer to the outer symbol.

    Local `import`s are deliberately left OUT. `from x import foo` binds `foo`, but it binds
    it TO THE REAL SYMBOL — suppressing its uses would erase the true reference, which is the
    exact opposite of what this filter is after.
    """
    bound: set[str] = set()
    declared_outer: set[str] = set()
    # Computed ONCE for the whole function: the rule is about all the binders of a name
    # together, so asking it per-comprehension is what let the multi-comprehension case slip.
    inner_only = _bound_only_inside(node)
    a = node.args
    for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg):
        if x:
            bound.add(x.arg)

    stack = list(node.body)
    while stack:
        n = stack.pop()
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue                      # its interior is another scope; its name, a symbol
        if isinstance(n, ast.Lambda):
            # A lambda's parameters bind, and they were not registered — same class as the
            # comprehension case below and found the same way: `sorted(out, key=lambda x:
            # -x["fraccion"])` left `x` unbound, so every read of it resolved to whatever
            # one-letter symbol the project happened to define. Same conservative rule: bind
            # only when every read of the name is inside a binder of that same name.
            for a in n.args.args + n.args.posonlyargs + n.args.kwonlyargs:
                if a.arg in inner_only:
                    bound.add(a.arg)
            for extra in (n.args.vararg, n.args.kwarg):
                if extra and extra.arg in inner_only:
                    bound.add(extra.arg)
            stack.append(n.body)
            stack.extend(n.args.defaults)
            continue

        if isinstance(n, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):

            # A comprehension has ITS OWN SCOPE in py3, and that cuts both ways.
            #
            # Skipping the targets is right for the ENCLOSING function: `[x for x in …]` does
            # not make `x` local to it, so a read of `x` afterwards legitimately refers to the
            # outer symbol. Suppressing it would delete a real edge — the failure this filter's
            # other four rules exist to avoid.
            #
            # But INSIDE the comprehension the target IS bound, and not registering it
            # fabricated an edge carrying the strongest evidence there is: `[x for x in
            # node.body if isinstance(x, ...)]` resolved every `x` to a one-letter function
            # defined elsewhere in the project. Measured: 3 fabricated strong edges from one
            # comprehension variable.
            #
            # So the target is bound only when EVERY read of it falls inside a binder of the
            # same name. That
            # covers the real case (a throwaway loop variable) and leaves the ambiguous one
            # alone, which keeps the bias pointing at the false negative. A blanket binding was
            # tried first and `check_reach` rejected it: its fixture reads the name after the
            # comprehension, and that read is a legitimate reference.
            for g in n.generators:
                for t in ast.walk(g.target):
                    if isinstance(t, ast.Name) and t.id in inner_only:
                        bound.add(t.id)
            stack.extend(g.iter for g in n.generators)
            stack.extend(c for g in n.generators for c in g.ifs)
            stack.extend(x for x in (getattr(n, "elt", None), getattr(n, "key", None),
                                    getattr(n, "value", None)) if x is not None)
            continue
        if isinstance(n, (ast.Global, ast.Nonlocal)):
            declared_outer.update(n.names)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        stack.extend(ast.iter_child_nodes(n))
    return bound - declared_outer


def _decorator_name(d) -> str:
    t = d.func if isinstance(d, ast.Call) else d
    if isinstance(t, ast.Name):
        return t.id
    if isinstance(t, ast.Attribute):
        return f"{t.value.id}.{t.attr}" if isinstance(t.value, ast.Name) else t.attr
    return ""


class Project:
    """One analysed project. Building is cheap: sub-second on ~600 files."""

    def __init__(self, cfg, file_cache: dict | None = None):
        self.cfg = cfg
        # {rel: (mtime_ns, FileFacts | None)} owned by the CALLER (the MCP server's cache).
        # Facts are derived from one file's text alone — never from the config — so they
        # survive a config edit and die with the process: no state on disk, by design.
        self._file_cache = file_cache
        self.symbols: dict[str, Symbol] = {}
        self.by_file: dict[str, list[Symbol]] = defaultdict(list)
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.edges: dict[str, set[str]] = defaultdict(set)
        self.strong_edges: dict[str, set[str]] = defaultdict(set)
        # multiplicity: calling something from 20 places is not the same as from 1.
        # The heat map needs it; reachability does not.
        self.weights: dict[tuple[str, str], float] = defaultdict(float)
        # THE CALL ORDER, which until now was thrown away. `edges` is a `set`: it knows
        # that A calls B and C, not that B is called before C. A graph like that can answer
        # "where does it reach?" and NEVER "what happens first?" — and the second is the
        # question when you want to understand a turn, not a reach. The line already made it
        # to `_refer`; all that was needed was not to discard it.
        self.call_order: dict[str, list[tuple[int, str]]] = defaultdict(list)
        # IN WHICH BRANCH OF WHICH CONDITIONAL each line falls: "file:line" → "cond#i".
        # Without this, two consecutive calls look identical to two alternatives of an `if`,
        # and the reference split reads as if it were a decision. It is the same kind of
        # data as the line — it is in the tree and it was being thrown away.
        self.branches: dict[str, str] = {}
        self.roots: set[str] = set()
        self.product_roots: set[str] = set()
        self.reasons: dict[str, int] = defaultdict(int)
        # WHICH symbols are roots per reason, not just how many. The count was enough for
        # the report; to draw the dispatch you need to know which symbols a given decorator
        # registered — the agent chooses among THOSE, by name and not by call.
        self.roots_by_reason: dict[str, set[str]] = defaultdict(set)
        self.module_refs: dict[str, set[str]] = defaultdict(set)
        self.strong_module_refs: dict[str, set[str]] = defaultdict(set)
        self.sources: dict[str, str] = {}
        # symbol → names bound in its scope (its own + inherited from the enclosing ones).
        # A read of one of those names does NOT reference the project's homonymous symbol.
        self._locales: dict[str, set[str]] = {}
        # `{file_of: {alias: nombre_real}}` — ver `_analyze`.
        self._alias: dict[str, dict[str, str]] = {}
        self._arboles: dict[str, ast.AST] = {}
        self._build()
        # STEP 4 — THE DECLARED DOORS ARE ROOTS. It runs HERE and not inside `_build` because the TypeScript path overrides `_build`
        # entirely: the step lived in the Python one, so on a filesystem-routed frontend the
        # doors resolved, were reported as doors, and seeded nothing. `__init__` is the point
        # both parsers pass through. It needs the inventory:
        # a surface names symbols, and until step 1 finished there were none to name.
        #
        # Why it is worth its own step. A file listed in `dirs` makes EVERY symbol in it a
        # root, which is right for a directory loaded by name and wrong for an entry point:
        # measured on a gateway, eight entry FILES contributed 1,234 roots where the project's
        # own `[project.scripts]` declares eight `main`s. With everything an entrance there is
        # no "how do you get in", and the heat map ends up measuring the files you declared
        # instead of where a message arrives — its top three were the declared files
        # themselves, and became the three platform adapters once the doors were exact.
        #
        # Cost of the precision, measured on the same project: 8 symbols move to
        # DEAD_CANDIDATE, one of them a module-level `__getattr__` that Python calls itself.
        # They were alive because their FILE was a root, not because anything reaches them.
        self._seed_from_surfaces()

    # -- route ---------------------------------------------------------
    def _files(self):
        for dirpath, dirnames, filenames in os.walk(self.cfg.root):
            dirnames[:] = [d for d in dirnames if d not in self.cfg.ignored_dirs]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                abs_p = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_p, self.cfg.root)
                if self.cfg.excluded(rel):
                    continue
                yield abs_p, rel

    def _build(self):
        # step 1 — per-file FACTS: parse, inventory, lexical scope, branch marks and the
        # reference SITES. All of it derives from one file's text, so a warm cache entry
        # (same mtime) skips the whole step for that file.
        cache = self._file_cache
        facts_by_file: dict[str, FileFacts] = {}
        seen: set[str] = set()
        for abs_p, rel in self._files():
            seen.add(rel)
            facts, mt = _MISS, None
            if cache is not None:
                try:
                    mt = os.stat(abs_p).st_mtime_ns
                except OSError:
                    continue
                hit = cache.get(rel)
                if hit is not None and hit[0] == mt:
                    facts = hit[1]
            if facts is _MISS:
                try:
                    src = open(abs_p, encoding="utf-8").read()
                    facts = _extract(src, ast.parse(src))
                except (SyntaxError, UnicodeDecodeError, OSError):
                    # cached too: a file that does not parse today will not parse on the
                    # next call either, and re-reading it every build is silent waste
                    facts = None
                if cache is not None and mt is not None:
                    cache[rel] = (mt, facts)
            if facts is None:
                continue
            facts_by_file[rel] = facts

            # compose — cheap dict filling; the ids carry `rel`, which the facts do not know
            self.sources[rel] = facts.src
            self._arboles[rel] = facts.tree
            for name, kind, line, end in facts.symbols:
                s = Symbol(name, kind, rel, line, end)
                self.symbols[s.id] = s
                self.by_file[rel].append(s)
                self.by_name[name].append(s.id)
            for (line, name), bound in facts.locales.items():
                self._locales[f"{rel}:{line}:{name}"] = bound
            if facts.alias:
                self._alias[rel] = facts.alias
            for ln, mark in facts.branches.items():
                self.branches[f"{rel}:{ln}"] = mark
        if cache is not None:
            for rel in [r for r in cache if r not in seen]:
                del cache[rel]           # deleted or newly-excluded files must not linger

        for lst in self.by_file.values():
            lst.sort(key=lambda s: s.end - s.line)   # the tightest one first

        # step 2 — roots and name resolution: the ONLY cross-file work. It re-runs on every
        # build because editing one file can change `by_name` for all of them — a name that
        # was unambiguous may stop being so. Measured: 0.19 s of the 3.2 s build.
        for rel, facts in facts_by_file.items():
            self._resolve(rel, facts)


    def _seed_from_surfaces(self) -> None:
        """`[surfaces]` → roots. A door is a door whether or not it is also in `dirs`."""
        for name, objetivos in (getattr(self.cfg, "surfaces", {}) or {}).items():
            for t in objetivos:
                # `file.py:symbol` when the name is not unique — `main` exists once per
                # entry point, so naming it alone would seed all of them at once.
                from config import split_surface_target
                file_of, symbol = split_surface_target(t)
                ids = {sid for sid, s in self.symbols.items()
                       if s.name == symbol and (not file_of or s.file == file_of)}
                if not ids:
                    # A door is often a FILE — in a filesystem-routed framework that is the
                    # only way to name it, because every one of them is called `page.tsx`.
                    # Matching symbol names only made those declarations a silent no-op: they
                    # resolved, they were reported as doors, and they seeded nothing.
                    ids = {sid for sid, s in self.symbols.items() if s.file == t}
                if not ids:
                    continue
                self.roots |= ids
                self.product_roots |= ids
                self.reasons["surface"] += len(ids)
                self.roots_by_reason["surface"] |= ids

    def file_of(self, extremo: str) -> str:
        """The file of one end of an edge. An end is a symbol or —if the reference is at module
        level, which executes on import— the path of the file itself."""
        s = self.symbols.get(extremo)
        return s.file if s else extremo

    def _owner(self, rel: str, line: int) -> str | None:
        for s in self.by_file.get(rel, ()):
            if s.line <= line <= s.end:
                return s.id
        return None

    def _resolve(self, rel: str, facts: FileFacts):
        """The config-dependent and cross-file half of a file's analysis: root reasons
        (they read the config, so they must NOT be cached with the facts) and name
        resolution against the whole project's `by_name`."""
        is_root_module = self.cfg.is_root_dir(rel)
        index = {s.name: s.id for s in self.by_file[rel]}

        for (line, name), decs in facts.decorators.items():
            reason = None
            for d in decs:
                reason = self.cfg.root_reason(d)
                if reason:
                    break
            if reason is None and is_root_module:
                reason = "root_module"
            if reason and name in index:
                self.roots.add(index[name])
                self.reasons[reason] += 1
                self.roots_by_reason[reason].add(index[name])
                if reason != "root_module" or self.cfg.is_product_dir(rel):
                    self.product_roots.add(index[name])

        for line, name, fuerza, lexico in facts.ref_sites:
            self._refer(rel, line, name, fuerza, lexico)

    def _refer(self, rel: str, line: int, name: str, fuerza: float = 1.0,
                 lexico: bool = True):
        targets = self.by_name.get(name)
        if not targets:
            # The name may be an alias. Resolved AFTER the direct lookup on purpose: if a real
            # symbol carries the alias's name, that symbol wins — the alias is the fallback,
            # never an override, so this can only ADD edges that were missing and never divert
            # one that already resolved.
            real = self._alias.get(rel, {}).get(name)
            targets = self.by_name.get(real) if real else None
        if not targets:
            return                       # external symbol (stdlib, dependency)
        source = self._owner(rel, line)
        # SCOPE. A read of a LOCALLY BOUND name refers to the local, not to the project's
        # homonymous symbol. Without this, `docs_read = audit.get(...)` inside
        # `compute_quality_score` fabricated an edge toward the Google Docs tool — and since
        # `docs_read` is a unique name, it fabricated it with the STRONGEST evidence there is.
        # Measured before the fix: 502 of 8,001 strong edges (6.3%) were of this kind, and
        # `Evaluation`'s flow reported 166 roots where there are 20.
        # It only applies to LEXICAL references: in `x.docs_read` no local shadows the name.
        if lexico and source and name in self._locales.get(source, ()):
            return
        unambiguous = len(targets) == 1
        if source:
            self.edges[source].update(targets)
            # An ambiguous reference SPLITS 1 unit across the N homonyms; it does not
            # contribute 1 to each. Adding 1 per candidate REINFORCES ambiguity instead of
            # diluting it: `get` (10 homonyms) came to absorb 47% of the mass because every
            # dictionary `.get(...)` injected 10 units into it.
            cuota = fuerza / len(targets)
            for t in targets:
                self.weights[(source, t)] += cuota
            # `x.replace(...)` on a string binds to the TYPE's method, not to the single
            # project function with that name — but because it is unique, the edge came out
            # with the STRONGEST evidence there is. In hermes, `replace` exists exactly once
            # (`tools/memory_tool.py`) and every string `.replace()` pointed there; the turn's
            # sequence began with that step, and a narrative that starts with a false step
            # reads as a fact.
            #
            # It is DEMOTED to weak, not killed: if the project really does have a function
            # named `replace`, its real calls stay in the graph and in `ALIVE_PRODUCT_WEAK`.
            # Killing them by list would be over-suppressing, which is the failure mode this
            # module avoids in its other four scope rules.
            metodo_nativo = not lexico and name in BUILTIN_METHODS
            if unambiguous and not metodo_nativo:
                self.strong_edges[source].update(targets)
                self.call_order[source].append((line, next(iter(targets))))
        else:
            # module-level code: it EXECUTES on import
            self.module_refs[rel].update(targets)
            cuota = fuerza / len(targets)
            for t in targets:
                self.weights[(rel, t)] += cuota
            if unambiguous:
                self.strong_module_refs[rel].update(targets)

    # -- reachability ----------------------------------------------------
    def _close(self, seed, edges) -> set[str]:
        seen, queue = set(seed), deque(seed)
        while queue:
            for t in edges.get(queue.popleft(), ()):
                if t not in seen:
                    seen.add(t)
                    queue.append(t)
        return {s for s in seen if s in self.symbols}

    def _by_containment(self, alive: set[str]) -> set[str]:
        """Nested inside something alive → alive. Closures and callbacks are passed by
        reference, never called by name."""
        alive = set(alive)
        changed = True
        while changed:
            changed = False
            for rel, lst in self.by_file.items():
                spans = [(s.line, s.end) for s in lst if s.id in alive]
                for s in lst:
                    if s.id in alive:
                        continue
                    if any(a < s.line and s.end <= b for a, b in spans):
                        alive.add(s.id)
                        changed = True
        return alive

    def _alive_fixpoint(self, seed) -> set[str]:
        """`_close` and `_by_containment` ALTERNATE until nothing grows. One pass of each is
        not enough: a method is alive only by nesting inside its class, and the module-level
        helper that ONLY that method calls needs the closure to run again after nesting spoke.
        Measured on mcview itself: the single pass left 9 of 14 DEAD_CANDIDATE falsely dead,
        every one of them exactly this shape."""
        alive = self._close(seed, self.edges)
        while True:
            grown = self._close(self._by_containment(alive), self.edges)
            if grown == alive:
                return grown
            alive = grown

    def levels(self) -> dict[str, set[str]]:
        todas = set(self.module_refs)
        seed = set(self.roots) | {t for r in todas for t in self.module_refs[r]}

        seed_product = set(self.product_roots)
        for rel in {self.symbols[r].file for r in self.product_roots}:
            seed_product |= self.module_refs.get(rel, set())

        seed_strong = set(self.roots) | {
            t for r in self.strong_module_refs for t in self.strong_module_refs[r]}

        reachable = self._alive_fixpoint(seed)
        no_containment = self._close(seed, self.edges)
        product = self._alive_fixpoint(seed_product)
        strong = self._close(seed_strong, self.strong_edges)

        dead = set(self.symbols) - reachable
        return {
            "ALIVE_PRODUCT": product & strong,
            "ALIVE_PRODUCT_WEAK": product - strong,
            "ALIVE_NOT_PRODUCT": reachable - product,
            "ALIVE_BY_NESTING": reachable - no_containment,
            "DEAD_CANDIDATE": dead,
        }

    # -- structural fingerprint (for duplicates) --------------------------------
    def _fingerprint(self, body: list, min_statements: int) -> str | None:
        """A list of statements → an anonymised shape. The unit does not matter: it works
        the same for a function's body as for an `except`'s."""
        body = [x for x in body
                  if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
        if len(body) < min_statements:
            return None
        try:
            copia = ast.parse(ast.unparse(ast.Module(body=body, type_ignores=[])))
        except (SyntaxError, ValueError, RecursionError):
            return None
        return ast.dump(_Anonymizer().visit(copia), annotate_fields=False)

    def _def_of(self, s: Symbol):
        tree = self._arboles.get(s.file)
        if tree is None:
            return None
        for n in ast.walk(tree):
            if (isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.lineno == s.line and n.name == s.name):
                return n
        return None

    def skeleton(self, s: Symbol, min_statements: int) -> str | None:
        n = self._def_of(s)
        return self._fingerprint(n.body, min_statements) if n else None

    def blocks(self, s: Symbol, min_statements: int) -> list[tuple[int, str, str]]:
        """The fingerprints of the NESTED blocks inside a function.

        Comparing only function bodies leaves the tool blind to the duplication nobody has
        extracted yet — which is precisely the worst kind. Measured in CIRE's ingestion
        subsystem: the same error-translation pattern lived in 13 places and the detector saw
        2, exactly the 2 somebody had already bothered to pull into their own function.

        THE UNIT IS THE BODY OF A CONTROL CONSTRUCT, not an arbitrary window of statements. An
        `if`, an `except`, a `for`: blocks the author already delimited. With windows, a
        function of N statements produces O(N²) candidates and most correspond to no unit
        anybody could extract; with this, the finding always names something that exists.

        It does not descend into nested functions: each `def` is its own symbol and its blocks
        are emitted when its turn comes, not twice.
        """
        root = self._def_of(s)
        if root is None:
            return []
        out = []
        for node, label, body in _nested_bodies(root):
            h = self._fingerprint(body, min_statements)
            # the function's whole body is already covered by `skeleton()`
            if h and body is not root.body:
                out.append((getattr(node, "lineno", s.line), label, h))
        return out
