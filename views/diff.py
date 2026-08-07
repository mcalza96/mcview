"""Diff mode — what this change did to the repository.

It emits no single score. A composite number is unfalsifiable: if it goes up, nobody knows
which term moved or whether its weight made sense — and the moment it becomes a gate, the
number gets optimized instead of the code.

It returns **typed signals**, each with its own reading and its own confidence. The ones that
can be acted on today are deterministic:

    duplicacion_introducida   a new function with a structural twin already present
    huerfanos_nuevos          added symbols that nothing references
    net_symbols               how much the surface grew or shrank

The mass-based ones (concentration, change heat) are informative, not a verdict: they have to
be backtested against real history before being believed.

Everything is read **per area**: adding 200 cold symbols to `auxiliary` is not the same as
adding them to the core.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

import config as _config
import duplicates as _dup_mod
import heatmap as _heatmap
import factory as _factory
import core as _core


class Snapshot:
    """The project's state at one commit. The expensive part is computed once."""

    def __init__(self, project, cfg):
        self.cfg = cfg
        # IDENTITY WITHOUT THE LINE. The core's id is file:line:name, which works for
        # the graph but NOT for comparing commits: inserting one line above renames
        # everything below it and it shows up as "new". Measured: a +9 symbol commit
        # reported 30 new functions with a twin.
        self.symbols = {}
        for sid, s in project.symbols.items():
            self.symbols[(s.file, s.name)] = (s.file, s.name,
                                                    cfg.area_of(s.file))
        self._ids = {sid: (s.file, s.name) for sid, s in project.symbols.items()}

        levels = project.levels()
        self.dead = {self._ids[x] for x in levels["DEAD_CANDIDATE"] if x in self._ids}
        self.weak = {self._ids[x] for x in levels["ALIVE_PRODUCT_WEAK"] if x in self._ids}

        rank = _heatmap.pagerank(project)
        self.rows = _heatmap.by_file(project, rank)
        self.conc = _heatmap.concentration(self.rows)

        # A whole `duplicates.analyze()` used to run here per snapshot —two per diff— whose
        # only product was a `self.fingerprints` nobody ever read. What the comparison really
        # uses are the `grams` below, which build themselves. Deleting it took 30 s off
        # `--diff` without changing a single number in the report.
        self.esqueletos: dict[str, str] = {}
        self.grams: dict = {}
        for s in project.symbols.values():
            if s.kind != "function" or cfg.excluded_from_duplicates(s.file):
                continue
            esq = project.skeleton(s, cfg.min_statements)
            if esq:
                self.esqueletos[(s.file, s.name)] = hashlib.blake2b(
                    esq.encode(), digest_size=16).hexdigest()[:8]
                # n-grams of the skeleton: the exact hash only sees Type-1/2, and the
                # duplication an agent introduces is Type-3/4 (same work, different
                # code). Measured: with the exact hash, 0/2 known positives.
                self.grams[(s.file, s.name)] = _dup_mod._ngrams(esq)

    def by_area(self) -> dict[str, int]:
        d: dict[str, int] = {}
        for _, _, area in self.symbols.values():
            d[area] = d.get(area, 0) + 1
        return d


def snapshot_of(repo: str, ref: str | None, toml_path: str) -> Snapshot:
    """Analyzes the tree at `ref` (or the working tree if ref is None)."""
    if ref is None:
        cfg = _config.load(toml_path)
        return Snapshot(_factory.make_project(cfg), cfg)

    tmp = tempfile.mkdtemp(prefix="mcview-wt-")
    try:
        subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", "-q", tmp, ref],
                       capture_output=True, text=True, check=True)
        rel_toml = os.path.relpath(os.path.abspath(toml_path), repo)
        toml_tmp = os.path.join(tmp, rel_toml)
        if not os.path.exists(toml_tmp):
            # the .toml may not exist in old commits: the current one is used and
            # reapunta su root al worktree
            os.makedirs(os.path.dirname(toml_tmp), exist_ok=True)
            shutil.copy(os.path.abspath(toml_path), toml_tmp)
        cfg = _config.load(toml_tmp)
        return Snapshot(_factory.make_project(cfg), cfg)
    finally:
        subprocess.run(["git", "-C", repo, "worktree", "remove", "--force", tmp],
                       capture_output=True, text=True)
        shutil.rmtree(tmp, ignore_errors=True)


def compare(before: Snapshot, after: Snapshot) -> dict:
    ids_antes, ids_despues = set(before.symbols), set(after.symbols)
    nuevos = ids_despues - ids_antes
    gone = ids_antes - ids_despues

    # -- duplication introduced: a new function whose skeleton ALREADY existed ---
    THRESHOLD = before.cfg.jaccard_threshold
    dup_intro = []
    for sid in nuevos:
        g = after.grams.get(sid)
        if not g:
            continue
        best, contra = 0.0, None
        for old, gv in before.grams.items():
            if old == sid:
                continue
            inter = len(g & gv)
            if inter < 3:
                continue
            j = inter / len(g | gv)
            if j > best:
                best, contra = j, old
        if best >= THRESHOLD:
            arch, nom, area = after.symbols[sid]
            dup_intro.append({"name": nom, "file": arch, "area": area,
                              "jaccard": round(best, 2),
                              "twin": f"{contra[1]} ({contra[0]})"})

    # -- new orphans -----------------------------------------------------------
    huerfanos = []
    for sid in after.dead - before.dead:
        arch, nom, area = after.symbols[sid]
        huerfanos.append({"name": nom, "file": arch, "area": area,
                          "nuevo": sid in nuevos})

    # -- net per area ----------------------------------------------------------
    a_antes, a_despues = before.by_area(), after.by_area()
    neto = {k: a_despues.get(k, 0) - a_antes.get(k, 0)
            for k in set(a_antes) | set(a_despues)}

    # -- mass ------------------------------------------------------------------
    mass_after = {f["file"]: f["pct"] for f in after.rows}
    touched = {after.symbols[s][0] for s in nuevos} | {before.symbols[s][0] for s in gone}
    heat = sum(mass_after.get(a, 0.0) for a in touched)

    return {
        "duplicacion_introducida": dup_intro,
        "huerfanos_nuevos": huerfanos,
        "net_symbols": neto,
        "net_total": sum(neto.values()),
        "debiles_delta": len(after.weak) - len(before.weak),
        "concentration": {
            "before": before.conc["archivos_50pct"],
            "after": after.conc["archivos_50pct"],
        },
        "change_heat_pct": round(heat, 2),
        "files_touched": len(touched),
    }


def verdict(d: dict) -> tuple[str, list[str]]:
    """A reading in words. NOT a score: these are the signals that fired."""
    signals = []
    if d["duplicacion_introducida"]:
        n = len(d["duplicacion_introducida"])
        signals.append(f"introduces {n} function(s) with a structural twin already in the repo")
    nuevos_huerfanos = [h for h in d["huerfanos_nuevos"] if h["nuevo"]]
    if nuevos_huerfanos:
        signals.append(f"adds {len(nuevos_huerfanos)} symbol(s) that nothing references")
    if d["net_symbols"].get("core", 0) > 0 and d["change_heat_pct"] < 0.05:
        signals.append("adds surface to the core in a cold zone (mass < 0.05%)")
    if d["net_total"] < 0:
        signals.append(f"NET-REDUCE: {abs(d['net_total'])} fewer symbols")

    if not signals:
        return "clean", []
    if any(s.startswith(("introduces", "adds")) for s in signals):
        return "review", signals
    return "clean", signals
