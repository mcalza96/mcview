---
name: mcview-install
description: >-
  For INSTALLING `mcview/` in a repository where it is not there yet, or for fixing an
  installation whose numbers cannot be believed. Use it when someone copies the tool into
  a new project, when a repository that was never measured has to be measured, when "no
  mcview.toml found" shows up, or when the results come out absurd —everything dead,
  everything alive, the flow saying nothing, hundreds of roots. It triggers on "install
  mcview here", "measure this repo", "this was never analyzed", "these numbers make no
  sense", "why does it say everything is dead?", even when the tool is never named. The
  only thing you write is ONE `.toml`: declaring the roots is half the work, and it is
  where it gets decided whether the measurement is useful or just noise shaped like data.
  Do NOT use it if the `.toml` already exists and works (that is `mcview-repo` to measure,
  or `orient-session` to get oriented), nor to add a new yardstick over an
  already-installed project — for that, copying the `.toml` and changing its roots is
  enough.
---

# Installing mcview in a repository

Copy the directory and write **one** `.toml`. There is no build, no package, and the core
is never touched.

```
my-project/
  mcview.toml        ← the ONLY thing you write
  mcview/            ← the directory, copied as is (skills and vendor travel inside)
  src/…
```

```bash
mcview/mcview.py --init                       # derive a starter mcview.toml — then READ it
mcview/mcview.py                              # the census — if this runs, it is installed
mcview/selfcheck/check_portability.py         # proves the copy is self-sufficient
```

**Start with `--init`, and then read what it wrote.** It does not replace the section below —
it does the looking, and every root it writes carries the file it came from, so you are
reviewing evidence instead of recalling a procedure. What it could not decide it leaves as a
`# candidate —` comment with the file to open. If it found nothing real it says so loudly and
falls back to whole directories, which is the expensive mistake described further down: that
message is the signal to do this by hand.

The config **is discovered** by walking up from the current directory, so it works from
any subdirectory. Several projects in one workspace: `mcview.<name>.toml` and
`--project <name>`.

## Roots are not invented: they are found where the project already declares them

Without roots, reachability declares **the entire project dead**. It is the only mandatory
part, and where it gets decided whether the measurement is useful.

And it is not a judgement call — the project already declares them somewhere. Look there,
in this order:

| where to look | what it gives |
|---|---|
| `pyproject.toml` `[project.scripts]`, `package.json` `bin`/`scripts` | the entrypoints, stated by the project itself |
| `Dockerfile` `CMD`/`ENTRYPOINT`, `docker-compose`, `Procfile` | what runs in production |
| the framework | decorators that REGISTER into a dispatch dict (`@app.get`, `@task`, `@tool`) |
| `grep -rn "uvicorn.run\|app.listen\|if __name__"` | the processes that actually start |
| the product config | which plugins/platforms/modules it TURNS ON |

```toml
[project]
name = "my-api"
root = "src"

[roots]
decorators    = ["task", "command"]      # @task(...) registers into a dict → it is a root
route_methods = ["get", "post"]          # @router.get(...) / @app.post(...)
route_objects = ["router", "app"]
dirs          = ["src/cli/", "tests/"]   # every module in here is a root
product_dirs  = ["src/cli/"]             # of those, which ones are NOT tests
```

**`dirs` vs `product_dirs` is the distinction that makes everything else readable.** Tests
have to be roots —otherwise everything only they touch comes out "dead"— but they are not
product. Without that second list, the heat map and the paths fill up with tests and bury
the real system.

### The expensive mistake: declaring WHOLE DIRECTORIES

It is tempting and it ruins the measurement silently. If `dirs` lists large folders, almost
the whole project is a root — and then *"how do you get into this subsystem?"* has no
answer, because **everything is an entrance**.

Measured (2026-08-06) on a project with 448 product files: declaring directories gave
**649 roots**, and the flow said nothing. Declaring what actually starts —eight files,
taken from `[project.scripts]` and the single `uvicorn.run`— and the flow started
answering.

**The exception that IS a directory:** whatever is loaded BY NAME at runtime (plugins,
platform adapters, handlers resolved from config). No static analysis reaches them, so
declaring them is the only correct route. Add a comment saying why, or the next person to
read the config will want to remove them.

## Checking the yardstick is not broken, BEFORE believing a number

Four checks, in order. Any one of them failing invalidates everything after it.

```bash
mcview/mcview.py --no-duplicates      # the census
mcview/mcview.py --map                # does the mass look like your system?
mcview/mcview.py --orient <known-target> --no-twins --flow
```

1. **How many roots against how many product files?** If the root count approaches the
   file count, you declared directories. Go back up.
2. **Is `DEAD_CANDIDATE` plausible?** Hundreds of dead symbols in a healthy repo means
   roots are missing —almost always a registration decorator you did not declare. Zero
   dead in an old repo means there are too many.
3. **Does the map look like your system?** If something you know is marginal tops it, ask
   yourself what an EDGE is in this codebase before reading the mass. In a service backend
   the plumbing dominates; in a component UI the walker stays inside the files and the mass
   measures something else.
4. **Ask it something whose answer you already know.** A module you know: who uses it, what
   does it depend on? If it answers nonsense, the problem is the config, not the repo.

## Declaring the lines of work (optional, but it is what makes the rest readable)

A module is NOT a directory: "retrieval" can live in `store/`, in `api/` and in `services/`
at the same time. Without `[modules]` everything falls back to the two-level directory,
which is almost never the unit you think in.

```toml
[modules]
"Retrieval" = ["store/retrieval", "api/routers/search.py", "services/search_service.py"]
```

Declare them by **responsibility**, crossing folders. Declaring them by folder means
measuring physical proximity, which predicts coupling almost by definition and tells you
nothing.

And `[areas]` (`core` / `auxiliary` / `test`): a tooling or benchmark directory is cold BY
DESIGN. Without declaring it, the map reads it as dead periphery.

## What can be missing, and how it looks

| symptom | cause |
|---|---|
| "no mcview.toml found" | it is not at the root, or you are outside the tree |
| everything `DEAD_CANDIDATE` | roots are missing — look at the registration decorators |
| the flow says nothing | too many roots: you declared directories |
| "install numpy/scipy" | only `--modules`, `--k`, `--hierarchy`, `--islands`, `--views` ask for them |
| "install tree_sitter" | the project is TypeScript: `language = "typescript"` |
| tests top the map | `product_dirs` is missing |

The main path —census, `--orient`, `--flow`, `--atlas`, the diagrams— runs on the **bare
stdlib**, and that is verified by blocking the modules, not by reading the imports.

## After installing: two things that multiply

**The pre-write gate** (a `PreToolUse` hook on `Write|Edit`, ~60 ms) warns you if what is
about to be written already exists. It never blocks and it fails open: a hygiene tool
cannot stop the work.

```bash
mcview/mcview.py --reindex            # build the cache
mcview/mcview.py --exists <new-file>  # does this already exist?
```

**The runtime census.** Where code is resolved by name, it is the only evidence there is.
It lives on the measured project's side, not the tool's: it has to be wired into the
process startup. See `mcview-repo`, which carries the protocol and the two traps that
produce an empty census without warning.

## When reporting an installation

Say **what you declared and where you got it from**, not just that it works. A config whose
roots came from `[project.scripts]` can be audited; one whose roots came from your judgement
cannot — and six months from now nobody will know whether that directory is there for a
reason or because somebody put it there.

And run the portability check. It is what proves the copy is self-sufficient and does not
depend on anything from your machine:

```bash
mcview/selfcheck/check_portability.py
```
