"""A JOURNEY as a figure — lanes, stages in order, and the cuts drawn as cuts.

The other views answer over a graph, and a graph has no "before". Somebody asking "what happens
from the message to the answer" is asking for a SEQUENCE, and the honest answer has a shape no
call graph carries: stages grouped into lanes, in an order a person knows.

So this view does not infer the journey. **It receives it** — a small `.toml` naming the lanes,
the stages and their order — and does the four things it can actually do:

    verify     every stage names a target that RESOLVES. A box for something that does not
               exist is the failure a diagram cannot survive, because whoever reads it is not
               going to check
    cuts       drawn as a band across the figure, never as an arrow. Past a dispatch the
               target is chosen BY NAME; an arrow there invents a call
    caveats    printed IN the figure, not left in a JSON nobody opens
    layout     a canvas that grows with the content

WHY THE SPEC IS AN INPUT AND NOT A GUESS. `journey.py` draws one box per CALL, taken from the
AST, and for a real turn that is 100 boxes across 11,772 px — a hairline nobody can read. The
useful unit is the STAGE ("1 · GATHER — reunir evidencia"), which is a grouping a person makes.
The tool cannot invent it and should not pretend to.

THREE LAYOUT DEFECTS, prevented by construction rather than by care. They come from a
hand-made figure where they were only visible once it was opened: a label covering the
neighbouring box's text, a diagonal arrow crossing a lane title, and a footer outside the
canvas. So: text is measured before anything is placed, arrows are L-shaped and never diagonal,
and the canvas height is computed from the content instead of being a constant.

    mcview --walkthrough docs/turno.toml            # SVG to stdout
    mcview --walkthrough docs/turno.toml --png out.png
"""
from __future__ import annotations

import html
import os
import shutil
import subprocess
import tomllib

# Measured in a browser at these sizes, and it only has to be an UPPER bound: the wrap breaks
# earlier than it must, which costs a line and never overlaps. Guessing low is what puts one
# box's text on top of the next.
CHAR_W = {"titulo": 8.4, "nota": 6.3, "medida": 6.0}

BOX_W, BOX_MIN_H = 300, 96
MARGIN, GAP = 28, 18
WIDTH = 1360


def load(path: str) -> dict:
    with open(path, "rb") as f:
        return tomllib.load(f)


def verify(project, spec: dict) -> list[str]:
    """Every `verify` target must resolve. Returns the failures.

    This is the property that makes the figure worth trusting: a box whose target does not
    resolve is a box somebody invented, and the reader —by construction someone who will not
    open the code— has no way to tell. A stage with no `verify` is allowed and reported, so
    "not checked" never looks like "checked".
    """
    import locks as _locks

    failures = []
    for st in spec.get("stage", []):
        target = st.get("verify")
        if not target:
            failures.append(f"stage «{st.get('title', '?')}»: no `verify` — it cannot be checked")
            continue
        # The weave has its OWN resolver —`project▸target`— and the project's does not know
        # the prefix. Calling the wrong one reports "does not resolve" for targets that do,
        # which is a verification that fails closed on correct input: the worst kind.
        ids, err = (project.resolve(target) if hasattr(project, "resolve")
                    else _locks._resolve(project, target))
        if err or not ids:
            failures.append(f"stage «{st.get('title', '?')}»: «{target}» does not resolve"
                          f"{' — ' + err if err else ''}")
    lane_ids = {c["id"] for c in spec.get("lane", [])}
    for st in spec.get("stage", []):
        if st.get("lane") not in lane_ids:
            failures.append(f"stage «{st.get('title', '?')}»: lane «{st.get('lane')}» not declared")
    for cut in spec.get("cut", []):
        if cut.get("after") not in lane_ids:
            failures.append(f"cut after «{cut.get('after')}»: that lane is not declared")
    return failures


def _wrap(text: str, width_px: float, kind: str) -> list[str]:
    """Word wrap by MEASURED width, not by character count.

    Counting characters treats `iii` and `WWW` as equal and puts the long one over the next
    box. It is an approximation —no font metrics without a font engine— but it is an upper
    bound, so it breaks early and never late.
    """
    if not text:
        return []
    advance = CHAR_W[kind]
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) * advance <= width_px or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _box_height(st: dict) -> float:
    n = len(_wrap(st.get("note", ""), BOX_W - 32, "nota"))
    m = len(_wrap(st.get("measured", ""), BOX_W - 32, "medida"))
    return max(BOX_MIN_H, 46 + n * 17 + (14 + m * 15 if m else 0))


def draw(spec: dict, cuts: list[dict] | None = None,
         caveats: dict | None = None) -> str:
    # DOS fuentes y una sola lista: el `[[cut]]` de la spec dice DÓNDE va el cut (`after`),
    # y el blueprint dice QUÉ cortes existen de verdad. Tomar sólo los del blueprint dejaba
    # `after` sin llenar y el cut no se dibujaba — la figura salía sin lo más importante que
    # tiene, y sin ningún error.
    declared = list(spec.get("cut", []))
    real_cuts = {(c.get("at") or c.get("id")) for c in (cuts or [])}
    for c in declared:
        c.setdefault("kind", "declared")
        if c.get("at") and c["at"] not in real_cuts:
            c["ojo"] = True             # declarado en la spec y no confirmado por el blueprint
    cuts = declared or list(cuts or [])
    by_lane: dict[str, list[dict]] = {}
    for st in spec.get("stage", []):
        by_lane.setdefault(st["lane"], []).append(st)

    # ── layout, computed before a single element is emitted ──────────────────
    # The canvas has to grow with the content. A constant height is how a footer ends up
    # outside the viewBox, invisible and impossible to notice from the code.
    usable = WIDTH - 2 * MARGIN
    per_row = max(1, int((usable - 2 * GAP) // (BOX_W + GAP)))
    plan, y = [], 96
    cut_after = {c["after"]: c for c in cuts if c.get("after")}
    for lane in spec.get("lane", []):
        stages = by_lane.get(lane["id"], [])
        rows = [stages[i:i + per_row] for i in range(0, len(stages), per_row)] or [[]]
        row_heights = [max((_box_height(s) for s in row), default=40) for row in rows]
        height = 44 + sum(row_heights) + GAP * (len(rows) - 1) + 18
        plan.append({"lane": lane, "y": y, "height": height, "rows": rows,
                     "row_heights": row_heights})
        y += height + 20
        if lane["id"] in cut_after:
            y += 74
    # MEDIDO, no estimado. Con una constante el último caveat quedaba fuera del viewBox:
    # invisible en el SVG e imposible de notar leyendo el código. Es el tercero de los tres
    # defectos que este módulo dice prevenir por construcción, cometido en su primera figura.
    lineas_pie = sum(len(_wrap(f"· {k}: {v}", usable - 10, "nota")) + 1
                     for k, v in (caveats or {}).items())
    total_h = y + 46 + 21 + lineas_pie * 16 + 24

    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {total_h:.0f}" '
         f'width="{WIDTH}" height="{total_h:.0f}" font-family="-apple-system,Segoe UI,'
         f'Helvetica,Arial,sans-serif">',
         f'<rect width="{WIDTH}" height="{total_h:.0f}" fill="#FFFFFF"/>']
    q = html.escape

    o.append(f'<text x="{MARGIN}" y="46" font-size="27" font-weight="700" fill="#0F172A">'
             f'{q(spec.get("title", "recorrido"))}</text>')
    if spec.get("subtitle"):
        o.append(f'<text x="{MARGIN}" y="72" font-size="13" fill="#64748B">'
                 f'{q(spec["subtitle"])}</text>')

    for p in plan:
        lane, y0, height = p["lane"], p["y"], p["height"]
        tint = lane.get("color", "#F8FAFC")
        o.append(f'<rect x="{MARGIN}" y="{y0}" width="{usable}" height="{height}" rx="14" '
                 f'fill="{tint}" stroke="#E2E8F0"/>')
        o.append(f'<text x="{MARGIN + 20}" y="{y0 + 26}" font-size="11.5" font-weight="700" '
                 f'letter-spacing="1.1" fill="#94A3B8">{q(lane.get("title", lane["id"]).upper())}</text>')

        yy = y0 + 44
        for row, alto_fila in zip(p["rows"], p["row_heights"]):
            for i, st in enumerate(row):
                x = MARGIN + 20 + i * (BOX_W + GAP)
                h = _box_height(st)
                o.append(f'<rect x="{x}" y="{yy}" width="{BOX_W}" height="{h:.0f}" rx="10" '
                         f'fill="#FFFFFF" stroke="{st.get("color", "#CBD5E1")}"/>')
                o.append(f'<text x="{x + 16}" y="{yy + 26}" font-size="14" font-weight="700" '
                         f'fill="#0F172A">{q(st.get("title", ""))}</text>')
                ty = yy + 46
                for ln in _wrap(st.get("note", ""), BOX_W - 32, "nota"):
                    o.append(f'<text x="{x + 16}" y="{ty}" font-size="11.5" fill="#475569">'
                             f'{q(ln)}</text>')
                    ty += 17
                if st.get("measured"):
                    ty += 8
                    for ln in _wrap(st["measured"], BOX_W - 32, "medida"):
                        o.append(f'<text x="{x + 16}" y="{ty}" font-size="11" font-weight="600" '
                                 f'fill="#047857">{q(ln)}</text>')
                        ty += 15
                # The arrow to the next stage: horizontal, INSIDE the row. Never diagonal —
                # a long diagonal is what crossed a lane title in the figure this replaces.
                # Un carril de ALTERNATIVAS no encadena: dos puertas por las que se puede
                # entrar no son dos pasos. Una flecha entre ellas afirma un orden que no existe.
                if i + 1 < len(row) and not lane.get("alternatives"):
                    xa = x + BOX_W
                    o.append(f'<path d="M {xa + 3} {yy + h / 2:.0f} H {xa + GAP - 4}" '
                             f'stroke="#94A3B8" stroke-width="1.6" marker-end="url(#p)"/>')
            yy += alto_fila + GAP

        cut = cut_after.get(lane["id"])
        if cut:
            yc = y0 + height + 12
            o.append(f'<rect x="{MARGIN}" y="{yc}" width="{usable}" height="52" rx="8" '
                     f'fill="#FFFBEB" stroke="#F59E0B" stroke-width="2" '
                     f'stroke-dasharray="9 6"/>')
            txt = cut.get("text") or (
                f'CUT — {cut.get("kind", "seam")} {cut.get("at") or cut.get("id", "")}: '
                f'the target is chosen BY NAME. No call crosses this line.')
            o.append(f'<text x="{WIDTH / 2:.0f}" y="{yc + 31}" font-size="13" font-weight="700" '
                     f'text-anchor="middle" fill="#B45309">{q(txt)}</text>')

    yf = y + 24
    o.append(f'<text x="{MARGIN}" y="{yf}" font-size="12.5" font-weight="700" fill="#0F172A">'
             f'What this figure does NOT claim</text>')
    for k, v in (caveats or {}).items():
        yf += 14
        for ln in _wrap(f"· {k}: {v}", usable - 10, "nota"):
            o.append(f'<text x="{MARGIN}" y="{yf}" font-size="11" fill="#64748B">{q(ln)}</text>')
            yf += 16

    o.append('<defs><marker id="p" markerWidth="7" markerHeight="7" refX="6" refY="3.5" '
             'orient="auto"><path d="M0,0 L7,3.5 L0,7 z" fill="#94A3B8"/></marker></defs>')
    o.append("</svg>")
    return "\n".join(o)


def to_png(svg: str, destino: str) -> str | None:
    """PNG only if a converter is already on the machine.

    mcview ships with zero dependencies and that is why the diagram renderer travels vendored
    and compressed instead of coming from a CDN. Rasterising needs a real font engine, so
    either an external binary or a new dependency — and the second would break the promise for
    everybody in order to serve the case where somebody wants a bitmap. The SVG is always
    written: it scales without blurring and its text can be searched.
    """
    conv = shutil.which("rsvg-convert") or shutil.which("cairosvg")
    if not conv:
        return None
    tmp = destino + ".svg"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(svg)
    try:
        if conv.endswith("cairosvg"):
            subprocess.run([conv, tmp, "-o", destino], check=True, capture_output=True)
        else:
            subprocess.run([conv, "-w", "2400", tmp, "-o", destino],
                           check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError):
        return None
    finally:
        os.remove(tmp)
    return destino
