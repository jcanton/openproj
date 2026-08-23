# The editor jcanton asked for

Written 2026-08-19, rewritten 2026-08-20 when the audit it asked for finished. Nothing
here is built yet. The audit is the point of this file: six probes measured the
candidates, three proposals argued from the measurements, a judge chose, and thirteen
skeptics attacked the choice. Three of them landed and the choice changed. What follows
is the search, so that the next person inherits it rather than repeating it —
`AGENTS.md`'s **Look for it before you write it**, which also says the answer is allowed
to be no, as long as the no is written down.

## What was asked for

A body editor as close to HackMD's as we can get, in this order of importance:

1. Three views: edit only, edit with live preview, preview only.
2. The buttons along the top of the editor.
3. A full-page interface rather than a resizable text box.
4. Line numbers.
5. Tabs to spaces, and a choice of how many.
6. A vim keymap that can be toggled.
7. Autosave, with the interval settable.

And two constraints on top of the seven:

* **The co-editing has to keep working.** Two people, one document, one commit — see
  `coedit.py` and the room in `web.py`.
* **Keep both editors and let a person choose.** The textarea that is there now stays as
  an option. This is a preference like the theme and the measure, and `remembered` in the
  shell is where those live.

Plus: the hover cards and double-click-to-open are not the editor's, and nothing here
should cost them.

## The audit

Everything below was fetched, checksummed and run. Byte counts are `stat` on the fetched
artifact; page counts are `render_detail(index, ROUTES, only=…, base_commit=…,
may_write=True)` encoded to UTF-8; gzip is `gzip -9`.

**The number every candidate is weighed against.** A writer's editable detail page is
318,526 B raw / 132,288 B gz on the `tests/fixtures/corpus` pitch, and 324,285 B /
133,650 B on the seed corpus through the served route — two fixtures, not a disagreement;
three parties landed on each. Of that, the inlined Yjs IIFE is 93,162 B raw / 29,833 B gz
marginal, the whole `_COEDIT` script is 21,251 / 7,097, and the Inter `data:` URI is
64,367 / 49,640. A signed-out reader's page is 209,872 B, the static export's
`detail.html` is 257,922 B, and `graph.html` already ships 2,230,144 B / 689,001 B gz to
every reader with no gate at all. "Too big" is not an argument this repository can make in
the abstract. It can only make "who pays, for what they asked for".

### No library at all — the `<textarea name=body>` that is already in the page

Six of the seven asks land on it. Three views is a class on `article.record` plus the
`/api/preview` round trip that already exists at `render.py:8482`. The full page is CSS.
The toolbar is more entries in `FORMATS` (`render.py:7386`) — with a fourth `insert:`
branch in `applyMark` (`render.py:7402`), which today has exactly three: `fence`,
`prefix`, `wrap`. Tabs-to-spaces is a Tab branch in the `keydown` handler that already
exists at `render.py:7476`, going through `replaceRange` so native undo survives.
Autosave is a throttle and a receipt on the per-input draft write at `render.py:8581`.

Line numbers were the item every probe called the one that forces a library, and that is
now measured false. One `display:block` span per logical line in a mirror that copies the
same twelve computed styles `render.py:8831` already copies for the seat bands reproduces
the textarea's soft wrapping exactly: 6 hostile corpora × 481 widths swept 1 px at a time
= 2,886 measurements, zero mismatches, worst |delta| 0 px, correct per-line row counts
(1,1,4,1,1,1,4,1,2,1,1 on the sample document), and `offsetTop` gives each number's
position directly. 4.4 ms to rebuild 400 logical lines, 22 ms at 2,000. A second party
got the same answer independently over 8 text shapes × 5 widths, including a proportional
font, at 2.0 ms per 400 lines and 18.7 ms per 4,000.

What made it look impossible is a one-line bug that is in shipped code: syncing the mirror
with `ghost.style.width = BODY.clientWidth + 'px'` (`render.py:8838`) — an integer, where
the textarea's real content box is fractional. At widths sitting on a wrap boundary that
flips one break, and every line below it lands a whole line height wrong, up to three:
8 to 50 of 481 widths per corpus, 1.7% to 10.4%. Syncing the mirror as a fractional
content box takes all six corpora to 0 of 481.

Vim is the one ask a textarea cannot have. It is modal editing over `selectionStart` —
motions, operators with a register, counts, text objects, visual line, macros, the ex
line — and an undo stack you do not own. CodeMirror 5's implementation is 232,206 B;
Ace's is 119,277 B minified. Hand-rolling it is not a smaller version of the same job.

Estimated cost of the whole textarea route: **~18,000 B raw / ~5,000 B gz**, +5.7% raw and
+3.8% gz on the writer's page, and zero on the reader's page and zero on the export. That
figure is an estimate calibrated at 46 B/line against the shipped `_COEDIT` block (458
lines, 21,203 B), not a measurement, because the code does not exist yet. It is the one
number in this audit nobody has measured.

### Ace 1.44.0 (`ace-builds`, `src-min-noconflict`) — admissible, measured, and not bought

| file | bytes | sha256 (head) | gz -9 |
|---|---|---|---|
| `ace.js` | 475,029 | `072d13e5…` | 126,124 |
| `mode-markdown.js` | 75,276 | `7492ad87…` | 22,165 |
| `keybinding-vim.js` | 119,277 | `464f901e…` | 36,518 |

BSD-3-Clause — this repository's own licence. Classic scripts, self-registering through
`ace.define`, zero `import`, zero `export`, zero bare `require(`; they parse and run in a
bare node `vm`, so no `_yjs()` analogue is needed. No CSS file at all — 7
`importCssString` calls, and the CSP probe measured that runtime `<style>` injection,
CSSOM `insertRule` and `adoptedStyleSheets` all work under this exact policy. Zero
`cdn.`, zero `</script`, zero `eval(`, zero `new Function`, zero `localStorage`. Two
external URLs in all three files: the XHTML namespace and a github.com link in a comment.
The bytes are byte-identical to the published npm tarball's `src-min-noconflict/`, not a
CDN-generated derivative like CodeMirror's `.min.js`, and refetches reproduce the digests.
`ajaxorg/ace` is not archived, was pushed 2026-08-13, and has zero advisories for the
package's whole life.

**The worker gate passes, and it was measured rather than reasoned.** Three parties
inlined the three files under `render.CSP` verbatim in headless Chrome, with `window.Worker`
hooked before Ace parsed: 0 Workers constructed, 0 CSP violations, 0 network,
`session.$worker === null`, markdown tokenised (`markup.heading.1`, `string.strong`,
`string.emphasis`), gutter cells numbering **source** lines under soft wrap, soft tabs at
widths 2/3/8 with no literal tab, vim attached as `ace/keyboard/vim`. Two of them forced
the failure as a control: `ace/mode/javascript` does build a `blob:` Worker, Chrome logs
`worker-src <- blob`, and it surfaces as an `error` event with `message: ""` — no
exception, and Ace's own `console.warn("Could not load worker")` never fires because the
constructor does not throw. The detection was real.

One supporting fact in the evidence is wrong and must not be repeated: `mode-markdown.js`
contains **four** `createWorker` definitions, not zero — they belong to the bundled
javascript, css, html and xml sub-modes. The right reason is structural: `MarkdownMode`
inherits `TextMode`, whose `createWorker` returns `null`, and `createModeDelegates` wires
highlight rules only. The consequence is that four worker-spawning sub-modes ship dormant
in the page, so any future `setMode('ace/mode/javascript')` for a fenced-code sub-editor
builds a blocked `blob:` Worker that fails in silence.

Three costs the "verbatim, no rewrite" framing does not carry:

* `mode-markdown.js` **fails `test_no_page_asks_the_network_for_a_font`**. Five parties
  ran that test's own regex over the bytes. `ace.js` has 24 `url(`, all `data:`.
  `keybinding-vim.js` has 0. `mode-markdown.js` has two that are neither `data:` nor `#`:
  offset 9046, `regex:"(?:url(:?-prefix)?|domain|regexp)\\("`, captured `:?-prefix`; and
  offset 47867, `"background-image":{"url('/$0')":1}`, captured `/$0`. Demonstrated end to
  end: the editable page has 0 failures today, the same page with the three files inlined
  has exactly 2. Nothing fetches — one is a tokenizer regex and one is a completion
  template — but the assertion is a bare pattern scan over the whole page body including
  `<script>` contents, and `static/VENDOR.md`'s own written acceptance check says the same
  thing in prose.
* **Ace's default keymap fetches four modules over the network.** `ace.js`'s command table
  calls `config.loadModule` for `ace/ext/searchbox` (find, Ctrl-F/Cmd-F, and replace),
  `ace/ext/settings_menu`, `ace/ext/error_marker` and `ace/ext/prompt` — none of which is
  in the three files — falling through to `net.loadScript`, which is
  `createElement('script'); i.src = e; head.appendChild(i)`. Measured under the verbatim
  CSP: `metaKey+f` gives `defaultPrevented=true`, `scriptsInjected=['ext-searchbox.js']`,
  a `securitypolicyviolation` on `script-src-elem`, `searchbox_in_dom=false`, and the only
  signal is an empty `window.error`. Ace takes Cmd-F away from the browser and gives back
  nothing, silently. `test_no_page_reaches_the_network`'s `<script[^>]+src=` regex cannot
  see a runtime injection. `ext-searchbox.js` is 14,164 B and clean; the alternative is
  `removeCommand` on five default commands, which is application code and therefore not
  "verbatim behaviour".
* **The licence notice does not travel.** All three minified files contain 0 occurrences
  of `Copyright`, `BSD` or `Ajax.org`; `src-noconflict/ace.js` opens with the full block.
  The real LICENSE is 1,490 B, sha256 `850f545c…`. BSD-3 clause 2 asks for the notice in
  binary redistribution, and this repository already reads "every rendered page is a copy"
  as redistribution for Inter, enforced by `test_the_font_licence_travels_with_the_font`.
  So `ace-LICENSE.txt` ships in `static/` and the notice goes in the page.

What Ace would deliver against the seven asks: line numbers (4), soft tabs at a set width
(5), and vim (6). Since line numbers now come free on the textarea and markdown
highlighting is on nobody's list, the honest purchase is **`ace.js` + `keybinding-vim.js`,
594,306 B raw, for ask 6 alone**; with `mode-markdown.js` it is 669,582 B. The readable
build is strictly worse rather than better: `src-noconflict` is 1,307,387 B and fails the
`url()` assertion 24 more times, because its `url(\"data:…\")` escaping makes the regex
capture a bare backslash.

**The half that does not survive is the co-editing binding.** Every measured claim about
reusing this repo's one Yjs binding across Ace came back the other way; that is the next
section but one. There is no upstream to fall back on: `y-ace`, `y-ace-editor`,
`ace-yjs`, `yjs-ace` and `y-brace` all 404 on the npm registry.

### CodeMirror 6 + `y-codemirror.next` — refused on the linker and the bytes

Nine artifacts from esm.sh's `?bundle&external=` route, MIT throughout, **816,104 B raw /
278,694 B gz**, taking the writer's page to 1,134,630 B (3.56x):
`@codemirror/state` 49,353, `view` 201,701, `language` 67,885, `commands` 48,189, `search`
21,634, `autocomplete` 38,447, `lang-markdown` 245,937, `@replit/codemirror-vim` 123,207,
`y-codemirror.next` 19,751.

It was proved to work, by running it rather than reading it: with the bare specifiers
rewritten to relative paths, one `EditorState` was built from extensions contributed by
all nine packages at once — `vim()`, `lineNumbers()`, `history()`, `markdown()`,
`indentUnit.of('    ')`, `yCollab(ytext, awareness)` — against this repository's own
`static/yjs.bundle.mjs`. It built, which is the single-copy proof: two copies of
`@codemirror/state` throw `Unrecognized extension value in extension set`.

It is refused on the shape of the inlining. Nine files carry **42 import statements and 9
export clauses = 51 module lines**, which must be inlined in a hardcoded topological order
with each file's imported bindings rebound to the previous IIFE's return value.
`render._yjs()` handles one import and one export by string partition, and its own
docstring already refuses the four-module version of this: "joining four modules by
rewriting each one's imports, which is a bundler written at render time". Nine is more of
the refused thing, not less. Two further facts belong on the record: esm.sh's `/build`
API is dead (`POST` answers 403, "The `/build` API has been deprecated"), so there is no
single-artifact route at all; and the naive `?bundle` route gives seven private copies of
`@codemirror/state` in 1,967,935 B of silently non-functioning editor.

Two traps worth inheriting. `https://esm.sh/codemirror@6?bundle` does **not** give you
CodeMirror 6: it resolves to `codemirror@6.65.7`, a CodeMirror **5**.65.7 mis-published
under a 6.x number in 2022 and never unpublished, and the 174,497 B you get back ends in
`fromTextArea` and `version="6.65.7"`. And the `X-<base64>` externals paths are an
undocumented cache-key encoding of a query string; they are byte-reproducible today, but
whether they are "upstream's bytes" in the sense `VENDOR.md` means is a judgement, not a
measurement.

What CodeMirror 6 alone would have bought that nothing else does: `yCollab` — Yjs sync,
remote carets and **collaborative undo** in one call, from an upstream that is tested.
Its awareness surface is entirely duck-typed (`.on`, `.off`, `.getLocalState`,
`.setLocalStateField`, `.getStates`, `.doc.clientID`, `.meta`), so the hand-rolled
awareness this application owns satisfies it without vendoring `y-protocols`.

### CodeMirror 5 — the thing that was refused before, and its upstream has left

Sixteen files, all UMD or the classic `else mod(CodeMirror)` browser branch, all inlining
byte for byte with no rewriting, all carrying their own MIT notice on line one, none
containing `</script` or `cdn.`. It was proved in Chrome across 23 assertions: editor
built, gutter drawn, markdown tokenised, Enter continued a list, vim toggled on and off,
two editors synced through `y-codemirror` bound to this repository's vendored Yjs.

The set the record counted is **692,765 B** exactly (402,055 + 8,720 + 232,206 + 31,325 +
13,353 + 5,106), of which vim is 232,206 = 33.5%. Re-measured at 5.65.18, the release
current when the decision was written: 692,718 B. The recorded "690 KB — a third of it the
vim keymap" is exact and nobody rounded in their own favour. With the Yjs binding and the
vim prerequisites the honest total is 755,159 B; without vim, 498,145 B.

Two things changed since the record, and both point the same way. `github.com/codemirror/
CodeMirror` is `archived: true`, description "In-browser code editor (version 5, legacy)",
last two commits 2026-04-15 "Remove github links" and 2026-04-16 "Add forwarding link",
README now opening "This repository has moved to https://code.haverbeke.berlin/codemirror/
codemirror5". And `y-codemirror` 3.0.1 was last published 2021-11-15; its author's last
substantive commit was a pointer to the CM6 successor; its two live issues are both in the
remote-cursor code, which is the part that would be the reason to take it; and npm
publishes nothing that runs in a page, so the only usable artifact is esm.sh's bundle,
whose two imports sit at byte offsets 178 and 2004 — mid-file, so the rewrite is regex at
arbitrary positions rather than a partition on a fixed string. That is a second, looser
instance of the one non-verbatim inline this repository is willing to defend. It spends
the precedent rather than following it.

### Toast UI Editor 3.2.2 — looks like the answer to asks 1 and 2, and does not survive contact

`toastui-editor-all.min.js` 534,289 B + `toastui-editor.min.css` 165,438 B = 699,727 B,
MIT (with DOMPurify 2.3.3 under Apache-2.0 OR MPL-2.0 inline). It clears the bar everyone
expects it to fail: 8 `url()` in the CSS and every one `data:`, no `@import`, no
`@font-face`, no icon font. It fails on four other things.

The self-contained bundle exists **only on `uicdn.toast.com`**; the npm package publishes
no `.min.js` and no `-all` build, and its `dist/toastui-editor.js` is a webpack UMD whose
browser branch reads `factory(root[undefined], …)` eight times over for its externalised
prosemirror packages. The bundle carries a live beacon to
`https://www.google-analytics.com/collect` with `location.hostname`, on by default,
suppressed only by a runtime `usageStatistics: false` — a telemetry call site compiled
into bytes whose guarantee is supposed to live in the checksum, and
`test_no_page_reaches_the_network` would not catch it because the string has no `cdn.`.
Its live preview is its own incremental parser and cannot be `/api/preview`: the only hook
is `beforePreviewRender?: (html: string) => string`, synchronous, handed HTML that
ToastMark has already produced — so the headline reason to take the library is the half
that would have to be switched off. And asks 4, 5 and 6 are simply absent: `lineNumbers`
0, `gutter` 0, `tabSize` 0, `indentUnit` 0, `vim` 0, because it is ProseMirror underneath
even in markdown mode and there is no text buffer to hang a gutter on. Latest release
3.2.2, 2023-02-17.

### EasyMDE 2.21.0 — the closest to a drop-in, and mechanically disqualified

One browserify UMD, 327,475 B + 12,923 B of CSS, MIT, CodeMirror 5 and marked bundled in;
toolbar, side-by-side, fullscreen, `lineNumbers`, `tabSize`, `indentUnit` all present, and
its `previewRender` is genuinely async-capable (`var t = e.options.previewRender(...); null
!= t && (i.innerHTML = t)`), so `/api/preview` would work — the only candidate whose
preview can be the server's.

It dies on three facts. The bundle contains the literal string `cdn.` six times, which
fails `assert "cdn." not in body` outright and no option changes that. It injects a
`<link>` to `maxcdn.bootstrapcdn.com/font-awesome` at runtime unless
`autoDownloadFontAwesome: false`, and its 20 toolbar buttons are `<i class="fa fa-*">`
elements with zero glyph data in its own CSS, so switching that off gives a blank toolbar
to be rebuilt button by button. And vim is not in it — 0 hits — while adding CM5's
`vim.js` (232,206 B) needs a global `CodeMirror` the browserify wrapper never publishes
plus the `dialog` addon it does not bundle. Its spell checker also XHRs two dictionaries
from jsDelivr unless disabled.

### Milkdown / ProseMirror — not candidates, on two independent grounds

Distribution: `prosemirror-view` 247,836 B ships CJS + ESM with three bare imports and no
`browser`/`unpkg`/`jsdelivr` field; `@milkdown/core` 23,632 B ships one ESM entry with 13
bare specifiers including `unified`, `remark-parse` and `remark-stringify`, and
`@milkdown/crepe` adds `@codemirror/*`, `katex`, `dompurify` and `lodash-es` on top. Yjs
was vendorable because esm.sh publishes one bundled artifact whose module boundary is two
lines. Nothing in this family has such an artifact.

Product: this repository's shared type is a `Y.Text` of markdown **source**, spliced by
offset on both sides, previewed through `/api/preview` over that exact text, and stored in
git as that text so people read the diffs. A ProseMirror-backed WYSIWYG's source of truth
is a document tree serialised to markdown on the way out, so an untouched paragraph can
change in the diff because the round trip normalised it. That is a different product, and
asks 4, 5 and 6 are meaningless in it.

### The gates every candidate had to pass, and what they cost

The CSP is `default-src 'none'; img-src 'self' data:; font-src data:; style-src
'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none';
form-action 'self'` (`render.py:917`). Measured in Chrome against that exact string:
`eval`, `new Function` and WebAssembly compilation all throw; **every** form of Worker —
`blob:`, `data:` and same-origin — is blocked, and blocked silently, as an `error` event
with an empty message rather than an exception; and every style-injection form works, so a
library's runtime stylesheet is not the problem.

Four mechanical gates in the suite. `assert "cdn." not in body` is a bare substring over
the whole page. `test_no_page_asks_the_network_for_a_font` rejects any `url(` token that
is not `data:` or `#`, scanning `<script>` bodies too. `test_every_library_is_inlined_
exactly_once_and_no_marker_survives` (`tests/test_render.py:134`) asserts `len(inlined) ==
4` over `static/*.js` and that each file's first 200 characters appear exactly once in
`graph.html`. And the documented `shasum -a 256 *.js *.mjs *.woff2 > SHA256SUMS`
truncates: a companion file with a new extension silently loses its checksum. One
repeated hazard is **not** a hazard here — `test_every_vendored_file_is_the_one_that_was_
checksummed` explicitly exempts `*LICENSE.txt` by design, "a licence is read, not
executed".

## What the recorded CodeMirror refusal said, and what this audit does with it

712dea2, in full on this point:

> 291 tests green. CodeMirror and vim keys were vendored, weighed and cut, which is what
> the spec's own cut line already said: 690 KB of editor to change a handful of fields and
> one markdown body is not a trade to make before somebody is measurably slowed down by a
> textarea. Revisit then, not before.

d6997e3:

> Not CodeMirror. It is 700 KB against a repository whose premise is that nothing is
> fetched and there is no build step, it ships as ES modules that would need bundling, and
> it would not have brought image upload: paste and drop are DOM events a textarea already
> receives. The recorded decision to cut it stands, and this is the evidence it asked for
> rather than a reversal.

`static/VENDOR.md`, "What is deliberately not here":

> **No editor library.** CodeMirror 5 was vendored and then removed: the spec's cut line
> already said CodeMirror saves nothing and costs two days, and vim keys are a preference,
> not a requirement. A plain `<textarea>` with a preview needs no dependency at all, and
> the 690 KB — a third of it the vim keymap — buys nothing for editing a handful of fields
> and one markdown body. Revisit when somebody is actually slowed down by the textarea,
> not before.

Three recorded reasons. Under measurement in 2026 they do not all stand.

**690–700 KB: stands, and is exact.** Re-measured from scratch by two parties: 692,765 B,
vim 33.5% of it.

**"It ships as ES modules that would need bundling": false for two of the three
candidates it is aimed at, and it decided nothing.** CodeMirror 5 is UMD and runs in a
`<script>` block untouched; Ace is a classic self-registering script and does the same. It
is true of CodeMirror 6, and CodeMirror 6 is where the linker objection now lives. So one
clause of the record is genuinely overturned — for Ace, comprehensively: zero `import`,
zero `export`, runs in a bare node `vm`, needs no `_yjs()` analogue. But the plank the
refusal turned on is the size, and the size is untouched: Ace delivering the same seven
asks is 669,582 B = **96.7%** of the number this repository refused in writing twice, and
594,306 B without the markdown mode = 85.8%. Add `ext-searchbox.js` to give Cmd-F back and
it is 683,746 B, within 1.3%.

**"It would not have brought image upload": stands.** Paste and drop are DOM events, and
`attachUploads` (`render.py:7513`) is a handler on the element, not an editor feature —
but a library that installs its own `preventDefault`ing paste and drop handlers swallows
both, so it has to be re-attached rather than assumed.

**This audit honours the refusal.** The revisit condition the record names is "before
somebody is measurably slowed down by a textarea" — and nobody has produced that
measurement. What we have instead is a feature request, which is a legitimate reason for a
human to override a recorded rule, and is not the same thing as evidence that the rule was
wrong. So: nothing is vendored. Six of the seven asks are built on the element that is
already in the page, for an estimated ~18 KB. Ace is recorded as **admissible** — measured
under this CSP, with a forced-failure control — and **priced**, and buying it is a
separate decision jcanton makes with the price in front of him. If the answer is yes, the
commit that vendors it has to say in those words that it is an override of a recorded
rule, not a correction of one.

## The decision

Extend the `<textarea name=body>` into a full-page, three-view, gutter-carrying,
soft-tabbed writing surface. Zero vendored bytes. Add `Y.UndoManager` from bytes already
on the page. Put one adapter boundary between the co-editing code and the surface, so that
a second surface stays possible without being promised. Then stop and ask, with the price
written down, before anything is vendored for ask 6.

| ask | delivered by |
|---|---|
| 1. three views | a tri-state class on `article.record`, three mutually exclusive buttons in the existing `bodybar` (`render.py:8261`) on Ctrl+Alt+E/B/V — Ctrl+Option on Mac, never Cmd, because the page already claims Cmd+S and Cmd+B/I/E/2/8/. — plus `?edit`/`?both`/`?view` off the existing hash router. The preview stays the `/api/preview` round trip, debounced ~300 ms with an `AbortController`, an unchanged-text skip and a preserved `#body-preview.scrollTop`. |
| 2. toolbar | four `FORMATS` entries: check list `- [ ] ` and strikethrough `~~` drop into the existing prefix/wrap shapes; a table template and a horizontal rule need a fourth `insert:` branch in `applyMark`, ~4 lines. Not link and not image, on the corpus counts the toolbar was sized from. Both new marks need the server one-worders in the same commit, or the buttons emit syntax the committed renderer does not honour. |
| 3. full page | `article.record` becomes a viewport-filling grid with two independently scrolling panes, and `#grip`/`--measure` gets an explicit rule so the drag handle does not park at the left edge. |
| 4. line numbers | one span per logical line in the mirror that already exists for the seat bands, numbers positioned from `offsetTop`, rAF-coalesced, redrawn on `document.fonts.ready` and resize, with a line-count ceiling above which the gutter turns itself off out loud. `drawSeats` is then repointed at the same mirror, which deletes its per-caret `measure()` loop. |
| 5. tabs to spaces | a Tab/Shift-Tab branch in the `keydown` handler at `render.py:7476`, through `replaceRange` → `execCommand('insertText')` so native undo survives, with list and blockquote nesting reusing `LIST_ITEM`, and an Escape-armed one-shot Tab pass-through announced rather than silently implemented. Tab width is a **typing** setting, never a "convert this document" command. |
| 6. vim | **not delivered.** It is the only ask that needs a library. Priced at 594,306 B raw / ~165 KB gz (Ace core + vim, markdown mode dropped), plus a second hand-written Yjs binding, and deferred behind the first open question below. |
| 7. autosave | read as **draft** autosave: a settable throttle with a ceiling on the per-input write at `render.py:8581`, a visible "draft saved 12s ago" beside `#unsaved`, and surfacing that the room already commits at `QUIET_SECONDS = 20`. Not a POST on a timer — that turns one shaping session into fifty commits and destroys one-Save-one-commit. |
| both editors | `openproj:editor:1`, one JSON object through `remembered.map` holding `{mode, indent, autosave}`, versioned in the key with the old key explicitly forgotten. Today that preference is plain box vs full surface — two modes of one textarea. Whether that satisfies the request is the first open question. |

And one thing nobody asked for, which is free and fixes a live defect: **`Y.UndoManager`
with `trackedOrigins {'typed'}`**. `UndoManager` is already in the export clause of
`static/yjs.bundle.mjs`, so it costs zero new vendored bytes.

## What the skeptics broke

Thirteen refutations ran against the decision's load-bearing claims. Three landed hard
enough to change the design, and the design before and after is worth stating plainly.

**Before:** Ace 1.44.0 as an opt-in second editor, 550 KB verbatim, with ONE surface
adapter and ONE Yjs binding, because `typed()` is surface-agnostic and line numbers force a
library anyway. That was scored 8 and it won.

**After:** the textarea, extended; Ace admissible, priced, deferred, and separately
decided.

### 1. "One splice recovery serves both editors" — refuted five times, on the condition it named

The claim was that `typed()` (`render.py:8719`) reads only `BODY.value` and
`text.toString()`, so `session.getValue()` feeds it unchanged. The algorithm really is
surface-agnostic. Everything drawn from that is false, and the reason is at the root: **a
textarea's programmatic `.value =` fires zero `input` events** — measured — which is
exactly why the current design needs no re-entrancy guard and does not have one. Ace's
`session.on('change')` fires identically for programmatic and user edits, its deltas carry
no origin field, and `editor.curOp.command.name` is `(anon)` for a user keystroke and for
`session.replace` alike.

* `session.setValue()` is remove-all-then-insert-all: two change events with an **empty
  document between them**. Measured: `setValue` of a document onto itself yields
  `deleted=1532, inserted=1532`. `typed()`'s prefix/suffix walk cannot recover a splice
  from `""` versus a whole document.
* `session.replace(Range, text)` — the API the evidence recommended as "strictly better,
  splices in place" — is **also** remove-then-insert, two change events, and a handler
  reading `getValue()` between them observes a document state that never existed on either
  side and splices it into the `Y.Text` as a local edit.
* The credit invariant is destroyed, measured against this repository's own `Room`: one
  remote 4-character keystroke reflected via `setValue` made a **passive** tab push the
  whole document up the socket — 1,532 characters on a 1,532-character body, 97,892 on a
  97,890-character body — and `Room._count` credits inserts to the socket they arrived on.
  `Room.credits`' "authored by whoever typed the most" becomes "authored by whoever
  reflected last", or falls to alphabetical order. Wire amplification measured at
  6,711–6,819x: a 35-byte update becomes 235–246 KB, three frames fill
  `MAX_OUTBOX_BYTES`, and the eviction path fires as a forced `reload`.
* The obvious `applying` guard suppresses the credit bug, and then `setValue` calls
  `selection.moveTo(0,0)` and `getUndoManager().reset()`: caret `{row:2,col:5}` →
  `{0,0}` and `canUndo` true → false on **every** remote keystroke. That is `reflect()`'s
  own stated purpose defeated and d6997e3's data loss reopened.
* And the one-shot shape is wrong the other way too. Multi-cursor plus one keystroke
  deleted 14,789 characters and reinserted 13,345 on a 14,810-character document; vim
  `:%s/cycle/bet/g` and `editor.replaceAll` did the same. Binding per change instead gives
  722 events at ≤5 characters each, but `typed()` materialises two full code-point arrays
  per call — 1.90 ms on a 250 KB body — so one Replace All is ~1.4 s of blocked main
  thread.

A correct Ace binding consumes Ace's own deltas, converts `{row,column}` through
`positionToIndex`, applies them directly to the `Y.Text` inside `doc.transact`, batches per
Ace operation, and applies remote `Y.Text` deltas back as Ace deltas — never `setValue`,
never `replace` — behind an explicit `applying` flag that has no counterpart today and no
test. That is a second, editor-specific, hand-written Yjs binding with no upstream. The
decision's central engineering argument, the one the judge weighted hardest, is gone.

### 2. "It slots in behind a preference" — refuted, measured three ways

`ace.edit(BODY)` **removes** the textarea from the DOM and from the form:
`document.contains(ta)` false, `form.elements.namedItem('body') !== ta`, the container is
now a `<pre>`. The sibling-div arrangement keeps it in the form but stale: typing 17
characters through Ace left `BODY.value === ""` and fired **zero** `input` events, measured
with a capture-phase listener on `document`. Each consequence is pinned:

* `render.py:8581`'s per-input draft write never runs again — and `coedit.py`'s own module
  note calls that draft "the floor under a lost room", the thing under the twenty-second
  quiet window.
* `welcomed()`'s `mine = BODY.value !== ORIGINAL_BODY` is then always false, which is
  verbatim the bug the `bound` gate was written to fix, arriving by a new cause the gate
  does nothing about.
* `save()`'s `const body = BODY.value === ORIGINAL_BODY ? null : BODY.value` sends
  `body: null`, so the recovery path for `file://`, a dropped upgrade, the Cloud Run 300 s
  teardown and the `reload` frame silently sends nothing — and that frame's message
  promises "Nothing in this tab is lost: Save writes the whole document, the way it did
  before rooms existed."
* `dirty()` reads the same value and says "Nothing changed yet" over unsaved work.
* The four tests in `tests/test_seats.py` and the page-mode `drive.js` tests select
  `textarea[name=body]` and dispatch `new Event('input')`. They stay **green** against a
  surface nothing reads.

Separately: `document.execCommand('insertText')` **silently no-ops under vim NORMAL mode**
— A/B'd in one page, it returns `true`, throws nothing, and leaves the document unchanged.
So every toolbar button and the image-paste placeholder-then-replace do nothing at all
when vim is on. Asks 2 and 6 destroy each other on the `replaceRange` path.

There is no cheap mounting. Either every read of `BODY.value` in `_DETAIL` goes through an
adapter, or the textarea is kept in the form and written from the binding on every change
with the draft write called explicitly.

### 3. "Only asks 4 and 6 force a library" — refuted for ask 4, three times over

Three independent Chrome measurements now corroborate the one the judge docked for being
unreplicated, and more rigorously than the original: 2,886 swept measurements with
per-line row counts, and 40 configurations including a proportional font. Ask 4 comes off
the library's ledger, and with it two-thirds of what Ace was being bought for. It also
upgrades ask 1 for free: the mirror is the line-to-pixel API the HackMD probe said a
textarea lacks, so scroll sync becomes exact rather than coarse.

### Also landed, and folded in

**The gating test was aimed at the wrong failure.** The narrow claim — Ace's
`positionToIndex` returns UTF-16 code units — survives, and one skeptic tried hard to
break it and could not; Ace's surrogate clamping is emergent, from `moveCursorBy`'s
screen-coordinate round trip, not from any guard. But two strings both counted in code
units are still two spaces if the strings differ, and Ace makes them differ by itself:
`Document.$detectNewLine` autodetects one line ending from the first it sees and
`getValue()` rejoins every line with it. Measured: `"a\r\nb\nc"` → all-LF; `"a\r\nb\nc\r\n"`
→ all-CRLF; `"a\nb\rc\nd"` → same length, different bytes, invisible to any length or index
check. A `<textarea>` normalises CRLF→LF unconditionally in both directions. The two
editors this decision keeps both normalise, in **opposite** directions. It is reachable:
`store.py` decodes the blob with `.decode("utf-8")` and no newline translation, there is no
`.gitattributes text=auto`, and measured on a 15,897-byte body whose first ending is CRLF
and whose other 400 are LF, merely **opening** Ace produced cut 15,852 / put 16,252 and a
16,288-byte Yjs update before anybody typed. On a 200-line mixed-ending document
`positionToIndex` returned 490 where the real file offset was 395 — one unit per preceding
line — and `Room.sits` relays uninterpreted, so nothing on the server can catch it.
`indexToPosition(1)` on a leading emoji returns `{row:0,column:1}`, unclipped, between the
surrogate halves; `Document`, `Anchor` and `applyDelta` do no clipping, only
`Selection.moveCursorTo` does — so failure mode 2 is reintroduced by the route named as its
safety. And decisively, the proposed gate is a case this repository already wrote down as
proving nothing: `tests/test_coedit.py:1379-1444`'s own comments name "an emoji typed in
from the picker, which lands whole between two characters that are not halves of anything"
as a **control** that passed with the defect in place. A skeptic ran the proposed gate end
to end against `static/yjs.bundle.mjs` on a room seeded with `"Ann says\rand then\nlast
line\n"`: the emoji arrived, the indices agreed, the test passed, and `copies_converged`
was false.

**Collaborative undo is worse than the decision knew.** Local `insert('LOCAL ')`, then a
remote peer's edit applied the correct in-place way as
`session.replace(Range(0,0,0,0),'REMOTE ')` giving `"REMOTE LOCAL mine"`; one `undo()`
gives `"mine"` — undo removed the remote edit too, and the room propagates that deletion.
Detaching the `UndoManager` around the remote edit is worse: `" LOCAL mine"`, a corrupted
document with a stray leading space, because Ace's stack holds absolute ranges the remote
edit invalidated. d6997e3's "ctrl-Z lost your ten minutes" becomes "ctrl-Z deleted your
colleague's paragraph and committed it".

**"Behind a preference" contains no bytes for anybody.** `editable = base_commit is not
None` (`render.py:13163`) and the served route passes `base_commit` for everyone; only
`yjs` and `coedit` carry the extra `may_write` gate (`render.py:13185-13186`). Measured: a
signed-out reader's detail page is 209,872 B and already contains `<textarea name="body">`,
`id="marks"` and two `attachEditing(` calls. An Ace block where the current editor lives
ships to every public reader: 209,872 → 879,454 B, 4.19x. And the bytes are inlined into
the HTML, the CSP has no `'unsafe-eval'` and no `'self'` in `script-src` so there is no
lazy path, and `remembered` is `localStorage`, which the server cannot see. A preference
that decides which bytes render has to be a cookie. If the cookie is refused, drop the
second editor rather than charge every reader and every writer for it.

**The headline number was wrong by 21.7%.** The decision's sentence bought "line numbers,
markdown highlighting and vim … 550 KB". 550,305 B is core+markdown and excludes vim. The
honest figure for the set named is 669,582 B. The probe's own evidence line printed both
correctly; the decision attached the larger feature list to the smaller number.

### Two defects that are in this repository today, not in anybody's proposal

**The network assertions have never inspected an editing surface.**
`tests/test_render.py:22` `PAGES` is the eight static-export files. `render_static` calls
`render_detail(index)` with no `base_commit`, and `render_detail`'s signature
(`render.py:13135-13136`) is `base_commit: str | None = None, may_write: bool = False`, so
the exported `detail.html` carries no editor at all — 0 `<textarea>`, 0 `const YJS`, 0
`WebSocket`. Therefore `test_no_page_reaches_the_network` **and**
`test_no_page_asks_the_network_for_a_font` have never looked at the textarea, the toolbar,
the Yjs bundle or `_COEDIT`. That is a pre-existing hole, independent of which editor
wins, and it is what concealed the `url()` finding: `mode-markdown.js` would have shipped
two failing `url(` tokens into every editable page under a green suite, because the rule is
unenforced exactly where the newest bytes would land. It also concealed the reader-page
gate above. Assertions over `render_detail(base_commit=…, may_write=True)` belong in the
tree **before** any vendored byte, not after.

**Two things are measurably wrong in shipped code.** `render.py:8838` sets
`ghost.style.width = BODY.clientWidth + 'px'` — an integer, where the content box is
fractional — so the seat bands land whole line heights wrong at 1.7–10.4% of pane widths,
against `VENDOR.md`'s own "a caret one line off is worse than no caret". And in a live
room, `reflect()` (`render.py:8756`) does `BODY.value = want` on every remote update at
`render.py:8764`, while `render.py:7357` records that assigning `.value` wipes the
browser's native undo stack, and
`test_no_script_ever_assigns_a_textarea_its_value` scopes only `replaceRange`, `FORMATS`
and `attachUploads` — it deliberately does not look at `_COEDIT`. So every remote keystroke
already destroys your undo history, unguarded and unnamed. Both are fixable with zero
vendored bytes, and the plan fixes them early.

**Both are fixed, and the second one turned out to be worse than this paragraph knew.** The
write stays — a remote change cannot be merged into a native undo stack, so `.value` under
`apply` is the right call — and S4 gives the document a history of its own instead:
`Y.UndoManager` tracking the `'typed'` origin alone, with the two buttons the screenshot
puts leftmost on the bar. What was not known when this was written is that the wiped stack
does not come up *empty*. Measured in Chrome: after `.value` is assigned,
`queryCommandEnabled('undo')` goes on answering `true` while `execCommand('undo')` returns
`true` and moves nothing at all. An empty stack a page can see and say so about; a lying one
it cannot, which is why the room takes the question off the box entirely rather than
falling back to it.

## What must not be lost

In the terms the current code uses. Every one of these is either load-bearing or the
scar of a shipped defect.

* **A room, not a socket.** `COEDIT.live()` / `COEDIT.save(fields)` are the entire public
  surface (`render.py:9084`, called from `render.py:8521`). Every refusal path returns
  `asleep = {live: () => false, save: () => {}}` (`render.py:8654`), so a page with no Yjs
  and no WebSocket takes the pre-room path with no branching anywhere else.
* **One Save is one commit**, authored by whoever typed the most, everyone else as
  `Co-authored-by:` (`coedit.py:280` `Room.credits`, `:168` `_count`, `web.py:2286`
  `_commit_room`). Characters are credited to the socket they arrived on, never to a client
  id off the payload. It depends on the browser sending fine-grained per-keystroke deltas.
* **`typed()` / `units()` / `reflect()`** (`render.py:8719`, `:8706`, `:8756`). Three index
  spaces exist — code points, UTF-16 code units, UTF-8 bytes — and mixing them raises
  nothing; `units()` is the one conversion at the one boundary, `coedit.byte_offset`
  (`coedit.py:78`) is its server twin, and `test_the_browser_splices_on_a_whole_character`
  holds every index handed to the document to coming from `units(`.
* **`welcomed()`'s three-way decision and the `bound` gate** (`render.py:8922`, `:8786`).
  `mine = BODY.value !== ORIGINAL_BODY`, `theirs = text.toString() !== ORIGINAL_BODY`; both
  → refuse to guess. The welcome's `applyUpdate` fires `text.observe` **synchronously**, so
  the document does not own the editing surface until the one decision that can lose work
  has been made. No binding may attach on construction.
* **The seat bands** (`render.py:8850` `drawSeats`, `:8831` `measure`, `:8817` `hueOf`,
  `:8880` `sit`; CSS `:9211-9220`; `tests/test_seats.py`). A sibling layer over
  `.bodywrap`, positioned through the ghost mirror, one hue per login derived from the
  name, redrawn on input, scroll, keyup/click, resize and `openproj:editing`.
* **The draft and its `base_commit`** (`render.py:8379` key, `:8581` write, `:8584-8606`
  restore). `openproj:draft:2:${id}` holds `{base, text}`; a restore moves `BASE.value`
  **back** to the draft's base and says the ground moved. A bare-text draft paired with
  today's base is how somebody's paragraph was reverted with no 409 and no report. Cancel
  drops the draft and deliberately does not move the base forward (`render.py:8477`).
* **`ORIGINAL_BODY`** is `let` (`render.py:8404`) and the room reassigns it on a `saved`
  frame (`render.py:9017`), because a room can commit this body without this tab pressing
  anything. `dirty()` (`render.py:8421`) counts what a save would send.
* **The conflict box** (`render.py:8284`, 409 branch `:8543`). Every refusal is written
  with `textContent` into an `aria-live` region under the box and never into the editing
  surface: text pasted into the editing surface is text somebody saves back.
* **`replaceRange` and the undo stack** (`render.py:7364`). `execCommand('insertText')` is
  deprecated and is still the only API that edits a textarea as though a person had typed.
  Every new write path inherits this rule — a toolbar, an autosave, a tabs-to-spaces pass,
  a vim command.
* **Image paste and drop** (`render.py:7513`, server `web.py:1999`): placeholder first,
  then POST raw bytes to `/api/asset`, then find the token and replace it through
  `replaceRange`. Bracketed by `openproj:writing` / `openproj:wrote`, which the shell
  counts in pairs — two writings against one wrote silences the banner for the life of the
  page.
* **The preview is the server's markdown** through `/api/preview` (`render.py:8482`,
  `web.py:1602`). A second markdown implementation in JavaScript would eventually disagree
  with the one whose output gets committed. It also governs PR-reference linking, asset src
  rewriting and HTML suppression, none of which a JS renderer reproduces. It is also **read-only
  by decision rather than by omission**: ticking a checkbox in the rendered pane would write to the
  source from a copy of it, which fights compare-and-swap. `- [ ]` lists render as real checkboxes,
  so a reader can see them and cannot press them.
* **Degradation is the ordinary case** (`render.py:8636-8654`): `file://`, a proxy that
  drops the upgrade, Cloud Run tearing every socket down at 300 s, and a reader the server
  would refuse. Every path ends at a value, a `base_commit`, Save and a 409. Nothing here
  is allowed to be a prerequisite for editing.

## What jcanton answered, 2026-08-20

The questions below were put to him with the prices attached. Four were answered as a
choice, and one sentence answered three more: *"implement both: improvements to our editor
as well as ace."* That is the strict reading of "keep both editors", and it is an override
of the recorded refusal rather than a re-derivation of it — which is what this section is
for, because the commit has to say so.

**Both surfaces are in scope.** The textarea, extended, is one editor; Ace is the other.
Ask 6 is therefore in scope and the plan runs to its last stage. The stop-and-ask gate
before vendoring is answered in advance: proceed.

**Ace ships minified.** `src-min-noconflict`. He answered "unminified" first, on the plain
reading of "readable by a person", and reversed it the same day once this file had measured
what that costs: 1,307,387 B against 670,198 B, which is 1.89x the 690 KB this repository
refused in writing twice, and 24 more failures of the font-url assertion because of how the
unminified build escapes its own `data:` URIs. So the precedent stands as `cytoscape.min.js`
set it, and it is a better precedent than it looks: `src-min-noconflict` is inside the npm
tarball rather than generated by a CDN, so a SHA256 over those bytes identifies something
upstream actually published. Dropping the markdown mode as the plan does, ask 6 costs
**594,306 B** and takes a writer's page from 318,526 B to ~913,000 B.

**The preference is a URL parameter plus a remembered setting, not a cookie.** `?editor=ace`
makes the server inline the editor; `openproj:editor:1` makes it sticky once opted in. This
is the answer that also disposes of the reader problem: `editable` is gated on `base_commit`
alone, so a signed-out reader already receives the textarea and `attachEditing`, and an Ace
block at that gate would have shipped 594–670 KB — or 1.3 MB unminified — to every public
reader. Behind a parameter nobody types, a reader pays nothing. It is also the shape that
answers "let me play with both tomorrow": two tabs, same document, one editor each.

**Ask 7 is draft autosave.** A settable throttle on the write that already fires at
`render.py:8581`, plus a visible receipt, plus surfacing the room's `QUIET_SECONDS = 20`.
Nothing reaches git on a timer. The picker needs a ceiling, because a user-settable interval
otherwise lets somebody set their own floor coarser than the window it backstops.

**The two shipped defects are fixed early and regardless** — the seat bands measuring
through an integer `clientWidth`, and `reflect()` wiping the native undo stack on every
remote keystroke in a live room. Neither costs a vendored byte and both are in this
repository today. Both are done; the undo one is S4 and its record is in the plan.

## What is still open

1. **The migrated HackMD corpus is not in this repository.** The seed corpus is synthetic
   and returns zero hits for `[TOC]`, `:::`, `[name=]`, `{%youtube%}`, `[^fn]`, `- [ ]`,
   `$math$` and ```` ```mermaid ````, so it cannot say which renderer extensions and which
   toolbar buttons are worth building. The existing seven-button toolbar was sized off
   exactly that kind of count — 485 inline code spans, 161 bullets, 124 headings, 83 bold,
   8 links — and without the corpus, every item below stage 2 is a guess. Point at it, or
   the toolbar gets built on the seed counts and the commit says so.
2. **Line numbers now come free on the textarea**, which nobody expected: three independent
   Chrome measurements say a mirror gutter is exact rather than drifting, and the thing that
   made it look impossible turned out to be an integer-rounding bug that is also in the
   shipped seat bands. Ace still brings its own gutter, so this is no longer a question that
   blocks anything — but it means ask 4 is delivered twice, and the textarea's copy lands
   first.
## What was built, 2026-08-20

Ace 1.44.0 is vendored, behind `?editor=ace`, with the markdown mode dropped, and vim is in
the status bar. The audit above stands as the search; three of its findings turned out
differently once the thing was built, and they are recorded here rather than by editing the
paragraphs that made them.

**The worker gate passed on the shipped assembly, with the control.** `ace.js` +
`keybinding-vim.js`, no mode set: 0 Workers, 0 CSP violations, 0 injected scripts,
`session.$worker === null`, vim attached. The same page plus `mode-markdown.js` with
`ace/mode/javascript` set: one `blob:` Worker, `worker-src <- blob`, **and no `error` event at
all** — the recorded "empty `window.error`" was optimistic; on this Chrome the failure is
completely silent, which strengthens rather than weakens the reason for the control.

**Who pays turned out to have three answers, not two.** The section above says a reader's
page is 209,872 B and already carries the box and the toolbar, and that gating Ace on
`editable` would take it to 879,454 B. `?editor=ace` alone does not fix that: a signed-out
reader can type it. `_ace_wanted` therefore asks `may_write` as well — the same second gate
`yjs` and `coedit` already carry — so the parameter buys a reader exactly nothing. Measured
on `tests/fixtures/corpus`: a reader's page is 311,497 B with the parameter and 311,497 B
without it.

**The `url()` finding cost nothing, because the file that carried it is not here.** `ace.js`
has 24 `url(` tokens and every one is a `data:` URI; `keybinding-vim.js` has none. The two
that fail the assertion are both in `mode-markdown.js`. Nothing had to be loosened.

**The binding is the delta path, and `typed()` was not touched.** The room asks
`SURFACE.onSplice` where a surface has it and falls back to `SURFACE.onInput(typed)` where it
does not — so the path that has shipped since rooms existed is byte-for-byte unchanged and
the second surface brings its own better channel rather than borrowing a worse one. Ace's
deltas are converted at the moment they arrive, because everything before a delta's `start`
is untouched by it and everything after has moved; the runs are batched per Ace operation and
applied in one `doc.transact`. Measured: `:%s/cycle/bet/g` over a 48-occurrence document is
**one** update frame, converges with a real `Room`, and is credited to the tab that pressed
the key.

**The line-ending hazard was worse than the audit priced it, and the fix is server-side.**
`setNewLineMode('unix')` is necessary and is not sufficient: `reflect()` splicing a lone `\r`
into Ace produces a LINE BREAK, so the document grows a row and the two copies never converge.
The one boundary is `coedit.one_newline`, applied where text enters the room — the seed and
`absorb` — so the room holds what every surface can hold. The cost, stated: saving a document
whose file had CRLF writes LF back, which was already true the moment anybody typed in it.

**The Escape arbitration turned out not to need a line of code.** S2.8 promised
`if (event.defaultPrevented) return;` as the seam a keymap would claim a key through. Ace's
`stopEvent` already does `stopPropagation` as well as `preventDefault`, so a key its command
table handled never reaches the page's own listener: measured in Chrome, Tab does not arrive
and Escape and Cmd+S do. The guard was written, measured, and removed, and the comment where
it stood says so — a guard whose condition is never true is one no mutation can catch.

**The three-view chord is Ctrl+Shift+1/2/3, not the Ctrl+Alt+E/B/V the decision table above names.**
Ctrl+Alt *is* AltGr — Chrome delivers the AltGr key as `ctrlKey` and `altKey` together — and on the
Swiss-German layout half this team types on, AltGr+E is the euro sign, which the chord swallowed.
Digits and not letters, because Ctrl+Shift+B is Chrome's bookmarks bar and Ctrl+Shift+V is
paste-as-plain-text; matched on `event.code`, because shift-1 is `!` on one layout and `+` on
another. Never Cmd still holds, for the reason it was written. The argument in full is at
`render.py:12870`.

**What is not built, and is the first thing to add:** the seat bands do not draw on the Ace
path. `coordsAt` answers over Ace's screen rows and `drawSeats` says out loud that they are
not drawn rather than clearing the layer in silence, but the band's origin is the box's border
box and the mirror's is its padding box, and nothing has measured that pairing in a browser.
`static/VENDOR.md`'s own "a caret one line off is worse than no caret" is why it is absent
rather than guessed. The presence line still names who else is in the document, and a tab on a
textarea still draws the Ace tab's band correctly, because `sit()` sends the same index.

## Three changes jcanton asked for after using it, 2026-08-20

Recorded here rather than by editing the paragraphs above that argued the other way,
which is how the rest of this file is kept.

**1. Ace is the default.** *"make ace the default, I think it's worth it."* The parameter
inverts: `?editor=plain` opts out and an address that says nothing gets the second editor.
The machinery is unchanged — the server still has to know before it renders, because
`remembered` is this browser's own store — and only the default arm moved. The reload the
sticky preference costs moved with it, onto the people who want the plain box, which is the
better side to pay it on: the smaller page arriving for the person who asked for a smaller
page, rather than 594 KB arriving twice for everybody else.

**This is a human override on top of a human override, and `static/VENDOR.md` says so.** The
revisit condition that file records — "when somebody is actually slowed down by a textarea" —
is still unmet by anybody. Measured on `tests/fixtures/corpus`, raw / gz -9:

| page | before | after |
|---|---|---|
| reader, no parameter | 352,779 / 145,908 | 366,151 / 150,333 |
| reader, either parameter | 352,779 / 145,908 | 366,151 / 150,333 |
| writer, no parameter | 478,742 / 186,557 | **1,110,377 / 362,045** |
| writer, `?editor=plain` | 478,742 / 186,557 | 492,311 / 191,035 |

A reader still pays zero for the library and zero for the parameter, and that is the half the
inversion could most easily have destroyed — the default arm is now the one that ships it, so
`_ace_wanted`'s `may_write` gate is asserted three ways round rather than assumed.

**2. The theme toggle and the sign-in control are in the editor's own header row.** *"the
light/dark mode toggle and sign in button seem to have disappeared from the edit view."* The
cause was ours and it was right: `body > nav, body > a.skip` are made `inert` while the
full-page surface is up, because eight focusable elements were geometrically covered by an
opaque fixed article and still in the tab order. The nav stays inert; the two controls MOVE,
into the `.editbar` beside the view switcher, and back to the nav when the surface closes. The
same nodes, not copies — `#theme` and `#who` are ids, and the shell's own scripts fill exactly
one of each — so the accessible name, the listeners and the identity survive by construction.

**3. Which editor is a switch beside the three view segments.** Two states drawn as a switch
rather than as a fourth segment, because the three views are one control with three states and
this is a different question. `role="switch"` with `aria-checked` rendered by the server from
the same `_ace_wanted` that decided the bytes; the visible words are the accessible name; a
real `<button>`, so Enter and Space work without a line of code; and the focus ring is asked of
Chrome twice — once for whether anything is painted and once for whether an ancestor's
`overflow` crops it, which are different failures and were measured to fail differently.

**It is honest that it reloads.** It decides which bytes the server rendered, so flipping it is
a navigation. The resting `title` says what pressing it will do and that it reloads; the press
says the same thing through `announce`, into the visible `#state` region; and the knob stops
HALFWAY rather than completing its travel, because halfway is what is true — this page will
never be the page with the other editor in it, and a switch that arrives and is then wiped out
by a load reads as one that worked and then glitched.

One finding worth keeping. The label on the surface object was first called `editor`, and the
Ace surface already publishes `editor` — the Ace instance. A second key of that name later in
the same object literal is an error nowhere: it silently wins, and every use of the real one
became the string `'ace'`. It is `editorName` now, and it is a label that must never be
branched on; a behavioural difference between the surfaces goes in `provides`.

## The app's look is the default, and the corner is the toolbar's, 2026-08-20

This work forked before `main`'s `4076b1c`, which is the commit that made the app's chrome the
DEFAULT for every `button` and `select` rather than a rule naming ids. Until the merge, this
branch's Edit button was a bare `<button id="toggle">` inside `.editbar` — which styles layout
and nothing else — so Chrome drew it `2px outset`, the operating system's own button, beside a
correctly-styled Save. jcanton saw it: *"I thought we had managed to impose the style of
buttons and dropdowns to be coherent across the entire app? why did that work? this is rather
important for preventing future drifts."*

It did not work, and the reason is the shape of the rule rather than the rule. A rule that
names ids reaches the controls somebody thought of and none of the ones they did not, and the
failure is silent — a control looks like the operating system and nobody notices until two of
them are side by side. The default fixes it on contact, and **nothing this branch added opts
out of it**: the sixteen toolbar buttons, the three view segments, the status strip and the
editor switch each declare only what is theirs.

**The corner is 3px, and that is jcanton's number.** He looked at the toolbar, which had been
drawing its own 3px against the app's 2px, and preferred it — so the global radius moved and
`button.mark`'s private copy was deleted rather than kept. Moving one number found the four
rules that had quietly kept a copy of it (`#clear-filters`, `td.clamp .more`, `.confirm
button`, `#start`), each of which would otherwise have been the only control left on the old
corner. That is the whole argument for a default, demonstrated by moving it once.

The guard is `test_every_control_on_every_page_is_drawn_the_same` in `tests/test_cascade.py`,
which measures every `button` and `select` in Chrome rather than reading the stylesheet — a
test that reads a stylesheet can only say a rule exists, and what matters is which controls it
reaches. Two things had to change for it to see this work at all. The editing surface is
`.field`s inside `article.record.editing`, so on a served record nobody is editing it has no
client rects and the sweep skipped all twenty controls; the create page is the same markup with
the mode already on, and is now the seventh page in the parametrize. And `bare()` — the list of
controls deliberately drawn with nothing — was a list of NAMES, which is the shape the rule
exists to kill; it asks the drawing now (no border and no ground), so the browser's own chrome
still lands in the set that has to match and `button#theme` stops being excused wholesale.

## A session ends the same way through every door, 2026-08-20

Written down because it came back through a new door after being fixed, which is this
repository's characteristic failure. Press a view, then end the editing session: the surface
has to come down with it, or the reader is left inside a fixed, opaque, window-filling article
whose switcher — the documented way back — is drawn only under `.record.editing` and goes at
the same instant. That was found on Cancel and fixed by writing `showView(null)` at the call
site. Then the same line was written at the issue page's toggle, and again at the note page's.

The fourth door had no copy. **A Save made in a room does not reload** — the document is
already what everybody in the room has — so `_COEDIT`'s `saved` branch ends the session with a
bare `showEditing(false)`. Measured in Chrome from the split view: `full view-both` on the
article, `fullpage` on the body, the nav still `inert`, no switcher, and the theme toggle and
sign-in control still lodged in `.editbar` where the session had put them.

It is one listener on `openproj:session` now — the event that already exists to mean "a session
began or ended" — and the three call-site copies are deleted. An invariant written three times
was an invariant guarded twice.

## The trap that is still written down

`tests/js/drive.js` is a DOM shim, not a browser. `AGENTS.md` records that it has misled
three rounds of this work, twice on this exact feature: it handed the host realm's `String`
into its vm, so every Yjs insert became an empty embed; and it copied parsed text into
`textContent` and never into `.value`, so `ORIGINAL_BODY` was always empty in page mode,
which flips the one branch in the editor that can lose unsaved work. An editor is layout,
selection and key handling. Ask Chrome (`tests/browser.py`), not the shim. Anything about
convergence is driven against a real `Room`.

**And a second one, found by the five-lens audit and structural rather than accidental: a
source-grep guard cannot follow a write through the surface boundary.**
`test_no_script_ever_assigns_a_textarea_its_value` scans the shared editing block MINUS the
textarea surface, because the surface is the one place allowed to assign `.value` — that is
what makes the subtraction the right window rather than a list of function names. But
`applyMark`, which is the largest write path on the page and reaches sixteen buttons, does not
assign anything: it calls `surface.splice`, whose only implementation is inside the region the
guard subtracts. Measured: replacing that implementation's non-`applying` branch with a
`.value` splice left the guard green **and** left all twenty of `_MARKING`'s text assertions
green, because the box ends up holding exactly the same characters either way. What it does
not hold is a stack. The only question that can tell the two apart is `execCommand('undo')`,
pressed in Chrome, and `_MARKING` presses it on both shapes that write — `mark.insert` and the
wrap tail. Seed two words, not one, or "one step back" and "everything gone" look the same.

🤖 Written by an agent on behalf of @jcanton
