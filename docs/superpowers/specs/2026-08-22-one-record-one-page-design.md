# One record, one page

Three changes that are one change: every record in the plan becomes the same kind of thing, gets
the same page, and is found in the same list.

jcanton, 2026-08-22: *"i'd like all entities to have the same editing page, it's just that some
entities have editable fields that the others don't"* — and, on the landing page, *"just a list of
all entities with the usual search box ... sorted by last edited, something like it's done in
hackmd"*.

The tool has three record families today and two of them are second-class. An issue and a note are
written on hand-built pages that were forked from the entity page and have drifted ever since: no
draft store, no conflict box, no co-editing, no delete, a Cancel that means something else, and —
since #67 landed a week ago — a status hill on the note page and a plain `<select>` on the issue
page. That drift is not a series of oversights. It is what two copies of a surface do, and there is
no version of "keep them in step by being careful" that has ever worked here.

## What was considered and rejected

**Shared partials, three templates.** Extract the common regions, leave `_ISSUE`, `_NOTE` and
`_DETAIL` in place. Cheapest, and #67 already ran the experiment: the note got the hill and the
issue did not, in the same commit, by the same author. Rejected.

**A page-level merge with the model left alone** — one template, `Issue` and `Note` still standalone
`BaseModel`s off the index. This was the first design and jcanton rejected it: *"everything is an
entity, it's just that notes and issues are a bit more special and excluded from the PM places,
simplifies more, doesn't it"*. It does, and the reason is `Rung`.

## Why the model change is the cheap one

`Rung` (`model.py:965`) already exists and already carries "everything that is true of one kind and
not of its neighbours" — its id prefix, its directory, its model class, what it may be filed under,
whether the scheduler dates it, whether it may depend, whether it may be sized, whether it cards.
The ladder was made data because adding `product` "had to go and find in twelve places" what a kind
is. An issue is a kind. A note is a kind. They have been a fifth and sixth rung all along, written
out longhand somewhere else.

Two facts make this nearly free:

- **`kind` already falls back to the id prefix** (`model.py:1088-1090`), and the corpus ids are
  already `issue-778899`, `note-11aa22`. No file changes, no backfill, no `kind:` key stamped into
  a file that had none — and nothing stamps one, because no production writer calls `serialise`,
  only `patch_text`.
- **`product` already proves the shape of a kind that reads almost nothing.** `schedules=False`
  strips the nine work fields through `unread_fields` (`model.py:1009`). An issue is a product-shaped
  rung with a different vocabulary.

## 1. The model change

`Rung` gains two fields:

```python
planned: bool                 # does this kind appear in the plan: table, graph, timeline, people, scheduler
statuses: tuple[str, ...]     # the status vocabulary this kind reads; () means status is not read
```

Six rungs. `product` keeps `statuses=()`, which preserves today's behaviour exactly — status is one
of the nine fields a product does not read. `project`, `pitch`, `task` take `STATUS_ORDER`. The two
new rungs:

```python
Rung("issue", "issue", "issues", Issue, under=(), schedules=False, depends=False,
     sized=False, carded=False, planned=False, statuses=ISSUE_STATUS),
Rung("note",  "note",  "notes",  Note,  under=(), schedules=False, depends=False,
     sized=False, carded=False, planned=False, statuses=NOTE_STATUS),
```

`Issue` and `Note` become `Entity` subclasses, keeping their own fields — `reported_by`,
`opened_on`, `pitched_into`; `written_by`, `written_on`, `became`. `Entity` gains
`state(entities) -> str` returning `self.status`; the two subclasses override it with the
precedence they already have (`model.py:195`, `319`). The subclass **is** the per-rung hook; no new
mechanism is invented for it, because `Rung.model` is already a class per kind.

### `status` moves gate

`unread_fields` is re-cut. `status` leaves `_WORK_FIELDS` and is gated by the vocabulary instead:

```python
if not rung.statuses:
    fields.append("status")
```

Everything else in `_WORK_FIELDS` stays gated by `schedules`. Product is unaffected — `statuses=()`
keeps status unread — and issue and note read a status without inheriting the eight fields that come
with being scheduled.

**This is not a tidy-up; without it the change cannot land.** `_vocabulary_problems`
(`model.py:1975`) validates every entity's status against `STATUS_ORDER`. The moment a note is an
entity, `thinking` and `dropped` are words nobody defined, and three seed files become **blockers** —
ungrandfatherable, because the grandfather clause turns on a schema version these files do not
carry. Reading the vocabulary off the rung fixes that, and closes the hole in the other direction at
the same time: `ISSUE_STATUS` is exactly `STATUS_ORDER` minus `shaping`, so `shaping` is silently
legal on an issue today and will not be after.

`issue_problems` and `note_problems` fold into `_problems_for` keyed per rung. Issues and notes
acquire `openproj check` coverage, which they have never had (`cli.py:94` never ran those rules).
The shelved exemption becomes structural — `rung.statuses and status == rung.statuses[-1]` — because
every ladder ends in its terminal state: `shelved`, `shelved`, `dropped`. A dropped note is exempt
exactly as a shelved pitch is, and `done` is not.

## 2. The exclusion

This is the load-bearing part, and it is where the first design was wrong.

`model.py:161-167` argues that making an issue a separate *type* is what keeps it off the table, the
graph, the people page and the timeline "by construction, rather than by an exclusion in each of
them that somebody later forgets". That argument is correct, and a design that answers it with "we
will add a filter to each of those pages" is the thing it warns against.

The first draft proposed `Index.plan` beside a superset `Index.entities`. That distributes
enforcement across sixty-odd read sites of the same type with no compiler behind it, and every one of
them fails **open**: forget to change one and an issue appears on the timeline.

**Invert it.**

- `Index.entities` **becomes plan-only**. `build_index` filters on `RUNG[e.kind].planned` once, in
  one comprehension. Every existing consumer is then correct with no edit at all, and a consumer
  that is forgotten fails closed — it sees fewer records, never more.
- The superset takes the **new** name: `Index.records: dict[str, Entity]`. Reaching for it is a
  deliberate, greppable act, and the word looks wrong in a function about the timeline.
- A `model_validator` on `Index` asserts that no unplanned kind is in `entities`. That is the
  by-construction guarantee, in one line, replacing the one the type system gives up.

Which collection each surface takes:

**`entities` (the plan)** — the table payload, the graph, the timeline, the people page, the cycle
and deck pages, facets, progress, the scheduler, the parent and `depends_on` completion pickers
(offering an issue there would write an edge the model forbids), `/api/index.json` and
`schedule --json`. The last two matter: the external contracts are unchanged **by construction**
rather than by remembering to filter them.

**`records` (everything)** — the landing list and its search, the record page and its fact rows, the
detail 404 lookup, the hover card, the loop guard, the delete cascade, the people and tag suggestion
blobs, `validate_all`. The `blocked_by` and `blocks` maps stay total over `records` so a fact row
cannot `KeyError`.

The scheduler needs nothing: it already filters on `RUNG[e.kind].schedules`.

**The one test that makes a leak unshippable** is derived from `KINDS` rather than written out. For
every rung with `planned=False`: seed one record, then assert it is absent from `index.entities` and
from the rendered `/table`, `/graph`, `/timeline`, `/people`, the schedule payload,
`/api/index.json`, every facet value and the suggestions datalist; present on `/` and on its own
`/detail` page; and that a hand-built `Index` containing it is rejected by the validator. A seventh
unplanned rung is covered on the day it is added.

## 3. The record page

`_DETAIL` becomes the only record template. `_ISSUE`, `_NOTE` and `_NEW` are deleted, with
`render_issue`, `render_note` and `render_new`. Roughly 1,080 lines go and 400 come back.

**Absorbed from `_NEW`**: the creating mode — the kind picker, the template picker, and the
union-of-fields-with-the-other-kinds-hidden mechanic, which is already exactly the kind-switch the
merged page needs. `save()` gains a POST-vs-PATCH branch.

**Per kind, from data**:

- Fields flow through the pipeline that already exists: `EDITABLE ∩ type(entity).model_fields`,
  minus `unread_fields`. `EDITABLE` gains `reported_by` and `written_by` (text, person suggestions),
  and `pitched_into` and `became` (id lists rendered through `_links`, like `depends_on` — links,
  not bare ids, which is a gain over both pages today). `opened_on` and `written_on` are **derived
  rows, not editable**: the server sets them at creation and that stays true.
- The status control stops hardcoding the entity ladder. `_control_html` takes its ladder from a
  per-kind entry and a `live` flag; `_CONTROL` gains `disabled` and a hint slot. All four
  `ISSUE_STATUS` words already have hill stops, so the issue page gets the hill and the last of #67's
  asymmetry goes with it. The hand copy of `STATUS_ORDER` in `render.py` is retired.
- **The read display shows `state()`, not `status`.** Without this an issue whose pitch has shipped
  reads "ready" on its own page.
- The lock is expressed once: when `state() != status` the control is disabled and the hint says why
  — "from the work it was pitched into", "from what it became".
- The promote panel appears when the kind is promotable. Delete-with-cascade serves every kind
  unchanged; `cascade_of` is total and empty for a kind nothing may be filed under.

**What issues and notes gain, free, by arriving on the shared page**: the commitbar, the draft store
and its restore, the conflict box, co-editing, Cmd+S, and Delete. **Cancel changes meaning for them**,
deliberately: they adopt `_DETAIL`'s Cancel — the text stays in the box and the stored draft is
forgotten — instead of their own restore-the-body. The draft store is the body-undo now, and one
Cancel that means one thing beats two that mean two.

**The write path.** `POST /api/issue` and `POST /api/note` are deleted. `POST /api/entity` gains
per-kind server stamping — mint the id, set `reported_by`/`written_by` to the signed-in login, set
`opened_on`/`written_on` to today, set the opening status — from a small per-rung table.
`_reject_bad_issue` and `_reject_bad_note` are replaced by one generic gate that refuses any status
outside `RUNG[kind].statuses` before anything is committed. `ID_PATTERN` is derived from `KINDS`,
which incidentally repairs a drift already in the tree: `prod` is missing from it, so a product can
be created and then neither patched nor deleted.

## 4. The view machine

Today `showView` forces `showEditing(true)` — *"A view of the document is a way into editing it"* —
and takes the page full-page with the nav inert. So there is no way to look at a rendered document
without opening a session, and the landing state is a fourth, unnamed one.

**Three states, and the landing one is `view`.** `view` is sessionless: no full-page, nav live and
not inert, and the body is the server-rendered `.doc.read` that every page already carries and hides
under `.entity.editing`. `edit` and `both` are sessions and keep everything they do today. The
switcher becomes visible outside `.entity.editing` — it is the only door into a session — and is
withheld entirely when the reader cannot write, which makes preview the whole page for them instead
of today's editor whose every save would 403.

No `POST /api/preview` on landing. The server already rendered those bytes through the same
`_markdown`, and asking for them again would be a round trip to redraw what is on the screen.

Session end, Escape, pressing the pressed segment and the keyboard chord all retarget from the
vanished null state to `view`.

**localStorage** `EDITOR.mode` now stores only `edit` or `both` — "the mode a session opens in". A
stored legacy `view` migrates to `edit` on read, which retires an ambiguity that would otherwise be
real: the same stored word meant a session mode yesterday and a sessionless state today.

**URL flags**: `?view` becomes a sessionless read link and no longer opens a session; `?edit` and
`?both` are unchanged.

### The seat rule fixes a bug that is already here

`connect()` runs at script load. So a signed-in person who merely *opens* a record takes a
co-editing seat, is listed to everyone else as "also editing", and holds a Room, a watch and an
outbox task per record they visited, lingering after they leave. The landing list, which is a page
whose whole purpose is opening records, would have multiplied that.

`connect()` moves to session start and disconnects at session end. The deferral is safe: the
draft-versus-room arbitration keys off `ORIGINAL_BODY` rather than the socket, non-writers are
already refused at the handshake, and non-members already learn of moves from the events banner.
Pinned by test: **a reader holds no seat, appears in no presence list, and never delays the
last-person-out commit.**

### The draft rule, which is the one exception

The stored-draft restore stays at page load and **keeps forcing a session**. This is the single
place where landing does not mean sessionless, and it is not a compromise — deferring the restore
to the Write press splices the draft in after binding, so it leaves as ordinary typing and bypasses
the refusal that exists to stop a draft silently overwriting a room that moved on. That is the exact
class of defect this branch has shipped three times.

The two changes compose in the right order: restore before connect, so the surface holds the draft
before the room is joined.

And the landing pane always renders the **stored commit**, never the live surface. Cancel
deliberately leaves draft text in the box; a pane built from that would show uncommitted text as
though it were the record.

### The export gets simpler

`render_static` passes no base commit, so it is already editable-false: no view machine, no
co-editing, no form. The export has been rendering the sessionless landing state all along. The
served page converges on the exported page's shape rather than the other way round, and every new
preview branch stays inside `if editable`.

## 5. The landing list

One row per record in `index.records`: kind badge, title linking to `/detail/{id}`, and one relative
last-edited time. Sorted last-edited descending. Nothing else — no owner, no status, no tags,
matching the count of what a HackMD card carries, which is four things.

**The date is relative when recent and absolute when not**, which is what the screenshot actually
does: `17 hours ago` through `10 days ago`, then `2026-05-26`. Past the threshold the relative form
is abandoned rather than extended; nobody is shown "2 years ago".

**The search box is the existing one.** `_facets_html` renders the query box, the error region and
the unfilter control unconditionally, which is precisely what `_FILTER_JS` requires — its listeners
are unguarded. Rows must carry `predicates: []`, because `matches()` dereferences it without a guard
and an omitted array plus a `?predicate=` in the URL is a blank page. The timeline already proves
`_FILTER_JS` runs over a payload that is not the table's.

The search blob for every kind comes from one shared helper, retiring the two narrower hand-built
ones on the issue and note list pages. Facets stay plan-only, so `kind:issue` never becomes a dead
facet on the table.

### Last edited comes from git

There is no such timestamp today: no field on any model, no working tree to stat — the store is a
bare repository and Cloud Run re-clones — and no revwalk anywhere in `src/`. A stamped frontmatter
field is rejected: it needs a backfill, it is derived data in a file, and it lies about every file
edited by hand and pushed, which the README calls first-class on purpose.

So: a history walk, on `Store`, beside `blobs()`. Revwalk from head, tree diffs with subtree
pruning, a path stamped by a commit when its blob differs from **all** parents — git-log semantics,
which matters because merges are routine here, not exceptional, and first-parent diffing would stamp
a side-branch edit with the merge's time. Stop when every path at head is settled.

**Measured**, on synthetic plans of 520 records:

| commits | walk |
|---|---|
| 500 | 257 ms |
| 2 000 | 937 ms |
| 8 000 | 898 ms |

The 8 000 figure is not a bound — an earlier draft of this spec claimed the cost was
coupon-collector and therefore capped, and that is wrong. A note is written once and never touched
again, so it forces the walk down to its own creation depth; the bound is history length. What the
numbers give is a slope, about 0.45–0.5 ms per commit, and at that slope a full walk stays near a
second at any size this plan will reach for years. It is logged at startup so the drift is visible
long before it hurts.

**Cache**: a second single-entry closure beside the index cache, `(commit, {path: epoch})`, keyed on
**commit alone** — the index cache is also keyed on today, and a midnight rebuild must not re-walk
history. Swapped atomically, because two dozen routes run on worker threads. The first walk runs
eagerly in `_serve` before uvicorn binds: the lifespan hook does nothing at startup, and this must
never ride a request.

**Advancing it**, and the four cases:

1. **Several commits at once** — walk `cached..head` newest-first, first touch wins, diffing against
   all parents. Never a single diff between the endpoints: that stamps every intermediate with head's
   time and misses an edit that was reverted inside the batch, because the blob matches at both ends.
2. **The cached commit is not an ancestor** — and this is *routine*, not a force-push story. The ref
   is published before the push, a lost race rewinds it, and the window is around 600 ms. Rule:
   discard and re-walk. Retract-by-rebuild is the whole correctness story, there is no retraction
   logic to get wrong, and it is affordable only because the walk is about a second. It is also what
   stops a doomed commit's "edited just now" from outliving the commit.
3. **A deleted path** — gone from the map; the walk settles only paths present at head.
4. **An added path, and a retry that lands as a merge** — stamped by the commit that carried it,
   which is correct.

The relative-time string is built outside `render.py` and `web.py` and passed in as a value: those
two files are AST-banned from every `.replace` attribute call, `datetime.replace` included.

**Four empty states, not three** — the table already distinguishes them and the landing must too: a
payload that did not load, a plan with no records at all, a query that cannot be read (which goes to
the error region, not to a row), and a search that matched nothing.

**Export**: the landing becomes `index.html`, the table `table.html`. `openproj render` can be
pointed at a plain directory with no git in it, so the rule is: walk when the directory is a
repository, and otherwise render the list **without the time column** — omitted, not blank, because
blank looks broken. Never file mtimes, which lie after a fresh clone.

### The nav word is Records

Not "Entities": it is untrue today, and it collides with the table's own empty-state copy. Not
"Recent": that names the sort, not the page. **Records** is this codebase's own superset word — the
record table, "this file is not a record" — it names a population where Table names a presentation,
and it is honest before the flip as well as after.

## 6. Routes

| Before | After |
|---|---|
| `GET /` → table | `GET /` → Records |
| — | `GET /table` → table |
| `GET /graph`, `/timeline`, `/people`, cycles, deck | unchanged |
| `GET /detail/{id}` — entities only | every kind |
| `GET /issue/{id}`, `/note/{id}` | redirect → `/detail/{id}` |
| `GET /issues`, `/notes` | redirect → `/` |
| `GET /new`, `/issue/new`, `/note/new` | `GET /new?kind=…`; old paths redirect |
| `POST /api/issue`, `/api/note` | deleted; `POST /api/entity` stamps per kind |
| `PATCH`/`DELETE /api/entity/{id}` — three kinds | all six, pattern derived from `KINDS` |
| `POST /api/preview`, `/api/index.json`, `/api/events` | unchanged |
| login/logout → `/` | unchanged; now lands on Records |

## 7. Tests

**Rewritten**: the issue and note page tests become the exclusion sweep; the table tests repoint at
`/table` and about 125 of them survive verbatim; the editor's view/session pins move to three states;
the search tests split — table parity over `entities`, the new landing twin over `records`; the
injection census re-registers the changed page set; the nav map; the render `PAGES` list.

**Added**, each named by the defect it catches:

1. The `KINDS`-derived exclusion sweep — a PM view, or a future unplanned rung, reading `records`.
2. Index purity — a `build_index` regression admitting an unplanned kind to `entities`.
3. Seed-check pin: `openproj check` over `seed/` produces an identical problem list before and after
   the rungs land — the `unread_fields` re-cut silently changing validation.
4. Write-path vocabulary 422 — the loss of the two bespoke gates on the generic path.
5. A reader holds no seat — `connect()` creeping back to load time.
6. `?view` is sessionless and `?both` opens a session — either half of the re-cut regressing.
7. After Cancel with a divergent draft, the landing shows the stored commit — a pane wired to the
   live surface.
8. A draft at load forces a session and the room-collision refusal still fires — restore deferred
   past binding.
9. An issue whose pitch is done reads its derived state, with a locked hill and the hint.
10. A created issue carries a minted id, `reported_by` and `opened_on` — the lost route defaults.
11. Non-ancestor cache rebuild: rewind the ref the way a lost race does, assert the map is discarded
    and rebuilt with no phantom "edited just now".
12. A side-branch edit merged in carries the side commit's time — first-parent diffing.
13. An edit reverted inside one fetch batch is stamped correctly — the endpoint-diff shortcut.
14. **Census completeness**: every GET route in `app.routes` appears in the injection census. This
    converts a hand-maintained list that fails open into one that fails closed, permanently.
15. Landing search parity with issue and note needles, and a non-ASCII title — blob drift between
    the shared helper and its JS twin.
16. Hostile but well-formed issue and note ids in the injection corpus. They are deliberately
    malformed today because those routes "never render". They render now.

## 8. Risks

1. **New code choosing `records` in a PM context.** The inversion makes existing code safe, not
   future code. Caught by the sweep, the validator, and the word being greppable in review.
2. **The injection census fails open.** Land test 14 in the same commit that moves the table, or
   `/table` leaves the census green and empty-handed.
3. **Last-edited wrongness under a write race.** Retract-by-rebuild plus tests 11–13. The residual
   window is a transiently wrong time between a doomed publish and the next head change, and it
   self-heals.
4. **`unread_fields` ripple** breaking the agreement between the form and the validator — the "a form
   offering a box the validator then complains about" failure. Caught by test 3 and the editor pins.
5. **View-machine regressions**: an empty full-page grid if `edit` ever lands sessionless, an
   invisible switcher, Cancel re-entering a session. Caught by the browser pins and screenshots.
6. **The widened write surface** accepting something the bespoke routes refused. Caught by test 4 and
   the hostile ids.

## 9. Build order

Nine commits. Each leaves the suite green.

1. `Rung` gains `planned` and `statuses`; `unread_fields` re-cut; per-rung vocabulary; `Entity.state`.
   Four rungs only — behaviour identical. The seed-check pin lands here.
2. **The inversion**: `entities` filtered on `planned`, `records` added, the validator, search blobs
   over `records`. With only planned kinds existing the two are equal, so this is green by
   construction; the sweep lands here and is armed for commit 8.
3. Editor pipeline: ladder, lock and hint through `_control_html`/`_CONTROL`; the issue hill; `state()`
   in the fact rows; the new `EDITABLE` entries, inert until the subclasses exist.
4. `web.py` derivations: `ID_PATTERN` from `KINDS` (products become writable — its own reviewable
   change), the generic status gate.
5. **The view machine** — goal 2 entire, independent of goal 1.
6. Absorb `_NEW` into `_DETAIL`; `/new?kind=…`.
7. **The landing** — the walk, the cache, the eager first walk, `/` and `/table`, the nav, the export,
   census completeness. It shows plan records until commit 8, which is exactly right.
8. **The flip, atomic.** The two rungs, the subclasses, and the deletion of every parallel reader in
   one commit — the `_ENTITY_DIRS` change makes the new readers live the moment it lands, so a split
   would double-read. Issues and notes appear on the landing here.
9. Cleanup: `_RECORD_STYLE`, the comment rewrites, the dead status copy.

Commits 1–4 are invisible. 5 and 7 are each shippable on their own. 8 is the one that cannot be
split, and everything before it exists to make it small.

🤖 Written by an agent on behalf of @jcanton
