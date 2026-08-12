# openproj — design spec

**Date:** 2026-08-12
**Status:** approved for Phase 1
**Owner:** jcanton
**Successor:** msimberg

A planning tool for the icon4py team. Markdown files in a git repo are the source of truth;
a web page is the primary editor; dates are derived from appetite and dependencies rather than
typed; a filterable table, a dependency graph and a timeline are rendered from the same in-memory
index.

Companion documents:
- Tool selection investigation — https://claude.ai/code/artifact/644376c2-b473-4292-a8c3-b041add0edbf
- Architecture and build decision — https://claude.ai/code/artifact/ce592dad-1082-4c1d-bbbb-5c39b5929781

---

## 1. Problem

The team runs Shape Up: roughly fourteen pitches bet per cycle, cycles currently numbered to 38.
Pitches are markdown shaping documents in HackMD (~730 notes at `hackmd.io/@gridtools`). Task
tracking is a hand-maintained markdown table in a separate HackMD note, and a barely-configured
GitHub Projects v2 board exists alongside it.

Four failures were established by inspecting the actual artifacts:

1. **Nothing propagates.** Rows marked `Done` cite pull requests that were closed without merging.
   No mechanism notices.
2. **No rollup.** A milestone declaring ten dependencies cannot be reported on without a human
   re-deriving its state each time.
3. **The plan lives in six places.** The task table, a hub note, 153 pitches, 24 cycle overview
   docs, a fifth note that is itself a board, and 108 repo issues.
4. **The join is stored in a regenerated blob.** A generator script emits columns that humans fill
   in by hand, so re-running it destroys data.

A fifth problem, raised separately by the team: **pull requests struggle to find reviewers.** Review
assignment happens after the work exists, when it is already someone's problem to chase.

The single structural cause of the first four is that the pitch record and the shaping document are
two objects kept in sync by hand. No existing product collapses them — 53 were screened and six
deep-verified; none satisfies free, a rendered dependency graph, and a timeline simultaneously.

**Design goal: make the shaping doc and the record the same file, derive everything derivable, and
make review a property of the bet rather than an afterthought on the PR.**

## 2. Requirements

Load-bearing:

- **R1** One file per entity, human-readable, editable both in a browser and by `git commit`.
- **R2** Many-to-many dependencies between entities of any kind.
- **R3** Three levels — project, pitch, task — with zoom between them.
- **R4** Dates derived from appetite/effort + dependency graph + `assigned_on`. A human types at
  most one date per item.
- **R5** Three views over the same index — a filterable table, a dependency graph, a timeline — with
  every field filterable and free-text searchable.
- **R6** Web editing with no pull-request step, for ~30 concurrent-capable users.
- **R7** Identity, authorization and audit supplied by GitHub, not built.
- **R8** Priority, owner, reviewers, status, cycle, tags, and links to one or more pull requests.
- **R9** Required fields enforced at creation, in CI, and at index load.
- **R10** Seed data drawn from the **short projects in the existing HackMD task table** — a handful
  of small, self-contained items used as worked examples. Explicitly **not** a bulk import of the
  ~730-note corpus or of the 108 repo issues. Content moves in; nothing links back out.

Explicitly out of scope, permanently: real-time collaborative editing, notification
infrastructure, user-defined custom fields, a PR-based editing workflow in the UI, time tracking,
burndown charts, per-project permissions.

## 3. Decisions taken

| # | Decision | Reasoning |
|---|---|---|
| D1 | `appetite_weeks` means **elapsed weeks at nominal availability**, not person-weeks | Matches how the team already speaks about a "three-week bet" |
| D2 | Shape Up cycles are **soft walls** — the scheduler ignores them, the timeline flags overruns | The circuit breaker is a human decision; silently reflowing a bet misrepresents the process |
| D3 | Project and repository name: **`openproj`**. Local-only while it is just jcanton and Claude; **pushed to the C2SM GitHub organisation at the same moment it goes to Cloud Run** | Nothing is shared yet, so nothing needs to be pushed. Going online and gaining an org-owned remote are the same event, which is also when backups start existing (§12) |
| D4 | The plan data lives in **its own repository**, separate from `openproj`'s source | A plan commit must not trigger CI on tool code, and the write credential must be structurally incapable of touching source repos. While local, this is a second directory |
| D5 | Effort is **appetite** for pitches, **`effort_weeks`** for tasks, both mandatory | The team fills appetite on 145 of 153 pitches. Making task effort mandatory is a deliberate change of habit, and §5.4 is how it is made to stick |
| D6 | **No `hackmd` field.** Content moves in; nothing links back | A link to the old system is how two sources of truth survive. The shaping doc becomes the entity body |
| D7 | Required fields are enforced at **three points**, and requiredness is a validation rule, never a parse constraint | §5.4 |
| D8 | Hosting is **local now, Cloud Run when shared**. No NAS, no personal hardware | §12 |

## 4. Storage

### 4.1 Layout

```
projects/prj-4f21--dycore-port.md
pitches/p-a3f81c--fold-gtir-lowering.md
tasks/t-91c2b7--fix-domain-inference.md
config/defaults.yaml       # nominal_availability, schema_version
config/cycles.yaml         # cycle number -> start/end dates
config/holidays.yaml
links/prs.jsonl            # BOT-OWNED, append-only. Humans never edit.
derived/                   # CI-OWNED. Humans never edit.
  INDEX.md                 #   whole board as a markdown table
  schedule.json            #   computed spans
  graph.mmd                #   mermaid DAG, renders natively on GitHub
```

Flat, not sharded. A flat 2,000-entry tree object is 76 KB rewritten per commit, ~660 bytes once
packed, roughly 13 MB per year at 20,000 commits. `git gc` weekly from cron.

Filenames are `<id>--<slug>.md`. The **ID is authoritative**; the slug may drift. Files resolve by
ID through the index, never by path, so renaming a title never breaks a reference.

### 4.2 Entity schema

```python
class Entity(BaseModel):
    id: str                          # <prefix>-<6 hex>, prefix in {prj, p, t}
    kind: Literal["project", "pitch", "task"]
    title: str
    parent: str | None = None        # project for a pitch, pitch for a task
    status: Literal["todo", "wip", "done", "shelved"] = "todo"

    owner: str | None = None         # single GitHub username, accountable
    assignees: list[str] = []        # additional people doing the work
    reviewers: list[str] = []        # GitHub usernames expected to review
    review_waived: bool = False      # deliberately no reviewer, recorded by a human

    assigned_on: date | None = None  # the ONLY date a human types
    priority: int = 2                # 0 must, 1 should, 2 could, 3 someday
    depends_on: list[str] = []       # m:n, cross-kind permitted
    cycle: int | None = None
    tags: list[str] = []
    prs: list[str] = []              # "C2SM/icon4py#1842"

class Pitch(Entity):
    appetite_weeks: float | None = None   # elapsed weeks at nominal availability

class Task(Entity):
    effort_weeks: float | None = None
```

Every field is Optional at the type level. **That is deliberate and is explained in §5.4** — it is
not laxity, it is what keeps a hand-edited file from taking the index down.

The markdown body is the shaping document. No length or structure constraint is enforced.

**IDs are random, not sequential** (`<prefix>-<6 hex>`), so two people creating entities in different
tabs or on different branches never collide.

### 4.3 The dependency invariant

**Only `depends_on` is stored, on the dependent. `blocks` is derived and presented as a backlinks
panel.** Every edge therefore has exactly one owning file, so two people wiring opposite ends of the
same dependency touch different files and never conflict.

This is the most important schema decision in the system and it costs nothing. It must not be
"improved" by adding a stored `blocks` field.

### 4.4 Derived data

**Computed values are never written into entity frontmatter.** Rescheduling one blocker would
otherwise rewrite fifty files. Derived output goes only to `derived/`, written by CI, never by the
server and never by a human.

### 4.5 Deletion

Deletion is `status: shelved`, never `rm`. The validator warns on references to shelved entities and
the graph greys them. A genuine `rm` produces a dangling-reference error, which is correct and
visible.

## 5. Required fields and how they are enforced

### 5.1 The rules

Requiredness is **status-gated**: permissive when an idea is first captured, strict by the time work
starts, strictest when it is claimed done.

| Status | Additionally required | Severity |
|---|---|---|
| `todo` | `owner`; `reviewers` (≥1) **or** `review_waived: true`; and `appetite_weeks` (pitch) or `effort_weeks` (task) | blocker |
| `wip` | `assigned_on`, and **at least one reviewer who is not the owner** unless review is waived | blocker |
| `done` | at least one entry in `prs` | blocker |
| any | `title` non-empty; `id` matches `^(prj\|p\|t)-[0-9a-f]{6}$` with the prefix matching `kind` | blocker |
| any | `parent` set for every task | **warning** |
| `shelved` | nothing — shelving is always allowed, so a stuck record is never trapped by validation | — |

`reviewers` is required from the moment an item exists rather than when a PR appears. Review
assignment is a routing problem, and routing it at bet time is the point: a bet nobody will review is
a bet that should not be made.

**`review_waived` exists because some work has nothing to review** — reading a paper, a spike, an
investigation. It is a deliberate act recorded by a human, and it is distinct from `reviewers: []`,
which means nobody has decided yet. The table surfaces waived items as their own facet and counts
them, so a team that waives everything can see itself doing it. Without the distinction, the honest
answer for a reading task is to name a fake reviewer, and the field becomes noise.

**An unparented task is a warning, not a blocker.** The first real chore we tried to record — adding
missing unit tests — belongs to no pitch, and inventing a parent to satisfy a rule would be
falsifying the plan to please the validator. Orphans group under "unparented" in the table, which
makes them visible without making them illegal.

### 5.2 The principle — parse permissively, validate strictly

The model parses any well-formed YAML into an entity with optional fields. **A missing required
field never makes a file unparseable and never takes the index down.** Requiredness lives in
`validate_all`, not in the parse types.

Getting this backwards is the classic failure of file-backed systems: one hand-edit with a missing
field makes the repo unloadable, and the tool becomes something people are afraid to edit.

### 5.3 The three enforcement points

1. **At creation, in the web form.** Server-side validation on `POST /api/entity` rejects the
   create, and the form cannot be submitted with the fields empty. Roughly all entities are born
   here, so this is where enforcement actually bites. The form suggests reviewers from recent
   reviewers of the same tags, because the fastest way to get a field filled is to make the good
   answer the default one.
2. **In CI, via `openproj check`.** Runs on every push. Fails, and names the file, the field, and
   the commit author. This catches hand-edits and scripts — the paths that bypass the form.
3. **At index load, via the validation gate.** The server refuses to promote an invalid commit,
   keeps serving the last good index, and banners the breaking commit, its author and the exact
   error. Nothing silently degrades.

### 5.4 Grandfathering

`config/defaults.yaml` carries a `schema_version`. Each rule records the version that introduced it.
**An entity is only held to rules that existed when it was created**; older entities failing a newer
rule are reported as warnings, not blockers.

Without this, adding one required field invalidates the entire repository at once, and the rule gets
reverted rather than adopted.

### 5.5 Making the gaps visible

The table view ships a built-in filter, **"missing required fields"**, and the header shows a
persistent count. Bulk-fixing ten records in a table is a two-minute job; hunting them one at a time
never happens. Enforcement stops things getting worse; visibility is what makes them get better.

## 6. Module decomposition

```
openproj.model      pydantic schemas, round-trip parse/serialise, validate_all
openproj.schedule   pure function: records -> spans + explanations
openproj.store      bare-repo git operations: read, commit, push, fetch
openproj.index      in-memory index built from a commit; backlinks; validation gate
openproj.web        FastAPI + Jinja2 + HTMX; the only module that knows about HTTP
openproj.cli        everything the web can do, from a terminal
```

Dependencies point downward only: `web` and `cli` depend on `index`, which depends on `store` and
`model`; `schedule` depends only on `model`.

### 6.1 `openproj.model`

Owns parsing, serialisation and validation. Uses `python-frontmatter` with **`ruamel.yaml` in
round-trip mode** — non-negotiable, because a human's key order, comments and formatting must
survive a web save. Lose round-trip and "commit directly if you prefer" becomes false after the first
web edit.

Interface: `parse(path) -> Entity`, `serialise(entity, original_text) -> str`,
`validate_all(entities, schema_version) -> list[Problem]`, where `Problem` carries severity, entity
id, field, message and the rule's schema version.

### 6.2 `openproj.schedule`

A pure function. No I/O, no clock access — `today` is a parameter.

```python
def schedule(records, config, today) -> tuple[dict[Id, Span], dict[Id, Explanation]]
```

Specified fully in §7.

### 6.3 `openproj.store`

All git operations via `pygit2` against a **bare** repository. No working copy, no shared index.

Interface: `read_blob(commit, path)`, `commit_change(base, path, content, author) -> oid`,
`push()`, `fetch()`, `head()`. While the project is local-only, `push` and `fetch` are no-ops behind
a configured remote that is simply absent.

`commit_change` builds a tree with `TreeBuilder` from the parent commit's tree and creates the commit
directly. Measured at 4.27 ms per single-entity commit, ~230 commits/sec.

**A process-wide `flock` on the repository directory is acquired at startup and the process refuses
to boot if it cannot get it.** Single-writer is a correctness invariant, not a deployment preference;
the comment explaining this goes next to the code.

### 6.4 `openproj.index`

Rebuilds fully from a commit — always everything, never incrementally. Measured ~50 ms at 300
entities, ~250 ms at 2,000. Full rebuild deletes the entire class of incremental-invalidation bugs.

The index is an immutable snapshot swapped in atomically. Readers hold a reference and are never
blocked by a write.

The index also carries the **filter and search structures** for §9: a per-field value set for
building filter menus, and a lowercase concatenation of title, tags and body per entity for
substring search. At this scale both are rebuilt with the index and no search engine is needed.

### 6.5 `openproj.web`

FastAPI + uvicorn, **exactly one worker**. Jinja2 templates, HTMX for interaction, a little
Alpine.js. Cytoscape.js + dagre for the graph, frappe-gantt for the timeline. All vendored as pinned
files under `static/`.

**No npm, no build step.** A Node toolchain that rots is the most common way a small internal tool
becomes unbuildable in two years. Treat this as a hard constraint.

Server-Sent Events for cache invalidation, not WebSockets.

### 6.6 `openproj.cli`

`openproj check`, `openproj serve`, `openproj new`, `openproj schedule --json`. The CLI can do
everything the web can. This is a bus-factor mitigation: if the web app stops working, the team is
not blocked.

## 7. The scheduler

Written first, before any server, with property tests. **This is the product.**

### 7.1 Algorithm

1. Build a `networkx.DiGraph` of `depends_on` edges over all non-shelved entities.
2. **Cycle check.** Every node in a cycle, and every descendant of one, is marked `unscheduled` and
   rendered red with the cycle named. Everything else still schedules. Never raise and produce
   nothing.
3. **Completed work does not occupy the future.** Entities with status `done` are excluded from
   forward scheduling and from capacity entirely. Their span, if drawn at all, is historical — from
   `assigned_on` to the merge date of their last PR, or a point marker if neither is known. An
   earlier draft excluded only `shelved`, which scheduled a task finished in 2025 as though it were
   about to start and consumed its owner's capacity for it.
4. **Duration resolution:**

   ```
   size_weeks  = appetite_weeks (pitch) | effort_weeks (task)
   duration    = size_weeks × (nominal_availability / availability(owner))
   ```

   With a single global availability figure (D4) the ratio is 1 and **duration equals the stated
   size**, which is exactly what D1 means by "elapsed weeks at nominal availability". The ratio only
   does work later, if per-person availability is ever introduced.

   An earlier draft divided by availability unconditionally. That silently reinterprets appetite as
   *person*-weeks and contradicts D1 — it stretched every three-week bet to five weeks. It also
   applied to pitches but not tasks, so a three-week pitch and a three-week task scheduled to
   different lengths.

   - **A pitch with children takes no duration of its own**; its span is the union of its children's,
     computed after them.
   - **Missing effort or appetite** — a validation error under §5, but the scheduler must still cope
     with grandfathered records: fall back to 0.5 weeks and draw the span **hatched with an
     "estimated" badge**. Guessing silently is worse than guessing loudly; refusing to schedule is
     worse than both, because one unestimated task would blank half the timeline.
5. **Ordering: children before parents, blockers before dependents.** Containment is *not* a
   dependency, so a topological sort over `depends_on` alone visits a parent before its children and
   its rollup reads spans that do not exist yet. Build the ordering graph as the union of
   `depends_on` edges **and** child → parent containment edges, then
   `networkx.lexicographical_topological_sort` keyed by `(priority, id)` for determinism. The cycle
   check in step 2 runs on `depends_on` alone — a containment loop is a separate, and simpler,
   validation error.
6. For each **leaf** node in that order:

   ```
   workers(n) = [n.owner] + n.assignees
   ready(n)   = max(n.assigned_on or today,
                    max(end(b) for b in blockers(n)),
                    default=today)
   start(n)   = next_free_slot(workers(n), ready(n), duration(n))
   end(n)     = start(n) + duration(n)        # working days, per holidays.yaml
   ```

   `next_free_slot` walks each worker's already-placed intervals and returns the first gap of at
   least `duration` at or after `ready`. Because blockers are always placed first, resource-driven
   delay propagates correctly.
7. **Each worker is capacity 1, and only leaves consume it.** A parent's span is a rollup of work
   already accounted for by its children; booking the parent as well double-books its owner for the
   same weeks. A multi-worker leaf consumes all of its workers for its whole span — pessimistic,
   simple, right often enough. **Items with no owner schedule with infinite capacity and draw
   hatched**: they are forecasts, not commitments, and the visual difference matters. Reviewers do
   **not** consume capacity; review load is surfaced in the table (§9) instead, because modelling it
   here would double the model's complexity for a small correction.
8. Roll up: parent span is `[min(child start), max(child end)]`.
9. Cycles are drawn as vertical rules. An item finishing past its cycle end is flagged amber:
   *"overruns cycle 38 by 1.4 weeks"*. The scheduler does not move it.

Steps 3, 4, 5 and 7 all exist because a hand-run of an earlier draft against the real seed corpus
produced an absurd schedule. That exercise is worth repeating whenever the algorithm changes: run it
on paper against real records before trusting the code.

### 7.2 Explanations

**Every span carries an explanation naming its binding constraint**, shown on hover:

> starts 2026-09-14 because p-77d1a0 ends 2026-09-11 and jcanton is busy until 2026-09-13

Do not ship the timeline without this. The first unexplained surprising date is when people stop
trusting it, and an untrusted tracker is dead.

### 7.3 Property tests

1. No item starts before all its blockers end.
2. No worker has two overlapping spans.
3. Adding an item that shares no worker and no ancestor with an existing item never moves that
   item's span.

Property 3 must be stated exactly as written. The looser "adding an unrelated item never moves
anything" is false under a capacity-1 resource model, and a test asserting it will be deleted as
flaky.

## 8. The write path

1. Browser sends `PATCH /api/entity/{id}` with `{base_commit, fields_changed: {...}, body}` —
   **only the touched fields**, which is what makes field-level merge possible. No autosave; drafts
   in `localStorage`; one Save is one commit.
2. The request goes on an `asyncio.Queue` served by the single writer task.
3. If a remote is configured and the last fetch was more than 15 s ago, fetch and fast-forward.
4. **Scoped compare-and-swap:**
   - `base_commit == HEAD` → proceed.
   - Otherwise diff **just this path** between `base_commit` and `HEAD`.
     - Path unchanged (someone edited a different entity) → **retry silently against the new
       HEAD**. This is ~95% of collisions and it is invisible. It is why thirty people can work at
       once.
     - Path changed → structured merge. Frontmatter merges per key: they changed a key I did not →
       theirs; I changed a key they did not → mine; both changed the same key differently →
       conflict. Body merges three-way; taken if automergeable.
   - Genuine collision → **HTTP 409** with a rendered side-by-side diff, the other author's name and
     time, and three actions: keep mine, keep theirs, edit merged. **No conflict markers ever reach
     the editor.**
5. Commit: new blob, `TreeBuilder` from HEAD's tree, `author = <the signed-in user>`,
   `committer = openproj-bot`, message `p-a3f81c: status todo → wip`. The author/committer split
   makes `git log --format='%an'` a free per-person audit trail, while any future push credential
   stays a bot.
6. When a remote exists: push inside the lock, 5 s timeout. **Invariant: local `main` is only ever
   ahead of `origin/main` inside the writer lock**, so divergence cannot accumulate. Rejected →
   reset to `origin/main`, back to step 4, maximum three attempts. Unreachable → HTTP 200 with an
   honest "saved locally, not yet pushed" badge and a background retrier. **Never a green tick for
   an unpushed commit.**
7. Rebuild the index, swap atomically, broadcast SSE `{commit, changed: [...]}`.

Expected user-perceived latency 250–500 ms with a remote, ~10 ms local-only.

## 9. Views

Three views over one index. All are pure functions of it; none has its own persistence.

**Every view shares one filter model**, so a filter set in the table survives a switch to the graph
or the timeline, and every view is a shareable URL.

### 9.1 Filtering and search

Filterable fields: `kind`, `status`, `owner`, `assignees`, `reviewers`, `priority`, `cycle`,
`project` (via `parent` closure), `tags`, and the computed predicates **blocked**, **unblocked**,
**overruns cycle**, and **missing required fields**.

Filters combine as AND across fields and OR within a field, which is the behaviour people expect
from GitHub's own filter bar and therefore needs no explanation. Free-text search is a
case-insensitive substring match over title, tags and body, computed from the index — instant at
this scale, and no search engine is needed or wanted.

**All filter and search state lives in query parameters.** This makes every view shareable, makes
the back button work, and deletes the entire "saved views" feature request.

### 9.2 Table

The primary view, and the one people will live in. Columns: id, title, kind, status, owner,
reviewers, priority, cycle, appetite/effort, derived start and end, blocked-by count, PRs, tags.

- Sortable by any column; grouped by any field (status, owner, cycle, project).
- **Inline editing of every editable field** — one field, one commit, per §8. This is the low-friction
  write path that the whole tool rests on.
- Derived columns are visually distinct and not editable.
- A **review-load** grouping — group by `reviewers` — answers "who is on the hook to review what",
  which is the reporting the team currently lacks.

### 9.3 Graph

Cytoscape.js + dagre, left-to-right. Compound nodes give the three-level zoom natively: a control
collapses tasks into pitches and pitches into projects, aggregating edges. Colour is status, border
is priority, badge is owner; solid edges are `depends_on`, dashed is containment. Dragging node to
node creates a dependency — one PATCH, one file, one commit.

**Filters narrow the record set before layout**, which is what keeps several hundred nodes readable.

### 9.4 Timeline

The computed schedule handed to frappe-gantt, grouped by owner or project, cycle boundaries as
vertical rules, today as a line. **Bars drag only to change `assigned_on`. End dates are derived and
structurally undraggable** — making it impossible is how the UI teaches the model.

A ~300-line hand-rolled SVG Gantt is kept as a fallback. The scheduler emits exact spans, so the
renderer is interchangeable; evaluate frappe-gantt against ~200 real rows on day one.

`?format=json` on every endpoint, because someone will want matplotlib within a fortnight.

## 10. Scope

### 10.1 v1

In priority order. Items 1–14 ship; everything below the line does not.

1. `openproj.model` — schemas, round-trip parse/serialise, `validate_all` with status-gated rules
2. `openproj.schedule` — the pure scheduler, explanations, property tests
3. `openproj check` CLI and a git hook or CI job running it
4. Read-only viewer: table with filters and search, graph, timeline, rendered from a checkout
5. `openproj.store` — bare repo, TreeBuilder commits, fetch/push behind an optional remote
6. Scoped compare-and-swap, frontmatter key-merge, three-way body merge
7. `openproj.index` — full rebuild, backlinks, filter/search structures, validation gate, atomic swap
8. Create form with required-field enforcement and reviewer suggestions
9. Inline table editing, pitch page with a plain `<textarea>` and preview, graph edge creation by drag
10. GitHub OAuth plus org-membership check. **One permission level: member = full write**
11. SSE invalidation plus 30 s poll
12. `derived/` written by CI — `INDEX.md`, `schedule.json`, `graph.mmd`
13. Seed corpus: the short projects from the HackMD table, hand-converted, committed as real data
14. README and a one-page runbook: run it, fix a broken repo, get the data out

**— cut line —**

Deferred: per-record history tab; PR→status automation via `links/prs.jsonl` (v1 types the `prs:`
list by hand, which is thirty seconds of work and proves whether anyone cares); CodeMirror; image
paste; SQLite index export; saved views; comment threads; mobile layout; sharded storage; reviewer
load in the scheduler.

### 10.2 Never build

Write these in the README so a future contributor does not:

- Real-time collaborative editing. Compare-and-swap *is* the design; a CRDT is a different
  architecture.
- Email or notification infrastructure. Its own project, and Slack exists.
- User-defined custom fields. Edit the model and run a migration script.
- A PR-based editing workflow in the UI. Git exists for that, and the premise is that PRs are the
  wrong default.
- Time tracking, burndown charts, multi-repo support, per-project permissions.
- **Anything that makes the CI bot write entity frontmatter.** The bot owns `links/prs.jsonl` and
  `derived/` and nothing else. If it starts patching frontmatter, bot and humans fight over the same
  files forever. Put the reason in a comment next to the code.

### 10.3 Size budget

~4,000 lines of Python, ~1,000 lines of JavaScript. Materially larger means scope has escaped and
someone should say so out loud.

## 11. Build plan and gates

**Phase 0 — four hours, before any code.** One person runs OpenProject Community locally, builds one
real pitch with three tasks and two dependencies, enables automatic scheduling and looks at the
Gantt. The purpose is to steal its scheduling semantics and to document an off-ramp.

**Phase 1 — 9 days.** `openproj.model` with the validation rules (3d), `openproj.schedule` with
property tests (3d), static read-only table with filters and search, graph and timeline from a
checkout, with no server, no auth and no writes (3d). Seed with the short projects from the HackMD
table — a handful of small, self-contained items across `done`, `wip` and `todo`, converted by hand
with their shaping docs inlined as bodies. Do not import the rest of HackMD or the repo issues; the
point of Phase 1 is to test the model against real work, not to migrate.

Phase 1 front-loads the two things that can kill the project — *does the scheduler produce dates the
team believes, and will anyone fill in the mandatory fields* — for one week rather than nine. A
read-only viewer that dies is a broken bookmark; a write path that dies is data loss. Never invert
that order.

> **Gate 1, day 9.** Show the timeline in a planning meeting. **Continue only if someone argues with
> a date** — that means they read it and believe the model. Silence or polite agreement means stop
> and adopt OpenProject; one week was spent and a useful static page exists either way.

**Phase 2 — writes, 17 days.** Store with TreeBuilder (3d), scoped CAS and merges (4d, mostly
test-writing), index with validation gate and filter structures (2.5d), create form with enforcement
and reviewer suggestions (1.5d), OAuth (1.5d), inline table editing and pitch page (3d), SSE and
poll (1.5d).

**Phase 3 — views and deploy, 10 days.** Graph with edge creation (2.5d), timeline (2.5d), CLI and
check job (1.5d), container and deployment (1.5d), README and runbook (2d).

Subtotal 36 days × 1.3 for OAuth callback URLs, timezone bugs, Cytoscape layout tuning and an
afternoon lost to libgit2 wheels ≈ **47 engineer-days**. One six-week cycle for two people. Ongoing
cost is **1–2 days per month, indefinitely**.

> **Gate 2, end of the first full cycle running on it.** Stop and adopt something off the shelf if
> any of these is true:
> - more than a quarter of active pitches fail `openproj check`;
> - fewer than one `depends_on` edge per two pitches — the graph is decoration;
> - nobody opened the timeline in a planning meeting;
> - the successor named above is no longer willing.
>
> Recorded before the build starts, because criteria authored after a tool exists are never applied
> to it. The cost of stopping is a `git clone`.

## 12. Hosting

**Now: local only.** A git repository on disk, `openproj serve --repo <path> --auth dev --offline`.
No remote, no accounts, no deployment. This is the whole of Phase 1 and most of Phase 2.

**When it is shared: Google Cloud Run.** The container unmodified, scaled to zero. The free tier is
perpetual — 2M requests, 180,000 vCPU-seconds and 360,000 GiB-seconds per month — and this workload
uses roughly 1% of it. Two rules: never set `min-instances=1` (always-on is about seven times the
free grant), and bake the repository into the image so a cold start is a fetch rather than a clone.
At that point the plan repository gains a remote in the C2SM organisation, which is also when
backups start existing.

**An ETH-owned cloud project is optional and is not about capability.** Cloud Run's free tier is
sufficient indefinitely; the only thing an institutional project buys is **account ownership** — a
GCP project on a personal card dies with the person. With a named owner and successor and at least
three project owners, this is adequately mitigated for now. If it later matters, it is one email to
`cps@id.ethz.ch` with the cost centre and Budget Officer, and the same image redeploys unchanged.
There is no technical migration and nothing in the design depends on it.

> **Open risk while local-only: there is no backup.** A single laptop holds the only copy. This is
> acceptable for Phase 1, when the data is a handful of seed records that can be recreated, and stops
> being acceptable the moment anyone treats the tool as the real plan. Adding a remote — even a
> private one — is the fix, and it takes a minute.

## 13. Security

Deferred while local-only; the following applies from the moment a remote exists.

The task list is low-confidentiality. **The real asset is the write credential**, because a token
that can write to a C2SM repository is a supply-chain foothold in a scientific codebase.

- **User login: a GitHub OAuth App with scope `read:org` and nothing else. Never `repo`.** The token
  establishes identity once and is then discarded. Requesting `repo` for login would put thirty
  write-capable tokens in a session store.
- **The server's push credential is separate and never derived from a user token.** Preference
  order: a GitHub App installation token (single repo, `contents: write`, one-hour lifetime, so a
  token leaked into a log expires by itself) > a write deploy key > a PAT (worst: tied to a human and
  survives their departure). It must be structurally incapable of touching `icon4py` or `gt4py`.
- **Branch protection** blocking force-push and deletion on the plan repository. The app only ever
  needs fast-forward commits, so this is free, and it turns "history destroyed" into "revert three
  commits".
- Secrets live in the platform's secret store, never in the image or the repository.

## 14. Risks

Ranked by probability × damage.

1. **Mandatory fields go unfilled and the tool becomes decoration.** The most likely failure and it
   is not technical: the team cannot currently keep a 38-row table current, and this asks for more
   per-item discipline, not less. Mitigations, in order of effectiveness: enforcement at creation, so
   the fields are never absent in the first place; reviewer suggestions, so the good answer is the
   default; CI failure that names the author; the persistent "missing required fields" count and
   filter (§5.5); and Gate 2. Accept that no amount of building fixes an adherence problem — but note
   that enforcement at creation is a genuinely different intervention from the honour system the
   HackMD table relied on.
2. **The author leaves.** Truck factor is now 2 (jcanton, msimberg), which is above the base rate for
   this class of tool but not comfortable. Mitigation is architectural: plain markdown, under 5,000
   lines, no npm, no database, no migrations, `derived/` rendering the whole board on GitHub with
   zero infrastructure, a CLI that does everything the web does, and a one-page runbook.
3. **Concurrent editing turns out to be co-editing.** Scoped CAS covers ~95% of collisions
   invisibly, but if the real pattern is three people co-editing one pitch body during a shaping
   session, this architecture is wrong and polish will not save it. Shape Up assigns a bet to a small
   team, so this should be rare by construction — verify against two real cycles rather than assume.
4. **The scheduler looks wrong once and trust never recovers.** Tie-break rules are arbitrary by
   necessity, so the per-date explanation is the trust mechanism, not a nice-to-have. Hatch
   unowned and estimated spans so a forecast never looks like a commitment.
5. **Someone runs `--workers 4`** to scale it up and silently corrupts writes. The `flock` that
   refuses to boot goes in during week one.
6. **Hand-edited YAML breaks the tracker.** The validation gate serving the last good index and
   naming the breaker and the exact error, from v1. Parse-permissively (§5.2) is what keeps this a
   warning banner rather than an outage.
7. **No backup while local-only.** §12.

**Least-certain technical choices, to resolve early:** frappe-gantt's behaviour at a few hundred
rows with dependency arrows (evaluate day one, keep the SVG fallback); `pygit2`'s
`merge_file_from_index` signature across versions (pin the version and write a test against it on
day one); whether `ruamel` round-trip survives every hand-formatted frontmatter block the team
writes.

## 15. Test strategy

- `openproj.schedule` — the three property tests from §7.3, plus golden-file tests over the seed
  corpus.
- `openproj.model` — round-trip fidelity: parse, serialise, assert byte equality against a corpus of
  hand-formatted files including comments, unusual key order and non-ASCII. Plus a rules table test
  asserting each status gate fires exactly when it should, and that grandfathered entities produce
  warnings rather than blockers.
- `openproj.store` — a concurrency test spawning N writers against a temporary bare repo, asserting
  all N commits land. This is the test that would have caught the 87.5% write-loss failure mode.
- `openproj.index` — a malformed-commit test asserting the last good index keeps serving and the
  error names the file and line.
- The seed corpus — the short projects from the HackMD table, plus a few synthetic entities covering
  edge cases the real data lacks (a diamond dependency, a cycle, an unowned item, an item overrunning
  its cycle) — is the shared input for all of the above.
