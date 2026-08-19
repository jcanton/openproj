# The editor jcanton asked for — implementation plan

**Goal:** six of the seven asks on the `<textarea name=body>` that is already in the page,
for an estimated ~18,000 B raw / ~5,000 B gz and zero vendored bytes; two defects in
shipped code fixed on the way; one adapter boundary so a second surface stays possible; and
then a stop, with the price written down, before ask 6 (vim) buys a library.

**The audit is `docs/EDITOR.md`.** Where this plan and that file disagree, that file wins.
The measured numbers, the rejected candidates and the eight questions live there and are
not repeated here.

**Stage 7 is the point.** Everything above it is shippable on its own and vendors nothing.
Stages 8 and 9 happen only if jcanton answers open questions 1 and 2 yes, and the commit
that starts them has to say, in those words, that it is a human override of a recorded rule
rather than a correction of one — `static/VENDOR.md`'s revisit condition is "before somebody
is measurably slowed down by a textarea", and nobody has produced that measurement.

## Why the stages are ordered this way

The cheap, visible things first, because the honest test of whether a 594 KB library is
wanted is whether anything is still missing after the free work is done. Then the two
shipped defects, because they are wrong today regardless of which editor wins. Then the
adapter, alone and with no features, because the code path it touches has destroyed
somebody's unsaved writing three times and a regression in it has to be attributable to
one commit. The library question is last because it is the only part that cannot be
undone by deleting one commit and one `SHA256SUMS` line.

Each stage is one commit that leaves the tool working. Each ends with `uv run pytest -q -p
no:warnings` green and `uv run ruff check .` clean.

## Verifying a change

**Anything about layout, selection, key handling or pixels is asked of Chrome, through
`tests/browser.py` (`measured_in`, `in_a_live_page`) — never of `tests/js/drive.js`.**
`AGENTS.md` records that the shim has misled three rounds of this work and twice on this
exact feature: it handed the host realm's `String` into its vm so every `YText.insert`
became an empty embed, and it copied parsed text into `textContent` and never into
`.value`, so `ORIGINAL_BODY` was empty in page mode — which flips the one branch in the
editor that can lose unsaved work.

**Anything about convergence is driven against a real `Room`** (`openproj.coedit.Room`),
and anything about backpressure against the real uvicorn `serving` fixture in
`tests/test_coedit.py`, because `TestClient`'s send never blocks and the whole class of
defect is that uvicorn's does.

**Anything about specificity is resolved with `tests/cascade.py`**, which weighs selectors
the way § Selectors 4 does and answers which rule wins by name.

**Any claim about bytes states the command.** The one this plan uses throughout:

```bash
PYTHONPATH=$PWD/src uv run python -c "
from datetime import date; from pathlib import Path
from openproj.cli import load_repo; from openproj.index import build_index
from openproj.render import ROUTES, render_detail
entities, config, _ = load_repo(Path('tests/fixtures/corpus'))
idx = build_index(entities, config, date(2026,8,17)); one = next(iter(idx.entities))
page = render_detail(idx, ROUTES, only=one, base_commit='deadbee', may_write=True)
print(len(page.encode()))"
```

Baseline for that exact invocation: **318,526 B raw / 132,288 B gz -9**. The served route
on the seed corpus is 324,285 B / 133,650 B; a reader's page (`may_write=False`) is
209,872 B; the static export's `detail.html` is 257,922 B.

**Environment trap.** The only venv on this machine is the main worktree's, installed
editable against `/Users/jcanton/projects/openproj/src`. Running `pytest` from this
worktree without `PYTHONPATH=$PWD/src` imports the *other* worktree's `openproj` while
reading this one's `static/` and `tests/`, and
`test_every_library_is_inlined_exactly_once_and_no_marker_survives` fails with a phantom
`assert 0 == 1` in exactly the test that governs where a vendored file may live.

## Global constraints

- **No npm, no build step, no CDN.** A candidate is a candidate only if it is fetched once
  at development time, committed verbatim into `static/`, checksummed in
  `static/SHA256SUMS`, inlined into a `<script>` block, readable, and BSD-3-compatible.
- **The preview is the server's markdown**, through `/api/preview` (`render.py:8482`,
  `web.py:1602`). A second markdown implementation in JavaScript is refused on record.
- **Every programmatic edit to the box goes through `replaceRange`** (`render.py:7364`),
  which uses `execCommand('insertText')`. `textarea.value = …` wipes the browser's native
  undo stack; that is d6997e3's shipped data-loss bug.
- **Tab width is a typing setting, never a "convert this document" command.** A global
  re-indent is recovered by `typed()` as one delete-all-insert-all, which
  `tests/test_coedit.py:756` already measures as larger than `MAX_BODY_BYTES`.
- **Colours are tokens in three blocks** (bare `:root`, `:root[data-theme="dark"]`, and
  `@media (prefers-color-scheme: dark)` guarded by `:root:not([data-theme="light"])`).
- **One global lexical scope.** Every page is classic `<script>` blocks sharing it, so a
  second top-level `const` of an existing name is a SyntaxError for the whole document.
  `test_every_page_carries_exactly_one_escaper` already pins `const esc = ` at one.
- **Preferences go through `remembered`** (`render.py:1238-1280`), four verbs, declared in
  the head before first paint, `openproj:`-namespaced with the version in the key and the
  old key explicitly forgotten.

## The four pages that inline a body editor

The evidence answers this outright: **four**, plus two plain boxes that get neither
toolbar nor upload handler.

| template | opens | bodybar | textarea | mounts |
|---|---|---|---|---|
| `_NEW` | `render.py:7884` | 7930 / 7946 | 7951 | 8007-8008 |
| `_DETAIL` | `render.py:8144` | 8261 / 8269 | 8280 | 8370-8371 |
| `_ISSUE` | `render.py:13525` | 13575 | 13580 | 13596-13597 |
| `_NOTE` | `render.py:13806` | 13856 | 13861 | 13878-13879 |

Plain, no toolbar: the cycle page's `#goal` (`render.py:10470`) and `#notes` (`:10534`).

The helpers are already **one shared block**: `_COMBOBOX` (`render.py:7352`) holds
`replaceRange`, `FORMATS`, `lineRange`, `applyMark`, `LIST_ITEM`, `attachEditing`,
`attachUploads` and `attachSuggest`, and `_combobox_html` (`render.py:13240`) emits it on
six pages — table, new, detail, cycle, issue, note. Each page then writes two lines. So
anything that lives in those helpers is **one block, four mount sites**; anything that is
markup, CSS or room-aware is **per template**. Two standing caveats: the CSS is duplicated
across `_DETAIL_STYLE` (`render.py:9097`, rules at `:9222`, `:9257`) and `_RECORD_STYLE`
(`render.py:13983`, rules at `:14055`, `:14068`) under two different mode classes
(`article.entity.editing` vs `body.editing`); and `_COMBOBOX` is also emitted on the table
and cycle pages, which have no body editor.

---

## S0 — Grep the migrated HackMD corpus

Ten minutes, before any renderer or toolbar decision. Not a code change.

- [ ] **S0.1** Grep the real migrated corpus for `[TOC]`, `:::info`/`:::warning`/
      `:::spoiler`, `> [name=`, `{%youtube`/`{%gist`/`{%pdf`, `[^`, `- [ ]`, `$…$`,
      ```` ```mermaid ````, `![… =200x`. Record the counts in the S1 commit message.

**Why it gates S1.** The seed corpus in this worktree is synthetic and returns **zero**
hits for every one of those, so it cannot answer the question, and the existing
seven-button toolbar was sized off exactly this kind of count: 485 lines with an inline
code span, 161 a bullet, 124 a heading, 83 bold, 8 a markdown link — which is why there is
no link button. Every renderer item in S1 is a guess until this runs, and jcanton is the
only person who can point at the corpus.

**Proved by:** nothing. It is a measurement, and its output is a paragraph in the S1
commit.

---

## S1 — The renderer batch, the keyboard, and the written-down search

Zero vendored bytes; at most one pip dependency. Ships ask 5 and improves every reading
page.

**Server** (`src/openproj/render.py`):

- [ ] **S1.1** `.enable("strikethrough")` on `_MD` at `render.py:941`, which is today
      `MarkdownIt("commonmark", {"html": False}).enable("table")`. Verified: `~~x~~`
      renders as literal tildes now.
- [ ] **S1.2** Task-list checkboxes — `- [ ] a task` renders as the literal text `[ ]`
      today. A `mdit-py-plugins` dependency, zero browser bytes.
- [ ] **S1.3** `data-startline` / `data-endline` stamped from markdown-it's `token.map` in
      a `RendererHTML` override beside `_pr_refs` and `_image` (`render.py:1088-1089`).
      Nothing consumes it until S2; it lands here because it is a renderer change.

**Client**, in the shared `_COMBOBOX` block (`render.py:7352`) — **one block, and all four
pages get it for free**:

- [ ] **S1.4** Tab / Shift-Tab soft indent through `replaceRange` (`render.py:7364`), in
      the `keydown` handler that already exists inside `attachEditing`
      (`render.py:7460`, the handler at `:7476`), with list and blockquote nesting reusing
      `LIST_ITEM` (`render.py:7458`) and `lineRange` (`render.py:7396`). Deletion through
      `execCommand('insertText', false, '')` is already a proven path — the empty-list-item
      branch does exactly that.
- [ ] **S1.5** An Escape-armed one-shot Tab pass-through, **announced** through `announce`
      rather than silently implemented: swallowing Tab removes the only way to leave the
      field by keyboard.
- [ ] **S1.6** Four new `FORMATS` entries (`render.py:7386`). Check list (`prefix: '- [ ] '`)
      and strikethrough (`wrap: '~~'`) drop into the existing shapes; a table template and
      a horizontal rule are neither wrap nor prefix nor fence and need a **fourth `insert:`
      branch in `applyMark`** (`render.py:7402`, which has exactly three today), ~4 lines.
      Explicitly not link and not image, on the S0 counts.
- [ ] **S1.7** Smart paste inside the listener that already handles images
      (`attachUploads`, `render.py:7513`): a URL pasted over a selection becomes
      `[selection](url)`; TSV becomes a markdown table. Both through `replaceRange`, so
      undo survives.

**The search, in the same commit**, because nothing here will mechanically force it and
`AGENTS.md:308` requires it:

- [ ] **S1.8** Rewrite `static/VENDOR.md`'s "No editor library" section to record that the
      revisit happened; that Ace 1.44.0 is **admissible and measured** (BSD-3, three classic
      scripts, zero rewrite, no worker for markdown mode, verified in Chrome under this CSP
      with a forced-failure control on `ace/mode/javascript`); and the numbers — Ace
      core+md+vim 669,582 B raw / 184,807 gz and core+vim 594,306 B; CodeMirror 6 816,104 /
      278,694 plus a ten-module render-time linker over 42 imports and 9 export clauses;
      CodeMirror 5 692,765 B with upstream archived — against a 318,526 B page. Add
      proposal 1's rule while it is being written: **any future Yjs-binding library that
      externalises `yjs` must bind to the same `Y.Doc` class the room came from**, so it can
      never be inlined beside `_yjs()` as a separate block.
- [ ] **S1.9** Correct the record in the same paragraph: `mode-markdown.js` contains
      **four** `createWorker` definitions, not zero. The right reason Ace spawns none is
      structural — `MarkdownMode` inherits `TextMode`, whose `createWorker` returns `null`.

**Proved by:**

- `tests/test_render.py` — a new `test_a_struck_out_line_and_a_task_list_render_as_what_
  they_are`, over `preview_html` and over a rendered detail page, parsed with the DOM
  parser rather than by substring.
- `tests/test_editor.py` — extend `test_the_toolbar_is_sized_to_what_this_team_writes`
  (the count at `:806` moves from 7 to 11) and keep its `](` assertion: no link button.
- **Chrome, `tests/browser.py`** — `test_tab_indents_the_lines_the_selection_touches_and_
  escape_then_tab_leaves_the_field`. Key handling and selection: not the shim.
- `tests/test_render.py` — a new `test_a_rendered_block_carries_the_source_line_it_came_
  from`, asserting `data-startline` on `h2`/`p`/`ul`.
- **NEW, and this is the hole the audit found:**
  `test_an_editable_page_reaches_the_network_no_more_than_a_read_only_one`. Both existing
  network assertions loop over `PAGES` (`tests/test_render.py:22`), which is the eight
  static-export files, and `render_static` calls `render_detail(index)` with no
  `base_commit`, so `editable` is False and **neither has ever inspected an editing
  surface**. The new test runs both bodies of assertions — the four in
  `test_no_page_reaches_the_network` (`tests/test_render.py:102`) and the `url(` scan in
  `test_no_page_asks_the_network_for_a_font` (`:1489`) — over
  `render_detail(idx, ROUTES, only=…, base_commit='deadbee', may_write=True)`. It lands
  here, before any vendored byte, not after. Mutation-test it: append
  `<style>a{background:url(http://x/y.png)}</style>` to the page and watch it fail.

**Hazards answered:** the network-rule coverage hole (partially — the runtime half waits for
S8); the bulk-gesture rule is stated in the commit and enforced in S5.

---

## S2 — Full page, three views, scroll sync, deep links

Zero vendored bytes. Ships asks 1 and 3 — the two highest felt value on the list.
**Markup and CSS, so `_DETAIL` and `_NEW` in this stage; `_ISSUE` and `_NOTE` in S5.**

- [ ] **S2.1** `article.entity` becomes a viewport-filling grid with two independently
      scrolling panes, as a tri-state class. `_DETAIL_STYLE` (`render.py:9097`), rules
      beside `:9115` (`article.entity { width: var(--measure, 64rem) }`) and `:9202-9203`
      (the `.field` / `.read` / `.editing` swap). Read mode and edit mode are one class
      apart today; full page is a third mode that has to compose with both.
- [ ] **S2.2** An explicit rule for `#grip` (`render.py:9142`) and `--measure` in the new
      mode, and `place()` (`render.py:8322`) taught about it, or the drag handle parks at
      the left edge — which is the bug `place()` already exists to fix on the index view.
- [ ] **S2.3** Three mutually exclusive buttons in the existing bodybar
      (`render.py:8261-8272`, which today holds `#together` at `:8266` and a single
      `#preview` toggle at `:8267`), bound to Ctrl+Alt+E / Ctrl+Alt+B / Ctrl+Alt+V —
      Ctrl+Option on Mac, **never Cmd**: the page already claims Cmd+S (`render.py:8566`) and Cmd+B/I/E/2/8/. through
      `attachEditing`.
- [ ] **S2.4** Live preview: the existing `/api/preview` round trip (`render.py:8482`)
      debounced ~300 ms with an `AbortController`, an unchanged-text skip, and a preserved
      `#body-preview.scrollTop`. A naive `innerHTML` replace scrolls to top on every
      keystroke and is worse than no live preview.
- [ ] **S2.5** Bidirectional scroll sync interpolating between the S1 `data-startline`
      elements, with `editScrolling` / `viewScrolling` flags to break the feedback loop.
- [ ] **S2.6** `?edit` / `?both` / `?view` read once on load, feeding the same tri-state,
      off the existing hash router (`show()` at `render.py:8617`, `hashchange` at `:8631`).
      Ids in `_DETAIL` are subject to the `{% if single %}` rule (`render.py:8211`): the
      static export renders this template once per entity into one file, so a new id that is
      not guarded makes `getElementById` answer the wrong one seventeen times over.
- [ ] **S2.7** **Fix in the same commit:** the existing `#preview` toggle sets
      `BODY.hidden = true` (`render.py:8482-8506`) and dispatches nothing, so `drawSeats`
      never learns the box changed size. `drawSeats` is triggered only by input, scroll,
      keyup/click, window resize and `openproj:editing` (`render.py:8810`). This stage
      turns that from transient into normal: every view change fires `openproj:editing` (or
      a `ResizeObserver` does).
- [ ] **S2.8** Arbitrate Escape and **write the answer down here**, not in S9. It has three
      claimants: end the editing session, leave full-page, and later leave vim insert mode.

**Proved by:**

- **Chrome, `tests/browser.py`** — `test_the_three_views_are_one_of_three_and_each_pane_
  scrolls_on_its_own` and `test_the_width_handle_finds_the_pane_in_every_view`. Layout and
  pixels: not the shim.
- `tests/cascade.py` — `test_the_full_page_class_does_not_beat_the_editing_class`, because
  qualifying a selector to win a fight is this file's characteristic failure and it has
  happened twice in one week in this stylesheet.
- `tests/test_editor.py` — `test_a_view_change_tells_the_seat_layer_the_box_moved`,
  asserting the event is dispatched; the pixel half is the Chrome test in S3.
- `tests/test_table.py:1638` still passes unmodified: `/new` and `/detail` must carry the
  same shapes (`<dl id="facts">`, `class="field title-field"`, `class="field bodybar"`,
  `class="field body-field"`, `id="preview"`), or the layout moves under you between
  reading an entity and making one.
- `tests/test_editor.py:138` still passes: `#commitbar` after `#facts` and `.body-field`,
  sticky at the bottom, holding `#save` and `#cancel` and not `#toggle`. That test encodes
  an ordering argument, not a coordinate — if full-page needs it moved, it is re-argued in
  this commit, not renumbered.

---

## S3 — One mirror: fix the seat bands, then build the gutter on them

Zero vendored bytes. Ships ask 4. **One shared block plus `_DETAIL`'s seat code**, since
`drawSeats` lives in `_COEDIT`.

- [ ] **S3.1** **Alone, first, as a correctness fix to shipped code:** `render.py:8838` is
      `ghost.style.width = BODY.clientWidth + 'px'` — an integer, while the textarea's real
      content box is fractional. Measured across six corpora × 481 widths, that mismatches
      at 1.7%–10.4% of widths, never by a pixel and always by a whole line height, up to
      three. Sync the mirror as a fractional content box instead:
      `getBoundingClientRect().width` minus fractional borders, padding and the integer
      scrollbar gutter. `VENDOR.md` holds this feature to "a caret one line off is worse
      than no caret".
- [ ] **S3.2** One `display:block` span per **logical** line in that same mirror; numbers
      positioned absolutely from `offsetTop`; rAF-coalesced; redrawn on
      `document.fonts.ready` and `resize` — the mirror's own comment already records that a
      mirror whose font is a fallback measures the fallback's line height.
- [ ] **S3.3** A line-count ceiling above which the gutter turns itself off **out loud**,
      rather than stuttering. 4.4 ms to rebuild 400 logical lines, 22 ms at 2,000.
- [ ] **S3.4** Repoint `drawSeats` (`render.py:8850`) to read band tops from the same
      mirror, deleting its per-caret `measure()` loop (`render.py:8831`). Co-editing gets
      cheaper as a side effect — the only item in this plan that reduces existing risk.

**Proved by:**

- **Chrome, `tests/browser.py`** — `test_every_line_number_sits_on_the_line_it_numbers`,
  pinning the gutter against an **independent ground-truth mirror** built in the test, over
  wrapped prose, CJK, ZWJ and regional-indicator emoji, a hard tab and an unbreakable URL,
  swept across several widths. A future style change that breaks the twelve copied
  properties has to fail loudly.
- **Chrome** — `test_a_seat_band_lands_on_the_right_line_at_a_width_that_wraps`, which is
  the regression test for S3.1. Delete the fix, watch it fail, put it back: it must
  disagree by a whole line height at a width on a wrap boundary.
- `tests/test_seats.py` stays **unmodified**: its four tests drive
  `document.getElementById('toggle').click()` and
  `document.querySelector('textarea[name=body]')`, and both selectors still exist and still
  mean the same thing.

**Hazards answered:** *the mirror is measured as a fractional content box.* The test that
would fail if it were reintroduced is `test_a_seat_band_lands_on_the_right_line_at_a_width_
that_wraps`.

---

## S4 — `Y.UndoManager`, and the undo defect that is already shipped

Zero new vendored bytes: `UndoManager` is already in the export clause of
`static/yjs.bundle.mjs` (confirmed by grep). **`_DETAIL` only** — it is the only template
with a room.

- [ ] **S4.1** `Y.UndoManager` over the room's `Y.Text` with `trackedOrigins {'typed'}` —
      the origin `typed()` already passes to `doc.transact(…, 'typed')` (`render.py:8741`).
      Ctrl-Z undoes what this tab wrote and nothing else.
- [ ] **S4.2** This closes a live bug nobody in the audit named: `reflect()`
      (`render.py:8756`, the write at `:8764`) does `BODY.value = want` on every remote
      update, and `render.py:7357` records that assigning `.value` wipes the browser's
      native undo stack. In a live room, every remote keystroke already destroys your undo
      history, unguarded and unnamed.
- [ ] **S4.3** Extend `test_no_script_ever_assigns_a_textarea_its_value`
      (`tests/test_editor.py:787`) to scope `_COEDIT`. It greps `replaceRange`, `FORMATS`
      and `attachUploads` today and deliberately does not look at the room's script — which
      is exactly why the defect above survived.

**Proved by:**

- **Chrome + a real `Room`** — `test_undo_never_takes_back_something_somebody_else_typed`:
  two documents, A types, B types into A's room through the real `Room`, A presses undo,
  assert B's characters are still there and that nothing was propagated as a deletion. This
  is the measured Ace failure (`"REMOTE LOCAL mine"` → one undo → `"mine"`) asked of the
  design we actually ship.
- **Chrome** — `test_a_remote_keystroke_leaves_the_caret_the_scroll_and_the_history_where_
  they_were`: caret position, `scrollTop` and undo availability before and after a remote
  update.
- `tests/test_editor.py:787`, extended, is the static half.

**Hazards answered:** *reflecting somebody else's keystroke must not move the caret, the
scroll or the undo history*; *undo must never delete text this tab did not write*; and half
of *a guard that greps source must follow the code it guards*.

---

## S5 — The preference, the status bar, and the draft receipt

Zero vendored bytes. Ships ask 7 and the two-editor preference in its textarea-modes form.
**This is the stage that reaches all four pages**, and the first commit of it is a
prerequisite.

- [ ] **S5.1** **First, alone:** unify `article.entity.editing` with `body.editing`.
      `_DETAIL` uses a class on the article; `_ISSUE` and `_NOTE` use a class on `<body>`,
      and their `.bodybar` / `.body-field` rules are a second copy in `_RECORD_STYLE`
      (`render.py:13983`, `:14055`, `:14068`). `tests/test_issues.py:337` exists because
      `.field` once beat `.bodybar` on specificity and put the textarea on the same line as
      the buttons. Resolve it with `tests/cascade.py` and say in the comment which way it
      resolves.
- [ ] **S5.2** `openproj:editor:1` — one JSON object through `remembered.map` holding
      `{mode, indent, autosave}`, matching the `openproj:widths:4` precedent. The version
      goes in the key and the old key is explicitly forgotten with a sentence to the reader,
      the way `render.py:8589-8595` already does it. `remembered.get`'s fallback makes the
      plain box the answer when storage throws, which is right for a preference about a
      control that must exist before the preference can be read.
- [ ] **S5.3** A status bar under the box: line/column, selection size, and HackMD's
      click-the-number indent picker with **independent** tab-width and space-width keys.
- [ ] **S5.4** Ask 7: a settable throttle **with a ceiling** on the existing per-input draft
      write at `render.py:8581`, plus a visible "draft saved 12s ago" beside `#unsaved`, plus
      surfacing that the room already commits after `QUIET_SECONDS = 20` (`coedit.py:60`).
      **Not** a POST on a timer. The ceiling matters: a user-settable interval otherwise
      lets somebody set their own floor coarser than the window it backstops.
- [ ] **S5.5** Roll the S2 view modes out to `_ISSUE` (`render.py:13525`) and `_NOTE`
      (`render.py:13806`). They have no room, no draft, no seat layer, no width grip, and a
      `#promote` bar that is hidden while editing (`render.py:14071`).

**Proved by:**

- `tests/test_editor.py` — `test_the_editor_preference_is_one_key_and_survives_a_browser_
  that_refuses_storage`, driven with `localStorage` throwing on the property itself, which
  is the failure `remembered` exists for.
- `tests/test_editor.py:668`'s draft tests still pass: the key, the `{base, text}` shape and
  the base-rewind are unchanged. A throttle must not change what is written, only when.
- **Chrome** — `test_a_throttled_draft_is_still_written_before_the_tab_can_be_closed`.
- `tests/test_render.py:1375` (the bare-`localStorage` grep) stays green: every new read
  goes through `remembered`.
- `tests/test_issues.py:337` and `tests/test_notes.py:286` still pass after S5.1.

**Hazards answered:** *a bulk gesture is recovered as what it is* — the indent picker
changes the typing setting only, never the document, and the commit says so.

---

## S6 — The surface adapter, textarea-only, shipped alone

Zero bytes, zero behaviour change. This is proposal 3's best single engineering judgement,
kept in shape and changed in purpose. **One shared block plus `_COEDIT`.**

- [ ] **S6.1** `_COEDIT` (`render.py:8636`), `FORMATS` / `applyMark`, `attachUploads`, the
      draft writer and `drawSeats` move behind seven methods — `text`, `caret`, `setCaret`,
      `splice`, `onInput`, `onCaret`, `coordsAt` — every one specified in **UTF-16 code
      units**, with the textarea as the only implementation.
- [ ] **S6.2** Add `test_the_body_is_read_through_one_place_and_nothing_else`: a source-grep
      test in the same shape as the splice guard, asserting `BODY.value` appears only inside
      the textarea implementation. The seventeen call sites — `read`, `changed`, `dirty`,
      `save`, the draft writer, the draft restorer, `ORIGINAL_BODY`, the preview,
      `attachUploads`, `attachEditing`, `applyMark`, `lineRange`, `drawSeats`, `sit`,
      `typed`, `reflect`, `welcomed` — have to be enumerable **before** anything is allowed
      to stop writing to it.
- [ ] **S6.3** Re-point `test_the_browser_splices_on_a_whole_character`
      (`tests/test_coedit.py:1446`) at the adapter's source rather than deleting it. It
      reads `str(_COEDIT)` and requires every `text.insert` / `text.delete` index to start
      literally with `units(`, so an adapter in a new module constant is invisible to it.
      Its regex `\btext\.(?:insert|delete)\(` is also blind to `ytext.insert`,
      `shared.insert` and `doc.getText('body').insert` — i.e. dodgeable by a rename. Widen
      it in the same commit.

**No features in this commit**, so any regression in the code path that has destroyed
unsaved writing three times is attributable to it.

**Proved by:**

- The whole existing `tests/test_coedit.py` and `tests/test_seats.py`, unmodified apart from
  S6.3. Thirty-five of sixty-five test functions in `test_coedit.py` address `BODY` /
  `textarea[name=body]`; if any of them moves, the adapter changed behaviour and this stage
  failed its own claim.
- `tests/test_editor.py:787` (extended in S4) and the new S6.2 grep.
- **Chrome + a real `Room`** — re-run
  `test_an_edit_across_an_emoji_reaches_the_room_as_the_character_it_was`
  (`tests/test_coedit.py:1414`) through the adapter. Note its own comments: two of its five
  cases are **controls that passed with the defect in place**.

**Hazards answered:** *nothing reads `BODY.value` except one place*; the rest of *a guard
that greps source must follow the code it guards*.

---

## S7 — Stop and ask — **ANSWERED 2026-08-20: proceed**

Answered before the stage was reached, so it is a checkpoint rather than a gate: *"implement
both: improvements to our editor as well as ace."* The price below was put with it and taken.
Three answers change what S8 and S9 build, and they are recorded here rather than only in
`EDITOR.md` because this is the file S8 is executed from:

- **Minified**, `src-min-noconflict`, so every byte figure in this stage stands as written.
  Answered "unminified" first and reversed once the cost was measured: `src-noconflict` is
  1,307,387 B against 670,198 B — 1.89x the number this repository refused — and it fails the
  font-url assertion 24 more times, because it escapes its own `data:` URIs differently. The
  bytes are still upstream's: `src-min-noconflict` ships inside the npm tarball rather than
  being generated by a CDN, so the checksum identifies something upstream published.
- **A URL parameter, not a cookie.** `?editor=ace` makes the server inline it; the remembered
  `openproj:editor:1` makes it sticky. So the "on every writer's page whether or not they opt
  in" cost below does not apply, and the reader problem — `editable` gated on `base_commit`
  alone — is disposed of: a reader who never types the parameter pays nothing.
- **Markdown mode stays dropped.** The textarea's own highlighting is not being replaced, and
  it removes four dormant worker-spawning sub-modes from the page.

The record has to say this was an override, not a re-derivation: the recorded revisit
condition — "before somebody is measurably slowed down by a textarea" — has still not been
met by anybody, and wanting vim because you want vim is a legitimate reason that the commit
must state in those terms.

The original stage text follows, unedited, because the price it names is the thing that was
accepted.

Not a commit. Six of the seven asks are shipped, two shipped defects are fixed, and not one
byte has been vendored — which is the honest test of whether anything below is wanted.

Put the question to jcanton with the price on it:

- ask 6 costs **594,306 B raw** (`ace.js` + `keybinding-vim.js`, dropping the markdown mode)
  or **669,582 B** with it, ~165–185 KB gzipped, on every writer's page whether or not they
  opt in, unless a server-visible cookie is accepted;
- plus a second, hand-written, upstream-less, delta-based, origin-guarded Yjs binding in the
  code path that has four documented shipped data-loss bugs;
- plus the hazards below that only S8 and S9 can answer.

It is 85.8% of the number this repository refused in writing twice, and the recorded revisit
condition has not been met by anyone. **If the answer is no, the work ends here and the
`static/VENDOR.md` paragraph written in S1 is already correct.**

---

## S8 — If and only if the answer is yes: vendor Ace, minus the markdown mode

**Gate first, in Chrome, under the real CSP with the console captured and `window.Worker`
hooked before load.** A blocked worker is an `error` event with an empty message, not an
exception, so no Python test can see it.

- [ ] **S8.0a** Confirm the measured zero-worker result on **this** assembly.
- [ ] **S8.0b** Confirm `ace.js` + `keybinding-vim.js` work with **no mode set**. Nobody has
      tested that configuration; `keybinding-vim.js` defines `ace/keyboard/vim` and
      `ace/ext/hardwrap` and reaches for nothing else, so it should work — but ask Chrome.
      If either gate fails, stop and escalate.

Then, in order:

- [ ] **S8.1** Two files into `static/`: `ace.js` (475,029 B, sha256 `072d13e5…`) and
      `keybinding-vim.js` (119,277 B, `464f901e…`). **Drop `mode-markdown.js`**: 75,276 B for
      syntax highlighting, which is not one of the seven asks; it is the only file that fails
      the font regex (twice, at offsets 9046 and 47867); and it is the one that inlines four
      dormant worker-spawning sub-modes.
- [ ] **S8.2** `static/SHA256SUMS`, from that directory, exactly:
      ```
      shasum -a 256 *.js *.mjs *.woff2 > SHA256SUMS && shasum -a 256 -c SHA256SUMS
      ```
      **The trap `VENDOR.md` records:** `*.js` alone was the old instruction and `>`
      truncates — running it once wrote three lines over four and silently dropped the
      woff2's checksum. Every glob, or name every file. Check the line count before and
      after. `ace-LICENSE.txt` is deliberately **not** covered: `test_every_vendored_file_is_
      the_one_that_was_checksummed` exempts `*LICENSE.txt` by design ("a licence is read, not
      executed").
- [ ] **S8.3** `static/VENDOR.md`: two table rows naming version, **BSD-3-Clause** and the
      `src-min-noconflict` source URL, plus a licence paragraph. All three minified files
      contain zero occurrences of `Copyright`, `BSD` and `Ajax.org` — the notice is stripped —
      so `ace-LICENSE.txt` (1,490 B, sha256 `850f545c…`) ships in `static/` **and** the notice
      goes in the page, on the precedent `test_the_font_licence_travels_with_the_font` already
      enforces for Inter: every rendered page is a copy, and a copy is a redistribution.
- [ ] **S8.4** `tests/test_render.py:134` — rewrite `test_every_library_is_inlined_exactly_
      once_and_no_marker_survives` from "four `.js`, all in `graph.html`" to "inlined exactly
      once into the page that uses it". `len(inlined) == 4` becomes 6, and
      `graph.count(signature)` is 0 for the Ace files because the graph page has no editor.
      **Do not dodge it with an `.mjs` suffix**: that is a false label on a classic script and
      it would also carry the file out of `test_no_vendored_library_can_end_the_block_it_is_
      written_into`, which filters on `.js`.
- [ ] **S8.5** `tests/test_editor.py:130` — `test_the_editor_pulls_in_no_library_at_all`
      asserts `"codemirror" not in page.lower()`. Its docstring says "If this ever fails,
      somebody has added an editor dependency and should have to argue for it." Ace passes it
      **unchanged**, which means it is a name check and not an argument. Rewrite it to say
      what is now true: inlined, checksummed, no `<script src>`, no network, and named.
- [ ] **S8.6** Extend the S1 editable-page network test with the **runtime** half:
      `test_no_editor_asks_for_a_script_after_the_page_has_loaded` — Chrome, exercise the
      default keymap (Cmd-F, Ctrl-H, Cmd-comma, Alt-E), assert zero `script[src]` elements and
      zero `securitypolicyviolation` events. Measured today: `metaKey+f` gives
      `defaultPrevented=true`, `scriptsInjected=['ext-searchbox.js']`, a `script-src-elem`
      violation, `searchbox_in_dom=false`, and an empty `window.error`. The source regex
      `<script[^>]+src=` cannot see a runtime injection.
- [ ] **S8.7** `commands.removeCommand` on the five default commands that reach
      `net.loadScript`, so Cmd-F falls through to the browser. This is application code, so the
      commit must not claim "verbatim behaviour" — only verbatim bytes.
- [ ] **S8.8** A new `may_write` gate on the editing script, and a **server-visible cookie**
      mirroring the preference. `editable = base_commit is not None` (`render.py:13163`) and
      the served route (`web.py:1577`) passes `base_commit` for everyone; only `yjs` and
      `coedit` carry the extra gate (`render.py:13185-13186`). A reader's page is 209,872 B and
      already contains the textarea and two `attachEditing(` calls; the same gate would take it
      to 879,454 B. If the cookie is refused, **drop the second editor**.
- [ ] **S8.9** Re-express Ace's injected theme across all three colour-token blocks — `ace.js`
      carries 27 hex colours and 53 `rgb()`/`rgba()` literals — and redraw the focus ring on
      `.ace_editor` via `:focus-within`, because Ace's real input is a 2.5×1 px opacity-0
      offscreen textarea whose `aria-label` Ace rewrites over the page's "Shaping document".
      The shell's ring is `:where(a, button, input, select, textarea, summary, [tabindex])` at
      specificity (0,1,0) and loses to Ace's runtime-injected `outline: none`.
- [ ] **S8.10** The binding: consume Ace's own change deltas, convert `{row,column}` through
      `positionToIndex`, apply directly to the `Y.Text` inside `doc.transact`, batch once per
      Ace operation, and apply remote `Y.Text` deltas back **as Ace deltas** — never
      `setValue`, never `replace` — behind an explicit `applying` re-entrancy flag. Pin
      `setNewLineMode('unix')` and assert the seeded value is **byte-identical** to
      `ORIGINAL_BODY` before binding, announcing any difference rather than splicing it.
      Attach only **after** `welcomed()` (`render.py:8922`) has made the three-way decision,
      the way the `bound` gate (`render.py:8786`) does.
- [ ] **S8.11** Re-attach paste, drop and Enter-continues-list through Ace's command table,
      and route the toolbar through the adapter's `splice` rather than `replaceRange`.

**Proved by, and these are blockers:**

- **Chrome + a real `Room`** — the **five-case parametrisation this repository already ships**
  (`tests/test_coedit.py:1390-1444`: thumb-up edited to thumb-down, backspacing one of two
  adjacent emoji, a flag's second regional indicator, and the two controls) **plus a
  line-ending case**. Not "type an astral character and assert convergence": that exact gate
  was run end to end against `static/yjs.bundle.mjs` on a room seeded with `"Ann says\rand
  then\nlast line\n"` — it **passed**, and `copies_converged` was false.
- **A real `Room`** — `test_one_save_is_one_commit_authored_by_whoever_typed_the_most_on_
  either_surface`, and `test_a_tab_that_is_only_watching_is_credited_zero_characters`.
  Measured today with the naive adapter: one remote keystroke credits a passive tab with
  97,892 characters on a 97,890-character body.
- **Chrome** — `test_opening_the_second_surface_changes_no_byte_of_the_document`. Measured
  today: opening Ace on a 15,897-byte body whose first ending is CRLF and whose other 400 are
  LF produced cut 15,852 / put 16,252 and a 16,288-byte Yjs update **before anybody typed**.
- **Chrome** — `test_every_toolbar_button_still_edits_the_document_with_the_keymap_on`.
  `document.execCommand('insertText')` returns `true`, throws nothing and changes nothing
  under vim NORMAL mode.
- The byte command above, run before and after, with the gzip figure in the commit message.
  Expected: 318,526 → ~913,000 B raw.

**Hazards answered:** *every programmatic write carries an origin, and the surface's own
change event is refused while one is in flight*; *a surface must not rewrite the document
merely by opening on it*; *one index space, and it indexes the text the room holds*; *the
gating test must be the case that catches the defect*; *the network rule is enforced where
the bytes actually are, and at runtime as well as in the source*; *the bytes are gated on
`may_write`, and the preference that decides them is visible to the server*.

---

## S9 — Vim itself, and the collisions it creates

- [ ] **S9.1** `setKeyboardHandler('ace/keyboard/vim')`, toggled live from the S5 preference.
- [ ] **S9.2** HackMD's "allow override browser keymap" escape hatch, and the Escape
      arbitration decided back in S2.
- [ ] **S9.3** The toolbar and the image-paste placeholder-then-replace go through the
      adapter's `splice` on the Ace path, never through `replaceRange`.
- [ ] **S9.4** A bulk gesture — `:%s///g`, `gg=G`, multi-cursor — is announced before it is
      sent, and `MAX_UPDATE_BYTES`'s answer is the `reload` frame `web.py:2667` already gives,
      never a bare `continue`. Measured: multi-cursor plus one keystroke deleted 14,789
      characters and reinserted 13,345, producing a 234,892 B frame; and 722 change events
      through `typed()` is ~1.4 s of blocked main thread on a 250 KB body.

**Proved by:** **Chrome** — `test_a_substitution_over_a_whole_document_is_announced_before_
it_is_sent`, and `test_the_toolbar_and_the_keymap_do_not_cancel_each_other`. Plus a real
`Room` for the credit of a bulk gesture.

Removable by deleting one commit and one `SHA256SUMS` line, which is the point of putting it
last.

---

## Where each hazard is answered

| hazard | stage | the test that fails if it comes back |
|---|---|---|
| Nothing reads `BODY.value` except one place | S6 | `test_the_body_is_read_through_one_place_and_nothing_else` |
| Every programmatic write carries an origin | S8 | `test_a_tab_that_is_only_watching_is_credited_zero_characters` |
| A remote keystroke moves no caret, scroll or history | S4 | `test_a_remote_keystroke_leaves_the_caret_the_scroll_and_the_history_where_they_were` |
| Undo never deletes text this tab did not write | S4 | `test_undo_never_takes_back_something_somebody_else_typed` |
| A surface must not rewrite the document by opening on it | S8 | `test_opening_the_second_surface_changes_no_byte_of_the_document` |
| One index space, and it indexes the room's text | S8 | the five-case parametrisation + a line-ending case |
| The gate is the case that catches the defect | S8 | same, run in Chrome against a real `Room` |
| A source-grep guard follows the code it guards | S4, S6 | `test_no_script_ever_assigns_a_textarea_its_value`, `test_the_browser_splices_on_a_whole_character` |
| A bulk gesture is announced, credited and refused out loud | S5, S9 | `test_a_substitution_over_a_whole_document_is_announced_before_it_is_sent` |
| The network rule is enforced where the bytes are | S1, S8 | `test_an_editable_page_reaches_the_network_no_more_than_a_read_only_one`, `test_no_editor_asks_for_a_script_after_the_page_has_loaded` |
| Bytes gated on `may_write`, preference visible to the server | S8 | `test_a_reader_who_may_not_write_is_sent_no_editor_library` |
| The mirror is measured as a fractional content box | S3 | `test_a_seat_band_lands_on_the_right_line_at_a_width_that_wraps` |

## What is explicitly not in this plan, and why

- **Remote carets with a name label.** They are drawable inside a real editor and not over a
  textarea, which is what `VENDOR.md` conceded: "a caret one line off is worse than no
  caret". They are worth having and they are not one of the seven asks. If S8 ever happens,
  they are the first thing to add on top of it.
- **Markdown syntax highlighting.** It is `mode-markdown.js`, 75,276 B, not on the list, the
  only Ace file that fails the font regex, and the only one carrying four dormant
  worker-spawning sub-modes.
- **In-editor find and replace.** The browser's own find already works on a textarea and on
  the preview, and this is the feature that makes an "override browser keymap" escape hatch
  necessary — it takes a key away to give back a worse version of what it did. The repo also
  already has cross-document search.
- **KaTeX/MathJax, mermaid and the other eight diagram languages, and every `{%embed%}`.**
  KaTeX is ~270 KB plus a font family inlined into every page; mermaid alone is larger than
  every currently vendored asset combined; PlantUML round-trips to a server that
  `test_no_page_reaches_the_network` forbids. A pitch that needs a diagram pastes an image,
  which already works.
- **Emoji shortcodes and a picker.** The shortcode changes the meaning of every `:` in prose
  full of `key: value`.
- **The table-cell toolbar and Tab-between-cells.** A spreadsheet grafted onto a text
  editor, and it eats Tab, which collides with ask 5 — CodiMD had to ship an off-switch for
  exactly that.
- **Click-to-tick a checkbox in the preview.** It writes to the source from the rendered
  pane, which fights compare-and-swap.
- **Inline comments and resolved threads.** They would be the first piece of plan state that
  is not a file, with a second store, a second permission model and a second notification
  path — while the review channel this team uses is the PR, which every pitch already names
  in `prs:`.
- **Revision history with diffs.** The most on-brand neighbouring feature — this application
  is git-backed and already has a better history than HackMD's and shows none of it. It is a
  `store.py` function and a page, and it is not the editor.
- **A `[TOC]` directive, `> [name=…]` blockquote tags, footnotes, `:::` containers.** All are
  cheap server-side plugins and all are guesses until S0 runs. They join S1 if the counts
  justify them.
- **An outline panel over the rendered headings.** ~30 lines and genuinely useful, but the
  gutter answers "where am I" for ask 4 and this is not on the list. Add it after S3 if
  anybody misses it.
- **Server-side autosave.** An interval that POSTs to `/api/entity` turns one shaping session
  into fifty commits and destroys "one Save is one commit, authored by whoever typed the
  most". See open question 6.

🤖 Written by an agent on behalf of @jcanton
