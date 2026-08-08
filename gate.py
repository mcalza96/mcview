#!/usr/bin/env python3
"""Pre-write gate — warns if what is about to be written already exists.

It hooks in as a `PreToolUse` hook over `Write`/`Edit`. Before the code reaches disk, it
queries the cached index and tells the model where the similar thing already in the repo
lives.

It exists because the measurement is clear: agents generate redundant code **because they
do not explore the tree before writing**. Relying on the agent remembering to search does
not work — it does not fail because of prompt wording but because the correct order
competes with the task. The hook is mechanical and cannot be skipped.

TWO RULES, both deliberate:

* **It never blocks.** `permissionDecision: "allow"`, always. Two functions with the same
  shape can be real duplication or two legitimate faces of an API; the one who decides is
  the one reading, not the gate.
* **Fail-open.** Any error, timeout or missing index → empty output and the write goes
  through. A hygiene tool can NEVER stop the work.

Threshold 0.75 by default. Measured over 45 real files in this repo: it fires on 13%. At
0.55 it would catch more real duplication but would fire on 58% — and a gate that shouts on
most writes becomes invisible.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

THRESHOLD = float(os.getenv("MCVIEW_GATE_THRESHOLD", "0.75"))
MAX_WARNINGS = 6


def _silently():
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
    sys.exit(0)


def main():
    try:
        entry = json.load(sys.stdin)
    except Exception:
        _silently()

    ti = entry.get("tool_input") or {}
    # the field name differs across versions/tools: both are accepted
    path = ti.get("file_path") or ti.get("path") or ""
    content = ti.get("content") or ti.get("new_string") or ""
    if not path.endswith(".py") or not content.strip():
        _silently()

    try:
        import config as _config
        import index as _index

        # The config is DISCOVERED from the file being written, the same way every other
        # entrypoint discovers it. The old default — `mcview/mcview.toml`, INSIDE the tool —
        # is a path `check_portability` forbids, so the gate was fail-opening on every
        # write since the config moved out: dead for months, indistinguishable from quiet.
        toml = os.getenv("MCVIEW_CONFIG") or _config.discover(
            src=os.path.dirname(os.path.abspath(path)))
        if not toml:
            _silently()               # no project config anywhere above the file
        cfg = _config.load(toml)

        if _index.load(cfg) is None:
            _silently()               # cold: building here would be slow — run --exists once
        # warm refresh: re-parses only what changed (73 ms measured on 762 files), so the
        # gate never compares against yesterday's photo of the repo.
        idx = _index.build(cfg)

        rel = os.path.relpath(os.path.abspath(path), cfg.root)
        if rel.startswith(".."):
            _silently()               # outside the configured project

        r = _index.query(idx, content, rel, threshold=THRESHOLD)
    except Exception:
        _silently()

    lines = []
    for c in r["by_shape"][:MAX_WARNINGS]:
        lines.append(f"- `{c['name']}` has the shape of a {c['kind']} "
                     f"(jaccard {c['jaccard']}) matching `{c['already_in']}`")
    seen = set()
    for c in r["by_name"][:MAX_WARNINGS]:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        lines.append(f"- a {c['kind']} called `{c['name']}` already exists "
                     f"in `{c['already_in']}`")

    if not lines:
        _silently()

    warning = (
        "mcview/gate: part of what you are about to write already exists in the repo.\n"
        + "\n".join(lines)
        + "\n\nCheck whether reusing or extending what is there beats writing a variant. "
          "If it is deliberate (two faces of an API, implementations of a protocol), carry "
          "on."
    )
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "additionalContext": warning[:9000],
    }}))
    sys.exit(0)


if __name__ == "__main__":
    main()
