#!/usr/bin/env python3
"""Is `mcview/` still a directory you copy into any project and it works?

ENCAPSULATION ERODES SILENTLY. Nobody notices until they try to extract it, and by then there
are months of coupling to unpick. One session proved it three times:

  · `paths.py` had never been committed — a clean clone could not run `--flow`, and both
    tracers had been broken for weeks on any machine that was not mine.
  · the skills lived in CIRE's `.claude/skills/`: copying the module took the engine and
    dejaba el manual.
  · `check_view.py` had two absolute paths from ONE machine embedded in it.

None of the three would have been found by reading the code. This finds all three.

HOW IT PROVES IT, AND WHY AS A SUBPROCESS
------------------------------------------
Importing the modules from here would prove nothing: `sys.path` and `cwd` are already
contaminated by this repository. `mcview/` is copied into a temporary directory with a
synthetic project next to it, and the CLI is executed **as a separate process, with that
`cwd`**. That genuinely exercises config discovery, path resolution and isolation.

It runs WITH NO NETWORK and WITHOUT numpy/scipy on purpose: that is the floor the tool
promises.

    mcview/selfcheck/check_portability.py        # 0 = pass
"""
from __future__ import annotations

import glob
import os
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import _layers  # noqa: E402  — mounts the layers; also the collisions() measurement

PROYECTO = {
    "app/main.py": '''
"""Entry point of the test project."""
from service import process


def main(payload):
    return process(payload)
''',
    "app/service.py": '''
from datos import save
from seguridad import validate


def process(payload):
    """Crosses the guard before touching the data: gives `WHAT IT CROSSES FIRST` something to see."""
    validate(payload)
    return save(payload)


def reprocess(payload):
    validate(payload)
    return save(payload)
''',
    "app/datos.py": '''
from seguridad import record


def save(row):
    record("save")
    if not row:
        raise ValueError("VACIO")
    if len(row) > 100:
        raise ValueError("MUY_LARGO")
    return {"ok": True, "n": len(row)}


def delete(key):
    record("delete")
    if not key:
        raise ValueError("VACIO")
    if len(key) > 100:
        raise ValueError("MUY_LARGO")
    return {"ok": True, "n": len(key)}
''',
    "app/seguridad.py": '''
def validate(payload):
    if payload is None:
        raise ValueError("NULO")
    return True


def record(accion):
    return accion
''',
    "mcview.toml": '''
[project]
name = "project de test"
root = "."

[roots]
dirs = ["app/"]
product_dirs = ["app/"]

[modules]
"Datos" = ["app/datos.py"]
"Servicio" = ["app/service.py"]
"Seguridad" = ["app/seguridad.py"]
''',
}


def _run(base: str, cwd: str, *args) -> tuple[int, str]:
    """The script is invoked by ABSOLUTE path and what varies is the `cwd`.

    With a relative path, running from a subdirectory failed because the script could not be
    found — and the message read as "it did not discover the config", which is the opposite of
    what was happening.

    And it is invoked DIRECTLY, without `sys.executable` in front, because that is how both
    skills write it (`mcview/mcview.py --orient X`). With the interpreter in front, the lock
    passed even with the `+x` bit off: the shebang was never exercised and EVERY documented
    command failed with 126 without anything saying so.
    """
    entorno = dict(os.environ)
    entorno.pop("PYTHONPATH", None)     # no inheritance from this repository
    try:
        r = subprocess.run([os.path.join(base, "mcview", "mcview.py"), *args],
                           cwd=cwd, capture_output=True, text=True, timeout=180, env=entorno)
    except PermissionError:
        return 126, ("mcview.py is not executable — it is missing the +x bit. The skills invoke "
                     "it directly (`mcview/mcview.py …`), so ALL their commands fail. "
                     "Arreglo: chmod +x mcview/mcview.py")
    return r.returncode, r.stdout + r.stderr


# Values the CLI accepts LITERALLY: they are not names from this project.
_LITERALES = {
    "DEAD_CANDIDATE", "ALIVE_PRODUCT", "ALIVE_PRODUCT_WEAK", "ALIVE_NOT_PRODUCT",
    "ALIVE_BY_NESTING", "ALIVE_PROVEN",         # --status
    "sequence", "map",                        # --mermaid
    "HEAD",                                     # --diff
}


def _generic_commands(d: str) -> list[str]:
    """A command from the manual either RUNS in a clean project, or reads as a placeholder.

    The manual is what gets copied and pasted. An `--orient "Retrieval"` is correct here and
    means nothing in another repository: the reader runs it, it does not resolve, and the
    defect reads as "the tool does not work". Prose is different —there the concrete name is
    what makes the lesson land, which is why this lock does NOT look at it—; what gets checked
    are the command blocks, which are the interface.

    The rule: every argument is a `<placeholder>`, a literal the CLI accepts, a number, or a
    file that exists in the test project. Anything else is a proper name.
    """
    failures = []
    for skill in sorted(glob.glob(os.path.join(d, "mcview", "skills", "*", "SKILL.md"))):
        name, inside = os.path.basename(os.path.dirname(skill)), False
        for n, line in enumerate(open(skill, encoding="utf-8"), 1):
            if line.startswith("```"):
                inside = line.strip() == "```bash"
                continue
            # only the tool's own invocations: `git log -S "<symbol>"` is generic shell
            # and its placeholders are already placeholders.
            if not inside or "mcview.py" not in line:
                continue
            limpia = line.split("#")[0].strip().rstrip("\\")   # without the line continuation
            for tok in shlex.split(limpia, comments=False, posix=True):
                if (tok.startswith("-") or "<" in tok or tok in _LITERALES
                        or tok.replace(".", "").isdigit()
                        or tok in {"|", ">", "\\", "&&"}
                        or tok.endswith(".html") or tok.startswith("mcview/")
                        or os.path.exists(os.path.join(d, tok))):
                    continue
                failures.append(f"{name}/SKILL.md:{n} the command uses a name from THIS "
                              f"repository: {tok!r} — use a <placeholder> or an example that "
                              f"exista en cualquier project")
    return failures


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as d:
        # the tool, copied as is — the way somebody installing it would
        shutil.copytree(HERE, os.path.join(d, "mcview"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "golden"))
        for rel, content in PROYECTO.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, "w", encoding="utf-8").write(content)

        # --- what has to travel inside ------------------------------------
        for piece, path in (("the skills", "mcview/skills/orient-session/SKILL.md"),
                            ("el renderizador", "mcview/vendor/mermaid.min.js.gz")):
            if not os.path.exists(os.path.join(d, path)):
                failures.append(f"{piece} did not travel with the tool ({path})")

        # --- nothing from THIS repository leaked in -----------------------
        # A PROJECT config inside the tool is the failure this catches: while `mcview.toml`
        # lived in `mcview/`, extracting the module carried the previous project's roots,
        # modules and seams with it. `pyproject.toml` is not that — it is the packaging
        # manifest, it describes the tool and not any project measured by it, and it has to
        # travel. The rule names what it is looking for instead of matching every `.toml`,
        # because a lock that fires on the wrong thing gets widened until it fires on nothing.
        PACKAGING = {"pyproject.toml"}
        for root, _, files in os.walk(os.path.join(d, "mcview")):
            for a in files:
                if a.endswith(".toml") and a not in PACKAGING:
                    failures.append(f"a project config was left inside the tool: {a}")

        # --- the skills' COMMANDS are not overfitted to this repo ---------
        failures += _generic_commands(d)

        # --- no module name collides across layers ------------------------
        # The flat `sys.path` is what keeps the imports flat (see `_layers.py`); its single
        # failure mode is two layers holding a file with the same name — one wins silently.
        # `_layers.collisions` existed to measure exactly that and nobody called it.
        cols = _layers.collisions(os.path.join(d, "mcview"))
        if cols:
            failures.append(f"module name collision across layers: {cols}")

        # --- the census runs on the bare stdlib ---------------------------
        code, output = _run(d, d)
        if code != 0 or "project de test" not in output:
            failures.append(f"the census did not run in a clean project: {output.strip()[:160]}")

        # --- the brief and the flow say something -------------------------
        code, output = _run(d, d, "--orient", "Datos", "--flow")
        if code != 0:
            failures.append(f"--orient --flow failed: {output.strip()[:160]}")
        else:
            for mark in ("ORIENTATION — Datos", "TEMPERATURE", "WHO USES IT",
                         "HOW YOU GET IN", "WHERE IT REACHES", "ONE CONCRETE PATH",
                         "ALREADY EXISTS"):
                if mark not in output:
                    failures.append(f"the brief is missing the `{mark}` section")

        # --- the walkthrough draws, and REFUSES when a stage is invented --
        spec = os.path.join(d, "wt.toml")
        with open(spec, "w", encoding="utf-8") as fh:
            fh.write('title = "t"\n[[lane]]\nid = "a"\ntitle = "a"\n'
                     '[[stage]]\nlane = "a"\ntitle = "s"\nverify = "Datos"\n'
                     '[[cut]]\nafter = "a"\ntext = "corte"\n')
        code, output = _run(d, d, "--walkthrough", spec)
        if code != 0 or not output.lstrip().startswith("<svg"):
            failures.append(f"--walkthrough failed: {output.strip()[:160]}")
        else:
            for mark in ("viewBox", "corte", "does NOT claim"):
                if mark not in output:
                    failures.append(f"--walkthrough lost `{mark}` from the figure")
        # An invented stage must STOP it. A figure with one box nobody can check is the
        # failure this view exists to prevent, and its reader will not notice.
        with open(spec, "w", encoding="utf-8") as fh:
            fh.write('title = "t"\n[[lane]]\nid = "a"\ntitle = "a"\n'
                     '[[stage]]\nlane = "a"\ntitle = "s"\nverify = "no_existe_xyz"\n')
        code, output = _run(d, d, "--walkthrough", spec)
        if code == 0:
            failures.append("--walkthrough drew a stage that does not resolve")

        # --- the diagram skeleton runs and refuses to invent -------------
        code, output = _run(d, d, "--blueprint")
        if code != 0 or "BLUEPRINT" not in output:
            failures.append(f"--blueprint failed: {output.strip()[:160]}")
        else:
            # `responsibility` empty is the CONTRACT, not an oversight: the moment this file
            # starts filling it in, the tool is guessing what a module is for.
            if "to be named" not in output:
                failures.append("--blueprint filled in `responsibility` — that is the one "
                                "field it must leave for whoever draws the diagram")
            if "CUTS" in output and "do not draw an arrow across" not in output:
                failures.append("--blueprint lost the instruction about cuts")

        # --- the exhaustive reach mode runs and counts its own cut --------
        # It is exercised here because the sibling view `--decisions` shipped broken and had
        # NEVER run: a name held two things and it crashed on every call, with no lock
        # touching it. A view that no check executes is a view nobody knows is alive.
        code, output = _run(d, d, "--sequence", "Datos", "--all")
        if code != 0 or "REACHABLE FROM" not in output:
            failures.append(f"--sequence --all failed: {output.strip()[:160]}")
        elif "UNAMBIGUOUS names" not in output:
            failures.append("--sequence --all lost the unambiguous-reach split")

        # --- the diagram comes out well formed ----------------------------
        code, output = _run(d, d, "--orient", "Datos", "--no-twins",
                               "--flow", "--mermaid")
        if code != 0 or not output.lstrip().startswith("flowchart"):
            failures.append(f"the diagram did not come out: {output.strip()[:160]}")

        # --- the page is generated and carries the embedded renderer ------
        code, output = _run(d, d, "--orient", "Datos", "--flow", "--html")
        if code != 0 or "<!doctype html>" not in output:
            failures.append("the HTML page was not generated")
        elif "mermaid-gz" not in output:
            failures.append("the page came out without the embedded renderer (it would need a network)")

        # --- descubre la config src un subdirectorio ---------------------
        code, output = _run(d, os.path.join(d, "app"), "--map")
        if code != 0 or "project de test" not in output:
            failures.append("it did not discover mcview.toml from a subdirectory")

        # --- a view needing numpy says what to install, it does not blow up
        code, output = _run(d, d, "--k")
        if code == 0:
            pass                       # numpy is installed here: nothing to test
        elif "pip install numpy scipy" not in output:
            failures.append("without numpy, `--k` does not say what to install")

    for x in failures:
        print(f"  ✗ {x}")
    if not failures:
        print("  ✓ portability: copied into a clean directory, it runs census, brief, "
              "flow, diagram and page")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
