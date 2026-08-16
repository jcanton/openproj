# Vendored assets

No npm, no build step, no CDN at runtime. These files are committed verbatim and
inlined into the pages; `tests/test_render.py` asserts no rendered page references an
external URL.

| file | version | licence | source |
|---|---|---|---|
| `cytoscape.min.js` | 3.30.2 | MIT | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| `dagre.min.js` | 0.8.5 | MIT | https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js |
| `cytoscape-dagre.js` | 2.5.0 | MIT | https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js |
| `inter-latin-wght-normal.woff2` | latin subset, variable 100–900 | OFL 1.1 | https://cdn.jsdelivr.net/fontsource/fonts/inter:vf@latest/latin-wght-normal.woff2 |
| `inter-LICENSE.txt` | — | OFL 1.1 | licence text for the face above |

The font was absent from this table for as long as it has been in the directory, which
is how the update procedure below came to delete its checksum. Its upstream Inter
release was not written down when it was vendored; the SHA256 below is what identifies
the exact bytes, and whoever replaces the file should record the version here.

Only cytoscape carries its MIT notice inline in the minified file. dagre and
cytoscape-dagre declare theirs in their upstream `package.json`.

## Checksums, and updating a file

Download the new file, then, from this directory:

```
shasum -a 256 *.js *.woff2 > SHA256SUMS && shasum -a 256 -c SHA256SUMS
```

`*.js` alone was the old instruction, and `>` truncates: running it wrote three lines
over four and silently dropped the woff2's checksum, leaving the one binary in the
repository as the one nobody could verify. Both globs, or name every file.

Then check that the graph page still lays out the seed corpus left to right, and — if
the font changed — that a rendered page still carries one `@font-face` whose `src` is a
`data:` URI, with no `url()` pointing anywhere else.

## The font, and what the OFL asks of us

`inter-latin-wght-normal.woff2` is Inter, Copyright 2016 The Inter Project Authors
(https://github.com/rsms/inter), under the SIL Open Font License 1.1. The full licence
text is `inter-LICENSE.txt` in this directory.

The OFL's condition is that the copyright notice and the licence travel with the font,
including when it is bundled inside something else. Every page openproj renders embeds
the whole face as a base64 `data:` URI, so **every rendered page is a copy of the
font** — a static export mailed to somebody, or a single HTML file on a memory stick,
has redistributed it. The notice is therefore written into the `@font-face` block in
`_SHELL` in `render.py`, where it ships with the bytes, as well as here.

Two further clauses to keep in mind before changing anything:

- The font may not be sold on its own. Bundled in this tool it is not, and openproj
  must never be sold *as* a font.
- A modified version may not use the reserved name "Inter". We do not modify it; if the
  face is ever subset or re-hinted here, the result has to be renamed, and the
  `font-family` in `_SHELL` and this table have to say so.

## What is deliberately not here

**No editor library.** CodeMirror 5 was vendored and then removed: the spec's cut line already said
CodeMirror saves nothing and costs two days, and vim keys are a preference, not a requirement. A
plain `<textarea>` with a preview needs no dependency at all, and the 690 KB — a third of it the vim
keymap — buys nothing for editing a handful of fields and one markdown body. Revisit when somebody
is actually slowed down by the textarea, not before.

**No Gantt library.** The timeline is hand-rolled SVG in `render.py`. Hatching for
estimated and unowned spans, cycle boundary rules and per-bar explanations are all
custom, the scheduler emits exact spans, and a library would be fought rather than
used. The spec sanctions this fallback.
