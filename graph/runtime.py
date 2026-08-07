"""What ACTUALLY ran. It confirms; it never rules out.

The sequence that comes out of the AST is the WRITTEN order. This module brings the other
side: what really executed, according to the census the measured project's probe leaves
behind.

**It is never exclusionary, and that is the whole rule.** A step that appears in the census
is CONFIRMED; one that does not appear is **neither dropped nor marked false** — it may not
have run inside the observed window, it may sit behind an `if` that did not hold that day,
or nobody may have turned the probe on in that process. Absence of evidence is not evidence
of absence, and it is the same rule the liveness census already applies: the probe only
PROMOTES to alive, never demotes to dead. Inverting it would turn a confirmation tool into
a deletion tool, which is the expensive mistake.

What can be asserted once the census is there: that a path believed to be theoretical does
happen, and —because the probe stamps the time— in what order it happened the first time.

WHERE IT READS FROM. `<root>/.mcview/` and `<root>/.salud/`. The second is not an oversight:
the probe lives on the PRODUCT side (`pkg/observability/liveness_probe.py`, switched on with
`SALUD_PROBE=1` in the compose file) and its directory was not renamed along with the tool,
because renaming a deployment environment variable is a different change with a different
verification. Reading both is the honest thing to do while that stays true.
"""
from __future__ import annotations

import glob
import json
import os

DIRS = (".mcview", ".salud")


def read_rows(root: str) -> dict[str, dict]:
    """`{relative_file: {name: {"line": int, "t": int}}}` for everything observed.

    The census's `f` is the path INSIDE the container (`/app/pkg/...`): the probe runs in
    the deployed process, not here. It is trimmed by the longest suffix that matches a file
    in the project rather than by declaring the prefix — `/app` today, something else
    tomorrow, and a declared path that ages leaves the census at zero without saying why.
    """
    out: dict[str, dict] = {}
    for d in DIRS:
        for path in sorted(glob.glob(os.path.join(root, d, "*.jsonl"))):
            if "liveness" not in os.path.basename(path):
                continue
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue          # append-only file: the last line may be cut off
                    f, q, l, t = r.get("f"), r.get("q"), r.get("l"), r.get("t")
                    if not f or not q:
                        continue
                    name = q.split(".")[-1]
                    prev = out.setdefault(f, {}).get(name)
                    if prev is None or (t or 0) < prev["t"]:
                        out[f][name] = {"line": l, "t": t or 0}
    return out


def observed(project, root: str) -> dict[str, int]:
    """`{symbol id: timestamp of its first execution}`.

    Matching is by FILE + NAME + LINE, and all three conditions matter: by name alone, the
    project's 96 `main`s would all be confirmed by the single one that ran. The line is
    compared with a tolerance because the probe stamps the first line of the code object
    while the inventory stamps the `def` — with decorators those are not the same line.
    """
    census = read_rows(root)
    if not census:
        return {}
    # `/app/api/v1/routers/x.py` → `api/v1/routers/x.py`: it looks for the longest suffix
    # that is a known file, so there is no declared prefix that can age out.
    by_suffix: dict[str, str] = {}
    known = {s.file for s in project.symbols.values()}
    for f in census:
        parts = f.strip("/").split("/")
        for i in range(len(parts)):
            cand = "/".join(parts[i:])
            if cand in known:
                by_suffix[f] = cand
                break

    out: dict[str, int] = {}
    for f, names in census.items():
        rel = by_suffix.get(f)
        if not rel:
            continue
        for sid, s in project.symbols.items():
            if s.file != rel:
                continue
            seen = names.get(s.name)
            if seen and abs((seen["line"] or s.line) - s.line) <= 3:
                out[sid] = seen["t"]
    return out


def summary(project, observed_: dict[str, int]) -> dict:
    total = len(project.symbols)
    return {
        "observed": len(observed_),
        "of": total,
        "pct": round(len(observed_) / total * 100, 1) if total else 0.0,
        "window_s": (max(observed_.values()) - min(observed_.values())
                     if observed_ else 0),
    }
