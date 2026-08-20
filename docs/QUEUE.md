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

## What was tried and dropped

* **A `<select>` converted into a button-and-menu, four more times.** The table's
  filter dropdowns are buttons because a native `<select>` cannot draw the caret
  and the ground this page wants. The timeline's zoom and the issues and notes
  state filters were offered the same conversion and did not get it — jcanton,
  2026-08-20: give them the border, the ground and the radius and keep the
  browser's caret. One rule against four popups with their own keyboard handling
  and their own tests, for a control with one choice in it.

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

* **The review deck**, awaiting jcanton's feedback after a proper read.
* **A write can still create a loop.** jcanton asked, 2026-08-19: "doesn't
  openproj forbid cycles? if not we should". Today it detects them — `validate_all`
  reports a parent cycle and a blocked-by cycle as blockers, through
  `_cyclic_members` — but nothing stops a PATCH of `parent` or `depends_on` from
  closing one, and the blocker then lands after the commit, on a protected branch.
  The shape of the fix is a `loop_made(candidate, plan)` in `model.py` asking that
  same `_cyclic_members` with this record's proposed edges substituted, called from
  `save()` and `create()` in `web.py` — so a refusal and a report cannot disagree.
  Detecting rather than refusing is right for a plan that *arrives* with a loop: a
  file in git is a fact, and refusing to load it takes every page down over
  somebody else's mistake. That is the distinction the fix has to keep.
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
"'Which entity is #1364?' is a question people ask in front of a screen", which
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
cycles selected means either, because an entity has one cycle and "both" is empty
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

## What is deliberately not here

A `support` field (reviewers carry it), a `from_note` field on `Entity` (the
provenance is prose in the shaping document, so a note id never enters the type
every view is built from), HackMD as a backend (tested and refused: a PATCH
disconnects every live editor, `lastChangedAt` does not move while somebody
types, 400 API requests a month), and a fourth entity kind for brainstorming
(that is what a note is).
