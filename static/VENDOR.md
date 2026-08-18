# Vendored assets

No npm, no build step, no CDN at runtime. These files are committed verbatim and
inlined into the pages; `tests/test_render.py` asserts no rendered page references an
external URL. One of them — Yjs — is inlined with two of its lines rewritten, because
nobody publishes it in a form a `<script>` block can run; there is a section on that
below, and the bytes in git are still upstream's.

| file | version | licence | source |
|---|---|---|---|
| `cytoscape.min.js` | 3.30.2 | MIT | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| `dagre.min.js` | 0.8.5 | MIT | https://cdn.jsdelivr.net/npm/dagre@0.8.5/dist/dagre.min.js |
| `cytoscape-dagre.js` | 2.5.0 | MIT | https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.js |
| `yjs.bundle.mjs` | 13.6.32 | MIT | https://esm.sh/yjs@13.6.32/es2020/yjs.bundle.mjs |
| `yjs-LICENSE.txt` | 13.6.32 | MIT | https://raw.githubusercontent.com/yjs/yjs/v13.6.32/LICENSE |
| `inter-latin-wght-normal.woff2` | latin subset, variable 100–900 | OFL 1.1 | https://cdn.jsdelivr.net/fontsource/fonts/inter:vf@latest/latin-wght-normal.woff2 |
| `inter-LICENSE.txt` | — | OFL 1.1 | licence text for the face above |

The font was absent from this table for as long as it has been in the directory, which
is how the update procedure below came to delete its checksum. Its upstream Inter
release was not written down when it was vendored; the SHA256 below is what identifies
the exact bytes, and whoever replaces the file should record the version here.

Only cytoscape carries its MIT notice inline in the minified file. dagre and
cytoscape-dagre declare theirs in their upstream `package.json`. Yjs's minified bundle
carries none, so the MIT text ships beside it the way Inter's OFL does.

## Checksums, and updating a file

Download the new file, then, from this directory:

```
shasum -a 256 *.js *.mjs *.woff2 > SHA256SUMS && shasum -a 256 -c SHA256SUMS
```

`*.js` alone was the old instruction, and `>` truncates: running it wrote three lines
over four and silently dropped the woff2's checksum, leaving the one binary in the
repository as the one nobody could verify. Every glob, or name every file — `*.mjs`
joined the line the day Yjs arrived, for exactly the same reason.

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

## Yjs, and the two lines that are not verbatim

Every other file here is inlined byte for byte. `yjs.bundle.mjs` cannot be, and the
reason is worth writing down rather than discovering.

Yjs publishes no self-contained browser bundle. `dist/yjs.mjs` (299,797 B) carries
twenty bare `lib0/*` imports, which resolve against nothing in a page; jsDelivr's
`+esm` (79,709 B) rewrites them to CDN paths, which is exactly what
`test_no_page_reaches_the_network` exists to catch. esm.sh's `es2020/yjs.bundle.mjs`
is the one artifact with lib0 bundled in, and it is still an ES module: it opens with
one `import` and closes with one `export{…}`, and a page built out of inlined
`<script>` blocks has no module graph to hand either to.

So `render._yjs()` reads these bytes, binds the import to `undefined`, turns the
export clause into the return value of an IIFE, and inlines the result;
`test_the_yjs_bundle_inlines_as_a_classic_script` asserts nothing that looks like a
module survives. The bytes in git stay upstream's and stay checksummed.

`undefined` is not a stub. The bundle dereferences the imported binding in one place
that is not already behind a guard — lib0 asking `typeof __Process$ < "u" &&
__Process$.release && /node|io\.js/.test(…)`, which means "am I under Node?" — and in
a page the answer is no. The alternative was vendoring esm.sh's `node/process.mjs`
beside it, which measurement rules out: that file is not a leaf. It imports
`node/events.mjs` (12,122 B) and `node/tty.mjs` (685 B), so honouring it means joining
four modules by rewriting each one's imports, which is a bundler written at render
time. Its `release()` returns `{}` anyway, so the polyfill answers the same "no",
20,668 bytes later.

**y-protocols is deliberately not here.** Awareness is a per-client map with a timeout,
which is a hundred lines over a socket this application owns, against a second copy of
lib0 and an import map the CSP forbids. **Automerge is deliberately not here either**:
`@automerge/automerge` 3.4.1's wasm is 3,571,259 bytes — 4,761,717 inlined as base64,
thirteen cytoscapes in every detail page — and running it needs
`script-src 'wasm-unsafe-eval'`. Weakening the policy to run a merge algorithm is the
wrong trade.

## What is deliberately not here

**No editor library.** CodeMirror 5 was vendored and then removed: the spec's cut line already said
CodeMirror saves nothing and costs two days, and vim keys are a preference, not a requirement. A
plain `<textarea>` with a preview needs no dependency at all, and the 690 KB — a third of it the vim
keymap — buys nothing for editing a handful of fields and one markdown body. Revisit when somebody
is actually slowed down by the textarea, not before.

Co-editing did not change this, and it is the one place it costs something: drawing
another person's caret over a `<textarea>` means measuring text through a mirror
element, which is the only real pixel work in that feature. So it is not drawn. The
presence list names who else is in the document, which is the half that survives every
reader — and a caret one line off is worse than no caret.

**No Gantt library.** The timeline is hand-rolled SVG in `render.py`. Hatching for
estimated and unowned spans, cycle boundary rules and per-bar explanations are all
custom, the scheduler emits exact spans, and a library would be fought rather than
used. The spec sanctions this fallback.
