"""Liveness probe — which code ACTUALLY runs. Reference implementation.

**This file is not part of mcview and mcview never imports it.** It has to run inside the
process you want to measure, so it belongs to that project. mcview only reads the JSONL it
leaves behind. Copy it, rename the variables to suit you, or write your own — what mcview
depends on is the FORMAT, described at the bottom.

Static analysis lies about what is alive, and when it is wrong it fails silently. This records
which functions executed at least once.

Instrument: `sys.monitoring` (PEP 669, py3.12+). The callback returns `DISABLE`, which turns
monitoring off *for that code object* after the first hit: each function costs once and nothing
thereafter. That is why it can be left on in a real process without degrading it — it is a
census, not a profiler. Measured overhead over 3M calls: indistinguishable from noise.

DIRECTION — non-negotiable: this probe only PROMOTES to alive. It never proves anything is
dead. A function not showing up may mean it did not run inside the observed window, not that it
is unreachable.

    from liveness_probe import start
    start()                       # a no-op unless MCVIEW_PROBE=1

WHAT HAS TO BE TRUE, and every one of these fails silently:

    MCVIEW_PROBE=1                off by default, on purpose
    Python 3.12+                  no `sys.monitoring` before that; returns False
    MCVIEW_PROBE_DIR writable     returns False on OSError
    code under MCVIEW_PROBE_ROOT  anything outside is filtered out as foreign
    start() runs in the DEPLOYED process
    no other profiler holds PROFILER_ID

Two traps that produced an empty census, both measured in a real deployment: the probe was not
in the baked image, and the container started the service in-process so the `main()` holding
the call never ran. Both look identical from outside — "on", and empty. **Check that the file
exists and has lines**, not that the variable is set.

WHERE TO WRITE IT. mcview reads `<project root>/.mcview/` and `<project root>/.salud/`, and
only files whose name contains `liveness`. Point `MCVIEW_PROBE_DIR` at one of those, or copy
the files in.
"""
from __future__ import annotations

import atexit
import json
import os
import sys
import threading
import time

_ACTIVE = False
_seen: set[tuple[str, str, int]] = set()
_pending: list[tuple[str, str, int]] = []
_lock = threading.Lock()
_path: str | None = None
_t0 = time.time()


def _flush() -> None:
    """Append what is pending. Append-only: it survives crashes and restarts."""
    global _pending
    with _lock:
        if not _pending or not _path:
            return
        batch, _pending = _pending, []
    try:
        with open(_path, "a", encoding="utf-8") as f:
            for file, qualname, line in batch:
                f.write(json.dumps(
                    {"f": file, "q": qualname, "l": line, "t": int(time.time())},
                    ensure_ascii=False) + "\n")
    except OSError:
        pass  # the probe must NEVER take down the process it observes


def _loop(interval: float) -> None:
    while True:
        time.sleep(interval)
        _flush()


def start(flush_interval: float = 30.0) -> bool:
    """Start the probe. Returns True if it ended up active.

    A no-op unless MCVIEW_PROBE=1 — off by default on purpose: turning on observability nobody
    asked for is exactly the kind of change nobody can later explain.

    It returns False rather than raising, on every one of its preconditions, because it is
    wired into process startup and must not block it. That is also why it fails quietly, which
    is why the caller should check `state()` rather than trust the return.
    """
    global _ACTIVE, _path

    if _ACTIVE or os.getenv("MCVIEW_PROBE") != "1":
        return False
    mon = getattr(sys, "monitoring", None)
    if mon is None:  # py < 3.12
        return False

    directory = os.getenv("MCVIEW_PROBE_DIR", "/tmp/mcview")
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return False
    # The HOSTNAME goes in the name, and it is not cosmetic. Under Docker the pid is 1 in
    # EVERY container, so `liveness-{pid}-{t0}` discriminates only by the start second:
    # measured on a real deployment, bringing up three services against the same mounted
    # directory produced 2 files for 3 processes — two started within the same second and
    # ended up interleaved in one. No symbol is lost (the JSONL is append-only and every file
    # is read), but WHICH PROCESS each line came from is, and that is exactly what separates
    # "the enrichment never ran" from "it ran in a process nobody was watching".
    _host = os.uname().nodename if hasattr(os, "uname") else "host"
    _path = os.path.join(directory, f"liveness-{_host}-{os.getpid()}-{int(_t0)}.jsonl")

    root = os.getenv("MCVIEW_PROBE_ROOT", "/app")

    def on_enter(code, offset):
        file = code.co_filename
        # own code only: stdlib and site-packages are noise, and they cost
        if not file.startswith(root) or "/site-packages/" in file:
            return mon.DISABLE
        key = (file, code.co_qualname, code.co_firstlineno)
        if key not in _seen:
            _seen.add(key)
            with _lock:
                _pending.append(key)
        return mon.DISABLE  # ← the trick: this function never costs anything again

    tool_id = mon.PROFILER_ID
    try:
        mon.use_tool_id(tool_id, "mcview_probe")
    except ValueError:
        return False  # another profiler already took the slot; do not fight over it
    mon.register_callback(tool_id, mon.events.PY_START, on_enter)
    mon.set_events(tool_id, mon.events.PY_START)

    threading.Thread(target=_loop, args=(flush_interval,), daemon=True).start()
    atexit.register(_flush)
    _ACTIVE = True
    return True


def state() -> dict:
    """Expose this somewhere reachable — a health endpoint, a log line at startup.

    It is the only cheap way to tell "measured nothing" from "was never measuring", and those
    two are indistinguishable from the census alone.
    """
    return {
        "active": _ACTIVE,
        "symbols_seen": len(_seen),
        "pending": len(_pending),
        "path": _path,
        "window_seconds": int(time.time() - _t0),
    }


# THE FORMAT mcview READS — one JSON object per line, appended:
#
#     {"f": "/app/api/routers/x.py", "q": "create_user", "l": 42, "t": 1786055053}
#
#     f  absolute path inside the running process. mcview trims it to a project-relative path
#        by the longest suffix that is a known file — no declared prefix that can age out.
#     q  `co_qualname`. mcview takes the last dotted segment, so methods match their own name.
#     l  `co_firstlineno`. Matched against the inventory with a ±3 tolerance, because the probe
#        stamps the code object's first line and the inventory stamps the `def` — with
#        decorators those are not the same line.
#     t  unix seconds of first sighting. Used for the observed window and for ordering.
#
# A symbol is confirmed only when FILE, NAME and LINE all match. By name alone, a project's 96
# `main`s would all be confirmed by the single one that ran.
