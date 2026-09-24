# A plan says which views and kinds it has

jcanton, 2026-09-24, relaying a request for the `icon4py-plan` deployment: *remove all that isn't
cycles, graph and timeline.* And in the same message, the shape of the answer: *"Instead of deleting
code, can we make the deployment somehow configurable such that openproj features can be selected and
turned on/off?"*

The philosophy the switches serve, in his words: *"we want the tool to be focused on records,
dependencies between them and time and resources management."* Every decision below is checked
against that sentence. Records and the record page are the first half of it and are therefore never
switchable; the scheduler, cycles as data, and the dependency graph are the rest of it and are
never touched by a switch either — a switch removes a *page*, never a fact the schedule is computed
from.

## The two settings

Both live in the plan's `config/defaults.yaml`, beside `repositories`, for the reason that one does:
they are a fact about the plan and not about this tool's source. A deployment serves one plan, and
`AGENTS.md`'s answer to teams that differ is separate plans and separate deployments, so "the
deployment's views" and "the plan's views" are the same sentence.

```yaml
# Records is always on and always first. The rest appear in the nav in this order.
views: [cycles, graph, timeline]
# task, pitch, project and product are always on. These are the optional kinds.
kinds: [note]
```

|                             | `views`                                                              | `kinds`                            |
| --------------------------- | -------------------------------------------------------------------- | ---------------------------------- |
| vocabulary                  | `table` `graph` `timeline` `cycles` `deck` `people` `issues` `notes` | `issue` `note`                     |
| always on, whatever it says | Records (first, and the landing), every record page, Help (footer)   | `product` `project` `pitch` `task` |
| key absent                  | all eight, in today's nav order                                      | both                               |
| `[]`                        | Records only                                                         | neither                            |
| order                       | is the nav order, after Records; `deck` has no nav slot              | ignored                            |

**The vocabulary is the `Links` field names**, which are also the `_NAV` keys: one word per view
in the config, the router, the nav and the export, so there is no second spelling to map.

**`kinds`, not `records`, `record_kinds` or `additional_records`.** `records` is already the landing
view and `Index.records`, and `records: [note]` reads as "this plan holds only notes". "Additional
records" names the wrong noun — the switch turns kinds on and off, not files. `kinds: [note]` pairs
with the `kind: note` every record file already carries, and follows the same rule as `views`: the
core is implicit and the list names what is added to it. The comment in the file says what the core
is.

**Absent is everything and `[]` is the core.** Absent has to be everything, or every existing plan —
the demo included — would lose every view on the upgrade that introduced the key. `[]` is the core
alone because that is what an empty list says; jcanton: *"empty is therefore records only, not all
9."*

**The order is the nav order.** Proposed the other way round — the list as a set, the nav fixed —
and jcanton chose the list: *"do B."* A duplicate counts once, at its first position.

### Dependencies

| this            | needs          | because                                                      |
| --------------- | -------------- | ------------------------------------------------------------ |
| `deck`          | `cycles`       | a deck is one cycle's review, reached from that cycle's page |
| `issues` (view) | `issue` (kind) | a view of a kind the plan does not have is a list of nothing |
| `notes` (view)  | `note` (kind)  | the same                                                     |

A setting that breaks one leaves the dependent view off and says so. jcanton, on the deck: *"should
not be possible to turn it on without having cycles."*

The converse is deliberately allowed: **a kind can be on while its view is off.** That is exactly
icon4py's notes — *"we hide the nav but keep the kind: it's useful to draft ideas as a note without
having to assign a more structured kind to the record."* `/notes` is `/?kind=note`; the nav item was
a shortcut, and Records is one click from it.

### What is wrong with a setting is said on every page

Parse permissively, validate strictly. Every problem below is an `Unusable(path, field, why)` — the
type already exists for a config value nothing can compute with, it already rides in the banner
every page draws, and `openproj check` already prints it. Its headline stops saying "not a number"
and becomes *"One setting in the plan could not be used as written, so this page was drawn without
it."*

| setting                                       | what happens                                                                     |
| --------------------------------------------- | -------------------------------------------------------------------------------- |
| a name that is not a view (`cycels`)          | ignored; `Unusable` — a typo that silently hides Cycles is finding F1            |
| a broken dependency (`[deck]` alone)          | the dependent is off; `Unusable` naming what it needs                            |
| a duplicate                                   | counts once, at its first position; `Unusable`, since order means something here |
| an always-on name (`records`, `help`, `task`) | a no-op; `Unusable` saying it is always on, and where                            |
| not a list (`views: cycles`)                  | the key's default; `Unusable`                                                    |

**An always-on name is reported, not ignored in silence.** Somebody who writes `kinds: [task, pitch]` hoping to switch projects off has made a request the tool will not honour, and the branch
that decides not to act has to say so.

## The mechanism: one resolver, one seam, one gate

Nothing outside `read_config` reads `views` or `kinds` as written.

### The resolver (`model.py`)

`read_config` resolves both keys once. `Config.views` holds the ordered tuple of views that are on;
`Config.kinds` the set of kinds that are on, the planned four always in it. `Config.allows(kind)`
is the one predicate every kind question goes through.

The vocabulary lives in `model.py`, beside the kind ladder, because `openproj check` must know it
without importing `render`: `VIEWS`, the optional kinds **derived** from the ladder
(`planned=False`) rather than written out, and the dependency table. A third optional kind added to
the ladder is switchable on the commit that adds it.

### The seam: `Links`

`Links` is already the one thing that knows where the pages point, and it already has the
convention: `Links.new` and `Links.deck` are empty in the static export, and every template that
uses them asks `{% if links.deck %}` first. The switch generalises that convention rather than
inventing a second one.

- **`links_for(config, base)`** returns `base` (`ROUTES` or `STATIC`) with the field of every view
  that is off set to `""` — `cycles` off blanks `cycles` *and* `cycle`. It is computed once per
  index build, so it rides the per-commit memo in `index_now` and costs nothing per request.
- **`Links.nav`**, new: the ordered keys `("records", *views that are on and have a nav slot)`.
  `_page` draws the nav from it; `_NAV` keeps only the labels. `STATIC` defaults to all of them.
- **Every link site guards the empty field**, the way the deck link already does:
  - the slide-edit button on the record page, and the deck link on `/cycle/<n>` → `links.deck`.
    jcanton: *"if deck is off all of it is off."*
  - a cycle number that is a link → plain text when `links.cycle` is empty; the field itself stays,
    because the scheduler reads it.
  - "← all cycles" → `links.cycles`.
  - People's per-person and per-role filter links → `links.table or links.records`. Records
    honours the same URL filters (`_record_row` says why), so the link lands on the same rows.
- **The back link.** A record page rewrites its back link from an origin the tab stored in
  `sessionStorage`. That origin is honoured only if its path is still in `links.nav`; otherwise the
  link reads "all records". Without it, a tab that was on the Table before the switch was committed
  sends its reader to the switched-off page.

### The prerequisite: nothing sniffs server mode off a link

**This is a defect today, independent of the switches.** Three places decide whether a server is
behind the page by asking whether a *link* starts with `/`:

- `_page`: `live=links.table.startswith("/")` — the event stream, the pile, the plan head, the
  health poll;
- `markdown.py`: `served = ….table.startswith("/")` — whether mermaid is fetched;
- `render_cycles`: `per_cycle_page=links.cycle.startswith("/")`.

Blanking `table` would have switched off live updates and diagrams on every page of the plan, and
nothing would have said so. `Links.served: bool`, `True` on `ROUTES`, replaces all three. Two paths
written into page JavaScript by hand move onto `links` in the same change: `'/detail/'` after a
create, and `'/cycle/'` after "start cycle".

### The gate: switched-off routes (`web.py`)

One table maps each gated route to its switch:

| route                                                      | switch                |
| ---------------------------------------------------------- | --------------------- |
| `/table` `/graph` `/timeline` `/people` `/issues` `/notes` | the view of that name |
| `/cycles`, `/cycle/{n}`                                    | `cycles`              |
| `/deck/{n}`, `/detail/{id}?view=slide`                     | `deck`                |
| `/new?kind=X`                                              | `kinds`               |

A gated handler asks first. When its switch is off it answers **404** with `render_switched_off`:
the ordinary shell and nav, and one sentence naming the key and the file — *"The Table is turned off
for this plan. `views` in `config/defaults.yaml` decides which views it has."* When the address
carried a query (`/table?owner=ann`), the page adds one link to Records with the same query. The
slide view's page links to the record it was a view of.

**404, not a redirect.** A bookmarked `/table` that silently lands on Records is a page that changed
under its reader with nothing saying why — empty looking like broken, which is finding F1 again.
The same rule for every view, including the two that are Records filters, because two behaviours
for one situation is one more thing to explain.

**No API is gated.** jcanton: *"no toggle for API."* Reads are public by decision, `/api/index.json`
serves the whole plan, and the plan itself is on GitHub, so a switch is focus and never secrecy.
The record editor polls `/api/table.json` for a save landing, which is the concrete reason: an API
gated with its page would break a page that is always on.

### The gate: kinds

- **Written**: `POST /api/record`, `POST /api/rekind` (its target) and `openproj new` refuse a kind
  that is off with a 422 — or a non-zero exit — naming `kinds` and the file. This is validation of a
  write, not an API switch.
- **Offered**: the `/new` kind picker and the kind chip draw from `Config.allows`, and so does every
  "Create …" button.
- **Already there**: a file of a kind that is off still loads, is listed on Records and renders on
  its page; `validate_all` warns, through the same predicate. Hiding it would be a list that drops
  rows and looks normal, which is the thing `readable` exists to prevent.
- **Promote** is untouched: its sources are the inbox kinds and its targets are planned.

For icon4py the "already there" branch is empty on the day: jcanton, on the four issue files — *"we
can even delete them"*: three are grouped under `pitch-4f29ab` and the fourth has a GitHub issue
counterpart.

### Help moves to the footer

jcanton: *"we move help to the footer, before `report issue` and it stays always on there."* The
footer becomes `openproj 0.x · <plan head> · Help · Report issue`, and Help stops being a view:

- `help` leaves `_NAV` for `_OFF_NAV`, like `detail`; the footer link carries
  `aria-current="page"` on the Help page itself, so the page keeps its you-are-here mark.
- When `links.nav` is shorter than the full set, or a kind is off, Help opens with one sentence:
  *"This plan has Records, Cycles, Graph and Timeline. The guide below describes every view
  openproj has; the others are turned off here by `views` in `config/defaults.yaml`."* — with a
  clause for `kinds` when that is short too. The guide itself is not filtered.
- The argument for the footer is the one already written above `Report issue`: it is what you reach
  for at the moment the page in front of you is not what you expected.

### The static export

`openproj render` writes `index.html`, `detail.html`, `help.html` and one file per nav view that is
on, from `links_for(config, STATIC)`. The export has no per-cycle pages and no deck already.

## Testing

Every fixture is derived from the code — `VIEWS`, the optional kinds off the ladder, the gate table
off `web.py` — so a ninth view joins every test on the commit that adds it.

01. **A gate census that fails closed.** Every HTML GET route in `app.routes` is either in the gate
    table or in an explicit always-on set (`/`, `/detail`, `/help`). `/new` and `/detail/{id}` are
    always on as routes and gated by a query (`kind`, `view=slide`), and the gate table says so per
    row. A page route nobody decided about fails on the commit that adds it — the shape of
    `test_every_html_get_route_is_in_the_census`.
02. **The sweep, in a real DOM.** Parametrised over every view and every optional kind, each off
    alone. The switched-off route answers 404 naming the key. Every surviving page is parsed with
    `pages.elements()`, and every `href` and `action` is resolved the way Starlette dispatches it —
    against `app.routes` and the gate table, not as a substring — and none may reach the switched-off
    view. The controls that depend on it are absent: the slide button, the deck link, the cycle
    number as a link.
03. **JavaScript.** `drive.js` runs the shell's origin script with a stored `/table` origin on a plan
    without Table, and the back link reads "all records". A source tripwire in the manner of
    `test_no_page_is_assembled_by_substitution`: no string literal in `render/` spells a gated path,
    the paths coming from the gate table rather than from a list somebody wrote.
04. **The prerequisite.** A page rendered with `served=True, table=""` still carries the event
    stream and the mermaid loader.
05. **Resolution.** Table-driven over every row of the two tables above: the resolved tuple, the
    `Unusable`, the banner (`unusable_banner_says`), and what `openproj check` prints.
06. **Kinds through the write path**, not through fixtures: `POST /api/record` and `/api/rekind`
    answer 422 naming `kinds`; `/new?kind=issue` is the switched-off page; `openproj new issue`
    exits non-zero with the same sentence; `selects()` on `/new` offers no issue; a hand-committed
    issue loads, renders, and `check` warns.
07. **A live change.** A `defaults.yaml` committed through `Store` changes the next request's nav;
    the per-commit memo must not hold the old one.
08. **The export** writes exactly the nav set plus the three fixed files, and sweep 2 runs over
    those files with `STATIC` links.
09. **Pixels.** Through `tests/browser.py`: the footer with Help on a desktop and through
    `measured_on_a_phone`, where the footer already receives the corner's controls; a three-item nav;
    the switched-off page.
10. **Mutation-test the checkers**, each result written into the pull request: drop the slide
    button's guard, remove a route from the gate table, put `'/table'` back as a literal, restore a
    `startswith` sniff. Each has to turn its test red.

Tests that change: those asserting Help is in the nav (`test_help.py`, `nav_of` callers) and the
`_NAV` census.

## Rollout

Three pull requests, stacked, each green before the next merges:

| PR  | branch            | carries                                                                                                                             | changes behaviour           |
| --- | ----------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------- |
| A   | `served-flag`     | this record; `Links.served`; the two literal paths onto `links`; test 4                                                             | no                          |
| B   | `help-in-footer`  | Help to the footer and `_OFF_NAV`; pixels for the footer                                                                            | the nav loses Help          |
| C   | `views-and-kinds` | the resolver, `links_for`, the gates, the switched-off page, the kind gate, the export, `check`, the Help sentence; tests 1–3, 5–10 | not until a plan sets a key |

In C as well: `docs/architecture.md` (*The pages*) and the `Config` entry in `docs/data-model.md`
describe both keys; `bootstrap.plan_files` and `seed/config/defaults.yaml` write both keys out in
full, commented — a setting nobody can see is a setting nobody uses; and `AGENTS.md` gains one
invariant: *a view that is off is off everywhere, `Links` is the seam, and nothing reads server mode
off a link.*

Then v0.65.0, tagged and deployed. icon4py looks the same until its plan says otherwise.

In `icon4py-plan`, afterwards:

1. The four issues deleted through the record page's Delete, so the cascade check runs on each.
2. One commit to `config/defaults.yaml`: `views: [cycles, graph, timeline]`, `kinds: [note]`, and
   the stale `default_task_effort: 0.5` removed (ignored since `size_weeks` retired it).
3. Checked live: the nav reads Records, Cycles, Graph, Timeline; `/table` answers the switched-off
   page; Help in the footer carries the sentence; `/new` offers no issue; a record page has no slide
   button. Screenshots.

Rolling it back is deleting two lines from a file, effective on the next request, with no deploy.

## Decided against

- **Switching Records off.** jcanton: *"the record page which is also the homepage, should always
  be there. no option for turning records off."* It is also the only home of the Create button, and
  the page every login and logout returns to.
- **Switching the record page off.** Every bar, node and cycle row links to it.
- **Switching planned kinds off.** They are the hierarchy — `product ← project ← pitch ← task` is
  enforced — and the schedule. A plan without `project` would orphan the parent of every pitch.
- **Switching an API off.** Above.
- **Switching off cycles as data.** `cycles` off removes `/cycles`, `/cycle/<n>` and the deck. The
  `cycle:` field, the windows, the per-cycle availability and the timeline's bands all stay: they
  are the *time and resources* half of the sentence at the top. A plan with Cycles off edits its
  windows and rosters in git, since the cycle page is where they are edited.
- **A switch for the editor.** Ace carries every document body — the record page, the create form,
  the slide editor — and `?editor=plain` survives only as a per-page escape hatch in an address.
- **Switches for the hover card, the right-click menu, co-editing, drawings, the theme or sign-in.**
  None is a destination, each would double the test matrix, and nobody asked. Live pull requests
  already have their switch: `repositories`.
- **A deploy environment variable.** It would need a redeploy per change, the static export could
  not see it, and it would be a second source of truth for a fact the plan already holds.
- **A silent redirect for a switched-off address.** Above.
- **Filtering the Help page's guide per view.** It needs markers in `docs/*.md`, breaks the moment
  a paragraph mentions two views, and taxes every future edit of the guide to buy tidiness. One
  sentence at the top says what is true instead.
- **Hiding records of a kind that is off.** Above.
- **The People page for icon4py.** jcanton: *"deliberate drop on people. we can still see a view of
  it in the cycle."*

🤖 Written by an agent on behalf of @jcanton
