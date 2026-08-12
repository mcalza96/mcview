# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""The root of an SVG figure, with the metadata that makes it readable without eyes.

Measured before this existed: of the three SVG figures the tool produces, the walkthrough
had NO `role`, no `<title>` and no `<desc>`; the journey had `role` and an `aria-label`
but no description. A diagram whose whole content is geometry is, to a screen reader,
an empty box — and mcview's figures are meant to be pasted into documents other people
read.

THREE RULES, and the reason each one is here rather than in a style guide:

* **`<title>` FIRST CHILD, and short.** It is the accessible name; a name that arrives
  after the drawing has already been announced arrives too late. Long titles are not
  truncated away — the full text moves into `<desc>`, because dropping it silently is
  the failure this module exists to stop, not a formatting nicety.
* **`<desc>` says WHAT IT SHOWS, not what it looks like.** "Three lanes, twelve boxes"
  describes the geometry, which is exactly what somebody who cannot see it does not
  need. What they need is the claim the figure makes.
* **IDs are PREFIXED.** `walkthrough` defines `<marker id="p">`. Two figures inlined in
  one page would both define `p`, and the second one's arrows would silently point at
  the first one's marker — a defect invisible in the code of either.
"""
from __future__ import annotations

import html

TITLE_MAX = 60


def _e(s: str) -> str:
    return html.escape(str(s), quote=True)


def open_svg(*, uid: str, width: float, height: float, title: str, desc: str,
             view_box: str | None = None, extra: str = "") -> str:
    """The opening tag plus `<title>`/`<desc>`. `uid` prefixes every id in the figure.

    Returns the string the renderer starts its element list with; the caller closes with
    `</svg>` as before.
    """
    vb = view_box or f"0 0 {width:.0f} {height:.0f}"
    corto = title if len(title) <= TITLE_MAX else title[:TITLE_MAX - 1].rstrip() + "…"
    # nothing is lost: a title too long to be a name still has to be readable somewhere
    completo = desc if corto == title else f"{title}. {desc}"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vb}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" '
        f'aria-labelledby="{uid}-t {uid}-d"{(" " + extra) if extra else ""}>'
        f'<title id="{uid}-t">{_e(corto)}</title>'
        f'<desc id="{uid}-d">{_e(completo)}</desc>'
    )


def node_title(text: str) -> str:
    """A per-element tooltip, which ONLY works wrapped around its element.

    `journey.py` emitted these as siblings of the circles, flat at the root of the SVG.
    A `<title>` that is not a child of the shape it describes is not that shape's
    tooltip — and several of them at the root are just competing document names. They
    rendered nothing and read as if the figure were annotated.
    """
    return f"<title>{_e(text)}</title>"
