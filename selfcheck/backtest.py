"""Backtest — judging the tool before letting it judge commits.

A tool that evaluates changes without having been evaluated AGAINST real changes is exactly
the thing nobody can later tell works. This runs it over the history and shows which signals
fire and how often.

What is wanted is NOT that it "detects" a lot: a signal firing on 90% of commits discriminates
nothing. What is wanted is that it fires **rarely and on the right commits** — the final
judgement belongs to the human who knows those commits.

    python3 mcview/backtest.py [N] [--config path.toml]
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import diff as _dif   # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = int(args[0]) if args else 20
    toml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mcview.toml")
    if "--config" in sys.argv:
        toml_path = sys.argv[sys.argv.index("--config") + 1]

    repo = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                          capture_output=True, text=True, check=True).stdout.strip()

    log = subprocess.run(
        ["git", "-C", repo, "log", f"-{n + 1}", "--format=%h\t%s"],
        capture_output=True, text=True, check=True).stdout.strip().split("\n")
    commits = [l.split("\t", 1) for l in log if "\t" in l]
    commits.reverse()                      # oldest to newest

    print(f"backtest over {len(commits) - 1} commits · {os.path.basename(repo)}\n")

    t0 = time.time()
    previa = _dif.snapshot_of(repo, commits[0][0], toml_path)
    resultados, count = [], Counter()

    for i in range(1, len(commits)):
        sha, asunto = commits[i]
        try:
            current = _dif.snapshot_of(repo, sha, toml_path)
        except subprocess.CalledProcessError:
            print(f"  {sha}  (no analizable)")
            continue
        d = _dif.compare(previa, current)
        v, signals = _dif.verdict(d)
        resultados.append((sha, asunto, v, signals, d))
        count[v] += 1
        for s in signals:
            count[s.split(":")[0][:28]] += 1

        mark = {"revisar": "!", "limpio": " "}[v]
        neto = d["net_total"]
        print(f"  {mark} {sha}  {neto:+5d} sym  {asunto[:52]}")
        for s in signals:
            print(f"        └ {s}")
        previa = current

    print(f"\n{'='*68}")
    print(f"  {len(resultados)} commits en {time.time() - t0:.0f}s "
          f"({(time.time() - t0) / max(len(resultados), 1):.1f}s per commit)\n")
    total = max(len(resultados), 1)
    for k, v in count.most_common():
        print(f"    {v:4d}  ({100 * v / total:4.0f}%)  {k}")

    print(f"\n  A signal that fires on most commits does NOT discriminate.")
    print(f"  Whether it got it right is your call: you know these commits.\n")


if __name__ == "__main__":
    main()
