"""The turn as a JOURNEY: horizontal lanes, time running to the right.

Mermaid draws a correct `sequenceDiagram` that looks like mermaid. It is fine to paste into a
markdown file; it is no good for looking at a turn and understanding it. Here the drawing is
our own, in SVG —not canvas— for three concrete reasons: it scales without blurring on any
screen, the text can be selected and searched with ctrl-F, and not one line of JS is needed
for it to show.

FORM FOLLOWS THE QUESTION. A turn is "first this, then this, and in the middle it crosses into
the other repository": that is a timeline, and a timeline runs sideways. The vertical columns
of a classic sequenceDiagram force you to read 661 messages downward, which is how you lose
the thread.

Every visible thing says something measured elsewhere:

    lane          the line of work — where the step happens
    x position    the call order, taken from the AST
    lane change   the system changes hands; if the color changes too, it crossed repos
    fill          seen executing (runtime). A hollow outline = NOT OBSERVED, which is not
                  the same as "it does not happen"
    ×N            a stretch that repeats, with its count in view
"""
from __future__ import annotations

import html

ALTO_CARRIL = 62
ANCHO_PASO = 132
MARGEN_IZQ = 208
MARGEN_SUP = 56
RADIO = 7

# The tool's palette, not a new one. The per-project accent is used only to tell repositories
# apart; inside a single one, every lane shares the tone.
TONOS = ["#0F6E5C", "#B26A00", "#5B4BC4", "#B03A5B", "#20707F"]


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _flatten(tree: dict, lane_of) -> list[dict]:
    """The tree flattened into a list in CALL ORDER. Depth is kept as data (it drives the
    indentation) but stops being the axis: the axis is time."""
    out: list[dict] = []

    def descend(n: dict, prof: int):
        for p in n["steps"]:
            out.append({
                "name": p["name"], "loc": p["loc"], "lane": lane_of(p["id"]),
                "prof": prof, "veces": p.get("veces", 1),
                "ejecutado": p.get("ejecutado"),
                "echo_note": p.get("already_told"), "hidden": p.get("hidden", 0),
            })
            descend(p, prof + 1)

    descend(tree, 0)
    return out


def _project(lane: str) -> str:
    """A lane's repository, or empty if the map covers only one. Splitting on «▸» without
    checking it exists returned the whole name, so two lanes from the SAME repo counted as a
    crossing and the entire drawing came out dashed."""
    return lane.split("▸")[0] if "▸" in lane else ""


def draw(weave, r: dict, lane_of) -> str:
    steps = _flatten(r["tree"], lambda sid: lane_of(weave, sid))
    if not steps:
        return "<p>no steps</p>"

    # The lane order is the order of APPEARANCE, not alphabetical: that way the drawing descends
    # diagonally following the narrative instead of zigzagging in an order nobody asked for.
    lanes: list[str] = []
    for p in steps:
        if p["lane"] not in lanes:
            lanes.append(p["lane"])

    projects: list[str] = []
    for c in lanes:
        pr = _project(c)
        if pr not in projects:
            projects.append(pr)

    row = {c: i for i, c in enumerate(lanes)}
    W = MARGEN_IZQ + len(steps) * ANCHO_PASO + 80
    H = MARGEN_SUP + len(lanes) * ALTO_CARRIL + 40

    def y(c: str) -> float:
        return MARGEN_SUP + row[c] * ALTO_CARRIL + ALTO_CARRIL / 2

    def x(i: int) -> float:
        return MARGEN_IZQ + i * ANCHO_PASO

    def tone(c: str) -> str:
        return TONOS[projects.index(_project(c)) % len(TONOS)]

    o = [f'<svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
         f'xmlns="http://www.w3.org/2000/svg" class="journey" role="img" '
         f'aria-label="the turn\'s sequence by lanes">']

    # Lane bands. Alternating and very faint: they separate without competing with the steps.
    for c in lanes:
        yy = MARGEN_SUP + row[c] * ALTO_CARRIL
        if row[c] % 2 == 0:
            o.append(f'<rect x="0" y="{yy}" width="{W}" height="{ALTO_CARRIL}" '
                     f'class="banda"/>')
        o.append(f'<line x1="{MARGEN_IZQ - 16}" y1="{y(c)}" x2="{W - 40}" y2="{y(c)}" '
                 f'class="riel" stroke="{tone(c)}"/>')
        label = c.split("▸")[-1]
        proj = _project(c)
        o.append(f'<text x="{MARGEN_IZQ - 26}" y="{y(c) - 3}" class="lane" '
                 f'text-anchor="end">{_e(label)}</text>')
        if proj:
            o.append(f'<text x="{MARGEN_IZQ - 26}" y="{y(c) + 11}" class="lane-proj" '
                     f'text-anchor="end" fill="{tone(c)}">{_e(proj)}</text>')

    # Connectors: an orthogonal elbow between one step and the next. The lane change is what
    # has to be seen —that is where the system changes hands— so only those carry a marked
    # stroke.
    for i in range(len(steps) - 1):
        a, b = steps[i], steps[i + 1]
        x1, y1, x2, y2 = x(i), y(a["lane"]), x(i + 1), y(b["lane"])
        salta = a["lane"] != b["lane"]
        cruza_repo = _project(a["lane"]) != _project(b["lane"])
        kind = "salto cruce" if cruza_repo else ("salto" if salta else "sigue")
        middle = (x1 + x2) / 2
        o.append(f'<path d="M{x1} {y1} H{middle} V{y2} H{x2}" class="{kind}"/>')

    # The steps.
    for i, p in enumerate(steps):
        cx_, cy_ = x(i), y(p["lane"])
        t = tone(p["lane"])
        seen = p["ejecutado"]
        relleno = t if seen or seen is None else "var(--panel)"
        o.append(f'<circle cx="{cx_}" cy="{cy_}" r="{RADIO}" fill="{relleno}" '
                 f'stroke="{t}" stroke-width="2" class="hito"/>')
        if seen:
            o.append(f'<circle cx="{cx_}" cy="{cy_}" r="{RADIO + 5}" fill="none" '
                     f'stroke="{t}" stroke-width="1" opacity=".33"/>')
        arriba = (i % 2 == 0)
        ty = cy_ - RADIO - 11 if arriba else cy_ + RADIO + 20
        o.append(f'<text x="{cx_}" y="{ty}" class="step" text-anchor="middle">'
                 f'{_e(p["name"][:26])}</text>')
        sub = []
        if p["veces"] > 1:
            sub.append(f'×{p["veces"]}')
        if p["echo_note"]:
            sub.append(f'↑ {p["hidden"]} steps ya narrados')
        if sub:
            o.append(f'<text x="{cx_}" y="{ty + (-12 if arriba else 13)}" '
                     f'class="step-sub" text-anchor="middle">{_e(" · ".join(sub))}</text>')
        o.append(f'<title>{_e(p["name"])} — {_e(p["loc"])}</title>')

    o.append("</svg>")
    return "\n".join(o)


CSS = """
.journey-marco{overflow-x:auto; overflow-y:hidden; border:1px solid var(--line);
  border-radius:14px; background:var(--panel); padding:0 0 8px}
.journey{display:block; min-width:100%}
.journey .banda{fill:color-mix(in srgb, var(--ink) 3%, transparent)}
.journey .riel{stroke-width:2; opacity:.22}
.journey .sigue{fill:none; stroke:color-mix(in srgb, var(--ink) 22%, transparent);
  stroke-width:1.5}
.journey .salto{fill:none; stroke:color-mix(in srgb, var(--ink) 42%, transparent);
  stroke-width:2}
.journey .cruce{fill:none; stroke:var(--accent); stroke-width:2.5; stroke-dasharray:6 4}
.journey .lane{font:600 12.5px system-ui,sans-serif; fill:var(--ink)}
.journey .lane-proj{font:11px ui-monospace,monospace; opacity:.85}
.journey .step{font:12px ui-monospace,SFMono-Regular,monospace; fill:var(--ink)}
.journey .step-sub{font:600 10.5px system-ui,sans-serif; fill:var(--accent)}
.journey .hito{transition:r .12s ease-out}
.journey .hito:hover{r:10}
"""
