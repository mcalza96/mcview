# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""TypeScript/TSX parser. It produces THE SAME graph as `core.Project`, nothing more.

Why a subclass and not an `if language == ...` inside the core: the Python path is measured
and in use, and a shared branch puts it at risk every time the new side is touched. Here
`TSProject` only replaces **how the graph gets filled** —the symbol inventory, the references
and the roots—; everything downstream (`levels`, the heat map, MCL, the islands, the diff)
operates over those same structures and does not know which language they came from.
`core.py` is never edited: the guarantee that Python did not move is structural, not a test
somebody has to remember to run.

The price of that decision: `skeleton()` does have to be reimplemented, because anonymizing a
body to compare duplicates depends on the concrete tree. It is the only shared method that
was not agnostic.

**A real parser, not regexes.** A census of exports by regular expressions written to
evaluate this same frontend accumulated four defects in an hour —it absolved 28% of the
exports for appearing inside any string, declared every App Router page dead, lost the name
in `import X from`, and did not normalize paths—, and all four moved the result by dozens of
symbols. tree-sitter eliminates that entire class.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import core as _nucleo
from core import Project, Symbol

EXTENSIONES = (".ts", ".tsx", ".mts", ".cts")

# The App Router loads these files BY NAME: there is never an import pointing at them.
# In Python the roots had to be hunted (decorators, routes) and one escaped that only turned
# up with a runtime probe; here the framework declares them, so the walker starts exactly
# where a request comes in.
ARCHIVOS_RAIZ = frozenset({
    "page.tsx", "layout.tsx", "route.ts", "route.tsx", "template.tsx", "default.tsx",
    "loading.tsx", "error.tsx", "not-found.tsx", "global-error.tsx", "middleware.ts",
    "instrumentation.ts", "sitemap.ts", "robots.ts", "manifest.ts", "opengraph-image.tsx",
    "icon.tsx", "apple-icon.tsx", "not-found.ts",
})
# Names the framework invokes inside those files.
NOMBRES_RAIZ = frozenset({
    "default", "metadata", "generateMetadata", "generateStaticParams", "generateViewport",
    "viewport", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS",
})

_DECLARAN = {
    "function_declaration": "function", "generator_function_declaration": "function",
    "class_declaration": "class", "abstract_class_declaration": "class",
    "interface_declaration": "type", "type_alias_declaration": "type",
    "enum_declaration": "type",
}
# `const useFoo = () => {}` / `const Panel = memo(...)`: the declaration is a variable, but
# for the graph it is a symbol just like a function. Without this you lose most of the
# components and hooks of a modern React project.
_VARIABLE = "variable_declarator"


@dataclass
class _Parser:
    """Wraps tree-sitter so the bootstrap and the missing-import handling are not repeated."""

    language: object
    parser: object

    @classmethod
    def create(cls):
        try:
            import tree_sitter as ts
            import tree_sitter_typescript as tst
        except ImportError as e:                      # optional dependency: the Python side does not need it
            raise SystemExit(
                "The TypeScript parser is missing. Install it with:\n"
                "    pip install tree_sitter tree_sitter_typescript\n"
                f"({e})"
            ) from e
        # tsx accepts TS without JSX too, so a single parser covers .ts and .tsx.
        leng = ts.Language(tst.language_tsx())
        return cls(leng, ts.Parser(leng))

    def tree(self, src: bytes):
        return self.parser.parse(src)


def _text(n) -> str:
    return n.text.decode("utf-8", "replace")


def _declared_name(n) -> str | None:
    """The identifier this node declares, if it declares one."""
    campo = n.child_by_field_name("name")
    return _text(campo) if campo is not None else None


# Calls that WRAP a function and return a function: the result is still a unit of code. The
# list is explicit on purpose. The previous rule was structural —"any call receiving a
# function"— and sounded more general, but `list.find(u => …)` and `setInterval(() => …)`
# also receive a function and return DATA. Measured over the frontend: it captured 3 real
# wrappers and admitted 244 false ones, 19% of the symbols, which absorbed 40% of the heat
# map's mass.
_WRAP_FUNCTION = frozenset({
    # React and its ecosystem
    "memo", "forwardRef", "lazy", "dynamic", "cache", "useCallback",
    # Classic HOCs, absent from CIRE but standard — the tool is portable
    "styled", "observer", "connect", "withRouter", "withStyles",
})
# Deliberadamente FUERA: `useMemo` (devuelve cualquier cosa), `useRef`, `setTimeout`,
# `setInterval` and every array method. They receive a function; they do not return one.


def _is_functional(n) -> bool:
    """Is this variable's value a function/component rather than data?

    Only the former count as symbols: counting every configuration constant as a graph node
    inflates the denominator and dilutes the heat map without adding signal."""
    v = n.child_by_field_name("value")
    if v is None:
        return False
    if v.type in ("arrow_function", "function_expression", "function"):
        return True
    if v.type == "call_expression":
        fn = v.child_by_field_name("function")
        if fn is None:
            return False
        # `React.memo(...)` and `memo(...)` are the same: only the last segment matters.
        if _text(fn).split(".")[-1] not in _WRAP_FUNCTION:
            return False
        args = v.child_by_field_name("arguments")
        return bool(args and any(
            h.type in ("arrow_function", "function_expression", "function", "identifier")
            for h in args.children))
    return False


class TSProject(Project):
    """Same contract as `Project`, with the graph built from TypeScript."""

    def _files(self):
        for dirpath, dirnames, filenames in os.walk(self.cfg.root):
            dirnames[:] = [d for d in dirnames if d not in self.cfg.ignored_dirs]
            for fn in filenames:
                if not fn.endswith(EXTENSIONES) or fn.endswith(".d.ts"):
                    continue
                abs_p = os.path.join(dirpath, fn)
                rel = os.path.relpath(abs_p, self.cfg.root)
                if self.cfg.excluded(rel):
                    continue
                yield abs_p, rel

    # -- graph construction ------------------------------------------------
    def _build(self):
        self._parser = _Parser.create()
        self._raices_ts: dict[str, object] = {}

        # step 1 — inventario
        for abs_p, rel in self._files():
            try:
                src = open(abs_p, "rb").read()
            except OSError:
                continue
            tree = self._parser.tree(src)
            self.sources[rel] = src.decode("utf-8", "replace")
            self._raices_ts[rel] = tree.root_node
            for n in _recorrer(tree.root_node):
                name = kind = None
                if n.type in _DECLARAN:
                    name, kind = _declared_name(n), _DECLARAN[n.type]
                elif n.type == _VARIABLE and _is_functional(n):
                    name, kind = _declared_name(n), "function"
                if not name:
                    continue
                s = Symbol(name, kind, rel,
                            n.start_point[0] + 1, n.end_point[0] + 1)
                self.symbols[s.id] = s
                self.by_file[rel].append(s)
                self.by_name[s.name].append(s.id)

        for lst in self.by_file.values():
            lst.sort(key=lambda s: s.end - s.line)   # the tightest one first

        # step 2 — lexical scope (same as the Python side: needed BEFORE referring)
        for rel, root in self._raices_ts.items():
            self._map_reach_ts(rel, root)

        # step 3 — roots and references
        for rel, root in self._raices_ts.items():
            self._analyze_ts(rel, root)

    def _map_reach_ts(self, rel: str, root):
        """symbol → names bound in its scope, inheriting those of whatever contains it.

        Inheritance is resolved by LINE CONTAINMENT and not by the tree: a React component's
        symbol is the `variable_declarator`, and its inner handler is another
        `variable_declarator` inside it — the parent/child relation in the tree-sitter tree
        has several intermediate nodes, while the lines give it directly and are already
        computed.
        """
        por_nodo: dict[tuple[int, str], object] = {}
        for n in _recorrer(root):
            if n.type in _DECLARAN or (n.type == _VARIABLE and _is_functional(n)):
                name = _declared_name(n)
                if name:
                    por_nodo[(n.start_point[0] + 1, name)] = n

        symbols = self.by_file.get(rel, [])
        own_names: dict[str, set[str]] = {}
        for s in symbols:
            n = por_nodo.get((s.line, s.name))
            own_names[s.id] = _ts_bound(_reach_of(n)) if n is not None else set()

        for s in symbols:
            inherited = set(own_names[s.id])
            for other in symbols:
                if other.id != s.id and other.line < s.line and s.end <= other.end:
                    inherited |= own_names[other.id]
            if inherited:
                self._locales[s.id] = inherited

    def _analyze_ts(self, rel: str, root):
        base = os.path.basename(rel)
        is_entry = base in ARCHIVOS_RAIZ
        is_root_dir = self.cfg.is_root_dir(rel)
        index = {s.name: s.id for s in self.by_file[rel]}

        for n in _recorrer(root):
            # --- roots: what the framework invokes by convention -----------
            if is_entry and n.type in ("export_statement",):
                for name in _exported(n):
                    sid = index.get(name)
                    if sid and (name in NOMBRES_RAIZ or _is_default(n)):
                        self.roots.add(sid)
                        self.product_roots.add(sid)
                        self.reasons["convencion_next"] += 1
                    elif sid and is_entry:
                        # an export with its own name in an entry file
                        # (`export default function PaginaX`) tambien lo carga el framework
                        self.roots.add(sid)
                        self.product_roots.add(sid)
                        self.reasons["convencion_next"] += 1

            # --- referencias ------------------------------------------------
            if n.type == "identifier":
                if n.parent is not None and n.parent.type in _DECLARAN:
                    continue                          # its own declaration
                self._refer(rel, n.start_point[0] + 1, _text(n))
            elif n.type in ("type_identifier", "nested_type_identifier"):
                # `function f(x: Foo): Bar` — in TS half the graph is annotations, and the
                # parser labels them differently from a plain identifier. Without this branch,
                # EVERY type used only as an annotation shows up dead: it was 60% of the
                # candidates in the first run, types used two lines below included.
                if n.parent is None or n.parent.type not in _DECLARAN:
                    self._refer(rel, n.start_point[0] + 1, _text(n))
            elif n.type == "property_identifier":
                # `x.foo()` — bound to the type at runtime, worth less than a lexical name.
                # `lexico=False`: a local does NOT shadow an attribute. Without this, the
                # scope filter would erase `obj.foo` because the function declares a
                # `const foo`.
                self._refer(rel, n.start_point[0] + 1, _text(n),
                              fuerza=_nucleo.ATTRIBUTE_WEIGHT, lexico=False)
            elif n.type == "shorthand_property_identifier":
                # `export const Filters = { Bar, Input, Select }` — object shorthand is a
                # REFERENCE, but the parser gives it a node type of its own. Without this
                # branch, a namespace built that way leaves all of its members dead: measured,
                # 4 of the frontend's 45 candidates were this, and deleting them broke the
                # build. The third missing TS reference class, after the annotations.
                self._refer(rel, n.start_point[0] + 1, _text(n))
            elif n.type in ("jsx_opening_element", "jsx_self_closing_element"):
                nm = n.child_by_field_name("name")
                if nm is not None:
                    self._refer(rel, n.start_point[0] + 1, _text(nm))

        # a file in a root directory declared in the .toml drags its modules along,
        # same as on the Python side (identical `module_refs` semantics).
        if is_root_dir or is_entry:
            self.reasons["root_module"] += len(self.by_file[rel])
            for s in self.by_file[rel]:
                self.roots.add(s.id)
                if is_entry:
                    self.product_roots.add(s.id)

    # -- fingerprint estructural ------------------------------------------------
    def skeleton(self, s: Symbol, min_statements: int) -> str | None:
        """The body's shape with the names erased, to compare duplicates.

        The Python version re-parses and anonymizes the AST; here the sequence of node TYPES
        in the body is enough: two functions with the same skeleton produce the same
        sequence, and identifiers —which are what has to be ignored— contribute no
        distinguishable type of their own. It is coarser than the Python equivalent, so it
        **detects less, never more**: a pair showing up here really is similar."""
        root = self._raices_ts.get(s.file)
        if root is None:
            return None
        for n in _recorrer(root):
            if n.start_point[0] + 1 != s.line or _declared_name(n) != s.name:
                continue
            body = n.child_by_field_name("body")
            if body is None and n.type == _VARIABLE:
                v = n.child_by_field_name("value")
                body = v.child_by_field_name("body") if v is not None else None
            if body is None:
                return None
            piezas = [h.type for h in body.children if h.is_named]
            if len(piezas) < min_statements:
                return None
            return "|".join(_shape(h) for h in body.children if h.is_named)
        return None


def _shape(n, prof: int = 0) -> str:
    """Nested node types down to a fixed depth. Without a cap, two long and different
    functions share a prefix and the hash stops discriminating."""
    if prof >= 3 or not n.is_named:
        return n.type
    children = [h for h in n.children if h.is_named]
    return n.type + ("(" + ",".join(_shape(h, prof + 1) for h in children) + ")" if children else "")


# Nodes that open a scope of THEIR OWN: on reaching one, its bindings no longer belong to
# the function being measured. `class_body` is included because a method body is another scope.
_OTRO_ALCANCE = frozenset({
    "function_declaration", "generator_function_declaration", "function_expression",
    "generator_function", "arrow_function", "function", "method_definition",
    "class_declaration", "abstract_class_declaration", "class_body",
})

# Where the name a node BINDS lives. The value is the field to hang the search off; inside
# there may be a loose identifier or a destructuring pattern.
_LIGAN = {
    "variable_declarator": "name",
    "required_parameter": "pattern",
    "optional_parameter": "pattern",
    "catch_clause": "parameter",
    "for_in_statement": "left",
}
# Identifiers that, inside a pattern, ARE the bound name.
_ID_PATRON = frozenset({"identifier", "shorthand_property_identifier_pattern"})


def _names_of_pattern(n) -> set[str]:
    """`const {a, b: {c}} = x` / `([p, ...q]) => …` → {a, c, p, q}."""
    out = set()
    for x in _recorrer(n):
        if x.type in _ID_PATRON:
            out.add(_text(x))
    return out


def _ts_bound(root) -> set[str]:
    """Names this scope binds: parameters, `const`/`let`/`var`, `catch`, `for-in`.

    It does NOT descend into nested functions or classes. And it does NOT record a nested
    function's name, for the same reason measured on the Python side: that binding IS the
    project's symbol, so referencing it is legitimate — counting it as a shadow kills live
    symbols by cascade.

    `import`s are left out: they bind the name TO THE REAL SYMBOL, and suppressing them would
    erase the
    referencia verdadera.

    DECLARED APPROXIMATION: in TS/JS `let`/`const` are BLOCK-scoped and this treats them as
    function-scoped. A `const x` inside an `if` should not shadow a global `x` used in another
    branch of the same function. The suppression-conservative option was chosen and verified
    through the only path that matters: how many LIVE symbols turn dead. If that number stops
    being zero, block scope is the next step.
    """
    out: set[str] = set()
    stack = list(root.children)
    while stack:
        n = stack.pop()
        if n.type in _OTRO_ALCANCE:
            continue
        if n.type == _VARIABLE and _is_functional(n):
            # `const Panel = () => {}` is the normal way to declare a component or a
            # handler: it IS a project symbol, just like a nested `def` in Python.
            # Counting it as a shadow erases the real references and kills it by cascade —
            # measured here: `handleAction` and `getCookie` came out dead while being called
            # su propio file.
            stack.extend(n.children)
            continue
        campo = _LIGAN.get(n.type)
        if campo:
            target = n.child_by_field_name(campo)
            if target is not None:
                out |= _names_of_pattern(target)
        stack.extend(n.children)
    return out


def _reach_of(node):
    """The subtree that IS a symbol's scope.

    For `function f() {…}` it is the whole node. For `const Panel = () => {…}` —the normal
    shape of a React component— the scope lives INSIDE the arrow, and the symbol's node is
    the `variable_declarator`: without this hop, the component's parameters and constants
    would not be seen.
    """
    if node.type == _VARIABLE:
        v = node.child_by_field_name("value")
        if v is not None and v.type in _OTRO_ALCANCE:
            return v
    return node


def _recorrer(n):
    stack = [n]
    while stack:
        x = stack.pop()
        yield x
        stack.extend(reversed(x.children))


def _is_default(n) -> bool:
    return any(h.type == "default" for h in n.children)


def _exported(n) -> list[str]:
    out = []
    for h in _recorrer(n):
        if h.type in _DECLARAN or (h.type == _VARIABLE):
            nm = _declared_name(h)
            if nm:
                out.append(nm)
        elif h.type == "export_specifier":
            nm = h.child_by_field_name("name")
            if nm is not None:
                out.append(_text(nm))
    return out
