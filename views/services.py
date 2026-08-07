# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""WHICH PROCESS EACH THING RUNS IN — and therefore what has to be restarted.

A repository is not a process. `backend/` produces TWO: the api (`entrypoints/main.py`) and the
worker (`entrypoints/worker.py`), which run in different containers and share almost all the
code. And the gateway is another process, in another repository.

That matters for a concrete operational reason, documented in this project's `CLAUDE.md` with
a real bug behind it: after changing an MCP tool you have to restart the api **and** the
gateway, because the gateway keeps a persistent connection that dies with the restart; and
after touching the scheduler you have to restart the worker, which runs without `--reload` and
keeps the old code in memory without warning. A file that runs in two processes and gets
restarted in one is
exactamente esa kind de falla silenciosa.

THE SERVICE IS NOT DECLARED BY DIRECTORY, IT IS DERIVED FROM THE ENTRYPOINT
------------------------------------------------------------------
Declaring `api = ["services/", "store/"]` would be a lie: `services/` runs in both. What gets
declared is each process's starting point, and the reach is COMPUTED with the graph that
already exists. That way a file can belong to several services — which is the truth.

    [services]
    api    = "entrypoints/main.py"
    worker = "entrypoints/worker.py"

WHICH GRAPH, AND WHY NOT THE ONE I PICKED FIRST
---------------------------------------------
For a restart decision the bias should invert —a false "this does not run in the worker"
leaves you without restarting it and with old code serving, which gives no signal— so the
first version used the COMPLETE graph. Measured, that degenerates: with homonym inflation it
gave 278 of 281 files as shared and ZERO belonging only to the worker, i.e. "everything runs
everywhere", which informs nothing.

The unambiguous-edge graph is used: 126 / 124 / 122 shared, with 4 and 2 of their own. And
the complete graph's number is reported as a CONSERVATIVE BOUND, because the operational
conclusion does not depend on which one is chosen:

    almost any backend change touches BOTH processes.

Which is exactly what the hand-written restart protocol in `CLAUDE.md` says.

IT IS STILL A LOWER BOUND, AND IT HAS TO BE READ THAT WAY
-----------------------------------------------------
The fixed point over the roots recovers what the framework invokes (MCP tools, routes), but
what is loaded by name at runtime —a plugin, a dispatch by string— is beyond any static
analysis. If the question is "do I restart this?", the safe answer when in doubt is yes: this
number says what runs FOR SURE in each process, not everything that runs.
"""
from __future__ import annotations


def reach(project, fuerte: bool = True) -> dict[str, set[str]]:
    """service → files that process can execute.

    Forward closure from the entrypoint's symbols, over the complete graph.
    """
    cfg = project.cfg
    declarados = getattr(cfg, "services", {}) or {}
    if not declarados:
        return {}

    out: dict[str, set[str]] = {}
    for service, entry in declarados.items():
        seed = {s for s, x in project.symbols.items() if x.file == entry}
        # the entrypoint's module-level code also starts the process
        seed |= set(project.module_refs.get(entry, ()))
        grafo = project.strong_edges if fuerte else project.edges

        def _close(sem):
            seen, queue = set(sem), list(sem)
            while queue:
                for d in grafo.get(queue.pop(), ()):
                    if d not in seen:
                        seen.add(d)
                        queue.append(d)
            return seen

        # FIXED POINT OVER THE ROOTS. An MCP tool or a route is not reachable from the
        # entrypoint through the call graph —the framework invokes them— but they run in the
        # process that IMPORTS their module. Without this step, `MCP Protocol` gave 2 of 8
        # files and `Ingestion` 17 of 31: an undercount, which is exactly the dangerous
        # direction here (a false "it does not run in the worker" leaves you without
        # restarting it, and that gives no signal).
        seen = _close(seed)
        while True:
            files_seen = {project.symbols[s].file for s in seen
                               if s in project.symbols}
            nuevas = {r for r in project.roots
                      if r in project.symbols
                      and project.symbols[r].file in files_seen
                      and r not in seen}
            if not nuevas:
                break
            seen = _close(seen | nuevas)
        out[service] = {project.symbols[s].file for s in seen if s in project.symbols}
    return out


def from_files(mapping: dict[str, set[str]], files: set[str]) -> dict[str, int]:
    """How many of these files each service runs. A target can live in several."""
    return {s: len(files & a) for s, a in mapping.items() if files & a}


def shared(mapping: dict[str, set[str]]) -> set[str]:
    """The files that run in MORE THAN ONE process: the ones that force several restarts."""
    count: dict[str, int] = {}
    for files in mapping.values():
        for a in files:
            count[a] = count.get(a, 0) + 1
    return {a for a, n in count.items() if n > 1}


def print_rows(mapping: dict[str, set[str]], project_name: str,
             cota: dict[str, set[str]] | None = None):
    if not mapping:
        print(f"\n  {project_name}: no `[services]` in the .toml — nothing to derive.")
        print("  Declaring each process's entrypoint is enough; the rest is computed.\n")
        return
    comun = shared(mapping)
    print(f"\n  SERVICIOS — {project_name}")
    print("  what code each process can execute, derived from its entrypoint\n")
    for s, files in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
        own_names = len(files - comun)
        print(f"    {s:12s} {len(files):4d} files   ({own_names} only theirs, "
              f"{len(files) - own_names} compartidos)")
    print(f"\n  {len(comun)} files run in MORE THAN ONE process. Touching one forces")
    print("  restarting every process that reaches it — and a process that is not restarted")
    print("  keeps the old code in memory without giving any signal.")
    if cota:
        print(f"  (conservative bound, over the complete graph: {len(shared(cota))} "
              f"shared — the conclusion does not change)")
    print()
