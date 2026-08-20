# Vendored assets

No npm, no build step, no CDN at runtime. These files are committed verbatim and
inlined into the pages; `tests/test_render.py` asserts no rendered page references an
external URL. One of them — Yjs — is inlined with two of its lines rewritten, because
nobody publishes it in a form a `<script>` block can run; there is a section on that
below, and the bytes in git are still upstream's.

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
**594,306 B raw / ~163 KB gzipped**, and it is charged to nobody who does not ask —
`?editor=ace` is what makes the server inline it, `openproj:editor:1` is what carries the
choice into the next visit, and a page nobody typed that on has not one byte of it.

The parameter alone is not the whole gate, and the missing half is worth writing down:
`editable` is `base_commit is not None` and the served route passes a commit for everyone,
so a signed-out reader already receives the box and the toolbar — and can type the
parameter too. `render._ace_wanted` therefore asks `may_write` as well, the same second
gate `yjs` and `coedit` already carry, so a reader's page is the same size with the
parameter as without it. Without that, Ace at the `editable` gate would have taken a public
reader from 209,872 B to 879,454 B, 4.19x, for a keymap whose every save is a 403.

The parameter is also the shape that answers "let me try both": two tabs, one document, one
editor each.

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

**No Gantt library.** The timeline is hand-rolled SVG in `render.py`. Hatching for
estimated and unowned spans, cycle boundary rules and per-bar explanations are all
custom, the scheduler emits exact spans, and a library would be fought rather than
used. The spec sanctions this fallback.
