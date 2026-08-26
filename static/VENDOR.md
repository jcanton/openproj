# Vendored assets

No npm, no build step, no CDN at runtime. These files are committed verbatim and
inlined into the pages; `tests/test_render.py` asserts no rendered page references an
external URL. One of them — Yjs — is inlined with two of its lines rewritten, because
nobody publishes it in a form a `<script>` block can run; there is a section on that
below, and the bytes in git are still upstream's. A second — `excalidraw.js` — is not
inlined and is not upstream's bytes at all: it is this repository's own build, fetched
by the browser rather than shipped on every page, and "The editor side," below, is
where the override that permits a build step here is written down.

| file | version | licence | source |
|---|---|---|---|
| `cytoscape.min.js` | 3.30.2 | MIT | https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js |
| `yjs.bundle.mjs` | 13.6.32 | MIT | https://esm.sh/yjs@13.6.32/es2020/yjs.bundle.mjs |
| `yjs-LICENSE.txt` | 13.6.32 | MIT | https://raw.githubusercontent.com/yjs/yjs/v13.6.32/LICENSE |
| `elk.bundled.js` | 0.9.3 | **EPL-2.0** | https://cdn.jsdelivr.net/npm/elkjs@0.9.3/lib/elk.bundled.js |
| `elk-LICENSE.txt` | 0.9.3 | EPL-2.0 | licence text for the file above |
| `ace.js` | 1.44.0 | **BSD-3-Clause** | `src-min-noconflict/ace.js` from https://registry.npmjs.org/ace-builds/-/ace-builds-1.44.0.tgz |
| `keybinding-vim.js` | 1.44.0 | BSD-3-Clause | `src-min-noconflict/keybinding-vim.js` from the same tarball |
| `ace-LICENSE.txt` | 1.44.0 | BSD-3-Clause | `LICENSE` from the same tarball |
| `inter-latin-wght-normal.woff2` | latin subset, variable 100–900 | OFL 1.1 | https://cdn.jsdelivr.net/fontsource/fonts/inter:vf@latest/latin-wght-normal.woff2 |
| `inter-LICENSE.txt` | — | OFL 1.1 | licence text for the face above |
| `excalidraw.js` | 0.18.1 (React 18.3.1) | MIT (code) + 6×OFL-1.1 + MIT (7 shipped font families) | **our own esbuild output — see "The editor side," below** |
| `excalidraw-LICENSE.txt` | 0.18.1 | MIT | https://raw.githubusercontent.com/excalidraw/excalidraw/master/LICENSE |
| `excalidraw-fonts-LICENSE.txt` | — | OFL-1.1 (6 families) + MIT (1) | seven sources, one per family, fetched 2026-08-26 — see "The font licences," below |

Not a file: the colour schemes in `src/openproj/themes.py` are data rather than a
library, and are copied from **tinted-theming/schemes**, spec 0.11, MIT, fetched
2026-08-20 from https://github.com/tinted-theming/schemes/tree/spec-0.11/base16 —
`default-light`, `default-dark`, `gruvbox-light-medium`, `gruvbox-dark-medium`,
`solarized-light`, `solarized-dark`, `tomorrow`, `tomorrow-night`, `one-light`,
`onedark`, `papercolor-light`, `papercolor-dark`, `equilibrium-light`,
`equilibrium-dark`, `silk-light`, `silk-dark`, `atelier-forest-light` and
`atelier-forest`. Each palette carries the name and author it was published under,
beside its sixteen values. Sixteen hex numbers per scheme is smaller than the
machinery to read a directory of YAML at startup, and a scheme that changes
upstream should arrive as a diff somebody reads rather than as a page that quietly
looks different.

The font was absent from this table for as long as it has been in the directory, which
is how the update procedure below came to delete its checksum. Its upstream Inter
release was not written down when it was vendored; the SHA256 below is what identifies
the exact bytes, and whoever replaces the file should record the version here.

**Ace is BSD-3-Clause, which is this repository's own licence**, so nothing about
combining it is in question. What is in question is the notice: all three of the
minified files contain **zero** occurrences of `Copyright`, `BSD` and `Ajax.org` —
upstream strips the block when it minifies, and `src-noconflict/ace.js` opens with it.
BSD-3 clause 2 asks for the notice in a binary redistribution, and this repository
already reads "every rendered page is a copy" as redistribution for Inter, enforced by
`test_the_font_licence_travels_with_the_font`. So `ace-LICENSE.txt` ships here **and**
`render._ace()` writes it into the page as a comment ahead of the bytes, where it travels
with them.

The bytes come out of the npm tarball rather than off a CDN, which is a better precedent
than `cytoscape.min.js` set: `src-min-noconflict/` is a directory upstream publishes, so a
SHA256 over those bytes identifies something a person can point at, not a minifier's
output on somebody else's machine. Verified: `sha256(ace-builds-1.44.0.tgz)` is
`a8116a1e…`, and the two files extracted from it are byte-identical to the ones here.

**`mode-markdown.js` is deliberately not here**, and this is the one to re-read before
adding it. It is 75,276 B for syntax highlighting, which is on nobody's list of asks; it
is the only one of the three files that fails `test_no_page_asks_the_network_for_a_font`,
twice, at offsets 9046 and 47867, on a tokeniser regex and a completion template that
fetch nothing at all; and it bundles the javascript, css, html and xml sub-modes, each of
which defines a `createWorker`. Those ship dormant — `MarkdownMode` inherits `TextMode`,
whose `createWorker` returns `null` — but any later `setMode('ace/mode/javascript')` for a
fenced-code sub-editor builds a `blob:` Worker this CSP blocks **in silence**: an `error`
event with an empty message, no exception, and Ace's own "Could not load worker" warning
never firing, because the constructor does not throw. Measured here, in headless Chrome,
under the real policy, with `window.Worker` hooked before Ace parsed: `ace.js` +
`keybinding-vim.js` with no mode set construct **0** Workers, take **0** CSP violations
and inject **0** scripts, and `session.$worker` is `null`; the same page with the markdown
mode added and `ace/mode/javascript` set constructs one `blob:` Worker and logs
`worker-src <- blob` — and fires **no `error` event at all**, which is one step worse than
the "empty `window.error`" recorded earlier and makes the point harder: the failure is
completely silent. The forced failure is what makes the zero evidence rather than a check
that could only pass.

**Five of Ace's default commands are removed at construction**, in `render.py`, and that is
application code rather than upstream behaviour — the bytes are verbatim, the behaviour
deliberately is not. `find`, `replace`, `showSettingsMenu`, `goToNextError` and
`goToPreviousError` all call `config.loadModule`, which is
`createElement('script'); i.src = e; head.appendChild(i)`. Measured under this policy,
Cmd-F gives `defaultPrevented=true`, one injected `ext-searchbox.js`, a `script-src-elem`
violation, no searchbox in the DOM, and an empty `window.error` — Ace takes Cmd-F from the
browser and gives back nothing. Removed, the key falls through to Chrome's own find, which
works on this document and on the rendered pane beside it.

**ELK is the one file here that is not permissively licensed.** EPL-2.0 is a weak,
file-level copyleft: this repository is BSD-3-Clause and stays BSD-3-Clause, the bundle is
shipped verbatim with its notice beside it in `elk-LICENSE.txt`, and its source is public
at https://github.com/kieler/elkjs. What EPL asks in return is that changes *to that file*
are released under EPL — so it is vendored unmodified, and a patch would go upstream rather
than into this copy. It is here because it is the only layout in reach that understands
nested nodes: measured on the real plan, it drew the graph with none of its six dependency
edges crossing a box they are not attached to, against three of six for dagre.

`cytoscape-edgehandles` was audited and refused, which is the other half of the rule in
AGENTS.md: it draws the connection gesture this page writes by hand, and its browser build
wants `lodash.memoize` and `lodash.throttle` as globals under those exact names — 28 KB
becomes 58 KB and a shim, to replace clicking one node and then another, which works and
which nobody has complained about.

`cytoscape-compound-drag-and-drop` was here for a day. It was taken because the gesture it
replaced had been written here and got wrong; it went because the gesture itself went —
jcanton, 2026-08-20, after using it: refiling belongs to the table, where rows do not move
under you. The extension is deleted rather than left in the directory for the reason dagre
was: a vendored file nothing inlines is a file nobody checks.

dagre and cytoscape-dagre were here until ELK replaced them; they are gone rather than
left in the directory, because a vendored file nothing inlines is a file nobody checks.

`cytoscape-elk` was here and is gone. The graph asks elkjs directly, because the adapter
reads node positions out of ELK's answer and never looks at an edge's `sections` — and
going round it is what lets an edge be declared on the box that holds it, and lets the
layout add the invisible edges that put the boxes in order. Deleted rather than left in
the directory, for the reason dagre was.

Only cytoscape carries its MIT notice inline in the minified file. ELK's ships beside it
as a file because EPL asks for that. Yjs's minified bundle carries none, so the MIT text
ships beside it the way Inter's OFL does.

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
`data:` URI, with no `url()` pointing anywhere else. And if Ace changed, re-run the worker
gate: open `/detail/<id>?editor=ace` in headless Chrome under the real CSP with
`window.Worker` hooked **before** Ace parses, confirm zero Workers and zero
`securitypolicyviolation` events, and force the failure with `ace/mode/javascript` as a
control — a blocked worker throws nothing and logs nothing, so a gate with no forced
failure beside it is a gate that can only pass.

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

**There is an editor library now, and it is Ace 1.44.0.** This section said "No editor
library" from the day CodeMirror 5 was removed until August 2026, and it is written out
here rather than deleted, because the sentence that replaced it has to be legible as an
override rather than as a correction.

The condition this file set for revisiting was **"when somebody is actually slowed down by
the textarea"**. Nobody has produced that measurement, and nobody has claimed to. What
arrived instead was jcanton asking for a HackMD-like editor in seven parts, six of which
were built on the `<textarea>` that was already in the page for about 18 KB — three views,
the toolbar, a full page, line numbers, tabs-to-spaces and draft autosave — and one of
which a textarea cannot have at all: **a vim keymap**. Modal editing over `selectionStart`,
with motions, operators, registers, counts, text objects, macros and an ex line, over an
undo stack you do not own, is not a smaller version of the same job. Asked which way to go
with the price attached, he answered: *"implement both: improvements to our editor as well
as ace."*

So: a human overrode a written rule, deliberately, having been shown what it costs.
**594,306 B raw / ~163 KB gzipped.**

**And then, on 2026-08-20, he moved it to the default side of the parameter:** *"make ace
the default, I think it's worth it."* That is a second override on top of the first and it
is recorded here as one. Nothing measured changed to justify it — the revisit condition
this file set is still "when somebody is actually slowed down by the textarea", and it is
still unmet. What changed is which arm of `render._ace_wanted` the address has to say
something to reach: `?editor=plain` is now the opt-out and an unsaid address means Ace, so
**a writer pays 594 KB by default**, measured on `tests/fixtures/corpus` at 492,311 B for
the plain box against 1,110,377 B beside it. It is the sticky preference that pays the
reload now, because it is the plain-box people whose address has to be corrected — the
smaller page arriving for the person who asked for a smaller page, rather than the library
arriving twice for everybody else.

**Who pays did not change, and that is the half that had to survive the flip.** `editable`
is `base_commit is not None` and the served route passes a commit for everyone, so a
signed-out reader already receives the box and the toolbar — and can type any parameter
they like. `render._ace_wanted` asks `may_write` as well, the same second gate `yjs` and
`coedit` already carry, so a reader's page is the same size with either parameter and with
none: 366,151 B all three ways, measured. Without that gate, Ace on the default arm would
now reach every public reader unasked, for a keymap whose every save is a 403.

Both spellings are still the shape that answers "let me try both": two tabs, one document,
one editor each — and since 2026-08-20 there is a switch beside the three view segments, so
the choice is on the page rather than only in this file.

The search that ended here follows. Everything in it was fetched, checksummed and run;
`docs/EDITOR.md` is the long form.

**The rule this leaves behind for whoever revisits it next:** the price was paid for ONE
ask. If a second editor ever has to be argued for again, the question is not "is it good",
it is "which ask on the list can only be had this way, and what does everybody who did not
ask for it pay".

**The record before this commit, kept because the reasoning in it is still right.**
CodeMirror 5 was vendored and then removed: the
spec's cut line already said CodeMirror saves nothing and costs two days, and vim keys are a
preference, not a requirement. A plain `<textarea>` with a preview needs no dependency at all, and
the 690 KB — a third of it the vim keymap — buys nothing for editing a handful of fields and one
markdown body. The condition written here for revisiting was "when somebody is actually slowed down
by the textarea".

That revisit ran in August 2026, against seven asks for a HackMD-like editor, and the full search is
`docs/EDITOR.md`. Nobody has produced the measurement this paragraph asked for; what arrived instead
was a feature request, which is a legitimate reason for a human to override a recorded rule and is
not the same thing as evidence that the rule was wrong. The finding, so that the next person
inherits the search rather than repeating it:

* **Ace 1.44.0 (`src-min-noconflict`) is admissible, it was measured rather than reasoned
  about, and it was then bought.** BSD-3-Clause — this repository's own licence. Three classic self-registering scripts,
  zero `import`, zero `export`, zero bare `require(`: they run in a `<script>` block untouched and
  need no `_yjs()` analogue. Inlined verbatim under this exact CSP in headless Chrome with
  `window.Worker` hooked before Ace parsed: 0 Workers constructed, 0 CSP violations, 0 network
  requests, `session.$worker === null`, and a forced-failure control on `ace/mode/javascript` that
  *did* build a blocked `blob:` Worker — so the detection was real and not a test that could only
  pass. `ace.js` 475,029 B (126,124 gz), `keybinding-vim.js` 119,277 B (36,518 gz),
  `mode-markdown.js` 75,276 B (22,165 gz). The honest purchase for the one ask a textarea cannot
  have is core + vim, **594,306 B**; with the markdown mode, 669,582 B — 85.8% and 96.7% of the
  number refused above, against a 318,526 B page. The unminified `src-noconflict` build is
  1,307,387 B and fails the font-`url()` assertion 24 more times than the minified one, because of
  how it escapes its own `data:` URIs.
* **One supporting fact in the earlier evidence is wrong and must not be repeated.**
  `mode-markdown.js` contains **four** `createWorker` definitions, not zero — they belong to the
  bundled javascript, css, html and xml sub-modes. The right reason Ace spawns none for markdown is
  structural: `MarkdownMode` inherits `TextMode`, whose `createWorker` returns `null`, and
  `createModeDelegates` wires highlight rules only. The consequence is that four worker-spawning
  sub-modes would ship dormant in every page, and any later `setMode('ace/mode/javascript')` for a
  fenced-code sub-editor builds a `blob:` Worker this policy blocks *silently* — an `error` event
  with an empty message, no exception, and Ace's own "Could not load worker" warning never firing.
* **Ace's default keymap fetches four modules over the network** through `config.loadModule` →
  `net.loadScript`, which is `createElement('script')`. Measured: `metaKey+f` gives
  `defaultPrevented=true`, `scriptsInjected=['ext-searchbox.js']`, a `script-src-elem` violation,
  and an empty `window.error`. Cmd-F is taken from the browser and nothing is given back. The source
  regex `<script[^>]+src=` cannot see a runtime injection, so this has to be tested in a browser.
* **CodeMirror 6 + `y-codemirror.next` is refused on the linker, not on taste.** Nine artifacts,
  816,104 B raw / 278,694 gz, taking the writer's page to 3.56x. It was proved to work — one
  `EditorState` built from all nine packages against this repository's own `yjs.bundle.mjs` — and
  then refused because those nine files carry 42 `import` statements and 9 `export` clauses that
  must be inlined in a hardcoded topological order with each file's bindings rebound to the previous
  IIFE. `_yjs()` below handles one import and one export by string partition and its own docstring
  already refuses the four-module version of that. Fifty-one is more of the refused thing, not less.
  esm.sh's `/build` API answers 403 and is deprecated, so there is no single-artifact route.
  Two traps worth inheriting: `https://esm.sh/codemirror@6?bundle` resolves to `codemirror@6.65.7`,
  which is CodeMirror **5**.65.7 mis-published under a 6.x number and never unpublished; and the
  naive `?bundle` route gives seven private copies of `@codemirror/state`, which is 1,967,935 B of
  silently non-functioning editor.
* **CodeMirror 5 is refused on its upstream.** The set is 692,765 B, vim 33.5% of it — the "690 KB"
  above is exact and nobody rounded in their own favour. But `github.com/codemirror/CodeMirror` is
  now archived and forwarding, and `y-codemirror` was last published in 2021 with both of its live
  issues in the remote-cursor code, which is the part that would be the reason to take it.
* **Toast UI Editor 3.2.2 and EasyMDE 2.21.0 do not survive contact.** Toast UI's self-contained
  bundle exists only on `uicdn.toast.com`, carries a live beacon to `google-analytics.com/collect`
  compiled into the bytes and on by default, and its live preview cannot be `/api/preview` because
  the only hook is synchronous and is handed HTML its own parser has already produced. EasyMDE
  contains the literal string `cdn.` six times, which fails `assert "cdn." not in body` outright,
  and injects a `<link>` to a Font Awesome CDN at runtime for the glyphs its own CSS does not carry.

**The rule that comes out of this and applies to anything vendored next to Yjs:** a binding library
that externalises `yjs` must bind to the **same `Y.Doc` class the room came from**. Two copies of
Yjs in one page are two constructors, and a document built by one is not a document the other will
observe — silently, with nothing raising in either. So such a library can never be inlined beside
`_yjs()` as a block of its own; it has to take this page's `Y` or it does not go in.

Co-editing did not change the decision above, and it is the one place it costs something: drawing
another person's caret over a `<textarea>` means measuring text through a mirror
element, which is the only real pixel work in that feature. So it is not drawn. The
presence list names who else is in the document, which is the half that survives every
reader — and a caret one line off is worse than no caret.

**Both halves of that paragraph have since been overtaken, 2026-08-24, and the sentence at the end
of it is why rather than despite.** A band IS drawn now, on both surfaces. On the `<textarea>` it is
the mirror, measured — the one real piece of pixel work, and it is a line and not a caret, which is
the concession that paragraph was really making. On Ace there is no mirror and no pixel work at all:
the band is a marker in Ace's own layer, laid out on the frame Ace lays out its selection on, and a
seat is an anchor the editor moves inside `applyDelta` rather than an index this page keeps. The
rule the paragraph set is what forced that shape and then what let it ship — the alternative was
five hand-measured terms against zero, and it is now measured at eighty widths, scrolled, folded and
against the painted row, in `tests/test_seats.py`.

**What this costs a re-vendoring**, and the only thing in this feature that does: `addDynamicMarker`,
`drawScreenLineMarker`, `documentToScreenRow`, `createAnchor` and the renderer's `updateBackMarkers`
have to survive it. All five are public. Nothing reads a `$`-prefixed field, and the login is drawn
by a custom property on the marker's own `cssText` rather than as a child node, because the marker
layer recycles its divs between markers and never clears their text.

**No Gantt library.** The timeline is hand-rolled SVG in `render.py`. Hatching for
estimated and unowned spans, cycle boundary rules and per-bar explanations are all
custom, the scheduler emits exact spans, and a library would be fought rather than
used. The spec sanctions this fallback.

## The editor side, and the one file here that is our own build

Every row above identifies bytes somebody else published; a SHA256 says "this is the
file at that URL." `excalidraw.js` breaks that pattern, and it is worth saying exactly
why rather than leaving it to look like an exception nobody explains. `@excalidraw/excalidraw`
0.18.1 ships ESM-only, with roughly thirty bare dependencies externalised for a bundler
to resolve, and it deleted its UMD build — the one shape a `<script>` tag could have run
— in v0.18.0. There is no file upstream publishes that this repository could drop in
and checksum the way `cytoscape.min.js` or `ace.js` are. So `static/excalidraw.js` is
**our own esbuild output**, built by `tools/build-excalidraw.mjs` from the pinned
`tools/excalidraw-package.json` and its lockfile, and what is checksummed is a build this
repository controls rather than an artifact somebody else is on the hook for. `tools/README.md`
has the mechanics; the two facts worth repeating here are that `--loader:.woff2=dataurl`
inlines nothing by itself (the fonts are reached as string literals inside the package's
own chunks, not as anything a loader sees) and that `--format=iife` folds every dynamic
`import()` in regardless, so "English only" and "no mermaid" are stubs the build script
writes rather than flags esbuild offers.

**The override — no npm, no build step, no CDN — was taken deliberately, by jcanton, on
2026-08-26, having been shown the cost, the way Ace's override was.** The cost: `static/`
goes from 2.7 MB to roughly 8.0 MB the day this vendors, all of it one file this
repository builds rather than receives. `detail.html`'s own byte count does not move —
none of these bytes are on the page until somebody presses the drawing button — which is
also why this file is **not inlined**. It is fetched on demand
(`connect-src 'self'` allows the fetch), not carried on every page the way the graph
libraries are, and that is the whole reason it does not appear in
`tests/test_render.py`'s inlining assertions: there is nothing to inline.

Measured, not the spike's earlier guess: **5,508,971 B raw, 1,963,903 B gzip**, against
`@excalidraw/excalidraw` **0.18.1** and React **18.3.1** — not React 19, which the peer
range permits but which was never on the scale. This is smaller than the figure the
spike first reported (5,603,202 B raw / 2,036,296 B gzip), and the difference is not
slack in the build, it is one font family removed after this vendoring looked at its
actual licence — see below. `tools/build-excalidraw.mjs` reproduces this exact byte count;
`node tools/build-excalidraw.mjs` prints the sha256 to compare against `SHA256SUMS`.

`GET /static/{name}` in `web.py` is what actually serves the file: an explicit allowlist
of vendored names, never a path taken off the request, `cache-control: public,
max-age=31536000, immutable` because a vendored file changes only with a release
(unlike a drawing, where the same header would be a lie), and deliberately not a
`StaticFiles` mount — this repository has never had one, and a mount takes a path from
the request where every other route here takes an id and derives the path itself.

## The drawings button's mark, lifted out of the same bundle

The control that opens Excalidraw carries Excalidraw's own mark rather than a text label —
jcanton, 2026-08-26 — inline SVG, like every icon in that bar, because nothing on a page
here may fetch one (`tests/test_render.py`'s `test_no_page_reaches_the_network`, the same
rule every other icon already obeys). The npm package ships no `.svg` files at all, so the
source is the vendored bundle itself: `static/excalidraw.js` defines two separate logo
components, `ExcalidrawLogo-icon` (the glyph, `viewBox="0 0 40 40"`) and `ExcalidrawLogo-text`
(the wordmark, `viewBox="0 0 450 55"`, illegible at the 24px a toolbar button draws at). The
icon is the one this repository took, byte-for-byte — `d`, `fill="currentColor"`, both
copied out of the bundle rather than redrawn — as `_DRAWING_MARK` in `render/detail.py`,
which `render/slides.py` imports rather than carrying a second copy of.

The path's own `viewBox="0 0 40 40"` is not this codebase's usual `24 24`, and is kept
rather than rescaled: the glyph is a 20-subpath compound shape carrying twenty `a`
(elliptical arc) commands, each with a rotation and two flags that are not coordinates, and
a mechanical find-and-multiply over 4,614 characters of path data would scale those exactly
as readily as the lengths beside them, silently drawing the wrong arc. The button's `<svg>`
keeps the house `viewBox="0 0 24 24"` and meets the path with `<g transform="scale(.6)">`
instead — 40 × .6 = 24 — a transform asks nothing of the numbers inside the path, so there
is nothing left in it to get wrong.

Same code, same licence: this is Excalidraw's MIT-licensed mark, used to label a control
that opens Excalidraw, in a bundle this repository already ships. No new licence obligation
follows from a second use of bytes already covered by `excalidraw-LICENSE.txt`, above.

## The font licences, and the one family that did not clear the bar the other seven did

The npm package ships no licence files at all — checked directly, not assumed: only a
`package.json` declaring `"license": "MIT"` and a README. That covers the code. It says
nothing about the twenty-five `.woff2` files the production build inlines as `data:`
URIs across eight families, and a licence claimed for the code is not a licence claimed
for a font bundled inside it. So each family was checked on its own, against the
strongest evidence available for it — most decisively, the font's own `name` table,
read directly out of the shipped bytes with `fontTools` rather than assumed from a
web page, since a page can say anything and a font's `nameID 13`/`14` is what a
`@font-face` actually ships with.

**Seven families shipped, one did not.**

- **Assistant** (4 files) — OFL-1.1. `nameID 13/14` in the shipped
  `Assistant-Regular.woff2` carry the licence text and `http://scripts.sil.org/OFL`
  directly; the copyright is 2020 The Assistant Project Authors
  (https://github.com/hafontia/Assistant) with portions from 2010 The Source Sans Pro
  Authors, Reserved Font Name 'Source'.
- **Cascadia** (1 file, `CascadiaCode-Regular.woff2`) — OFL-1.1. The shipped font's own
  `nameID 13` embeds the full OFL text ahead of a Microsoft embedding-restriction
  preamble that reads more narrowly; the operative licence, confirmed against
  Microsoft's own repository (https://github.com/microsoft/cascadia-code/blob/main/LICENSE,
  fetched 2026-08-26: "Copyright (c) 2019 - Present, Microsoft Corporation, with
  Reserved Font Name Cascadia Code," under OFL-1.1 with no such preamble at all), is the
  OFL grant, not the paragraph in front of it.
- **Comic Shanns** (4 files, one font pre-split for range-request loading) — MIT. The
  shipped font's `nameID 0` carries the entire MIT text inline, matching
  https://github.com/shannpersand/comic-shanns/blob/master/LICENSE (fetched 2026-08-26)
  word for word: Copyright (c) 2018 Shannon Miwa, with four more contributors added
  2023–2024.
- **Excalifont** (7 files) — OFL-1.1, and this is the one to read carefully rather than
  take on the same footing as the other six. The shipped font's own `nameID 0` is bare:
  "Copyright (c) 2024 by Excalidraw. All rights reserved." — no `nameID 13`, no
  `nameID 14`, no licence grant anywhere in the file, where every other shipped family
  carries one. Taken alone, that string is the opposite of a permissive grant. What
  makes this ship anyway is Excalidraw's own public statement about a font it holds the
  copyright to: https://plus.excalidraw.com/excalifont (fetched 2026-08-26) states
  "Download available under OFL-1.1 license (included in the font file)" and "Released
  under the OFL-1.1 license, Excalifont is freely available for both personal and
  commercial use... allowing designers and developers to integrate the font into their
  projects without restrictions." That is the same shape of gap Ace's stripped BSD
  notice left in this table — upstream's own bytes say less than upstream itself has
  said elsewhere — resolved the same way: on the copyright holder's word, with the gap
  written down rather than smoothed over. If a future re-vendoring finds this claim
  retracted or narrowed, this family has to be re-checked from nothing, not assumed.
- **Lilita** (2 files) — OFL-1.1. `nameID 0/14` of the shipped font: Copyright (c) 2011
  Juan Montoreano (juan@remolacha.biz), Reserved Font Name "Lilita One".
- **Nunito** (5 files) — OFL-1.1. `nameID 0/14`: Copyright 2014 The Nunito Project
  Authors, matching https://github.com/googlefonts/nunito (fetched 2026-08-26).
- **Virgil** (1 file) — OFL-1.1, from two independent sources that agree. The shipped
  font's `nameID 13` carries the OFL text in full, and its `nameID 0` reads "Copyright
  (c) 2011 by Your Own Font Foundry. All rights reserved." Excalidraw's own
  redistribution of the same font, https://github.com/excalidraw/virgil/blob/main/LICENSE.md
  (fetched 2026-08-26), restates it as "Copyright (c) 2021 - Present, Ellinor Rapp, with
  Reserved Font Name Virgil," under the same licence. Both copyright lines are recorded
  in `static/excalidraw-fonts-LICENSE.txt` rather than one silently dropped.

**Liberation Sans (1 file, `LiberationSans-Regular.woff2`, 70,668 B) is dropped**, and
not for the reason Xiaolai is cut from every build (209 files, 12,667,492 B, for a CJK
fallback this English-only tool never reaches — pure size). This is a licence call. The
shipped font's own `nameID 0` reads "Digitized data (c) 2007 Ascender Corporation. All
rights reserved," `nameID 13` points only to "the license agreement under which you
accepted the Liberation font software," and `nameID 14` is a dead Ascender Corporation
URL — no OFL text, no OFL URL, nowhere in the file. That absence identifies the vintage:
Red Hat's OFL-1.1 relicense of Liberation, current since 2012, carries its own distinct
copyright line, "Copyright (c) 2012 Red Hat, Inc. with Reserved Font Name Liberation"
(confirmed against Debian's packaging metadata for the current release), which does not
appear anywhere in this file. What ships inside `@excalidraw/excalidraw` 0.18.1 is the
**older, pre-2012 Ascender/Red Hat build**, licensed GNU GPLv2 with the standard font
embedding exception — and that exception's own text is scoped to "a document which uses
this font, and embed[s]... this font... into the document," not to software that bundles
the font as a bytes resource inside its own distributed binary. Unlike ELK, the one other
copyleft file in this table, Liberation Sans has no file of its own here for a notice to
travel beside: it is a `data:` URI string folded into one minified `excalidraw.js` file,
indistinguishable from Excalidraw's own MIT code once esbuild is done with it. A licence
that does not travel with what it covers is not a licence this table can carry, so
`dataUri()` in `tools/build-excalidraw.mjs` returns the same `local:` sentinel it returns
for Xiaolai, and `ExcalidrawFontFace.createUrls()` falls back with no fetch and no
console error — confirmed by the spike for the mechanism generally, and re-checked here
for this specific family after the build changed. Excalidraw's own font metadata marks
Liberation Sans `private: true`: it is an internal metrics-fallback face, never offered
in the font picker, so the cut changes nothing a person using this tool can choose.

**This is the one visible-to-users consequence worth stating plainly, because it is the
opposite of Liberation's:** Excalifont and Virgil, the two hand-drawn faces that give
Excalidraw drawings their look, both shipped. Nothing about the font search took away
the hand-drawn face.

The full texts are `static/excalidraw-LICENSE.txt` (Excalidraw's own MIT licence, for
the code) and `static/excalidraw-fonts-LICENSE.txt` (the seven shipped families, each
under its own heading, in the order above).
