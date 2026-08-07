# -----------------------------------------------------------------------------
# mcview/ — portable entropy module
# -----------------------------------------------------------------------------
"""The brief as a PAGE — to read it, not to parse it.

Terminal output is meant for an agent and for a quick scan. When the job is to UNDERSTAND a
subsystem —sit down, look at the route, compare two numbers— a page wins: the diagram is
drawn instead of read as text, the temperature is a bar rather than five rows, and the
caveats travel next to the number they qualify instead of living in a README nobody opens.

DECISIONES
----------
* **One file, no build and NO NETWORK.** Complete HTML is emitted on stdout: `> page.html`
  and open it. The diagram renderer is embedded (`vendor/mermaid.min.js.gz`, ~1.2 MB of
  base64 over 3.4 MB raw), so the page works on a plane, inside an email attachment, and in
  five years when the CDN no longer exists. Verified: zero network requests on open.
* **Degradation in three steps.** Embedded → CDN (a browser without `DecompressionStream`)
  → the diagram as readable TEXT inside its `<pre>`, the same one `--mermaid` emits. Never a
  blank gap.
* **Caveats stay glued to the number.** It is the rule of the whole tool: high mass is a lot
  of traffic and not a lot of value, `DEAD_CANDIDATE` is a hypothesis and not a deletion
  order. In the terminal that is printed at the bottom and lost; here it lives in the same
  block.
* **Both themes.** The page is read by day and by night; the color tokens are redefined
  through `prefers-color-scheme` and through the `data-theme` attribute.
"""
from __future__ import annotations

import base64
import html
import os

# `vendor/` lives at the tool's ROOT, not next to this file: `page.py` moved down into
# `render/` and the renderer stayed up top, where whoever installs it copies it.
VENDOR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "vendor", "mermaid.min.js.gz")


def _renderer() -> tuple[str, str]:
    """The diagram engine, embedded if it has been vendored.

    Returns (script, note). A page that depends on a CDN is not self-sufficient: with no
    network the diagram degrades to text, and "open the file with a double click" is exactly
    the use case. Embedded, it works on a plane, inside an attachment, and in five years when
    that URL no longer exists.

    It travels COMPRESSED: the raw bundle is 3.4 MB and the base64 of its gzip 1.2 MB.
    `DecompressionStream` decompresses it, which is a browser API and not a new dependency.

    If the vendored copy is missing —somebody copied `mcview/` without `vendor/`— it falls
    back to the CDN instead of failing: the tool stays a directory you copy into any project.
    """
    CDN = "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"
    if not os.path.exists(VENDOR):
        return (f'<script src="{CDN}"></script>',
                "Renderer from a CDN: <code>mcview/vendor/</code> is missing, so this "
                "page needs a network connection.")

    with open(VENDOR, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return (f"""<script id="mermaid-gz" type="application/gzip-base64">{b64}</script>
<script>
(function () {{
  function porCDN() {{
    var s = document.createElement("script");
    s.src = "{CDN}";
    s.onload = function () {{ window.__mcview_init && window.__mcview_init(); }};
    document.head.appendChild(s);
  }}
  if (!window.DecompressionStream) return porCDN();   // navegador old
  var crudo = atob(document.getElementById("mermaid-gz").textContent);
  var bytes = new Uint8Array(crudo.length);
  for (var i = 0; i < crudo.length; i++) bytes[i] = crudo.charCodeAt(i);
  new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream("gzip")))
    .text()
    .then(function (js) {{
      // As a <script> and not `eval`: the bundle assigns `globalThis.mermaid` at the end and needs
      // ejecutarse en reach global.
      var s = document.createElement("script");
      s.src = URL.createObjectURL(new Blob([js], {{ type: "text/javascript" }}));
      s.onload = function () {{ window.__mcview_init && window.__mcview_init(); }};
      document.head.appendChild(s);
    }})
    .catch(porCDN);
}})();
</script>""", "")

CSS = """
:root{
  --ground:#F7F8F7; --panel:#FFFFFF; --ink:#151B19; --muted:#68736E;
  --line:#DDE3E0; --accent:#0F6E5C; --accent-soft:#E4EFEB; --warn:#9A6B1F;
  --warn-soft:#F6EEDF; --dead:#8C3B36;
}
@media (prefers-color-scheme: dark){
  :root{
    --ground:#101513; --panel:#161D1A; --ink:#E4EAE7; --muted:#8A9791;
    --line:#242C29; --accent:#5FBFA6; --accent-soft:#172B26; --warn:#D2A354;
    --warn-soft:#2A2318; --dead:#D98882;
  }
}
:root[data-theme="dark"]{
  --ground:#101513; --panel:#161D1A; --ink:#E4EAE7; --muted:#8A9791;
  --line:#242C29; --accent:#5FBFA6; --accent-soft:#172B26; --warn:#D2A354;
  --warn-soft:#2A2318; --dead:#D98882;
}
:root[data-theme="light"]{
  --ground:#F7F8F7; --panel:#FFFFFF; --ink:#151B19; --muted:#68736E;
  --line:#DDE3E0; --accent:#0F6E5C; --accent-soft:#E4EFEB; --warn:#9A6B1F;
  --warn-soft:#F6EEDF; --dead:#8C3B36;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  font-variant-numeric:tabular-nums;
}
.wrap{max-width:60rem; margin:0 auto; padding:3rem 1.5rem 5rem; display:flex;
  flex-direction:column; gap:2.5rem}
code,.mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}

header h1{margin:0; font-size:2.1rem; letter-spacing:-.02em; text-wrap:balance}
.eyebrow{font-size:.75rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--accent); font-weight:600; margin-bottom:.4rem}
.cmd{margin-top:.9rem; font-size:.82rem; color:var(--muted); word-break:break-all}

/* Each strip is its own card. The previous version used the `gap:1px` trick over a line
   background, and when the last row came out incomplete the background peeked through as an
   empty grey block — visible on opening the page, not on reading the CSS. */
.tiras{display:grid; grid-template-columns:repeat(auto-fit,minmax(10rem,1fr)); gap:.75rem}
.tira{background:var(--panel); padding:.9rem 1rem; border:1px solid var(--line);
  border-radius:6px}
.tira .v{font-size:1.5rem; font-weight:600; letter-spacing:-.02em}
.tira .k{font-size:.72rem; text-transform:uppercase; letter-spacing:.1em; color:var(--muted)}
.tira .n{font-size:.76rem; color:var(--muted); margin-top:.25rem}

section h2{font-size:1.45rem; font-weight:600; margin:0 0 .35rem; letter-spacing:-.02em;
  line-height:1.25}
section .sub{font-size:.85rem; color:var(--muted); margin:0 0 1.1rem; max-width:62ch}

.barra{display:flex; height:1.6rem; border-radius:4px; overflow:hidden; border:1px solid var(--line)}
.barra span{display:block}
.leyenda{display:flex; flex-wrap:wrap; gap:.35rem 1.1rem; margin-top:.7rem; font-size:.8rem}
.leyenda i{display:inline-block; width:.6rem; height:.6rem; border-radius:2px; margin-right:.4rem}

figure{margin:0; border:1px solid var(--line); border-radius:6px; background:var(--panel);
  padding:1.2rem; overflow-x:auto}
figure pre{margin:0; font-size:.78rem; color:var(--muted); white-space:pre}
/* A wide diagram has to OVERFLOW and scroll (the `figure` carries `overflow-x:auto`), never
   shrink until it is illegible. Mermaid emits `width="100%"` as an ATTRIBUTE plus an inline
   `max-width`, so the SVG fills the container and a 3,565 px `viewBox` scales down to 463:
   the neighborhood map came out as a 42 px tall strip of stamps. CSS is not enough —the
   `width` attribute wins—; the natural size is set from JS once the render finishes. This is
   only the safety net. */
figure svg{height:auto}
figcaption{font-size:.8rem; color:var(--muted); margin-top:.9rem; padding-top:.9rem;
  border-top:1px solid var(--line)}

table{width:100%; border-collapse:collapse; font-size:.87rem}
th{text-align:left; font-size:.7rem; text-transform:uppercase; letter-spacing:.1em;
  position:sticky; top:0; z-index:2; background:var(--panel);
  box-shadow:0 1px 0 var(--line);
  color:var(--muted); font-weight:600; padding:0 .6rem .5rem 0; border-bottom:1px solid var(--line)}
tbody tr:nth-child(odd){background:color-mix(in srgb, var(--accent) 6%, transparent)}
tbody tr:hover{background:color-mix(in srgb, var(--accent) 12%, transparent)}
td,th{font-variant-numeric:tabular-nums}
td{padding:.55rem .7rem .55rem 0; border-bottom:1px solid var(--line); vertical-align:top}
td.num{text-align:right; width:6rem; white-space:nowrap}
tr:last-child td{border-bottom:none}
.tabla-scroll{overflow-x:auto}

.nota{border-left:3px solid var(--accent); background:var(--accent-soft);
  padding:.85rem 1rem; border-radius:0 4px 4px 0; font-size:.85rem}
.nota strong{font-weight:600}
.warning{border-left-color:var(--warn); background:var(--warn-soft)}
footer{border-top:1px solid var(--line); padding-top:1.4rem; font-size:.8rem; color:var(--muted)}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
"""

_COLOR_NIVEL = {
    "ALIVE_PROVEN": "var(--accent)", "ALIVE_PRODUCT": "var(--accent)",
    "ALIVE_PRODUCT_WEAK": "var(--warn)", "TEST_ONLY": "var(--warn)",
    "ALIVE_BY_NESTING": "var(--muted)", "DEAD_CANDIDATE": "var(--dead)",
}
_GLOSA_NIVEL = {
    "ALIVE_PRODUCT": "reachable from a real root, unambiguous name",
    "ALIVE_PRODUCT_WEAK": "only via an ambiguous name — this is where entropy lives",
    "TEST_ONLY": "alive purely because a test or a script touches it",
    "ALIVE_BY_NESTING": "alive only by being nested inside something alive",
    "DEAD_CANDIDATE": "no references at all — a hypothesis, NOT a deletion order",
}


def _e(x) -> str:
    return html.escape(str(x), quote=True)


def _table(cabeceras, rows) -> str:
    if not rows:
        return '<p class="sub">nothing to show.</p>'
    th = "".join(f'<th{" class=num" if c[1] else ""}>{_e(c[0])}</th>' for c in cabeceras)
    tr = "".join(
        "<tr>" + "".join(
            f'<td{" class=num" if cab[1] else ""}>{cel}</td>'
            for cab, cel in zip(cabeceras, row)) + "</tr>"
        for row in rows)
    return f'<div class="tabla-scroll"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _figure(code: str, caption: str) -> str:
    return (f'<figure><pre class="mermaid">{_e(code)}</pre>'
            f'<figcaption>{caption}</figcaption></figure>')


def render(r: dict, sequence: str, map_html: str, comando: str) -> str:
    """The complete page. `r` is the dict from `orient.orient` with `flow` inside."""
    if "error" in r:
        body = f'<div class="nota warning">{_e(r["error"])}</div>'
        return _wrap(_e(r.get("target", "mcview")), body, comando)

    f = r.get("flow") or {}
    total_sym = sum(r["temperatura"].values()) or 1

    tiras = [
        ("files", len(r["files"]), ""),
        ("symbols", r["symbols"], f'{r["frios"]} cold'),
        ("project mass", f'{r["mass_pct"]:.2f}%', "how much traffic, not how much value"),
        # The note read "below 0.15 it is not a unit" even at 0.33, and it looked as if the
        # value WERE below it. The caveat only applies when it applies.
        ("cohesion", f'{r["cohesion"]:.2f}',
         "threshold 0.15" if r["cohesion"] >= 0.15
         else "under 0.15: not a unit, it is crosscutting"),
    ]
    html_tiras = "".join(
        f'<div class="tira"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div>'
        f'<div class="n">{_e(n)}</div></div>' for k, v, n in tiras)

    call_order = ["ALIVE_PRODUCT", "ALIVE_PRODUCT_WEAK", "TEST_ONLY", "ALIVE_BY_NESTING",
             "DEAD_CANDIDATE"]
    barra = "".join(
        f'<span style="width:{100*r["temperatura"].get(k,0)/total_sym:.2f}%;'
        f'background:{_COLOR_NIVEL[k]}" title="{_e(k)}"></span>'
        for k in call_order if r["temperatura"].get(k))
    leyenda = "".join(
        f'<span><i style="background:{_COLOR_NIVEL[k]}"></i>'
        f'<code>{_e(k)}</code> {r["temperatura"][k]} — {_e(_GLOSA_NIVEL[k])}</span>'
        for k in call_order if r["temperatura"].get(k))

    parts = []
    parts.append(f'''<section>
      <h2>Temperatura</h2>
      <p class="sub">The grades of liveness evidence. <code>ALIVE_PRODUCT_WEAK</code> and
      <code>TEST_ONLY</code> are where entropy piles up: code nobody deletes because the graph
      says it is used, when what holds it up is a homonym or its own test.</p>
      <div class="barra">{barra}</div><div class="leyenda">{leyenda}</div>
      <p class="sub" style="margin-top:1rem">{r["frios"]} <b>cold</b> symbols (mass ~0):
      referenced, but the system barely goes through them. They are not dead candidates.</p>
    </section>''')

    if sequence:
        parts.append(f'''<section>
          <h2>El route</h2>
          <p class="sub">The real paths from the declared roots, merged. What to look at is where
          they <b>converge</b>: that is where the system decides once for many origins.</p>
          {_figure(sequence,
                   "Stadium = declared root · bold = subsystem door · "
                   "dashed = guard, called <i>before</i> and a sibling of the path, not a step.")}
        </section>''')

    if map_html:
        parts.append(f'''<section>
          <h2>El vecindario</h2>
          <p class="sub">One altitude up: which lines of work use it and which it depends on.
          No tests, no scripts — they are consumers of the system, not part of its
          structure.</p>
          {_figure(map_html, "To place the subsystem in the architecture, not to follow a path.")}
        </section>''')

    if f.get("guards"):
        rows = [(f'<code>{_e(g["name"])}</code>', f'{100*g["fraccion"]:.0f}%',
                  f'<code>{_e(g["loc"])}</code>') for g in f["guards"]]
        parts.append(f'''<section>
          <h2>What it crosses first</h2>
          <p class="sub">What the paths <b>call</b> without being on them. It is the
          anti-duplication signal: if the flow already crosses a tenant resolver, writing
          another one would be the second.</p>
          {_table([("guard", False), ("of the paths", True), ("where", False)], rows)}
        </section>''')

    usan, depende = f.get("usan") or [], f.get("depende") or []
    if usan or depende:
        rows = ([(f'<b>{_e(m["module"])}</b>', f'{m["refs"]:.0f}', "uses it") for m in usan[:6]]
                 + [(f'<b>{_e(m["module"])}</b>', f'{m["refs"]:.0f}', "depends on it")
                    for m in depende[:6]])
        parts.append(f'''<section>
          <h2>Relations per line of work</h2>
          {_table([("module", False), ("refs", True), ("direction", False)], rows)}
        </section>''')

    c = f.get("crossings") or {}
    if c.get("entra") or c.get("sale"):
        rows = ([(f'<b>◀ entra</b>', f'<code>{_e(x["literal"])}</code>',
                   f'{_e(x["project"])}<br><code>{_e(x["src"][0])}</code>',
                   f'<code>{_e(x["hacia"][0])}</code>') for x in c.get("entra", [])[:8]]
                 + [(f'<b>▶ sale</b>', f'<code>{_e(x["literal"])}</code>',
                     f'<code>{_e(x["src"][0])}</code>',
                     f'{_e(x["project"])}<br><code>{_e(x["hacia"][0])}</code>')
                    for x in c.get("sale", [])[:8]])
        parts.append(f'''<section>
          <h2>Crosses into another project</h2>
          <p class="sub">The path does not end at the repository boundary. What holds each
          edge up is that both sides write the <b>same literal</b> — a route, a tool name—,
          not something similar. And it is not a local call: it is a process hop over the
          network, which is where the expensive failure modes live.</p>
          {_table([("direction", False), ("literal", False), ("from", False), ("to", False)], rows)}
        </section>''')

    if r.get("duplicates"):
        rows = [(f'<code>{_e(d["what"])}</code>', f'{d["jaccard"]:.2f}',
                  "<br>".join(f'<code>{_e(x)}</code>' for x in d["where"]))
                 for d in r["duplicates"]]
        parts.append(f'''<section>
          <h2>Already exists</h2>
          <p class="sub">Structural twins touching this subsystem, nested blocks included: a
          name with a slash (<code>get_queue_status/except</code>) is a block. A block paired
          against an already-extracted function means the helper was pulled out in one file
          and is still copied by hand in the other.</p>
          {_table([("what", False), ("jaccard", True), ("where", False)], rows)}
        </section>''')

    parts.append('''<div class="nota warning"><strong>What this does NOT say.</strong> It is
      structure, not execution: a path that exists in the graph may never be walked in
      production, and an absent one may exist anyway (dynamic dispatch, plugins by name). The
      bias runs toward the false negative. And the graph says where the system goes, never
      why — decisions and what was refuted do not come from here.</div>''')

    return _wrap(_e(r["target"]), "".join(parts), comando, html_tiras, r)


def _journey_css() -> str:
    import journey as _journey
    return _journey.CSS


def _wrap(titulo: str, body: str, comando: str, tiras: str = "",
              r: dict | None = None, epigrafe: str = "orientation") -> str:
    kind = _e(r["kind"]) if r else ""
    motor, aviso_motor = _renderer()
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{titulo} — mcview</title>
<style>{CSS}{_journey_css()}</style></head>
<body><div class="wrap">
<header>
  <div class="eyebrow">mcview · {epigrafe}{' · ' + kind if kind else ''}</div>
  <h1>{titulo}</h1>
  <p class="cmd mono">{_e(comando)}</p>
</header>
{f'<div class="nota warning">{aviso_motor}</div>' if aviso_motor else ''}
{f'<div class="tiras">{tiras}</div>' if tiras else ''}
{body}
<footer>Computed from today's code, not from documentation. Regenerating is one command —
if the page and the repository disagree, the page is stale and the repository is right.</footer>
</div>
<script>
  // Defined BEFORE loading the engine: the loader invokes it when it finishes, whether it
  // came from the embedded bundle or the CDN. No `type="module"` — an `import()` from a
  // `file://` page is blocked by CORS even when the CDN answers 200, and opening the file
  // with a double click IS the use case. Verified by opening the page, not by reasoning.
  window.__mcview_init = function () {{
    if (!window.mermaid) return;
    var oscuro = matchMedia("(prefers-color-scheme: dark)").matches
      || document.documentElement.dataset.theme === "dark";
    mermaid.initialize({{ startOnLoad: false, theme: oscuro ? "dark" : "neutral",
                          securityLevel: "strict" }});
    mermaid.run().then(function () {{
      // Give each diagram back its NATURAL size. Mermaid leaves `width="100%"`, which makes
      // it shrink until illegible when it is wider than the column. We prefer it to
      // overflow and scroll: a tiny diagram cannot be read, a scrolling one can.
      document.querySereaderAll("figure svg").forEach(function (svg) {{
        var vb = svg.viewBox && svg.viewBox.baseVal;
        if (!vb || !vb.width) return;
        svg.removeAttribute("width");
        svg.style.maxWidth = "none";
        svg.style.width = Math.ceil(vb.width) + "px";
      }});
    }});
  }}
  // If NO route loads, the `<pre>` already holds the diagram as readable text — the same one
  // `--mermaid` prints. It degrades to that, never to a blank gap.
</script>
{motor}
</body></html>"""


def _bridge_diagram(bridges: list[dict], catalogs: dict) -> str:
    """The workspace as a diagram: who asks whom, and what state they share.

    Two classes of edge, and the distinction is the point: the solid arrow is a CALL
    (somebody writes the other's identifier); the dashed one into the cylinder is SHARED
    STATE — two projects touching the same table without ever calling each other. The second
    appears in no call graph and is, in this architecture, the most sensitive one.
    """
    from collections import Counter
    ids = {p: f"P{i}" for i, p in enumerate(sorted(catalogs))}
    L = ["flowchart LR"]
    for proj, nid in ids.items():
        L.append(f'  {nid}["{_e(proj)}"]')

    calls = Counter((p["from"], p["to"]) for p in bridges
                       if not p.get("recurso") and p.get("in_product", True))
    for (de, a), n in calls.items():
        if de in ids and a in ids:
            L.append(f"  {ids[de]} -->|{n} literales| {ids[a]}")

    recursos = [p for p in bridges if p.get("recurso")]
    if recursos:
        tocan = {x for p in recursos for x in p["compartido_por"]}
        L.append(f'  DB[("shared state<br/><i>{len(recursos)} tables and RPCs</i>")]')
        for proj in sorted(tocan):
            if proj in ids:
                L.append(f"  {ids[proj]} -.-> DB")
    return "\n".join(L)


def render_bridges(bridges: list[dict], catalogs: dict, comando: str) -> str:
    """The WORKSPACE page, not a target's: how the projects join to one another."""
    exact = [p for p in bridges
               if not p.get("recurso") and p["exacto"] and p.get("in_product", True)]
    solo_test = [p for p in bridges
                 if not p.get("recurso") and p["exacto"] and not p.get("in_product", True)]
    recursos = [p for p in bridges if p.get("recurso")]

    tiras = [("projects", len(catalogs), "joined by their literals"),
             ("calls", len(exact), "exact identifier, in production"),
             ("shared state", len(recursos), "tables and RPCs touched by 2+"),
             ("tests only", len(solo_test), "they prove no production relation")]
    html_tiras = "".join(
        f'<div class="tira"><div class="k">{_e(k)}</div><div class="v">{_e(v)}</div>'
        f'<div class="n">{_e(n)}</div></div>' for k, v, n in tiras)

    parts = [f'''<section>
      <h2>How the projects join</h2>
      <p class="sub">The seam between repositories is made of <b>strings</b>, not symbols:
      nobody imports a function from the other side. The solid arrow is a call — somebody
      writes the other's identifier. The dashed one is shared state.</p>
      {_figure(_bridge_diagram(bridges, catalogs),
               "Solid arrow = call · dashed = same table, never calling each other.")}
    </section>''']

    if exact:
        rows = [(f'<code>{_e(p["literal"])}</code>', _e(p["kind"]),
                  f'{_e(p["from"])} → <b>{_e(p["to"])}</b>', str(p["usos"]))
                 for p in exact[:40]]
        parts.append(f'''<section>
          <h2>Llamadas</h2>
          <p class="sub">What holds each one up is that both sides write the same identifier, not
          something similar — the same criterion as the unambiguous edges
          inside de un project.</p>
          {_table([("literal", False), ("kind", False), ("direction", False), ("uses", True)],
                  rows)}
        </section>''')

    if recursos:
        rows = [(f'<code>{_e(p["literal"])}</code>', _e(p["kind"]),
                  " + ".join(_e(x) for x in p["compartido_por"]), str(p["usos"]))
                 for p in recursos[:40]]
        parts.append(f'''<section>
          <h2>Estado shared</h2>
          <p class="sub">Tables and RPCs touched by two or more projects <b>without calling each
          other</b>. It appears in no call graph, and here it is the most sensitive relation:
          the frontend reads the database directly under RLS and the backend writes with
          service_role, so the table is the only point where they meet.</p>
          {_table([("recurso", False), ("kind", False), ("lo tocan", False), ("usos", True)],
                  rows)}
        </section>''')

    if solo_test:
        parts.append(f'''<div class="nota warning"><strong>{len(solo_test)} literals only in
          tests.</strong> A project names them solely from its own suite, so they prove no
          production relation. Counting them exaggerated the seam by 5×.</div>''')

    parts.append('''<div class="nota"><strong>What it does NOT say.</strong> A dynamically
      built literal is not detected: the bias runs toward the false negative, never toward
      inventing an edge. And only projects declaring <code>[seams]</code> are included —
      with no declaration there is nothing to join.</div>''')

    return _wrap("Workspace bridges", "".join(parts), comando, html_tiras,
                     epigrafe="workspace")


def render_sequence(weave, r: dict, comando: str, lane) -> str:
    """The sequence as a page: the lane diagram on top, the step-by-step narrative below —
    with the runtime mark next to each one.

    The narrative goes COMPLETE even when the diagram is large: a sequenceDiagram with 200
    messages cannot be read, but the numbered list can, and it is the one that answers "and
    then what happens?". The diagram shows the SHAPE —who talks to whom, how many times a
    lane is crossed—; the narrative shows the detail.
    """
    import sequence as _sec

    if "error" in r:
        return _wrap("sequence", f'<div class="nota warning">{_e(r["error"])}</div>',
                         comando, epigrafe="sequence")

    rows, marks = [], {"si": 0, "no": 0}

    def descend(n, depth_lvl):
        for p in n["steps"]:
            if "ejecutado" in p:
                marks["si" if p["ejecutado"] else "no"] += 1
                sello = ("<b title='seen ejecutar'>✓</b>" if p["ejecutado"]
                         else "<span title='not observed — it does NOT mean it does not happen'>·</span>")
            else:
                sello = ""
            indent = "&nbsp;" * (depth_lvl * 4)
            repeats = " ↻" if p.get("repeats") else ""
            rows.append([sello, f"{indent}{_e(p['name'])}{repeats}",
                          _e(lane(weave, p["id"])), _e(p["loc"])])
            descend(p, depth_lvl + 1)
        if n.get("off_path"):
            rows.append(["", "&nbsp;" * (depth_lvl * 4) +
                          f"<i>{n['off_path']} calls that do not lead to the target</i>",
                          "", ""])
        if n.get("pruned"):
            rows.append(["", "&nbsp;" * (depth_lvl * 4) +
                          f"<i>{n['pruned']} more calls, not expanded</i>", "", ""])

    descend(r["tree"], 0)

    body = [f'<h2>{_e(r["entry"])}</h2>',
              f'<p class="sub">arranca en <code>{_e(r["starts_at"])}</code>'
              + (f' · dst <code>{_e(r["dst"])}</code>' if r.get("dst") else "")
              + f' · {len(rows)} steps</p>']

    body.append('<div class="nota">The order is the <b>WRITTEN</b> one, not the executed '
                  'one: a call inside an <code>if</code> shows up anyway, and a dynamically '
                  'dispatched one does not.</div>')
    if marks["si"] or marks["no"]:
        body.append(f'<div class="nota">Runtime: <b>{marks["si"]}</b> steps seen '
                      f'ejecutar, <b>{marks["no"]}</b> no observed. '
                      f'<b>«not observed» is not «does not happen»</b> — it may sit behind an '
                      f'<code>if</code>, outside the measured window, or in a process with no '
                      f'sonda. Confirma, nunca descarta.</div>')

    import journey as _journey
    body.append(f'<div class="journey-marco">{_journey.draw(weave, r, lane)}</div>'
                  f'<p class="sub">time runs to the right · each lane change '
                  f'is a change of hands · <b>dashed</b> = crosses repository · '
                  f'filled = seen executing, hollow = not observed</p>')
    # `_table` expects (text, is_numeric) per header, not a bare string.
    body.append(_table([("", 0), ("step", 0), ("lane", 0), ("where", 0)], rows))
    return _wrap(_e(r["entry"]), "\n".join(body), comando, epigrafe="sequence")
