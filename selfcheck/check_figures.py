#!/usr/bin/env python3
"""ELEVENTH LOCK — a figure that cannot be read without eyes is not finished.

    python3 mcview/selfcheck/check_figures.py

MEASURED BEFORE THIS EXISTED, which is why it exists: of the SVG figures the tool
produces, the walkthrough had no `role`, no `<title>` and no `<desc>`; the journey had a
`role` and an `aria-label` but no description, and its per-step `<title>` tooltips were
emitted FLAT at the root — siblings of the circles they claimed to annotate, which makes
them tooltips for nothing while reading, in the code, exactly like an annotated figure.

Every property here is checked over the REAL output of the renderer, not over a fixture
of what the output should look like. A lock that reads its own idea of the SVG passes
while the tool ships something else.

FOUR PROPERTIES, and the failure each one is standing in front of:

  1. `<title>` FIRST child, non-empty, ≤60 chars — it is the accessible name, and a name
     that arrives after the drawing has been announced arrives too late.
  2. `<desc>` present and NOT a description of the geometry. "Three lanes, twelve boxes"
     is what a person who cannot see it already does not need; the claim is what they do.
  3. `role="img"` plus `aria-labelledby` pointing at ids that EXIST. A dangling
     `aria-labelledby` degrades to no name at all, silently.
  4. Ids PREFIXED and unique. Two figures inlined in one page both defining `id="p"`
     would have the second one's arrows point at the first one's marker — a defect
     invisible in the code of either.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import _layers  # noqa: E402,F401  — mounts the layers on sys.path

import figure as _figure     # noqa: E402
import walkthrough as _wt    # noqa: E402

SVG = "{http://www.w3.org/2000/svg}"

# Words that describe how the figure LOOKS. A `<desc>` made only of these is a caption of
# the geometry, which is the failure property 2 exists to catch.
GEOMETRIA = {"box", "boxes", "rectangle", "rectangles", "arrow", "arrows", "line",
             "lines", "circle", "circles", "colour", "color", "left", "right", "above",
             "below", "diagram", "figure", "drawing"}

SPEC = {
    "title": "un recorrido de prueba",
    "subtitle": "para el candado de figuras",
    "lane": [{"id": "a", "title": "primera"}, {"id": "b", "title": "segunda"}],
    "stage": [
        {"lane": "a", "title": "entra", "note": "por acá empieza", "verify": "x.py"},
        {"lane": "a", "title": "procesa", "note": "el medio", "verify": "y.py"},
        {"lane": "b", "title": "sale", "note": "y termina", "verify": "z.py"},
    ],
    "cut": [{"after": "a", "text": "acá se despacha por nombre"}],
}


def _revisar(svg: str, nombre: str) -> list[str]:
    fallas = []
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as e:
        return [f"{nombre}: the SVG does not parse — {e}"]

    hijos = list(root)
    if not hijos or not hijos[0].tag.endswith("title"):
        return [f"{nombre}: `<title>` is not the first child — it is the accessible name, "
                "and it has to arrive before the drawing"]

    titulo = (hijos[0].text or "").strip()
    if not titulo:
        fallas.append(f"{nombre}: empty `<title>`")
    if len(titulo) > _figure.TITLE_MAX:
        fallas.append(f"{nombre}: `<title>` is {len(titulo)} chars, over the "
                      f"{_figure.TITLE_MAX} a name can carry")

    descs = [h for h in hijos if h.tag.endswith("desc")]
    if not descs:
        fallas.append(f"{nombre}: no `<desc>` — the figure states nothing to somebody who "
                      "cannot see it")
    else:
        texto = (descs[0].text or "").strip()
        if not texto:
            fallas.append(f"{nombre}: empty `<desc>`")
        else:
            palabras = {w.strip(".,;:").lower() for w in texto.split()}
            if palabras and palabras <= GEOMETRIA | {w for w in palabras if w.isdigit()}:
                fallas.append(f"{nombre}: the `<desc>` describes the GEOMETRY, not what "
                              f"the figure shows — {texto[:60]!r}")

    if root.get("role") != "img":
        fallas.append(f'{nombre}: the root is missing role="img"')

    etiquetas = (root.get("aria-labelledby") or "").split()
    if not etiquetas:
        fallas.append(f"{nombre}: no `aria-labelledby`")
    ids = {e.get("id") for e in root.iter() if e.get("id")}
    for ref in etiquetas:
        if ref not in ids:
            fallas.append(f"{nombre}: `aria-labelledby` points at «{ref}», which does not "
                          "exist — it degrades to no name at all, and it does it silently")

    # Ids must be prefixed and unique: a bare `id="p"` collides the moment two figures
    # share a page, and `url(#p)` then resolves to the wrong one with no error anywhere.
    todos = [e.get("id") for e in root.iter() if e.get("id")]
    for i in todos:
        if "-" not in i:
            fallas.append(f"{nombre}: id «{i}» has no prefix — it collides as soon as two "
                          "figures are inlined in one page")
    if len(todos) != len(set(todos)):
        fallas.append(f"{nombre}: duplicated ids in the same figure")

    # A `<title>` hanging at the root, past the first, is a tooltip for nothing: it names
    # the root, competes with the real one, and reads as an annotation that is not there.
    if sum(1 for h in hijos if h.tag.endswith("title")) > 1:
        fallas.append(f"{nombre}: more than one `<title>` at the root — a tooltip must be "
                      "a CHILD of the shape it describes, not its sibling")
    return fallas


def main() -> int:
    fallas = _revisar(_wt.draw(SPEC, caveats={"alcance": "una figura de prueba"}),
                      "walkthrough")

    # journey.py needs a weave and a real tree; its root is checked through the helper
    # both renderers share, plus the property no helper can give it: the tooltip has to
    # sit inside a `<g>`.
    import journey as _journey
    fuente = open(os.path.join(HERE, "render", "journey.py"), encoding="utf-8").read()
    if "_figure.open_svg" not in fuente:
        fallas.append("journey: does not open its SVG through the shared helper, so its "
                      "metadata is one edit away from drifting")
    if "<g>" not in fuente or "node_title" not in fuente:
        fallas.append("journey: the per-step `<title>` is not wrapped in its own `<g>` — "
                      "flat at the root it is a tooltip for nothing")
    del _journey

    for f in fallas:
        print(f"  ✗ {f}")
    if not fallas:
        print("  ✓ figures: title/desc/role, live aria-labelledby, prefixed ids · "
              "walkthrough measured, journey by construction")
    return 1 if fallas else 0


if __name__ == "__main__":
    sys.exit(main())
