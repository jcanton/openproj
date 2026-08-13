# Vendored JavaScript

No npm, no build step, no CDN at runtime. These files are committed verbatim and
served from disk; `tests/test_render.py` asserts no rendered page references an
external URL.

| file | version | source |
|---|---|---|
| `cytoscape.min.js` | 3.30.2 | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| `dagre.min.js` | 0.8.5 | https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js |
| `cytoscape-dagre.js` | 2.5.0 | https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js |

Checksums in `SHA256SUMS`. To update: download, re-run `shasum -a 256 *.js > SHA256SUMS`,
and check the graph page still lays out the seed corpus left to right.

**No editor library.** CodeMirror 5 was vendored and then removed: the spec's cut line already said
CodeMirror saves nothing and costs two days, and vim keys are a preference, not a requirement. A
plain `<textarea>` with a preview needs no dependency at all, and the 690 KB — a third of it the vim
keymap — buys nothing for editing a handful of fields and one markdown body. Revisit when somebody
is actually slowed down by the textarea, not before.

**No Gantt library.** The timeline is hand-rolled SVG in `render.py`. Hatching for
estimated and unowned spans, cycle boundary rules and per-bar explanations are all
custom, the scheduler emits exact spans, and a library would be fought rather than
used. The spec sanctions this fallback.
