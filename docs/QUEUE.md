# What is designed and not built

Written 2026-08-19, and mostly emptied the same day. Everything here was settled
in conversation with jcanton; the reasoning is kept because the decision is the
expensive half.

## What has been built since

| Item | Where |
|---|---|
| 1. One searchable text, and a query language over it | #16 |
| 2. Multi-select in the dropdowns | #17 |
| 3. One hover card, three views | #18 |
| 5. A reader is not offered a socket | #19 |
| 6. Drag-to-reparent in the graph | #20, and taken out again — see below |
| 4. `v0.3.0`, tagged and released | #21, `v0.3.0` |

`v0.3.0` is deployed: revision `openproj-00006-bdv`, and the console lines that
opened item 5 are gone from the served page. The sections below are what is left,
and each says why it is still here.

* **The table's cells are read-only to a reader.** Owed here from 2026-08-24 —
  found while gating the create buttons and left alone in that commit on
  purpose — and built on the `reader-table` branch the same day. `render_table`
  set `editable = base_commit is not None`, "there is a server behind this
  page" standing in for "this person may write", so a signed-out visitor could
  double-click a cell, type, press Enter and collect a 403; `role="grid"`, the
  combobox and the draft row's `+` were all offered to them.

  This entry predicted `editable` would have to SPLIT rather than narrow,
  because the reader still sorts, filters, searches and follows links. Measured
  against the template, it narrows: sorting (the `<thead>` buttons and
  `draw()`), `_FILTER_JS`, the hover card and the row links in `rowHtml` all
  live outside the `{% if not editable %}` branch — the rendered-file export
  has been exercising exactly that read-only half since it existed — and
  everything inside the branch is write machinery (`refreshProblems` and
  `refreshRows` are reached only from save paths). `creatable` then named the
  identical expression and was deleted with it. `may_write` defaults False,
  `render_detail`'s precedent; the test call sites that expect an editable grid
  say `may_write=True` now, and a new test drives the reader's served page —
  no grid claim, no gate panel, no combobox, no adder row, and it still sorts,
  filters and links.

* **Drawings, in a popup over the editor.** Designed 2026-08-26 and built on the
  `drawings` branch the same cycle, written up in full at `docs/drawings.md` —
  read that rather than a summary here, because the rejected shapes carry the
  reasoning and one of them corrupts files. Excalidraw, vendored as our own
  single-file build and fetched on the first press of a button in the
  `.editbar`, opens in a popup over the editor. A drawing is a PNG exported with
  `exportEmbedScene`, so the file is both the picture and its own editable
  scene; it lives at a stable path, `drawings/draw-a1b2c3.png`, and an embed is
  ordinary image markdown that GitHub renders. Content-addressed `assets/` was
  the nearly-free shape and was refused because it would have raced the record
  editor's own save through the merge ladder on every drawing save;
  `Store.put_drawing` never decodes the bytes, because the store's own line
  merge corrupts a PNG silently and answers 200 while doing it.

## What was tried and dropped

* **A `<select>` converted into a button-and-menu, four more times.** The table's
  filter dropdowns are buttons because a native `<select>` cannot draw the caret
  and the ground this page wants. The timeline's zoom and the issues and notes
  state filters were offered the same conversion and did not get it — jcanton,
  2026-08-20: give them the border, the ground and the radius and keep the
  browser's caret. One rule against four popups with their own keyboard handling
  and their own tests, for a control with one choice in it.

* **Boxing the id strings in the table.** Offered by jcanton himself as the
  alternative when the kind chips came out of the id cell, and not taken: a box
  around all seventeen ids is the same noise wearing a different hat. The id is
  already monospace, and that is what marks it as a token to be cited; the kind
  is already the id's prefix, which the data model guarantees agrees with `kind`.
  Kind stays filterable in the KIND facet, which is where "show me only tasks" is
  actually asked.

* **Drag-to-reparent on the graph** (#20). Built, and removed the same day after
  jcanton used it: a pitch could not be dropped into a project at all, and taking
  one out looked like nothing happening — the project's outline follows the pitch
  being dragged, so the boundary travels with it and the drop only appears to
  have worked after the page reloads and the pitch is suddenly outside. The hit
  test was right and the drawing was not, and a gesture whose result you cannot
  see until it commits is not one to keep. Reparenting stays where it works: the
  table, by dragging a row onto another.
* **Single-click to edit a cell.** Dropped, not deferred — jcanton, 2026-08-19.
  A single click focuses the cell for the arrow grid, and cells are drag sources
  and drop targets. Enter and F2 open an editor.

## What is still owed

* **The drawing popup may still vanish for a second reason, and it has not been
  found.** jcanton reported it on 2026-08-26 as "sometimes the excalidraw editor
  seems to crash and close without warning". One cause was found and fixed the
  same day — the popup's own Escape closed a clean drawing silently, reproduced
  in headless Chrome, and `docs/drawings.md` has the whole account under "The
  popup, and what it asks before it closes". But jcanton then said he thinks he
  has seen it "even after drawing a couple of lines and without pressing
  escape", which the Escape fix does not explain: with strokes on the canvas
  `isDirty` is true, so that path raises the question rather than closing.

  What was ruled out, all measured in headless Chrome on the day: no console
  error and no CSP violation through a normal session; text, every font family
  in the picker, and the library panel all leave the popup alive; the
  `"Liberation Sans": error` in `document.fonts` is the dropped face's sentinel
  and is silent. What was NOT ruled out, and is where to look next: the popup
  also tears itself down on a failed bundle fetch, an unreadable PNG, a
  non-2xx on the drawing, and a scene that will not parse — each with a
  sentence, but only in the small status strip above the editor, which is easy
  to miss when the thing you were looking at was a full-screen editor. If it
  is one of those, the fix is to say it where the popup was rather than to stop
  closing. Left open at jcanton's word — "let's leave it for now I'll come back
  to you if I see it happen again" — so this entry exists to make sure the
  ruled-out list is not re-derived from scratch.

* **Inserting a raster image into a drawing is blocked, on purpose, by the same
  policy that blocks everything else it forbids.** pica and image-blob-reduce,
  which Excalidraw's own image tool uses to resize a pasted photo, each
  construct a Worker to do it — one from a `data:text/javascript;base64` URI to
  probe `createImageBitmap`, one from a `blob:` URI to resize — and the policy
  is `default-src 'none'` with no `worker-src` and no `blob:` anywhere in it.
  Rather than offer the tool and have it fail silently the first time somebody
  reaches for it, the mounted editor hides it (`UIOptions.tools.image = false`).
  jcanton accepted the gap on 2026-08-26; see `docs/drawings.md`, "The spike,
  which came first."

* **A record's page and a slide's page disagree about what a signed-out reader
  is given.** `render_detail` gates `editable` on `base_commit is not None`
  alone, so a reader of a record still gets a textarea, a toolbar and
  `attachEditing` wired to it — no Ace (that gate also checks `may_write`), no
  socket, no save, but a box that looks live and is not. `render_slide_editor`
  gates `editable` on `base_commit and may_write` together, so a reader of a
  slide gets no surface at all. Pre-existing on both pages, not introduced by
  the drawings work, and nobody has decided which of the two the other should
  match.

* **A save should not wait for GitHub.** Designed 2026-08-24, written up in full at
  `docs/deferred-push.md` — read that rather than a summary here, because the
  reasoning is the expensive half and the rejected shapes matter as much as the
  chosen one.

  The short version: a save is 1.45-2.04s on the deployed service and this
  application's own work in it is 8-12ms. The rest is GitHub's receive-pack, which
  is not ours to make faster — so the request stops waiting for it. The commit is
  still made under the lock exactly as today; a background pusher lands it; the
  table carries a quiet per-row mark until it does.

  The hard part is not the deferral, it is that `_attempt`'s rejection recovery
  rewinds `refs/heads/main` to a sha captured before its own commit, which is only
  sound while the lock is held across commit AND push. Three recoveries were
  designed and each was attacked; rebase-by-recommit won. It ships in four pieces
  and two of them are bugs that exist today: `deploy/boot.py` never receives
  SIGTERM in production, and `_merge_body` merges two same-text edits wrongly.

* **A container's progress rollup charges its container children half a week.**
  Found on 2026-08-23, the day the fixture corpus grew products, and unreachable
  before that: `Rung.under` lets nothing but a product nest a container, so a
  container could not be somebody's CHILD until one existed.

  `_progress_of` (`index.py`) weighs every child with `size_weeks`, which
  documents itself as *"none on a project — a container has no size of its own"*
  and then returns `config.default_task_effort` anyway, because that fallback was
  written for an unsized TASK. So a product holding a project that rolls up to
  5.0 weeks reports `done=0.0, total=0.5`, drawn on the record page as
  **"Progress 0/0.5 wk"** with a meter reading *"0 per cent of this bet is
  done"*. `prod-6d1a70` says 0.5 where its child rolls up to 1.0. The number in
  the denominator is one nobody typed.

  It contradicts `Progress`'s own docstring — *"as far along as its tasks are,
  weighted by their sizes — half a bet is half its weeks"* — and
  `_rollup_problems` already guards the same hole from the other side with
  `if not kids or defaulted: return`. It reaches the table row's fraction too,
  and anywhere else `index.progress` is read.

  **Written down rather than fixed because the fix needs a decision this does not
  contain.** Weighing a container child by its own rolled-up TOTAL is obvious and
  needs a post-order pass — the loop that builds `progress` visits records in
  `plan` order and a child's rollup may not exist yet. What is not obvious is the
  numerator: a container has no `status: done` of its own worth trusting, so
  either its DONE weeks roll up the same way (a product is 40% done because its
  projects are), or a container child counts in the denominator and never in the
  numerator until every descendant is done. The first is what the docstring
  implies. The second is what `status == "done"` does today for leaves.
  `Rung.sized` is the ladder property that tells the two cases apart, so whichever
  is chosen should be read off it rather than tested for by kind.


* **A chip that overflows into the next column.** jcanton, 2026-08-20, with a
  screenshot of a narrowed window: the status chip runs straight through the
  Owner column — `» IN PROGRESSjcanton` — instead of wrapping or being cut.

  Half-diagnosed already, so start here rather than from the screenshot. `.chip`
  is `white-space: nowrap` (render.py, near the status tints), which is right:
  "IN PROGRESS" broken across two lines is not a chip. What is missing is that
  the cell has nowhere to put the overflow. `CLAMPED` is `tags, prs, assignees,
  reviewers` and `SQUEEZABLE` is `title, owner`; `status` is in neither, so the
  fit hands it a width and nothing clips what does not fit. Priority is in
  neither either and gets away with it only because it is plain text, which wraps
  — which is why the same screenshot shows `Medi um` on two lines. Both are the
  same defect wearing different clothes.

  **DECIDED — jcanton, 2026-08-20: drop to the mark and hide the word.** Below a
  threshold the chip keeps its glyph and loses its text, and the priority cell
  keeps its bars and loses "Medium". Not an ellipsis, and not a column that stops
  shedding.

  It is what the rest of the app already does rather than a fourth idea: the
  timeline draws a status glyph inside a bar and drops it below `_GLYPH_MIN_PX`
  when the bar is too narrow to hold it, and the graph's legend already teaches
  `»` / `✓` / `?` and the five bars. So the narrow column falls back to a notation
  the reader has already been taught, instead of to a word cut in half.

  The two rejected, with why, so nobody re-opens them:

  * *Clip with an ellipsis* — cheapest, and leaves `IN PROG…`. Legible, but it
    teaches nothing and looks like a defect rather than a decision.
  * *Make `status` squeezable* so the fit takes the room from `title` instead —
    wrong way round. The title is the column somebody is actually reading.

  Both columns at once. Priority is drawn with the bars now, and `Medi um`
  wrapped under them is the same bug wearing different clothes — it went
  unreported only because a wrap looks less broken than an overflow.

* **Co-editing under Cloud Run's five-minute timeout.** Proven locally and never
  against the deployment, where `--timeout 300` closes every socket at five
  minutes and reconnection stops being exceptional. The deploy is done; the test
  needs two signed-in members, and signing in is not something an agent does.
* **Group-level ordering the layout does not guarantee.** ELK's recursive engine
  lays each box out over its own children and then lays the boxes out — and the
  root pass cannot reliably see a dependency between the CHILDREN of two boxes.
  Measured on a three-box synthetic where each box also holds an internal chain:
  all three stacked at the same x with both cross-box arrows drawn backwards. The
  real plan is immune by accident — its two project-to-project dependencies are
  root-level edges that carry the order — and the synthetic plans from
  `tests/plans.py` show 5 backwards of 76 at 208 records and 24 of 189 at 518.

  The fix the audit costed at twelve lines: before each layout, add invisible
  "ghost" edges between the top-level ancestors of every cross-group dependency,
  and remove them on `layoutstop`. Style them `opacity: 0` and `events: no` —
  never `display: none`, which drops them out of `:visible` and out of the
  layout.

  It is written down rather than built because its whole risk is leakage. A ghost
  that survives one `layoutstop` makes two unrelated projects neighbours in
  `applyFilter`'s `neighborhood()`, becomes tappable in edit mode, is walked by
  the cycle check, and would be sent to the server by Save. That is a lot of
  surface for an ordering nobody has complained about yet.
  `test_the_arrows_read_the_way_the_layout_was_asked_for` is the canary: if it
  fails on a corpus nobody touched, this is the entry to read.

* **Re-betting as a record of its own.** Deferred 2026-08-16, and the symptom is
  already visible: a standing item like `[GT4Py] Development work` is bet again
  every cycle, and because `cycle:` records where the bet was first made and is
  never re-stamped, it reads as a permanent overrun. The fix is not to re-stamp
  `cycle:` — that is the one thing `docs/data-model.md` forbids — it is a second
  record of the later bet.
* **The review deck**, awaiting jcanton's feedback after a proper read.
* **The editor.** Handed to a session of its own on 2026-08-19; the decisions,
  the library shortlist and the list of what must not be lost are in
  `docs/EDITOR.md`.

The rest of this file is the reasoning behind what was built, kept because the
next person to touch any of it will want to know why it is shaped this way.

## 1. The search box learns logic, and the two halves agree

**Do this one first, and its first commit is a bug fix.** The browser and the
server do not search the same thing:

```python
# server (index.py)   title + tags + prs + body
# browser (render.py) row.title + ' ' + row.tags.join(' ')
```

The table filters in the browser, so a word that appears in a shaping document
finds nothing in the UI while the same query through `apply_filters` matches it.
Searching a PR number has the same hole — and `index.py`'s own comment says
"'Which record is #1364?' is a question people ask in front of a screen", which
is exactly where it does not work.

So: one definition of the searchable text, built once and travelling with the
rows, plus a test that both sides agree — the shape of
`test_empty_is_spelled_the_same_on_both_sides_of_the_wire`. That is now the third
time this class of divergence has been found, after the `(none)` sentinel and the
search blob itself.

**Fields only, not bodies** — jcanton, 2026-08-19. So the searchable text is the
record's fields, and the shaping document is not swept into it. That makes the
divergence above a smaller fix than it first looked: the two sides have to agree
on a field list rather than on a blob, and searching a 900-word body for a
substring stops being something either side does.

Then the syntax on top: `field:value`, `and` / `or` / `not`, parentheses, bare
words across the fields. `tag:gpu and tag:distributed` is the query
the dropdowns cannot express, because a menu means OR within a field.

Three rules it must keep. The query lives in the URL, because a filtered view
here is a link. It is evaluated identically in both places. And a malformed query
**says so and matches nothing** — the existing rule is that an unknown field
matches nothing rather than everything, since a typo that silently widens a
result set is worse than one that visibly empties it.

## 2. Multi-select in the dropdowns

Exposes what `apply_filters` already does — AND across fields, OR within one. Two
cycles selected means either, because a record has one cycle and "both" is empty
by construction. For list fields (`tags`, `assignees`, `reviewers`) "both" is
meaningful and is what the query language above is for; the menus stay OR.

## 3. One hover card, three views

The timeline has one and it is good. The graph should have it, because a node
carries less information than anything else on screen — a title and a status
glyph. And the **table** should have it on the title, because the body is the one
field a row does not show, and in this tool the shaping document IS the record.

**One component, not three.** This codebase has been bitten by one fact formatted
two ways (`appetite_weeks` reading as three different numbers across three
pages), so the card is one function all three call.

The decision it forces: **where the body comes from.** Inlining every body into
the table's payload puts the whole corpus in every page load. So on the server the
card fetches on hover; in the static export there is no server, the card degrades,
and the title stays what it already is — a link into `detail.html#id`, where the
whole document is. Same shape as co-editing falling back to a plain textarea.

Larger and scrollable, with a max height so a 900-word pitch does not cover the
table. The graph is pannable and zoomable, so the card must survive a node moving
under it.

## 4. Tags and the version story

`v0.3.0` was agreed and not cut: bump `pyproject.toml` and `__init__.py` (which
disagree with each other and with the newest tag), `uv lock` — CI runs
`--locked`, so a bump without it goes red — tag `main`, and cut the first GitHub
release from the ~130 commits since `v0.2.0`. Then a line in `AGENTS.md` next to
the commit rules: **tag when you deploy**, so the running revision has a name
instead of a sha. 1.0.0 after adoption, per jcanton.

## 5. A reader should not open a socket they may not write through

Found from jcanton's console on the deployed service, 2026-08-19. Signed out, a
detail page tries `wss://…/api/coedit/<id>` five times and gets
`NS_ERROR_WEBSOCKET_CONNECTION_REFUSED` each time — the server correctly refusing
a socket to somebody who may not write. It is self-limiting (`if (!arrived &&
attempts >= 4) return stop('')`) and the comment there already names "a reader
who may not write" as one of the three causes, so nothing loops.

But reads are public here, so *most* page loads are readers, and every one of
them gets five red lines in a console for a page that is working exactly as
designed — which is how a real error comes to be ignored. The page already knows:
the shell fetches `/api/me` to draw the corner, and drew "Sign in". So `COEDIT`
should wait for that answer and connect only when it says `login` and `member`.
The awkward part is that the fetch lives in the shell and the editor is on the
detail page, so the shell has to publish it rather than the editor asking twice.

**And `/api/me` is the wrong question to gate on** — found 2026-08-19 while
verifying #14 against `openproj demo`. `/api/me` answers `viewer(request)`, which
reads the session cookie and nothing else. Under `--auth dev` — every `openproj
demo`, and `serve --auth dev` — there is no session, so `/api/me` answers
`{"org": …}` with no login and the corner draws "Sign in", while `writer()`
invents `User(login=dev_login, member=True)` and the write goes through
(`web.py`). That is why the demo says "Sign in" in the corner and creates rows
happily.

So a gate on `login` and `member` would refuse the socket in exactly the mode the
tool is tried in, and co-editing would be broken for everybody running the demo
while every test stayed green — the tests sign a cookie. The page has to be told
what `writer()` would answer rather than what `viewer()` does: either `/api/me`
gains the field the *write* path decides (`may_write`, answered by the same
function the write path calls, not by a second copy of the rule), or the shell
publishes what the server already put in the page to decide whether to draw the
editor at all. The second is smaller and it is already right by construction:
`EDITABLE` on the table and the editor on the detail page are drawn from the
server's own answer, on the server, per request.

## 6. Smaller, and still owed

- **Drag-to-reparent in the graph.** *Built in #20, as the mode toggle.* The
  costing was right about the gesture and wrong about the drop zone: the canvas
  needed no zone, it needed the boxes measured as they were when the drag
  started. A compound node's box follows the child being dragged, so until that
  changed there was no point on the canvas that meant "outside".
- **Single-click to edit a cell.** Asked about; deferred with an argument rather
  than refused. A single click currently focuses the cell for the arrow grid, and
  cells are drag sources and drop targets, so click-to-edit would open a box
  during navigation and during a drag. Enter and F2 already open one.
- **The review deck**, awaiting jcanton's feedback after a proper read.
- **Co-editing on Cloud Run.** Proven locally and never against the deployment,
  where `--timeout 300` closes every socket at five minutes and reconnection
  stops being exceptional.

## 7. Done: from jcanton's screenshots on 2026-08-20

Numbered in the order they were asked for. 1–6 landed in `polish3` and the second
round — the legend, the priority mark, the leaning edges on the real plan, a
product's status and PRs, and the progress column's units — in `polish4`.

1. **A narrow Priority column adds newlines where Status does not.** Status drops
   to its glyph and hides the word (built in #49); Priority keeps the word and
   wraps it a letter at a time. The same treatment, and the same chip: Priority
   should read as a card like Status does, not as bare bars beside text.
2. **The priority bars are tofu in the dropdowns.** The menu font has no glyph
   for the block characters, so the select shows boxes of different heights while
   the table shows real bars. Decide one of: a vendored icon font (which is a new
   vendored asset with a licence and a checksum), inline SVG everywhere a
   priority is drawn, or the same tofu everywhere so at least it is consistent.
   Inline SVG is the only one of the three with no new dependency.
3. **The graph edges are wrong again.** The screenshot shows long diagonal
   zig-zags across the canvas rather than the orthogonal routes the router draws.
   `test_graph_layout` reports zero overlaps and zero foreign-card crossings, so
   whatever this is, the probe does not see it — the first job is a probe that
   fails on the screenshot before anything is changed.
4. **A node's priority bars do not line up with its status glyph or its title**,
   and in the legend the bars are drawn under the swatch border, so `very_high`
   is the one that cannot be read.
5. **The legend is not vertically aligned, and the priority swatches are wider
   than the status ones.** Third time this has been reported; whatever is done
   here should be a measurement in a test, not an eye.
6. **Saving a body leaves the stale text on screen.** Edit the body of a record,
   save, the editor closes and the *old* text is shown until a refresh. The save
   itself lands. So the view is rendering from something the save did not update.

### What the second round settled

3 above was reported again against jcanton's own plan, and the seed corpus never
showed it: a `segments` edge is drawn from a node's CENTRE, and a compound's
centre is nowhere near the side its route leaves from. The probe could not see it
either — it read the path centre to centre and exempted the two ends, and no
generated plan had a dependency between two boxes to exempt. Both are fixed, and
`tests/plans.py` now writes box-to-box edges over boxes of unequal height.

2 was settled the third way round: not five elements, not nothing in menus, but
one character whose height is the rung, in the rung's colour. The vendored face
has none of the block elements, so the platform's fallback draws them — the cost
was weighed against three alignment problems that had each been fixed twice.

## 8. Themes — built, awaiting a look

Its own branch and its own PR, **not merged and not deployed**: jcanton wants to
see it locally first. Nine base16 families, each a light and a dark, in a picker
between the sign-in corner and the light/dark switch. See "Colour" in
`docs/architecture.md` for how sixteen colours become fifty-five.

To look at it: `git checkout themes && uv run openproj serve --plan <plan>`.

## What is deliberately not here

A `support` field (reviewers carry it), a `from_note` field on `Record` (the
provenance is prose in the shaping document, so a note id never enters the type
every view is built from), HackMD as a backend (tested and refused: a PATCH
disconnects every live editor, `lastChangedAt` does not move while somebody
types, 400 API requests a month), a `hackmd:` field or any other link back to
where a document came from (content moves in and nothing links out, because a
link to the old system is how two sources of truth survive a migration), and a
record kind of its own for brainstorming (that is what a note is).
