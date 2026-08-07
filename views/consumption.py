# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""COMPUTED AND GOVERNING NOTHING — the loose piece no other view sees.

`DEAD_CANDIDATE` answers *"does anybody reference this?"*. There is a whole kind that passes
that question comfortably and still does nothing: **a value that gets computed, transported,
logged, and that no decision path reads.** The graph sees it alive —it has references, it has
mass— and it is exactly as useless as if it were dead. Worse, actually: it costs something to
compute on every turn.

THE CASE THAT MOTIVATED IT (2026-08-03, measured)
-------------------------------------------
An intent classifier ran on every turn and returned four verdicts: `operacion`, `forma`,
`ancla`, `kind`. All four travelled in a header and were stored in contextvars. Two of them
—`ancla` and `kind`— were read only by the telemetry module, to put them in an audit row.
**They were computed on every turn of the system and changed no decision.**

No existing view says so. They are not dead (there is a `.get()`), not cold (the turn goes
through there), not `ALIVE_NOT_PRODUCT`. The only question that gives them away is *"who reads them,
and what for?"* — and that requires telling a reader that DECIDES from one that only WATCHES
or RELAYS.

WHY IT IS DECLARED AND NOT GUESSED
-----------------------------------
"What counts as observability" belongs to the project: in one it is `telemetry.py`, in
another `obs/`, in another a decorator. Guessing it by name would be the usual infinite list.
It gets declared, like the roots:

    [consumption]
    observability = ["pkg/observability/", "telemetry.py"]   # they only WATCH
    transport     = ["routers/mcp_server.py"]                # they only RELAY

Without `[consumption]` the view does not run and says so — it invents no default, which
would mean reporting findings over a partition nobody declared.

WHAT IS A FINDING AND WHAT IS NOT
----------------------------
A symbol shows up here when **all** of its external readers belong to observability or
transport. Eso NO significa "borralo":

- it may be deliberate (a metric exists to be looked at, and nothing else);
- it may be a built capability whose consumer was never wired — which is the interesting
  case, and the one this project found three times in a single day;
- the consumer may live **in another repository** (see `seams.py`): a value leaving through a
  header is consumed by the other side, and this analysis does not reach it.

THE BLIND SPOT THIS VIEW HAS, AND IT HAS TO BE SAID
-------------------------------------------------------
It looks at references TO A SYMBOL. **A value consumed through an ACCESSOR is invisible to
it**: if the turn stores `clase_pedida_ctx` and whoever decides reads it as
`get_turn_decision()["kind"]`, nobody references the contextvar and the view
it gets reported as having no consumer. It is measured — on 2026-08-04 three independent
analyses (two censuses and whoever coordinated them) claimed that `kind` governed nothing,
and it does. This view would have said the same.

Rule when reading a finding from here: **before believing it, look for an accessor**. A dict
with keys, a `getattr` by name, a `.get(field)` — any indirection breaks the search by name,
and the only defense is to ask WHERE the value is read, not who names the carrier.

Like the rest of the tool: **it generates candidates, not verdicts.**
"""
from __future__ import annotations


def _classify(rel: str, obs: tuple[str, ...], trans: tuple[str, ...]) -> str:
    for p in obs:
        if p in rel:
            return "observa"
    for p in trans:
        if p in rel:
            return "transporta"
    return "decide"


def _readers_by_symbol(project) -> dict[str, set[str]]:
    """symbol → FILES that reference it. The inverse of the graph, plus module level.

    The COMPLETE graph is used rather than the unambiguous one, on purpose: here the expensive
    error is the false "nobody consumes it" (we would flag a wired piece as loose). More
    readers = fewer findings = the bias points at the safe side, like the rest of the chain.
    """
    out: dict[str, set[str]] = {}
    for origin, targets in project.edges.items():
        sim_o = project.symbols.get(origin)
        if sim_o is None:
            continue
        for d in targets:
            out.setdefault(d, set()).add(sim_o.file)
    # module-level code: an `X.get()` in a file's body belongs to no symbol and is still
    # a real reader.
    for rel, targets in project.module_refs.items():
        for d in targets:
            out.setdefault(d, set()).add(rel)
    return out


def no_consumer(project) -> list[dict]:
    """Symbols whose external readers are ALL observability or transport.

    What defines a reader is the LAYER it lives in, not which symbol makes the reference.
    """
    cfg = project.cfg
    obs, trans = getattr(cfg, "observability", ()), getattr(cfg, "transport", ())
    if not obs and not trans:
        return []

    readers = _readers_by_symbol(project)
    out = []
    for name, sim in project.symbols.items():
        # EXTERNAL readers only: a reference from the file that defines it is usually its
        # own internal plumbing, and says nothing about who consumes it.
        externos = {a for a in readers.get(name, ()) if a != sim.file}
        if not externos:
            continue                      # no external readers: temperature already says that
        layers = {_classify(a, obs, trans) for a in externos}
        if "decide" in layers:
            continue
        out.append({
            "symbol": name,
            "where": f"{sim.file}:{sim.line}",
            "layers": sorted(layers),
            "readers": sorted(externos),
        })
    return sorted(out, key=lambda x: x["symbol"])


def print_rows(findings: list[dict], project_name: str, declarado: bool):
    if not declarado:
        print(f"\n  {project_name}: no `[consumption]` in the .toml — nothing to separate.\n")
        print("  Declare which modules ONLY WATCH (observability) and which ONLY RELAY")
        print("  (transport) reaches; the rest is computed.\n")
        print("      [consumption]")
        print('      observability = ["pkg/observability/", "telemetry.py"]')
        print('      transport     = ["routers/mcp_server.py"]\n')
        return
    print(f"\n  IT IS COMPUTED AND DOES NOT GOVERN — {project_name}")
    print("  symbols whose external readers ONLY watch or relay\n")
    if not findings:
        print("    none. Everything computed is read by some decision path.\n")
        return
    for h in findings:
        print(f"    {h['symbol']:34s} {h['where']}")
        print(f"      read only by ({'+'.join(h['layers'])}): {', '.join(h['readers'][:3])}")
    print(f"\n  {len(findings)} symbol(s). NOT a deletion order: it may be a metric that")
    print("  exists to be looked at, a capability whose consumer was never wired, or a")
    print("  value consumed by ANOTHER repository (see --seams).\n")
