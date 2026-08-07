# vendor/

## `mermaid.min.js.gz`

Mermaid **11.16.0**, licencia **MIT** (© Knut Sveidqvist y contribuidores).
Bundle UMD oficial, tomado de `https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js`
y comprimido con `gzip -9`.

**Por qué está acá.** `--html` genera una página que se abre con doble clic, y una página que
depende de una CDN no es autosuficiente: sin red el diagrama se degrada a texto. Incrustado, la
página funciona en un avión, dentro de un adjunto, o dentro de cinco años cuando esa URL ya no
exista.

**Por qué comprimido.** El bundle crudo pesa 3,4 MB; comprimido, 0,93 MB en el repositorio y
1,2 MB de base64 en cada página generada. La página lo descomprime con `DecompressionStream`,
que es una API del navegador — no agrega ninguna dependencia.

**Cadena de degradación**, en orden: incrustado → CDN (navegador sin `DecompressionStream`) →
el diagrama como texto legible dentro de su `<pre>` (sin red). Nunca un hueco en blanco.

**Para actualizarlo:**

```bash
curl -sL https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js | gzip -9 > mcview/vendor/mermaid.min.js.gz
```

Y actualizar la versión de arriba. `pagina.py` no la lee: sólo lee el archivo, así que un
olvido acá no rompe nada — pero deja el dato mal, que es peor de lo que parece.
