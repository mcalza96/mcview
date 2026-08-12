# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""ONE palette, in semantic ROLES, for the four figures the tool draws.

It was not duplication that motivated this — it was DISAGREEMENT. Measured before the
change: 100 colour literals across the four renderers, and they did not describe one
palette but three. `page.py` drew an editorial green (`#0F6E5C` on `#F7F8F7`),
`canvas.py` a Tailwind slate-and-sky (`#38bdf8` on `#f8fafc`), `walkthrough.py` a third
slate with no dark theme at all, and the same grey appeared spelled `#94a3b8` and
`#94A3B8` in the same tree. Four figures produced by one tool did not look like one
tool made them.

WHY ROLES AND NOT NAMES. A token called `slate500` moves the decision nowhere: the
renderer still has to know which grey means "secondary text". Naming the ROLE —`muted`,
`rule`, `edge`— is what lets the palette change in one place without reading four
renderers to find out what each hex was standing for.

TWO SCALES ARE DELIBERATELY *NOT* CHROME, and they keep their own hues:

    STATUS   the liveness levels. Green-is-alive / red-is-dead is MEANING, not
             decoration; flattening it into the accent would delete information.
    TONES    one hue per repository in the weave. They have to stay mutually
             distinguishable, which an accent-derived ramp does not guarantee.

Their harmonisation with the editorial palette is a design decision, not a cleanup, and
is deliberately left open.
"""
from __future__ import annotations

# -- chrome, by role ----------------------------------------------------------
LIGHT = {
    "ground": "#F7F8F7",      # the page behind everything
    "panel": "#FFFFFF",       # a card, a box, a node fill
    "ink": "#151B19",         # primary text
    "ink_soft": "#3D4744",    # a note, a sublabel — reads as text, not as chrome
    "muted": "#68736E",       # tertiary text: captions, footers
    "soft": "#95A09B",        # a lane label, an axis — present but never competing
    "rule": "#DDE3E0",        # borders and separators
    "edge": "#95A09B",        # connector strokes
    "accent": "#0F6E5C",
    "accent_soft": "#E4EFEB",
    "warn": "#9A6B1F",
    "warn_soft": "#F6EEDF",
    "warn_ink": "#7A5316",    # text ON warn_soft — the pair has to stay readable
    "dead": "#8C3B36",
}

DARK = {
    "ground": "#101513",
    "panel": "#161D1A",
    "ink": "#E4EAE7",
    "ink_soft": "#B9C4BF",
    "muted": "#8A9791",
    "soft": "#6E7A75",
    "rule": "#242C29",
    "edge": "#6E7A75",
    "accent": "#5FBFA6",
    "accent_soft": "#172B26",
    "warn": "#D2A354",
    "warn_soft": "#2A2318",
    "warn_ink": "#E8C88A",
    "dead": "#D98882",
}

# -- the two scales that carry meaning ---------------------------------------
STATUS = {
    "ALIVE_PROVEN": "#22c55e",
    "ALIVE_PRODUCT": "#38bdf8",
    "ALIVE_PRODUCT_WEAK": "#a78bfa",
    "ALIVE_NOT_PRODUCT": "#facc15",
    "ALIVE_BY_NESTING": "#fb923c",
    "DEAD_CANDIDATE": "#f43f5e",
    "": "#64748b",
}

TONES = ["#0F6E5C", "#B26A00", "#5B4BC4", "#B03A5B", "#20707F"]


def css_vars(names: dict[str, str] | None = None, attr: str = "data-theme") -> str:
    """The four blocks a themed page needs, generated instead of hand-kept.

    `page.py` used to carry the light palette twice and the dark one twice — a change of
    one colour meant four edits, and three of them were easy to forget. The blocks are
    identical by construction now.

    `names` renames a role for a surface that already speaks another vocabulary
    (`canvas.py` says `--bg`/`--fg`/`--sub`), so adopting the tokens does not force a
    rewrite of every rule in its stylesheet.
    """
    def block(pal: dict[str, str]) -> str:
        # `ink_soft` → `--ink-soft`: CSS accepts both, but a stylesheet mixing
        # `--accent-soft` with `--ink_soft` reads as two conventions and invites typos.
        return " ".join(f"--{(names or {}).get(k, k.replace('_', '-'))}:{v};"
                        for k, v in pal.items())

    return (f":root{{ {block(LIGHT)} }}\n"
            f"@media (prefers-color-scheme: dark){{ :root{{ {block(DARK)} }} }}\n"
            f':root[{attr}="dark"]{{ {block(DARK)} }}\n'
            f':root[{attr}="light"]{{ {block(LIGHT)} }}\n')
