# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""THE SEAM BETWEEN PROJECTS IS MADE OF STRINGS, NOT SYMBOLS.

The rest of the tool resolves BY NAME inside a project. Between projects that does not
exist: the gateway does not import a backend function, it hits
`/api/v1/internal/turn-sources` and asks for the `retrieval__query` tool. The backend
imports nothing from Supabase, it writes to `platform_access_grants`. The edge crosses as a
LITERAL.

Measured, and that is why this module exists: a session investigating a user's Telegram
access went blind twice with the tool and had to fall back to `grep` —
`platform_access_grants` is a table and `telegram` a crosscutting concept, and neither is a
symbol.

FOUR KINDS, AND THEY ARE NOT WORTH THE SAME
--------------------------------------------
    tool    `name="retrieval__query"`   an exact identifier — the consumer writes that same
    table   `.table("x")`               exact
    rpc     `.rpc("y")`                 exact
    path    `@router.get("/{id}/ast")`  exact AFTER rebuilding the mounting chain

The path was the hard case: what the decorator writes is a fragment, and the real path is
assembled across three different files (`APIRouter(prefix=…)` + the
`include_router(…, prefix=…)` of whoever mounts it + the literal). `route_prefixes` follows
that chain through the imports —subpackages included— and reconstructs the backend's 158
paths with their full prefix, verified against five known paths. Without that, the join
returned zero, and zero reads exactly like "there is no relation".

DETECTORS ARE DECLARED, NOT GUESSED
------------------------------------
Like the roots. `.table(…)` is Supabase; another project will use `session.query(…)` or
`db.collection(…)`. With no `[seams]` in the `.toml`, this module returns nothing and breaks
nothing — the same fail-open criterion as the rest: when in doubt, silence, not invention.
"""
from __future__ import annotations

import ast
import os
from collections import defaultdict


def _literal(node) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _kwarg(call, name: str) -> str | None:
    for k in call.keywords:
        if k.arg == name:
            return _literal(k.value)
    return None


def _module_to_file(project, module: str, src: str, level: int) -> str | None:
    """`api.v1.routers.documents` → `api/v1/routers/documents.py`, relative ones too.

    A relative import (`from .ingestion_ops import …`) resolves against the package of the
    file writing it, walking up `level-1` directories.
    """
    if level:
        base = src.rsplit("/", 1)[0] if "/" in src else ""
        for _ in range(level - 1):
            base = base.rsplit("/", 1)[0] if "/" in base else ""
        parts = [p for p in (base, (module or "").replace(".", "/")) if p]
        cand = "/".join(parts)
    else:
        cand = (module or "").replace(".", "/")
    for suf in (".py", "/__init__.py"):
        if cand + suf in project.by_file or cand + suf in getattr(project, "_arboles", {}):
            return cand + suf
    return None


def route_prefixes(project) -> dict[tuple[str, str], str]:
    """(file, router variable) → the FULL prefix its paths end up mounted under.

    An endpoint's real path is assembled in three segments across three different files:

        v1_router = APIRouter(prefix="/api/v1")            api_router.py
        v1_router.include_router(ops, prefix="/ingestion") api_router.py
        @router.post("/{id}/reingest")                     ingestion_ops.py

    Rebuilding it requires following the `include_router` chain through the imports. Without
    this, what was exported was a fragment (`/{id}/reingest`) and could not be joined with
    what the consumer writes (`/api/v1/ingestion/…`): the join returned zero, and zero reads
    exactly like "there is no relation".

    Fail-open, like everything else: a router that does not resolve keeps its own prefix
    instead of disappearing. One segment short produces a weak candidate; inventing a
    segment would produce a false edge.
    """
    arboles = getattr(project, "_arboles", {})
    propio: dict[tuple[str, str], str] = {}
    alias: dict[tuple[str, str], tuple[str, str]] = {}      # (arch, alias) → (arch_origen, var)
    modules: dict[tuple[str, str], str] = {}                # (file, alias) → module file
    incluye: list[tuple[tuple[str, str], object, str]] = []

    for rel, tree in arboles.items():
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                    and getattr(n.value.func, "id", None) in ("APIRouter", "FastAPI"):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        propio[(rel, t.id)] = _kwarg(n.value, "prefix") or ""
            elif isinstance(n, ast.ImportFrom):
                target_node = _module_to_file(project, n.module, rel, n.level or 0)
                if not target_node:
                    continue
                for a in n.names:
                    # `from api.v1.routers import ingestion` imports a SUBPACKAGE, not a
                    # name: it has to point at its `__init__.py`, not the parent's. Without
                    # this hop, `ingestion/`'s 37 paths were left with no prefix.
                    sub = _module_to_file(
                        project, f"{n.module}.{a.name}" if n.module else a.name, rel,
                        n.level or 0)
                    if sub:
                        modules[(rel, a.asname or a.name)] = sub
                    else:
                        alias[(rel, a.asname or a.name)] = (target_node, a.name)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    d = _module_to_file(project, a.name, rel, 0)
                    if d:
                        modules[(rel, a.asname or a.name.split(".")[-1])] = d
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr == "include_router" and n.args:
                parent = getattr(n.func.value, "id", None)
                if parent:
                    incluye.append(((rel, parent), n.args[0], _kwarg(n, "prefix") or ""))

    def _resolve(rel: str, node) -> tuple[str, str] | None:
        """The `include_router(X)`: X can be an imported alias or `module.attribute`."""
        if isinstance(node, ast.Name):
            target_node = alias.get((rel, node.id))
            return target_node if target_node else (rel, node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            arch_mod = modules.get((rel, node.value.id))
            if arch_mod is None:
                d = alias.get((rel, node.value.id))
                arch_mod = d[0] if d else None
            if arch_mod:
                # the module may re-export: `from .ops import router as ingestion_ops`
                return alias.get((arch_mod, node.attr), (arch_mod, node.attr))
        return None

    children: dict[tuple[str, str], list[tuple[tuple[str, str], str]]] = defaultdict(list)
    with_parent = set()
    for parent, node, extra in incluye:
        child = _resolve(parent[0], node)
        if child:
            children[parent].append((child, extra))
            with_parent.add(child)

    # The root is `app = FastAPI()`, not an APIRouter: starting only from routers with no
    # parent would orphan `v1_router` —`app` includes it— and the whole chain would fall
    # back to its own prefix. Root = a node whose parent is not in the mapping.
    parent_of = {h: p for p, hs in children.items() for h, _ in hs}
    completo: dict[tuple[str, str], str] = {}
    roots = [k for k in propio if parent_of.get(k) not in propio]
    pendientes = [(r, propio.get(r, "")) for r in roots]
    seen = set()
    while pendientes:
        node, prefijo = pendientes.pop()
        if node in seen:
            continue
        seen.add(node)
        completo[node] = prefijo
        for child, extra in children.get(node, ()):
            pendientes.append((child, prefijo + extra + propio.get(child, "")))
    for k, v in propio.items():
        completo.setdefault(k, v)                    # fail-open: at least its own prefix
    return completo


def _is_product(project, rel: str) -> bool:
    from heatmap import _is_product as _p
    return _p(project, rel) and not rel.startswith(("tests/", "test/", "scripts/"))


def detect(project) -> dict:
    """The literals this project EXPORTS and those it CONSUMES or TOUCHES.

    It dispatches by language: the TypeScript side has its own shapes —templates instead of
    plain strings, paths by filesystem convention— and lives in `detect_ts`.

    Returns, per kind, `{literal: [locs]}`. A literal can be touched from many places —
    knowing how many and which ones is exactly what answers "who writes this table?".
    """
    cfg = project.cfg
    c = getattr(cfg, "seams", {}) or {}
    if not c:
        return {"exports": {}, "touches": {}, "consumes": {}, "declarado": False}
    if getattr(cfg, "language", "python") == "typescript":
        return detect_ts(project)

    tools = set(c.get("exports_tool", ()))
    route_objects = set(c.get("exports_route", ()))
    metodos = {m: kind for kind, ms in (("table", c.get("touches_table", ())),
                                        ("rpc", c.get("touches_rpc", ())))
               for m in ms}
    prefijos_consumo = tuple(c.get("consumes_route", ()))
    # A foreign identifier does not always carry a prefix: an MCP tool's name
    # (`retrieval__query`) is only recognizable by its shape. Hence, besides prefixes, there
    # are patterns, declared like everything else.
    import re as _re
    patrones_consumo = [(_re.compile(p), kind)
                        for kind, ps in (("tool", c.get("consumes_tool", ())),)
                        for p in ps]

    # A literal used ONLY from tests does not prove a production relation between projects.
    # Measured: of 52 uses of CIRE tools inside hermes, 10 are production and 42 are its
    # test suite. Counting them all exaggerates the seam by 5×.
    en_producto: set[tuple[str, str]] = set()
    solo_prueba: set[tuple[str, str]] = set()
    exporta: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    toca: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    consume: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    prefijos_completos = route_prefixes(project)

    for rel, tree in getattr(project, "_arboles", {}).items():
        for n in ast.walk(tree):
            # --- what is EXPORTED: registration decorators ------------------
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for d in n.decorator_list:
                    if not isinstance(d, ast.Call):
                        continue
                    f = d.func
                    if isinstance(f, ast.Name) and f.id in tools:
                        name = _kwarg(d, "name")
                        if name:
                            exporta["tool"][name].append(f"{rel}:{n.lineno}")
                            if not _is_product(project, rel):
                                solo_prueba.add(("tool", name))
                    elif (isinstance(f, ast.Attribute)
                          and getattr(f.value, "id", None) in route_objects
                          and d.args):
                        path = _literal(d.args[0])
                        if path is not None:
                            var = getattr(f.value, "id", "")
                            entera = prefijos_completos.get((rel, var), "") + path
                            exporta["path"][entera or "/"].append(f"{rel}:{n.lineno}")
            # --- what is TOUCHED: data access methods -----------------------
            elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                kind = metodos.get(n.func.attr)
                if kind and n.args:
                    lit = _literal(n.args[0])
                    if lit:
                        toca[kind][lit].append(f"{rel}:{n.lineno}")
            # --- what is CONSUMED: foreign paths written as a literal -------
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                loc = f"{rel}:{getattr(n, 'lineno', 0)}"
                if prefijos_consumo and n.value.startswith(prefijos_consumo):
                    consume["path"][n.value].append(loc)
                    if _is_product(project, rel):
                        en_producto.add(("path", n.value))
                else:
                    for rx, kind in patrones_consumo:
                        if rx.match(n.value):
                            consume[kind][n.value].append(loc)
                            if _is_product(project, rel):
                                en_producto.add((kind, n.value))
                            break

    aplanar = lambda d: {k: dict(v) for k, v in d.items()}
    return {"exports": aplanar(exporta), "touches": aplanar(toca),
            "consumes": aplanar(consume), "declarado": True,
            "in_product": sorted(en_producto)}


def search(catalog: dict, literal: str) -> list[tuple[str, str, list]]:
    """Where a literal appears, on any of the three sides.

    It is what turns `--orient platform_access_grants` from "did not resolve" into an
    answer: the target is not a symbol, it is a resource, and what you want to know is who
    touches it.
    """
    out = []
    for side in ("exports", "touches", "consumes"):
        for kind, mapping in catalog.get(side, {}).items():
            for lit, locs in mapping.items():
                if lit == literal or literal in lit:
                    out.append((side, kind, sorted(locs)))
    return out


def print_rows(catalog: dict, project_name: str, top: int = 12):
    if not catalog.get("declarado"):
        print(f"\n  {project_name}: no `[seams]` in the .toml — nothing declared to detect.")
        print("  It is optional: without it the rest of the tool works the same.\n")
        return
    print(f"\n  COSTURAS — {project_name}")
    print("  the literals through which this project joins others\n")
    for side, glosa in (("exports", "what others can ask it for"),
                        ("touches", "the resources it uses"),
                        ("consumes", "what it asks of others")):
        mapping = catalog.get(side, {})
        if not mapping:
            continue
        print(f"  ── {side.upper()} ── {glosa}")
        for kind, entries in sorted(mapping.items()):
            print(f"    {kind}: {len(entries)} distintos")
            for lit, locs in sorted(entries.items(), key=lambda x: -len(x[1]))[:top]:
                print(f"      {len(locs):3d}×  {lit[:58]}")
        print()


def join(catalogs: dict[str, dict]) -> list[dict]:
    """The bridge: literals one project EXPORTS (or TOUCHES) and another CONSUMES.

    The graphs are NOT unified. Each project keeps its own and its `.toml`, and the seam is
    a table of literals relating them — the owner's architectural decision. Unifying
    simplifies the query but breaks "one toml per project, the core does not change", and
    pays the cost of the large graph (hermes' full report already takes minutes).

    ONLY EXACT KINDS ARE JOINED. `tool`, `table` and `rpc` are identifiers the consumer
    writes verbatim. Paths are NOT: what is exported is partial —the `include_router`
    prefix is missing— so an equality join would return zero, and zero reads exactly like
    "there is no relation". They are reported separately, by SUFFIX match, and marked as a
    hint.
    """
    EXACTOS = ("tool", "table", "rpc", "path")
    ofrece: dict[tuple[str, str], list[str]] = defaultdict(list)
    for proj, cat in catalogs.items():
        for side in ("exports", "touches"):
            for kind, mapping in cat.get(side, {}).items():
                for lit in mapping:
                    ofrece[(kind, lit)].append(proj)

    bridges = []
    for proj, cat in catalogs.items():
        for kind, mapping in cat.get("consumes", {}).items():
            for lit, locs in mapping.items():
                if kind in EXACTOS:
                    en_prod = (kind, lit) in set(map(tuple, cat.get("in_product", [])))
                    for owner in ofrece.get((kind, lit), ()):
                        if owner != proj:
                            bridges.append({"from": proj, "to": owner, "kind": kind,
                                            "literal": lit, "usos": len(locs),
                                            "exacto": True, "in_product": en_prod})
                elif kind == "path":
                    for (t2, lit2), duenios in ofrece.items():
                        if t2 != "path" or not lit.endswith(lit2) or len(lit2) < 6:
                            continue
                        for owner in duenios:
                            if owner != proj:
                                bridges.append({"from": proj, "to": owner, "kind": "path",
                                                "literal": lit, "usos": len(locs),
                                                "exacto": False, "contra": lit2})
    # SHARED RESOURCE: two projects that TOUCH the same table or the same RPC. It is not "A
    # calls B" — they share STATE, and that relation appears in no call graph. In this
    # architecture it is the most sensitive one: the frontend reads Supabase directly under
    # RLS and the backend writes with service_role, so the table is the only point where
    # they meet. It is reported separately because it is not a directed edge.
    por_recurso: dict[tuple[str, str], set[str]] = defaultdict(set)
    for proj, cat in catalogs.items():
        for kind, mapping in cat.get("touches", {}).items():
            for lit in mapping:
                por_recurso[(kind, lit)].add(proj)
    for (kind, lit), proys in por_recurso.items():
        if len(proys) > 1:
            bridges.append({"kind": kind, "literal": lit, "compartido_por": sorted(proys),
                            "usos": sum(len(catalogs[p]["touches"][kind][lit]) for p in proys),
                            "exacto": True, "recurso": True})

    return sorted(bridges, key=lambda p: (not p["exacto"], -p["usos"]))


def print_bridges(bridges: list[dict], catalogs: dict[str, dict], top: int = 14):
    print(f"\n  BRIDGES — {len(catalogs)} projects joined by their literals\n")
    if not bridges:
        print("  none. Either there is no relation, or `[seams]` is undeclared on one side.\n")
        return
    recursos = [p for p in bridges if p.get("recurso")]
    bridges = [p for p in bridges if not p.get("recurso")]
    exact = [p for p in bridges if p["exacto"] and p.get("in_product", True)]
    solo_test = [p for p in bridges if p["exacto"] and not p.get("in_product", True)]
    indicios = [p for p in bridges if not p["exacto"]]

    from collections import Counter
    print("  ── per pair of projects ──")
    for (de, a), n in Counter((p["from"], p["to"]) for p in exact).most_common():
        print(f"    {de}  ──{n} literales──▶  {a}")
    print()
    if exact:
        print("  ── EXACT ── the consumer writes the same identifier")
        for p in exact[:top]:
            print(f"    {p['kind']:6s} {p['literal'][:46]:46s} {p['from']} → {p['to']}  ×{p['usos']}")
        if len(exact) > top:
            print(f"    … and {len(exact) - top} more")
    if recursos:
        print(f"\n  ── SHARED RESOURCE ── {len(recursos)} tables/RPCs touched by TWO or more")
        print("     projects. Not a call: it is shared state, and it appears in")
        print("     no call graph.")
        for p in recursos[:top]:
            print(f"    {p['kind']:6s} {p['literal'][:40]:40s} {' + '.join(p['compartido_por'])}")
        if len(recursos) > top:
            print(f"    … and {len(recursos) - top} more")
    if solo_test:
        print(f"\n  ── TESTS ONLY ── {len(solo_test)} literals this project names")
        print("     only from its own suite. They do not prove a production relation.")
    if indicios:
        print(f"\n  ── HINTS ── {len(indicios)} path matches by SUFFIX.")
        print("     What is exported carries no `include_router` prefix, so this is NOT")
        print("     a proven edge: it is a candidate to verify.")
    print()


def workspace_catalogs(config_path: str, excepto: str | None = None) -> dict[str, dict]:
    """The catalogs of the workspace's other projects, so they can be crossed.

    Only the `mcview*.toml` files that DECLARE `[seams]` are loaded: with no declaration
    there is nothing to join, and building their graph would cost minutes to return empty.
    """
    import glob
    import config as _config
    import factory as _factory

    out = {}
    for tm in sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(config_path)),
                                            "mcview*.toml"))):
        cfg = _config.load(tm)
        if not getattr(cfg, "seams", None) or cfg.name == excepto:
            continue
        out[cfg.name] = detect(_factory.make_project(cfg))
    return out


def crossings(cat_propio: dict, files: set[str], otros: dict[str, dict]) -> dict:
    """Where this target's flow LEAVES the repository, and where it ENTERS from outside.

    The path does not end at the project boundary. A Telegram turn enters through the
    gateway, crosses to `/api/v1/internal/platform-auth/resolve` and only then touches the
    database. The three previous views each saw a single segment.

    CROSSING HAPPENS ONLY BY EXACT LITERAL. What holds the edge up is that both sides write
    the same identifier, not something similar — the same criterion as the unambiguous
    edges inside a project.
    """
    def _in_target(locs):
        return [l for l in locs if l.split(":")[0] in files]

    sale, entra = [], []
    for kind, mapping in cat_propio.get("consumes", {}).items():
        for lit, locs in mapping.items():
            aqui = _in_target(locs)
            if not aqui:
                continue
            for proj, cat in otros.items():
                for side in ("exports", "touches"):
                    target_node = cat.get(side, {}).get(kind, {}).get(lit)
                    if target_node:
                        sale.append({"kind": kind, "literal": lit, "project": proj,
                                     "src": sorted(aqui), "hacia": sorted(target_node)})
    for side in ("exports", "touches"):
        for kind, mapping in cat_propio.get(side, {}).items():
            for lit, locs in mapping.items():
                aqui = _in_target(locs)
                if not aqui:
                    continue
                for proj, cat in otros.items():
                    origin = cat.get("consumes", {}).get(kind, {}).get(lit)
                    if origin:
                        entra.append({"kind": kind, "literal": lit, "project": proj,
                                      "src": sorted(origin), "hacia": sorted(aqui)})
    return {"sale": sale, "entra": entra}


def print_crossings(c: dict, top: int = 8):
    if not c["sale"] and not c["entra"]:
        return
    print("\n  ── CROSSES INTO ANOTHER PROJECT ── the path does not end at the repo edge ──")
    for x in c["entra"][:top]:
        print(f"    ◀ ENTRA  {x['kind']:5s} {x['literal'][:44]}")
        print(f"             {x['project']} {x['src'][0]}  →  {x['hacia'][0]}")
    for x in c["sale"][:top]:
        print(f"    ▶ SALE   {x['kind']:5s} {x['literal'][:44]}")
        print(f"             {x['src'][0]}  →  {x['project']} {x['hacia'][0]}")
    rest = max(0, len(c["entra"]) - top) + max(0, len(c["sale"]) - top)
    if rest:
        print(f"    … and {rest} more crossings")


# --------------------------------------------------------------- TypeScript
def _ts_text(n) -> str:
    return n.text.decode("utf-8", "replace")


def _ts_strings(n) -> list[str]:
    """The content of a string literal or a template, without quotes.

    Templates matter more than loose literals: the frontend calls the backend with
    `` `${CIRE_API_URL}/api/v1/oauth/integrations` ``, so a plain-string detector missed
    EVERY cross-repo call. From a template its static fragments are taken, which is where
    the path lives.
    """
    if n.type == "string":
        return [_ts_text(n)[1:-1]]
    if n.type == "template_string":
        return [_ts_text(h) for h in n.children if h.type == "string_fragment"]
    return []


def _path_by_convention(rel: str, files: tuple, base: str) -> str | None:
    """In the App Router the route IS the file path: `app/api/x/[id]/route.ts` → `/api/x/[id]`.

    There is no literal to detect — the framework convention declares it, just like
    `ROOT_FILES` in `ts.py`. Without this, the frontend BFF exports nothing detectable.
    """
    name = rel.rsplit("/", 1)[-1]
    if name not in files:
        return None
    dirs = rel.rsplit("/", 1)[0].split("/")
    if base in dirs:
        dirs = dirs[dirs.index(base) + 1:]
    return "/" + "/".join(dirs) if dirs else "/"


def detect_ts(project) -> dict:
    """Same contract as `detect`, over the tree-sitter tree."""
    import re as _re
    from ts import _walk

    c = getattr(project.cfg, "seams", {}) or {}
    if not c:
        return {"exports": {}, "touches": {}, "consumes": {}, "declarado": False}

    metodos = {m: kind for kind, ms in (("table", c.get("touches_table", ())),
                                        ("rpc", c.get("touches_rpc", ())))
               for m in ms}
    prefixes = tuple(c.get("consumes_route", ()))
    patterns = [(_re.compile(p), t)
                for t, ps in (("tool", c.get("consumes_tool", ())),) for p in ps]
    file_path = tuple(c.get("exports_route_files", ()))
    base_path = c.get("exports_route_base", "app")

    exporta = defaultdict(lambda: defaultdict(list))
    toca = defaultdict(lambda: defaultdict(list))
    consume = defaultdict(lambda: defaultdict(list))
    en_producto = set()

    for rel, root in getattr(project, "_ts_roots", {}).items():
        if file_path:
            path = _path_by_convention(rel, file_path, base_path)
            if path:
                exporta["path"][path].append(f"{rel}:1")
        for n in _walk(root):
            if n.type == "call_expression":
                fn = n.child_by_field_name("function")
                if fn is not None and fn.type == "member_expression":
                    prop = fn.child_by_field_name("property")
                    kind = metodos.get(_ts_text(prop)) if prop is not None else None
                    args = n.child_by_field_name("arguments")
                    if kind and args is not None:
                        for h in args.children:
                            for lit in _ts_strings(h):
                                toca[kind][lit].append(f"{rel}:{n.start_point[0] + 1}")
                                break
                            else:
                                continue
                            break
            elif n.type in ("string", "template_string"):
                loc = f"{rel}:{n.start_point[0] + 1}"
                for lit in _ts_strings(n):
                    if prefixes and lit.startswith(prefixes):
                        consume["path"][lit].append(loc)
                        en_producto.add(("path", lit))
                    else:
                        for rx, kind in patterns:
                            if rx.match(lit):
                                consume[kind][lit].append(loc)
                                en_producto.add((kind, lit))
                                break

    aplanar = lambda d: {k: dict(v) for k, v in d.items()}
    return {"exports": aplanar(exporta), "touches": aplanar(toca),
            "consumes": aplanar(consume), "declarado": True,
            "in_product": sorted(en_producto)}


# =============================================================================
# REACHABILITY BY NAME — what is declared and nobody can select
# =============================================================================
#
# `--no-consumer` (consumption.py) answers this in the plane of SYMBOLS. There is a whole
# kind that plane cannot see: what is reached **by its name written as a string** from a
# registry. A plugin, an event handler, an agent tool, a CLI command, a queue task: the
# dispatcher does `registry[name](...)`, so the dispatcher→symbol edge DOES NOT EXIST in any
# call graph. They all look dead, and the ones that really are look exactly like the live
# ones.
#
# THE RIGHT QUESTION IS NOT "DID ANYONE CALL IT?" BUT "IS IT SELECTABLE?"
# -----------------------------------------------------------------------
# And "selectable" is not measured with traffic. It was measured with traffic once and came
# out wrong: in a system with NO operational usage, the absence of calls says nothing about
# the system — it says what whoever tested it happened to test. Here it is not needed: if the
# name appears in no artifact that makes it selectable, it is unreachable BY CONSTRUCTION,
# with or without users.
#
# That is why the evidence is the MENTION, not the reference: the artifact that makes a name
# selectable is almost never code. It is a list in a YAML file, a catalog, a prompt, a route
# table. An AST scan does not see them; a literal search does.
#
# THE THREE STATUSES, AND THE MIDDLE ONE IS THE ONE THAT MATTERS
# ---------------------------------------------------------------
#   ORPHAN       the name appears nowhere but in its own declaration
#   INERT_ONLY   it appears ONLY in artifacts that do not make it selectable (docs, tests,
#                changelogs)
#   REACHABLE    it appears in some live artifact
#
# `INERT_ONLY` is the real finding and the one no other view gives: something documented and
# tested —with every appearance of being alive— that the dispatcher can never offer. An
# `ORPHAN` is usually an obvious oversight; an `INERT_ONLY` survives for years because its
# test passes.
#
# WHAT COUNTS AS INERT IS DECLARED, LIKE EVERYTHING ELSE
# ---------------------------------------------
#     [seams]
#     inert = ["docs/", "tests/", "CHANGELOG"]
#
# Without `inert` the view still runs and collapses to two statuses — it invents no default,
# because "tests do not count" is true in almost every project and false in the ones that
# dispatch fixtures by name.

REACH_STATUSES = ("ORPHAN", "INERT_ONLY", "REACHABLE")


def scan_mentions(literales, directorios, ignored_dirs=(), tope_bytes=2_000_000):
    """Where each literal appears, in ANY text file.

    A single pass over the files and one `in` per literal: it is O(files × literals) with no
    index, which at real magnitudes (thousands × hundreds) is cheaper than building one.
    Binaries are skipped by decoding failure, not by an extension list — the list is always
    incomplete and the failure never lies.
    """
    mentions = {lit: set() for lit in literales}
    if not literales:
        return mentions
    lits = list(literales)
    for base in directorios:
        for dp, dirs, fs in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith(".")]
            for f in fs:
                path = os.path.join(dp, f)
                try:
                    if os.path.getsize(path) > tope_bytes:
                        continue
                    with open(path, "r", encoding="utf-8") as fh:
                        txt = fh.read()
                except (OSError, UnicodeDecodeError):
                    continue
                for lit in lits:
                    if lit in txt:
                        mentions[lit].add(path)
    return mentions


def reachability(catalog, mentions, inert=(), kinds=("tool",), selectors=()):
    """Classifies each EXPORTED literal by where it is mentioned.

    `kinds` defaults to `tool` because that is the case where dispatch by name is the norm.
    Tables and routes are also reached by literal, but their legitimate consumer usually
    lives in another project or outside the repo (a client, a dashboard), and there the
    absence of a mention is NOT evidence of anything. Widening `kinds` is the owner's call,
    with that caveat understood.
    """
    # TWO WAYS TO DECIDE WHETHER A MENTION COUNTS, and the allowlist wins when it exists.
    # It started with `inert` alone (a denylist) and running it refuted that: this repo
    # ENUMERATES its tools in several accounting tables —the mandatory catalog, the tiers,
    # the gate classification— so every tool is mentioned by construction and the result was
    # green across the board. Widening the denylist ended at "the whole repo except two
    # files", which is the usual infinite list. Declaring the SELECTORS is finite and says
    # what actually matters: which artifact can make the dispatcher offer it.
    def _count_of(path):
        if selectors:
            return any(m in path for m in selectors)
        return not any(m in path for m in inert)

    rows = []
    for kind, mapping in catalog.get("exports", {}).items():
        if kind not in kinds:
            continue
        for lit, locs in mapping.items():
            own_names = {l[0] if isinstance(l, (tuple, list)) else str(l) for l in locs}
            otros = {r for r in mentions.get(lit, ()) if not any(p in r for p in own_names)}
            vivas = [r for r in otros if _count_of(r)]
            if not otros:
                status = "ORPHAN"
            elif not vivas:
                status = "INERT_ONLY"
            else:
                status = "REACHABLE"
            rows.append({"literal": lit, "kind": kind, "status": status,
                          "declared_in": sorted(own_names)[:2],
                          "mentioned_in": sorted(otros)[:6], "n_mentions": len(otros)})
    call_order = {e: i for i, e in enumerate(REACH_STATUSES)}
    return sorted(rows, key=lambda f: (call_order[f["status"]], f["n_mentions"], f["literal"]))


def print_reach(rows, top=20):
    from collections import Counter
    c = Counter(f["status"] for f in rows)
    print(f"\n  REACHABILITY BY NAME — {len(rows)} exported literals\n")
    for e in REACH_STATUSES:
        print(f"    {c.get(e, 0):4d}  {e}")
    if not rows:
        print("\n  (no exported literals of the requested kinds — is [seams] declared?)")
        return
    for e in ("ORPHAN", "INERT_ONLY"):
        hits = [f for f in rows if f["status"] == e]
        if not hits:
            continue
        print(f"\n  ── {e}  ({len(hits)})")
        for f in hits[:top]:
            where = f["declared_in"][0] if f["declared_in"] else "?"
            extra = ""
            if e == "INERT_ONLY":
                extra = "   only in: " + ", ".join(x.rsplit("/", 1)[-1] for x in f["mentioned_in"][:3])
            print(f"     {f['literal']:<44} {where.rsplit('/', 1)[-1]:<26}{extra}")
        if len(hits) > top:
            print(f"     … and {len(hits) - top} more")
    print("\n  ORPHAN = nobody writes that name.  INERT_ONLY = only artifacts that do not")
    print("  make it selectable write it (docs, tests): it looks alive and is never offered.")
