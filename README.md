# openproj

Planning for the icon4py team. Markdown files in a git repository are the source of truth, the
shaping document *is* the record, and every date is derived rather than typed.

A human types one date per item — `assigned_on` — and one size. Start dates, end dates, the critical
path and every rollup are computed from the dependency graph.

```bash
uv sync
uv run openproj check seed                          # validate; exits 1 on blockers
uv run openproj render seed out --today 2026-08-17  # write the three pages
uv run openproj schedule seed --json                # the computed schedule
open out/index.html
```

## The three views

`index.html` is a filterable, searchable table and the one people live in. `graph.html` is the
dependency DAG, grouped by project and pitch. `timeline.html` is the derived Gantt. All three render
from one in-memory index, share one filter model, and keep their state in the query string — so
every view is a shareable URL, the back button works, and there are no saved views to manage.

## Data model

One markdown file per entity: YAML frontmatter, then the shaping document as the body. Three kinds —
`project`, `pitch`, `task` — with ids like `pitch-a3f81c`, where the prefix must agree with the kind.

Each kind is one thing and says so:

- A **pitch** is the unit of the bet. It is what the betting table offers, what carries an appetite
  and a `shaped_by`, and the only kind whose body the shaping hints read.
- A **task** is a piece of a pitch. It carries its own size and its own people, and it takes its
  cycle from the pitch it belongs to — a bet is made once, on the thing the room named. A task with
  **no** parent is a chore nobody pitched: it is bettable in its own right, and then the cycle is
  its own.
- A **project** is a container for grouping pitches. It has no size, holds no capacity, is never
  bet, and its span is the rollup of the pitches inside it.

`project ← pitch ← task` is enforced, not just documented: a parent of the wrong kind is a blocker
for anything written since the rule existed, and a warning for everything older.

A size is **person-weeks** on both a pitch and a task — the work one person would need — and the
people on it divide it, each at their own availability. Adding a second name halves the elapsed
time. A pitch that has tasks takes its dates and its capacity from them, so its own appetite is the
**bet**: what the room agreed to spend, kept as written. Where the tasks add up to more than it, the
pitch says so on its own page and `openproj check` warns — cutting scope or re-betting is a decision
for a person, so nothing here refuses the save.

Two invariants are load-bearing:

- **Only `depends_on` is stored, on the dependent.** `blocks` is derived by reversing it. A stored
  copy would be stale by construction and would let one file contradict the graph.
- **Derived data never reaches frontmatter.** No computed dates in entity files, ever. Rescheduling
  one blocker would otherwise rewrite fifty files.

An entity may not depend on its own ancestor or descendant. Containment already requires a child
before its parent, so a dependency along the parent chain demands to be both before and after itself.

**Dependencies cross kinds and are inherited down the tree.** A project may block a project, a task
may wait on a whole pitch: any kind may block any kind, and the only forbidden direction is your own
containment chain. A dependency written on a pitch is what every task inside it waits for — the edge
stays written once, where somebody wrote it, and `blocks` still means what the page says. Without
that, a pitch-level edge moved no date at all: only a leaf is placed against its blockers, and a
parent's span is the rollup of children that had never heard of the edge.

## Required fields

Requiredness is **status-gated** and enforced in three places: the create form, `openproj check` in
CI, and the index validation gate.

The five statuses are `shaping`, `ready`, `in_progress`, `done`, `shelved`, in the order work moves
through them. Priority is one of `very_high`, `high`, `medium`, `low`, `very_low` — five rungs
because three left the team writing `High+` in the margin of its own table.

| status | additionally required |
|---|---|
| `shaping` | nothing — an idea nobody has bet on has no owner and no size by definition |
| `ready` | `owner`; a reviewer or `review_waived`; a size; `shaped_by` on a pitch |
| `in_progress` | `assigned_on`; a reviewer who is not the owner |
| `done` | at least one PR |
| `shelved` | nothing — parked work is not broken work |

**Parse permissively, validate strictly.** Every field is optional at the type level, so a
hand-edited file with a missing field still loads and reports a problem instead of taking the index
down. Requiredness lives in `validate_all`, never in the parse types.

**Grandfathering.** Each rule records the `schema_version` that introduced it, and an entity is only
*blocked* by rules that existed when it was created; a newer rule warns instead. Without this,
adding one required field invalidates the whole repository at once and the rule gets reverted rather
than adopted. `shaped_by` is the live example: a version 2 rule warning against a version 1 corpus.

## What a cycle holds

A cycle is `cycles/<n>.md` — a record, not an entity. It carries `starts_on`, `build_weeks`,
`cooldown_weeks`, an `availability` fraction per person, and a body for the goal and for whatever
came up at the betting table.

`cycle:` records **where a bet was made** and is never re-stamped, so an overrun keeps accusing
(D-C1). It lives on the thing that was bet — a pitch, or a chore nobody pitched — and everything
under a pitch takes the pitch's. A project therefore has no cycle at all, which is why a milestone
spanning two of them is no longer accused of overrunning either. Load is charged where the
assignees are and split evenly among them (D-C2), and it
counts **carryover**: work bet in an earlier cycle and still running is being done with this cycle's
weeks, so the page that adds up who is full says so and names what it counted. An overrun is
measured against the end of *build*, never the end of the window — the cool-down is for the mess
afterwards, and the timeline draws both rules so the flag and the line agree.

## The shaping document

The body of a pitch is prose and stays prose. Nothing here validates it, rewrites it, or requires a
word of it — but two things read it, because the team's own pitch template already asks for them:

- **`## Progress`** — a task list, which is a **task's** business. A pitch's progress is its tasks:
  a panel above the document, one line per task, each ticked from that task's own `status` and
  weighted by its size, so `4/7.5 wk` is four weeks of a seven-and-a-half-week bet rather than a
  count of rows. That is why the pitch template has no `## Progress` and the task template does —
  the coarse list in a HackMD pitch becomes the tasks, and its sub-items become their checklists.
  A pitch with no tasks yet still has its own list counted, and one that keeps both is told which
  of the two the page is reading. Either way it is counted, never written: a checkbox stored beside
  a task's status is the same stale copy `blocks` would be. `predicate=untracked` finds live work
  that says nothing about how far along it is.
- **`## For later`** — deferred scope. The only record the plan keeps of a bet trimmed to fit its
  appetite, and it was invisible until it had a name.

A **missing `## Rabbit holes` or `## No-gos`** on a live pitch prints a note on that pitch's page,
and nowhere else. It is not a `Problem`: it never reaches `openproj check`, never fails CI and never
blocks a save. A validator with an opinion about prose is one people route around.

Creating an entity starts from a template — the team's own, with its guidance in HTML comments
exactly as HackMD carries it. Those comments are stripped when the page renders, so a pitch drafted
in either place is the same document. The three header lines of the HackMD template (`Shaped by`,
`Appetite`, `Developers`) are fields here instead: a heading restating a field is the
two-copies-of-one-fact problem this tool exists to end.

## How this maps to what the team already keeps

| in HackMD | in openproj |
|---|---|
| A pitch note | a `pitch` entity — frontmatter, and the shaping doc as the body |
| `Shaped by: @a and @b` in the header | `shaped_by: [a, b]` |
| `Appetite (FTEs, weeks)` | `person_weeks` — the work one person would need; the people on it divide it |
| The cycle sheet's `Available people` | `availability:` in `cycles/<n>.md`, a fraction of the build weeks |
| The cycle sheet's task table | the betting table on `/cycle/<n>` |
| The sheet's `## Goal`, and what was said while betting | the cycle record's body, editable on that page |
| `Support` | `reviewers` — the role includes support, and it makes somebody accountable |
| The Greenline table's `Depends on` | `depends_on`, with `blocks` derived from it |
| The Greenline table's `Shape doc` link | there is no link: the shaping doc *is* the record |

**Where this departs from Shape Up as written**, deliberately and with the team's practice as the
reason: a size is person-weeks and staffing divides it, so the tool forecasts dates the book would
not; cycles are soft walls and the scheduler runs work past them rather than stopping (D2), because
the circuit breaker is a human decision made at the review meeting; `project` is a milestone layer
the book does not have, because the Greenline table already tracks cross-cycle dependencies; and
progress is the body's own checklist rather than a hill chart, because a checklist is what the team
actually keeps.

## Two repositories

The tool and the plan are separate repositories, and stay separate in production.

```
C2SM/openproj        this repo — code, tests, and fixtures. No real plan data.
C2SM/<name>-plan     the data — markdown entities and config. No code.
```

`seed/` and `tests/fixtures/corpus/` live here only because they are a demo and a
test fixture. Neither is anybody's plan.

Three reasons the split is load-bearing:

- **A plan commit must not run the tool's CI.** Someone changing a status should not
  queue a test suite, and a red suite should not block someone changing a status.
- **The write credential must be structurally incapable of touching source.** The
  server commits to the plan repo continuously. Scoped to one repository with
  `contents: write`, a leaked token costs you a revertable plan; scoped wider it is a
  supply-chain foothold in a scientific codebase.
- **Their histories have nothing to say to each other.** `git log` on the plan is a
  record of decisions; on the tool it is a record of code. Interleaving them makes
  both harder to read, and `git blame` on an appetite field stops being useful.

The seam is the `--repo` argument. The server holds a bare clone of the plan repo and
knows nothing else about it, so pointing a deployment at a different plan is a flag,
not a fork.

```bash
uv run openproj serve --repo /srv/plan.git          # a bare clone of the data repo
uv run openproj serve --repo seed --auth dev        # the demo, locally
```

On Cloud Run the container clones the plan repo on boot and pushes on write, which is
also why the running service is close to stateless — the durable data is the git remote,
not the disk.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/render.py     the three pages
src/openproj/store.py      the git write layer — bare repo, one writer, scoped CAS
src/openproj/cli.py        check / render / schedule / serve
seed/                      the demo corpus
tests/fixtures/corpus/     the frozen golden corpus the scheduler goldens pin
static/                    vendored, pinned JS — see static/VENDOR.md
docs/superpowers/          the spec and the plan
```

**No npm, no build step, no CDN.** A Node toolchain that rots is the most common way a small
internal tool becomes unbuildable in two years. `tests/test_render.py` asserts no rendered page
reaches the network.

**`node` is not needed to build or run it, and is needed to test it fully.** Thirty-four tests run
the shipped page scripts against a minimal DOM — the table's rows, the timeline's tooltip, the
combobox and the cycle roster exist only after a script has run, so nothing in a rendered file
shows what they build. Without `node` on PATH those tests skip, and a suite missing them is green
for the wrong reason. `pytest` names every skip; a machine that is meant to gate a merge should
have `node` installed.

## Deliberately not built

Real-time collaborative editing, notification infrastructure, user-defined custom fields, a
PR-based editing workflow, time tracking, burndown charts, per-project permissions. If you are about
to add one of these, read the spec first — each is excluded for a reason recorded there.

Nothing may make the CI bot write entity frontmatter. The bot owns `derived/` and nothing else;
if it starts patching frontmatter, bot and humans fight over the same files forever.

## Status

Phase 1 is done: the static viewer renders, and Gate 1 was shown at a planning meeting.

Phase 2 is in progress. `store.py` — the git write layer — is complete: a bare repository with no
index to contend for, one writer behind an `flock`, and compare-and-swap scoped to the path being
written, so an edit to a different file retries invisibly and only a genuine overlap is refused.
The server and GitHub OAuth are next.

Spec: `docs/superpowers/specs/2026-08-12-appetite-design.md`.
Cycles, betting and capacity: `docs/superpowers/specs/2026-08-16-cycles-design.md`.
What the team actually does, and what was tailored to it:
`docs/superpowers/specs/2026-08-16-tailoring-plan.md`.
Plan and gates: `docs/superpowers/plans/2026-08-12-phase1.md`.

🤖 Written by an agent on behalf of @jcanton
