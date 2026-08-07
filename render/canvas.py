"""The atlas as a page: a 2D canvas, no libraries and no network.

It is hand-written instead of vendoring a graph library for the same reason the tool has no
dependencies: the use case is opening the file with a double click five years from now. A
`<script src>` to a CDN dies when the CDN dies, and an embedded library is hundreds of KB for
a drawing made of three primitives — circles, lines and text.

The JS here does NOT compute positions. Layers and columns arrive already resolved from
`atlas.py`, so the same repository gives the same map, a diff of the map means something, and
`--json` hands over exactly what is on screen. A layout decided in the browser is
irreproducible by construction.
"""
from __future__ import annotations

import html
import json

# The color says the census liveness level, NOT reachability. The distinction matters: in
# CIRE 73% of the symbols are not reached through unambiguous edges and almost all of them are
# alive — painting that as "unhooked" would be a measured lie.
COLORES = {
    "ALIVE_PROVEN": "#22c55e",
    "ALIVE_PRODUCT": "#38bdf8",
    "ALIVE_PRODUCT_WEAK": "#a78bfa",
    "TEST_ONLY": "#facc15",
    "ALIVE_BY_NESTING": "#fb923c",
    "DEAD_CANDIDATE": "#f43f5e",
    "": "#64748b",
}

_PAGINA = """<meta charset="utf-8"><title>atlas — __TITULO__</title>
<style>
:root{--bg:#f8fafc;--fg:#0f172a;--sub:#64748b;--panel:#fff;--borde:#e2e8f0;--edge:#94a3b8}
@media(prefers-color-scheme:dark){:root{--bg:#0b1120;--fg:#e2e8f0;--sub:#94a3b8;--panel:#111c33;--borde:#1e293b;--edge:#475569}}
:root[data-tema=dark]{--bg:#0b1120;--fg:#e2e8f0;--sub:#94a3b8;--panel:#111c33;--borde:#1e293b;--edge:#475569}
:root[data-tema=light]{--bg:#f8fafc;--fg:#0f172a;--sub:#64748b;--panel:#fff;--borde:#e2e8f0;--edge:#94a3b8}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;overflow:hidden}
#barra{position:fixed;top:0;left:0;right:0;height:44px;display:flex;align-items:center;
 gap:14px;padding:0 14px;background:var(--panel);border-bottom:1px solid var(--borde);z-index:5}
#path{font-weight:600;letter-spacing:-.01em}#path span{color:var(--sub);font-weight:400}
#path b{cursor:pointer;text-decoration:underline dotted}
#pista{color:var(--sub);margin-left:auto;font-size:12px}
button{font:inherit;padding:3px 10px;border:1px solid var(--borde);border-radius:6px;
 background:transparent;color:var(--fg);cursor:pointer}
canvas{position:fixed;top:44px;left:0;cursor:grab}canvas.arrastrando{cursor:grabbing}
#tip{position:fixed;pointer-events:none;background:var(--panel);border:1px solid var(--borde);
 border-radius:8px;padding:9px 11px;max-width:340px;box-shadow:0 8px 24px #0003;display:none;z-index:9}
#tip h4{margin:0 0 5px;font-size:13px}#tip dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:1px 10px}
#tip dt{color:var(--sub)}#tip dd{margin:0}
#leyenda{position:fixed;bottom:12px;left:12px;background:var(--panel);border:1px solid var(--borde);
 border-radius:8px;padding:9px 11px;z-index:5;font-size:12px}
#leyenda i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}
#leyenda div{white-space:nowrap;color:var(--sub)}
#nota{position:fixed;bottom:12px;right:12px;max-width:330px;color:var(--sub);font-size:11.5px;
 background:var(--panel);border:1px solid var(--borde);border-radius:8px;padding:9px 11px;z-index:5}
</style>
<div id=barra>
  <button id=backward>← volver</button>
  <div id=path></div>
  <div id=pista>rueda = zoom · arrastrar = mover · clic = abrir</div>
  <button id=tema>tema</button>
</div>
<canvas id=c></canvas><div id=tip></div>
<div id=leyenda></div>
<div id=nota><b>Height is the dependency layer:</b> plumbing at the bottom, whoever uses it on
top. Size is usage mass (PageRank), not file size. Color is the census liveness level —
<b>not</b> reachability.</div>
<script id=datos type="application/json">__DATOS__</script>
<script>
const M = JSON.parse(document.getElementById('datos').textContent);
const COLOR = __COLORES__;
const cv = document.getElementById('c'), cx = cv.getContext('2d');
let view = {level:'module', parent:null}, stack = [];
let esc = 1, dx = 0, dy = 0, nodes = [], edges = [], hover = null, opened = false;

// The symbol level is always drawn scoped to one file: 6,143 dots on screen is not a map,
// it is noise shaped like a map.
function datos(){
  const d = M.levels[view.level];
  let ns = view.parent ? d.nodes.filter(n => n.parent === view.parent) : d.nodes;
  // What sits behind the dispatch arrives COLLAPSED: 674 symbols across 14 modules, and
  // opened up they bury the path that really is made of calls, which is what you came to see.
  if (!opened) ns = ns.filter(n => !n.via_despacho);
  const ids = new Set(ns.map(n => n.id));
  return [ns, d.edges.filter(a => ids.has(a.from) && ids.has(a.to))];
}

function disponer(){
  [nodes, edges] = datos();
  const layers = Math.max(1, ...nodes.map(n => n.layer)) + 1;
  const anchoCapa = {};
  nodes.forEach(n => anchoCapa[n.layer] = Math.max(anchoCapa[n.layer]||0, n.col+1));
  const cols = Math.max(1, ...Object.values(anchoCapa));
  const W = cv.clientWidth, H = cv.clientHeight;
  const px = Math.min(170, Math.max(80, W / (cols+1))), py = Math.min(130, H/(layers+0.6));
  const maxPct = Math.max(0.001, ...nodes.map(n => n.pct));
  nodes.forEach(n => {
    const centered = (anchoCapa[n.layer]-1)/2;
    n.x = W/2 + (n.col - centered) * px;
    n.y = H - (n.layer + 0.7) * py;
    // Square root: the area grows with the mass, not the radius — otherwise a 24% covers half the map.
    n.r = 5 + 26 * Math.sqrt(n.pct / maxPct);
  });
}

const PROY = ['#38bdf8','#f59e0b','#a78bfa','#22c55e','#f43f5e'];
const projects = [...new Set(M.levels.module.nodes.map(n => n.project).filter(Boolean))].sort();
function colorDe(n){
  if (n.project) return PROY[projects.indexOf(n.project) % PROY.length];
  if (n.status !== undefined) return COLOR[n.status] || COLOR[''];
  const e = n.statuses || {}; let best = '', max = -1;
  for (const k in e) if (e[k] > max) { max = e[k]; best = k; }
  return COLOR[best] || COLOR[''];
}

function draw(){
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight;
  cx.setTransform(dpr,0,0,dpr,0,0); cx.clearRect(0,0,W,H);
  cx.setTransform(esc*dpr,0,0,esc*dpr,dx*dpr,dy*dpr);
  cx.lineJoin = 'round'; cx.lineCap = 'round';
  cx.textBaseline = 'alphabetic';
  const idx = {}; nodes.forEach(n => idx[n.id] = n);
  const maxPeso = Math.max(1, ...edges.map(a => a.weight));
  const css = getComputedStyle(document.documentElement);
  const fg = css.getPropertyValue('--fg').trim(), sub = css.getPropertyValue('--sub').trim();
  cx.strokeStyle = css.getPropertyValue('--edge').trim();
  edges.forEach(a => {
    const o = idx[a.from], d = idx[a.to]; if (!o || !d) return;
    const highlighted = hover && (a.from === hover.id || a.to === hover.id);
    cx.globalAlpha = highlighted ? .95 : (hover ? .06 : .3);
    cx.lineWidth = Math.max(.6, 3.2 * a.weight / maxPeso);
    cx.setLineDash(a.seam ? [5,4] : []);
    cx.beginPath(); cx.moveTo(o.x, o.y);
    cx.quadraticCurveTo((o.x+d.x)/2 + (o.y-d.y)*.12, (o.y+d.y)/2, d.x, d.y);
    cx.stroke();
    // The branch number, only where the node DECIDES: elsewhere it would be noise, and a
    // drawing with a percentage on every line does not read as a decision tree.
    if (a.p !== undefined) {
      const mx = (o.x+d.x)/2 + (o.y-d.y)*.06, my = (o.y+d.y)/2 - 4;
      cx.save(); cx.globalAlpha = hover && !highlighted ? .15 : 1;
      cx.font = '600 11px system-ui,sans-serif'; cx.textAlign = 'center';
      cx.lineWidth = 3.5; cx.strokeStyle = css.getPropertyValue('--bg').trim();
      cx.strokeText(a.p + '%', mx, my); cx.fillStyle = fg;
      cx.fillText(a.p + '%', mx, my); cx.restore();
    }
    // The arrowhead says who uses whom: without direction the map cannot tell a dependency
    // from its inverse, which is exactly what you came to look at.
    const ang = Math.atan2(d.y-o.y, d.x-o.x), L = 7;
    const hx = d.x - Math.cos(ang)*(d.r+2), hy = d.y - Math.sin(ang)*(d.r+2);
    cx.beginPath(); cx.moveTo(hx, hy);
    cx.lineTo(hx-Math.cos(ang-.4)*L, hy-Math.sin(ang-.4)*L);
    cx.moveTo(hx, hy);
    cx.lineTo(hx-Math.cos(ang+.4)*L, hy-Math.sin(ang+.4)*L);
    cx.stroke();
  });
  cx.setLineDash([]); cx.globalAlpha = 1;
  nodes.forEach(n => {
    cx.globalAlpha = hover && hover !== n ? .35 : .9;
    if (n.dispatch) {
      // A diamond and not a circle: it is not a component, it is a SEAM — the point where the
      // system stops resolving by call. Looking different is the point.
      const R = 16; cx.beginPath();
      cx.moveTo(n.x, n.y-R); cx.lineTo(n.x+R, n.y); cx.lineTo(n.x, n.y+R); cx.lineTo(n.x-R, n.y);
      cx.closePath(); cx.fillStyle = '#f59e0b'; cx.fill();
      cx.lineWidth = 1.5; cx.strokeStyle = '#b45309'; cx.stroke();
      cx.globalAlpha = 1; cx.fillStyle = '#fff'; cx.font = 'bold 11px ui-sans-serif,sans-serif';
      cx.textAlign = 'center'; cx.fillText(opened ? '−' : '+', n.x, n.y+4);
      cx.fillStyle = css.getPropertyValue('--fg').trim();
      cx.font = '11px ui-sans-serif,system-ui,sans-serif';
      cx.fillText('the agent chooses by name', n.x, n.y + R + 13);
      cx.fillStyle = sub;
      cx.fillText((opened ? 'ocultar ' : 'ver ') + n.symbols + ' tras la seam', n.x, n.y + R + 26);
      cx.globalAlpha = 1; return;
    }
    cx.beginPath(); cx.arc(n.x, n.y, n.r, 0, 7);
    cx.fillStyle = colorDe(n); cx.fill();
    // A ring where the flow splits: it is what you come to look for in this view, and
    // without the mark you have to deduce it by counting outgoing lines.
    if (n.decide) {
      cx.beginPath(); cx.arc(n.x, n.y, n.r + 4.5, 0, 7);
      cx.lineWidth = 1.6; cx.strokeStyle = colorDe(n); cx.globalAlpha = .55; cx.stroke();
      cx.globalAlpha = hover && hover !== n ? .35 : .9;
    }
    if (n.entry) {
      cx.beginPath(); cx.arc(n.x, n.y, n.r + 8, 0, 7);
      cx.lineWidth = 2; cx.strokeStyle = fg; cx.setLineDash([3,3]); cx.stroke();
      cx.setLineDash([]);
    }
    if (n === hover) { cx.lineWidth = 2; cx.strokeStyle = fg; cx.stroke(); }
    cx.globalAlpha = 1;
    if (esc > .28 || n.r > 9) {
      cx.fillStyle = hover && hover !== n ? sub : fg;
      cx.font = (n.r > 16 ? 12 : 11) + 'px ui-sans-serif,system-ui,sans-serif';
      cx.textAlign = 'center';
      const t = n.name.length > 26 ? n.name.slice(0,25)+'…' : n.name;
      // Halo: the background color stroked underneath the text. Without this, a label
      // falling on an edge reads half text half line, and in the map's dense area that
      // is most of the labels.
      cx.lineWidth = 3.5; cx.strokeStyle = css.getPropertyValue('--bg').trim();
      cx.strokeText(t, n.x, n.y + n.r + 13);
      cx.fillText(t, n.x, n.y + n.r + 13);
    }
  });
}

function enPantalla(ev){
  return [(ev.clientX - dx) / esc, (ev.clientY - 44 - dy) / esc];
}
function nodoEn(ev){
  const [x, y] = enPantalla(ev);
  let best = null, md = 1e9;
  nodes.forEach(n => { const r = n.dispatch ? 18 : n.r + 4;
    const d = Math.hypot(n.x-x, n.y-y); if (d < r && d < md) { md = d; best = n; } });
  return best;
}

const tip = document.getElementById('tip');
function mostrarTip(n, ev){
  const f = [];
  f.push(['mass de uso', n.pct.toFixed(2) + '%']);
  f.push(['layer', n.layer]);
  if (n.symbols !== undefined) f.push(['symbols', n.symbols]);
  if (n.status) f.push(['status', n.status]);
  if (n.statuses) for (const k in n.statuses) if (k) f.push([k, n.statuses[k]]);
  if (n.sueltos) f.push(['no strong path', n.sueltos]);
  tip.innerHTML = '<h4>' + n.name.replace(/</g,'&lt;') + '</h4><dl>' +
    f.map(([a,b]) => '<dt>'+a+'</dt><dd>'+b+'</dd>').join('') + '</dl>';
  tip.style.display = 'block';
  tip.style.left = Math.min(ev.clientX + 14, innerWidth - 350) + 'px';
  tip.style.top = Math.min(ev.clientY + 14, innerHeight - 160) + 'px';
}

function path(){
  const r = document.getElementById('path');
  const parts = ['<b data-i="-1">' + M.project + '</b>'];
  stack.forEach((p, i) => parts.push('<b data-i="'+i+'">' + (p.label||p.parent) + '</b>'));
  r.innerHTML = parts.join(' <span>›</span> ') +
    ' <span>· ' + nodes.length + ' nodes · ' + edges.length + ' conexiones</span>';
  r.querySereaderAll('b').forEach(b => b.onclick = () => {
    const i = +b.dataset.i;
    stack = stack.slice(0, i + 1);
    view = i < 0 ? {level:'module', parent:null} : stack[i].view;
    refresh();
  });
}
// Frame on entry: with 18 layers the content ran off screen and the map started by showing
// half of it. It is computed from the content, not from a hand-picked zoom.
function encuadrar(){
  if (!nodes.length) return;
  const x0 = Math.min(...nodes.map(n => n.x-n.r)), x1 = Math.max(...nodes.map(n => n.x+n.r));
  const y0 = Math.min(...nodes.map(n => n.y-n.r)), y1 = Math.max(...nodes.map(n => n.y+n.r+16));
  const m = 30;
  const W = cv.clientWidth, H = cv.clientHeight;
  esc = Math.min(1.6, (W-2*m)/Math.max(1,x1-x0), (H-2*m)/Math.max(1,y1-y0));
  dx = m - x0*esc + (W-2*m-(x1-x0)*esc)/2;
  dy = m - y0*esc + (H-2*m-(y1-y0)*esc)/2;
}
function refresh(){ disponer(); path(); encuadrar(); draw(); }

function abrir(n){
  if (n.dispatch) { opened = !opened; hover = null; refresh(); return; }
  const nxt = {module:'file', file:'symbol'}[view.level];
  if (!nxt) return;
  const children = M.levels[nxt].nodes.filter(h => h.parent === n.id);
  if (!children.length) return;
  stack.push({label: n.name, parent: n.id, view: {level: nxt, parent: n.id}});
  view = {level: nxt, parent: n.id};
  hover = null; refresh();
}

let arrastrando = false, ox = 0, oy = 0;
cv.addEventListener('mousedown', e => { arrastrando = true; ox = e.clientX - dx; oy = e.clientY - dy; cv.classList.add('arrastrando'); });
addEventListener('mouseup', () => { arrastrando = false; cv.classList.remove('arrastrando'); });
cv.addEventListener('mousemove', e => {
  if (arrastrando) { tip.style.display = 'none';
    dx = e.clientX - ox; dy = e.clientY - oy; draw(); return; }
  const n = nodoEn(e);
  if (n !== hover) { hover = n; draw(); }
  if (n) mostrarTip(n, e); else tip.style.display = 'none';
});
cv.addEventListener('wheel', e => {
  e.preventDefault();
  const k = Math.exp(-e.deltaY * .0016), [mx, my] = [e.clientX, e.clientY - 44];
  dx = mx - (mx - dx) * k; dy = my - (my - dy) * k; esc *= k; draw();
}, {passive:false});
cv.addEventListener('click', e => { const n = nodoEn(e); if (n) abrir(n); });
document.getElementById('backward').onclick = () => {
  if (!stack.length) return;
  stack.pop();
  view = stack.length ? stack[stack.length-1].view : {level:'module', parent:null};
  refresh();
};
document.getElementById('tema').onclick = () => {
  const r = document.documentElement;
  const oscuro = getComputedStyle(r).getPropertyValue('--bg').trim() !== '#f8fafc';
  r.dataset.tema = oscuro ? 'light' : 'dark'; draw();
};
document.getElementById('leyenda').innerHTML = projects.length
  ? projects.map((p,i) => '<div><i style="background:'+PROY[i%PROY.length]+'"></i>'+p+'</div>').join('')
    + '<div style="margin-top:6px">╌╌ seam (string, no call)</div>'
  : Object.entries(COLOR).filter(([k]) => k)
      .map(([k,v]) => '<div><i style="background:'+v+'"></i>'+k+'</div>').join('');
if (projects.length) document.getElementById('nota').innerHTML =
  '<b>Three repositories in one map.</b> The dashed lines are SEAMS: a literal ' +
  '—a route, a tool name— that one project writes and another serves. They are not ' +
  'calls, and no call graph crosses them.';

// The canvas is sized in PHYSICAL pixels and scaled to logical ones. Without this, on a
// retina screen (dpr=2) it is drawn at half the panel's resolution and everything —text and
// edges— comes out blurry. It is not a matter of taste: it is the difference between reading
// a label and guessing it.
function medir(){
  const dpr = window.devicePixelRatio || 1;
  const w = innerWidth, h = innerHeight - 44;
  cv.width = w * dpr; cv.height = h * dpr;
  cv.style.width = w + 'px'; cv.style.height = h + 'px';
  refresh();
}
addEventListener('resize', medir); medir();
</script>
"""


def page(modelo: dict) -> str:
    # Substitution by markers and not by `%`: the CSS and the JS are full of legitimate
    # `%` (`50%`, `toFixed(2)+'%'`) and the formatting would take them as directives.
    datos = json.dumps(modelo, separators=(",", ":"), ensure_ascii=False)
    return (_PAGINA
            .replace("__TITULO__", html.escape(modelo["project"]))
            .replace("__COLORES__", json.dumps(COLORES))
            # `</script>` inside a JSON string would close the tag containing it.
            .replace("__DATOS__", datos.replace("</", "<\\/")))
