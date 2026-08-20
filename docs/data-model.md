# The data model

One markdown file per entity: YAML frontmatter, then the shaping document as the body. Four kinds —
`product`, `project`, `pitch`, `task` — with ids like `pitch-a3f81c`, where the prefix must agree
with the kind (`prod`, `proj`, `pitch`, `task`).

They are one list, in one place: `KINDS` in `model.py`, coarsest first. Each rung says what its ids
start with, where its files live, what it may be filed under, and whether it is scheduled, may
depend on anything, carries an appetite, or has a shaping document to show. Everything else — the
directories the loader walks, the id pattern, the parent rules, the filter menus, the create form —
is derived from that table, so a fifth kind is an entry in it rather than a search for the places
`project` was written down.

**A plan directory is flat.** `products/`, `projects/`, `pitches/`, `tasks/`, `cycles/`, `issues/`, `notes/` and
`people/` hold one file per record and nothing below them, because every reader here takes an identity off the
filename. A `people/team/ann.md` is therefore not a record filed tidily — it is a second `ann`, and
one that only half the application can see. A markdown file below one of these directories is
reported as a file that is not a record, with the move that fixes it, on every page and by
`openproj check`.

Each kind is one thing and says so:

- A **pitch** is the unit of the bet. It is what the betting table offers, what carries an appetite
  and a `shaped_by`, and the only kind whose body the shaping hints read.
- A **task** is a piece of a pitch. It carries its own size and its own people, and it takes its
  cycle from the pitch it belongs to — a bet is made once, on the thing the room named. A task with
  **no** parent is a chore nobody pitched: it is bettable in its own right, and then the cycle is
  its own.
- A **project** is a container for grouping pitches. It has no size, holds no capacity, is never
  bet, and its span is the rollup of the pitches inside it.
- A **product** is a codebase, and a container for projects. gt4py is the DSL under icon4py, dace is
  a backend, pmap is another code — and work in one of them waits on work in another. One plan holds
  all of them for exactly that reason: separate plans cannot express a cross-product dependency, and
  a dependency the tool cannot express is one somebody tracks in their head.

  It is a container and **nothing else**: a title, a sentence or two, and a place for projects to
  sit. It is never scheduled, so it draws no bar on the timeline and demands none of the fields a
  status usually demands; it carries no appetite; it waits on nothing, because its projects, pitches
  and tasks do; and it has no shaping document, so no hover card is offered for one. Written into a
  file anyway, each of those is reported beside the record rather than refused — a blocker where it
  changes what the plan means (a dependency nobody will schedule, an appetite nobody will read) and
  a warning where the field is merely ignored.

  On the graph it is a dashed outline rather than a filled box, which is how a grouping is told from
  the work inside it at a glance. It carries no status and no PRs either — a codebase is not
  `in_progress` and does not have a pull request; the state of the work is the state of the work
  inside it.

`product ← project ← pitch ← task` is enforced, not just documented: a parent of the wrong kind is a
blocker for anything written since the rule existed, and a warning for everything older. A task may
still name a project directly — a chore that belongs to a milestone and no pitch — but nothing may
be filed straight under a product except a project.

An **issue** is stored beside these and is deliberately not one of them. An entity is a bet: it
carries an appetite, takes a place on the timeline and charges somebody's cycle. An issue is the
opposite — most of them will never be worked on, which is the point of having somewhere to put them.
Keeping it a separate type is what holds it off the table, the graph, the people page and the
timeline by construction, rather than by an exclusion in each of them that somebody later forgets.
It has no `shaping` status, because a shaped issue is a pitch, and that is its whole lifecycle:
somebody reads the open issues at the betting table and writes a pitch for what matters. What it was
pitched into is stored on the issue and in that direction only.

A **note** is the second inbox, and the distinction that pays for having two is one sentence:

> an issue is "we found something existing that is broken", a note is "we are thinking of creating
> something that does not exist and our ideas are confused".

A note is therefore not a pitch in `shaping`, which is what it most looks like from a distance. A
pitch presupposes that you know what you are shaping — it has a problem, a solution and an appetite,
and it sits on the betting table as something a room could take. A note precedes all three. Putting
one in the table as a `shaping` pitch would make the plan look like it holds bets nobody has made.

So a note has **no appetite, no owner, no size, no cycle and no dependencies**, and it is on the
notes page and nowhere else. It carries a title, a body, `written_by` — who to ask, not who owns it
— `written_on`, `tags`, and `became`.

**Two statuses, and the count is the design.** `thinking` and `dropped` are the only two things a
person decides about a note; `promoted` is a third *state* and is derived from `became`, never
stored, for the reason `blocks` is derived from `depends_on`. There is no `in_progress`, because
there is no such thing as working on a note — the moment there is work there is a record that is
work, and the note points at it. There is no `ready`, because "ready to be shaped" is a promise
about a document the Promote button writes in one press. And there is no `done`: a note is not
finished, it is answered.

## Promotion

**An inbox that cannot become work is a second inbox nobody empties.** A note graduates into a
project, a pitch or a task; an issue graduates into a pitch, which is the lifecycle its own record
already describes.

- **The source survives.** It is the only record of the thinking that led to the bet. It gains
  `became` (or `pitched_into` on an issue) — one direction, on the record where the decision was
  made, the same rule `depends_on` follows.
- **The new record says where it came from in its own shaping document**, in prose, above
  everything. Not a field: a `from_note` on `Entity` would put a note id into the type every view
  of the plan is built from, and the table, the graph and the detail page would each have to decide
  what to do with it — which is the coupling that keeping notes out of `Entity` exists to prevent.
  So "where did this pitch come from" is answerable from the pitch alone, in `git show`, with no
  index and no server.
- **One commit**, because it is one decision. Two files go into it through `Store.write_all`, each
  compared-and-swapped on its own path; written as two commits, the second can fail after the first
  has landed and leave a pitch nothing points at.
- **Title, tags and body cross. Nothing else does.** The new record is created in `shaping`, which
  is the one status whose required-field gate is empty, so a promotion always produces a record
  that validates without inventing an owner, a size or a cycle that nobody agreed to. Its body is
  the kind's template with the note's text under `## Problem` — which is exactly what that heading
  asks for — and every other heading empty. Nothing nags about that yet: a `shaping` pitch owes
  nothing, and the missing Rabbit holes and No-gos are named the moment somebody moves it to
  `ready`, which is the moment it claims to be shaped.

## Sizes

A size is **person-weeks** on both a pitch and a task — the work one person would need — and the
people on it divide it, each at their own availability. Adding a second name halves the elapsed
time. A pitch that has tasks takes its dates and its capacity from them, so its own appetite is the
**bet**: what the room agreed to spend, kept as written. Where the tasks add up to more than it, the
pitch says so on its own page and `openproj check` warns — cutting scope or re-betting is a decision
for a person, so nothing here refuses the save.

## Dependencies

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

A cycle is `cycles/<n>.md` — a record, not an entity. It stores **two dates, and both are
meetings**: `starts_on` is the betting table and the first day of build, `reviews_on` is the review
meeting, which is also the brainstorm for the next cycle. Build ended the working day before it.
Beside them sit an `availability` fraction per person and a body for the goal and for whatever came
up at the betting table.

Everything else about the calendar is worked out from those two: where the build ends, how many
**working** weeks it holds with the holidays taken out, and where the cool-down ends — which is the
next cycle's betting table, stored once, on the next cycle. A date the tool had to assume, because
a record names no review or because there is no next cycle yet, is marked as assumed on the page
rather than printed as though somebody had chosen it.

Lengths were stored instead, and a length is a prediction of a date somebody picks. It could not
know that a review moved for a conference, that the team leaves a month between two cycles, or that
a cycle over the ETH year-end closure holds a fortnight of building rather than four weeks — and
since `capacity = availability × build weeks`, that last one was the betting table's own number
being wrong.

`cycle:` records **where a bet was made** and is never re-stamped, so an overrun keeps accusing
(D-C1). It lives on the thing that was bet — a pitch, or a chore nobody pitched — and everything
under a pitch takes the pitch's. A project therefore has no cycle at all, which is why a milestone
spanning two of them is no longer accused of overrunning either. Load is charged where the
assignees are and split evenly among them (D-C2), and it counts **carryover**: work bet in an
earlier cycle and still running is being done with this cycle's weeks, so the page that adds up who
is full says so and names what it counted. An overrun is measured against the end of *build*, never
the end of the window — the cool-down is for the mess afterwards, and the timeline draws both rules
so the flag and the line agree.

## Who is on the team, and what each person picked

Two separate things, in two separate places, and they answer different questions.

`config/people.yaml` holds `known_people`, the **roster**. Empty means the check is off, which is the
right default: a tracker that refuses a name because nobody has written a roster yet is a tracker
nobody finishes setting up. When it does name people, an owner, assignee, reviewer or shaper who is
not on it is a **warning** and never a blocker — the roster is maintained by hand, so it is always
slightly behind reality and a new colleague must not be unassignable on their first day.

`people/<login>.md` is one **record per person**, frontmatter and a body like every other record
here, and it holds what that person chose for themselves:

```yaml
---
icon: fox
---
```

The two do not constrain each other. A record for somebody who is not on the roster is one person's
preference; a roster entry with no record is somebody who has not picked anything. Both are ordinary,
and nothing validates one against the other.

**The login is the filename and is not a field.** Every other record here carries its id in the
frontmatter as well, and has to: an id is minted, opaque, and pointed at by other records
(`parent`, `depends_on`, `pitched_into`), while the filename carries a slug that drifts as titles are
edited. Nothing points at a person record — it is looked up by the login, which is the filename — so
a second copy would only give the two halves of the app something to disagree about.

**The body is not a field either.** A person record has one, nothing reads it, and no page offers a
box to type it in. It is a place to say who somebody is, in git, for whoever opens the file; a save
rewrites the frontmatter and hands the prose back byte for byte, the same promise every record makes.

**Why a file each rather than a map in the config.** `store.write` merges a file as frontmatter
key-by-key plus a three-way *line* merge of the prose under it. A whole-YAML file put through that
turns two edits nobody would call a disagreement into text that is not YAML — and one file holding
everybody's icons is a file two people edit at once. One record per person means the settings *are*
the frontmatter, so the merge over them is the structured one, and two people picking at the same
moment write two different paths, where compare-and-swap is scoped. There is no merge to get right.

The drawings are inline SVG paths in `render.py` — not emoji, which are resolved by whatever colour
font the reader's machine happens to own and are a box on one that owns none, and this is a plan that
has to render off a memory stick with no network. What is stored is the **name**, so `git log` reads
as a decision and a drawing can be redrawn without touching anybody's choice.

Somebody sets **their own** icon and no one else's: the endpoint that writes this takes no path, no
file name and no login, so the only sentence it can express is "this session's login now has this
icon". Setting somebody else's is a git edit, which is a first-class way to use this tool.

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

🤖 Written by an agent on behalf of @jcanton
