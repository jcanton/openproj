# What is designed and not built

Written 2026-08-19. Everything here was settled in conversation with jcanton and
has no code. The reasoning is kept because the decision is the expensive half.

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

## 6. Smaller, and still owed

- **Drag-to-reparent in the graph.** Costed already: the predicate and the
  refusal are reusable, but cytoscape's own drag already means "move the node",
  so the gesture needs a modifier, a handle extension (a vendored library) or a
  mode toggle — and the canvas has no bottom edge that means "outside the tree",
  so unparenting needs a real drop zone.
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
