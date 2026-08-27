# Time in openproj: one field per fact, and no invented numbers

Written 2026-08-27, from a session with jcanton. Everything here was decided in
that conversation; the reasoning is kept because the decision is the expensive
half.

The tool had four separate ideas about time and no single place that held any of
them. A field named after an HR event stood for three different things depending
on status. An appetite nobody typed was invented at 0.5 weeks and then summed,
scheduled, charged to people and drawn as a bar. An end date was derived and
never recorded, so nothing could ever say whether a bet landed. And the moment a
record was marked done it fell out of every ledger that could have learned from
it.

This is one change because those four are one fact wearing four hats.

## 1. `assigned_on` becomes `start_date`

The field is a date and it records when work began. `assigned_on` reads as
something that happened to a person, and the column it feeds is already called
Start. `_SIZE_FIELD`'s one-field-one-word cleanup is the precedent.

**No back-compat, and that is not the same as silence.** An unknown key lands in
`record._unread` and is re-emitted verbatim by `serialise`, so a file still
saying `assigned_on:` parses clean, keeps the dead key forever, loses its date
and says nothing at all. `_RETIRED` is the mechanism already built for exactly
this — it holds one entry today, `shaped_by` — and it gains a second:

```python
"assigned_on": "start_date records when the work began — "
               "move the date there and delete this key",
```

That is not backwards compatibility. The field is gone; the file is told so.

**Three string literals in JavaScript that no Python rename reaches.**
`DERIVES_DATES`, the popup's prefill of today, and the WHY sentence on the Start
column. Miss the first and editing a start date in the table patches the row in
place instead of re-deriving, so Start and End keep showing dates computed from
the old value until somebody reloads. Miss the third and the tooltip reads
"Start is derived from start_date."

**The write door takes any key.** The record PATCH handler keeps every field in
the payload but `id`, with no check against `model_fields`, and `patch_text`
writes whatever it is handed. A tab left open across the deploy PATCHes
`assigned_on`, gets a 200, and commits a dead key into a file the validator will
then warn about forever. The door gets an allowlist in this change, beside the
`_reject_*` helpers that already refuse bad types and bad cycles.

### 1b. A start date in the past

Today the field means three things by status. At `ready` it is discarded if it
has passed — the start is `max(floor, start_date, blocker_ready)`. At
`in_progress` it *is* the start, with the floor and the blockers bypassed. At
`done` it is the entire span.

Under the name `assigned_on` that was tolerable. Under "Start date" it is a lie:
you type last Monday on a ready task and the Start column answers today, and
`_explain` is coded to stay silent in precisely that case (`if start <= floor:
return None`).

**The rule is scoped to status, and it has to be, or a legitimate edit becomes
impossible.** At `in_progress` a past start date is not merely allowed, it is the
correct value — "I started this on Monday and it is now Wednesday" is the normal
case, and the `in_progress` gate already demands the field. Unscoped, a blanket
refusal would force people to change the status first and backfill the date
second, which is the wrong order and the one everybody would get wrong.

So:

| Status | A `start_date` in the past |
| --- | --- |
| `thinking`, `shaping`, `ready` | **blocker** at the door, refused with 422 |
| `in_progress`, `done` | expected; this is what the field is for |

**And the door cannot be the whole rule.** A date typed as *future* becomes past
by the passage of time, with nobody editing anything, so no `_reject_*` ever
fires. The same predicate therefore has a twin in `validate_all`: a blocker for a
date typed into the past, a warning for one that drifted there. One function, two
callers — this repository has been bitten three times by one fact with two
implementations (the search blob, the `(none)` sentinel, and `appetite_weeks`
reading as three different numbers across three pages).

With the drift case named, `_explain` stops being silent: a ready record whose
stated date has passed says so, rather than showing a start nobody asked for and
offering no sentence about it.

## 2. There is no default appetite

`size_weeks` returns `(config.default_task_effort, True)` when `person_weeks` is
absent. The number is computed and never stored, so no file "has the default" and
nothing needs clearing — the only files carrying `person_weeks: 0.5` are two
fixture tasks where somebody chose it, and a chosen 0.5 is indistinguishable from
a defaulted one by construction. The whole change is deleting the fallback.

**`size_weeks` returns `float | None`.** Its own docstring is the argument for
doing it there rather than at the call sites: *"Read here rather than reached for
directly, so the scheduler, the index and the pages cannot disagree about what a
missing one means."* Ten call sites, three of which throw the `defaulted` flag
away today and must answer the question instead of inheriting an answer.

**An unsized leaf gets no span at all.** Not an `unscheduled` one. `Span.unscheduled`
is not a "no answer" state — it is `start=end=today`, and the flag is read in
exactly one place in `src/`: the timeline's `drawn` filter. The rows payload does
not carry it, the detail page prints `{} → {}` regardless, the cycle page prints
`{start} → {end}`. So an unsized task would read Start 27 Aug / End 27 Aug in the
table, styled `derived` exactly like a real forecast, with the End tooltip still
claiming "Derived from the start and the appetite", sorting to the top of a
Start-ascending sort — and simply absent from the timeline. Two pages, two
answers, and the table is the one people use.

The precedent for "no honest answer" already exists and every view already copes
with it: the childless project, which does `continue` and gets no span. That is
the landing.

**A floor span would be worse than none.** The parent rollup is
`start=min(child.start), end=max(child.end), estimated=any(child.estimated)` —
`unscheduled` is not in that constructor. So one unsized child would pin a
pitch's start to today, the overrun would be measured against that fabricated
end, and nothing on the parent row would mark it.

**Work in progress must be sized.** The size gate is `ready` only today, so the
unsized-and-running state is reachable through the normal path rather than by
skipping a rung — icon4py-plan has three such records. The gate extends to
`in_progress`.

**Shaping and thinking work is legitimately unsized, and the ledger must say
so.** The gate deliberately does not reach them: a bet nobody has shaped has no
appetite yet, and demanding one would be demanding a guess. But those records are
in `counts_in`, so today they are each charged half a week; after the removal they
contribute nothing, and the cycle total quietly drops with no reason given. So the
cycle and people pages carry a count of what was skipped —
`bet: 3.0 of 7.8 weeks · 5 bets not sized` — rather than a smaller number and
silence.

**`estimated` retires and `historical` takes its channel.** `Span.estimated` is
fed solely by the defaulted flag, so after this change the timeline hatch, the
legend row "appetite assumed", the screen-reader text, the row key and the `*`
suffix on two pages are all code that can never fire — a legend key explaining a
mark nobody will ever see. Meanwhile a recorded, measured end (§4) would otherwise
draw with the identical bar as a pure forecast. So the mark moves: `estimated`
goes, and `historical` — set on every done record's span today and read by
nothing — gets the hatch it never had.

## 3. What the tasks add up to, in the table

The reading view already answers this well: `8.0 · 5.1 in tasks`, with the second
number warning-coloured when it exceeds the bet. The table does not, and the
table is where people look.

**The comparison is already computed, and the warning already reaches the
table.** `_rollup_problems` fires when the sized children exceed the parent's
stated appetite, yields its field as `person_weeks`, and `MARK_COLUMN` routes
that to the size column, where the message hangs on the cell as a `sev-mark`.
Nothing here writes a second comparison; a second one would drift from the first.

**The pitch keeps its own appetite.** Replacing it with the children's sum was
considered and refused: `_rollup_problems`' guard is `if total <= stated:
return`, so making `stated` *be* the sum makes that condition true by
construction and "cut scope, or re-bet it" can never fire again — gone from
`check`, from `index.problems`, from the `has_blocker` filter. In Shape Up the
appetite is the fixed box and the tasks are what somebody proposes to put in it.
Collapsing the box into its contents deletes the question the tool exists to ask.

**The cell shows the sum, not both numbers.** jcanton, 2026-08-27: the colour
already says whether it is under, level or over, so repeating the bet beside it is
a number for nothing. And naming the contributing records was refused for the same
reason — the table is a tree by default, so the tasks that make up the sum are the
rows directly underneath.

| State | Tint | Glyph |
| --- | --- | --- |
| sum < appetite, every child sized | good | `▾` |
| sum = appetite, every child sized | `.inherited` | `=` |
| sum > appetite | warn | `▴` |
| any child unsized | muted, not good | `?` |

**The fourth state is not optional.** With the default gone, a six-week pitch
holding three one-week tasks and four unsized ones sums to 3 and would paint
green — green for a bet nobody has estimated, which is the exact inversion of what
the existing warning text says about that same data ("the N without a size can
only add to that"). Good has to mean *known* to be under.

`.inherited` rather than purple, on jcanton's agreement: the class already means
"this value came from the work underneath", which is what this is, and purple is
shaping's hue. One visual language, not two.

**The cell is read-only when it is a rollup.** A cell that displays a derived
number and opens an editor on a stored one is a cell that asks you to type at a
value you cannot see. The bet stays editable from the record's own page.

**The betting table gains the tree view**, so a pitch's tasks sit under it there
too, where their appetites remain editable — which is where the sum is actually
changed.

**One arithmetic, not two.** `_tasks_add_up_to` claims in its docstring to be
"the same number `_rollup_problems` compares against the appetite … so the
sentence on the page and the sentence in `check` cannot disagree". It is not:
it reads `index.progress[id].total`, which charges the default per unsized child,
while `_rollup_problems` sums only sized ones. Today the reading view's number is
silently inflated above the one `check` warns on. §2 fixes it, and a test pins the
two against each other so it cannot drift back.

## 4. `end_date`: store the actual, never the estimate

**The forecast stays derived.** A stored estimate has no writer and cannot have
one: the derived end moves on inputs nobody edits on that record — a blocker
slipping, worker contention, a cycle's review date, midnight. Left unrefreshed the
file says one date while the index says another, and the timeline, the cycle
"until" and the carryover list all keep using the span, so the number on the
record is the one number nothing else agrees with. Refreshed, it is a commit per
record per recompute on a protected branch under a single-writer lock, each one
invalidating every reader's index and 409-ing every browser holding a page
rendered against the previous head. This is the same drift already refused for the
start date.

**The actual is stored, and asked for at the transition.** Marking a record done
raises the existing missing-fields popup with `end_date` prefilled to today.

**Required, at a new rule version.** The gate is a blocker, shipped at a
`rule_version` above the plan's `created_schema_version`, so existing done records
warn rather than block — grandfathering only works that way round, and the corpus
carries records annotated `# was fabricated during migration; unknown` that no
required field can express. This means bumping `schema_version` 4 → 5 in
`seed/config/defaults.yaml` **and** in the plan repo. Shipped without the bump it
warns forever and blocks nothing.

**The bulk path has to answer too.** The bulk status edit refuses rather than
asks — "None of these can be Done yet: …" — and `end_date` is empty on every row
somebody is about to mark done, so the moment this gate lands, "select the
finished tasks, set done, one commit" would answer with that refusal every single
time. The bulk panel asks once and applies one end date to the selection. The
detail page's own save path gets the same ask, so there is one rule rather than
one per surface.

### 4b. Making it readable

Collecting a date nothing reads is not a feature. Three things read it:

- **The End column and the timeline bar.** The done branch builds
  `Span(start=start_date, end=start_date)`, so a finished record's End cell shows
  its *start* date and its bar is a dot. It ends at `end_date` now.
- **`overruns_cycle_weeks` for done records.** `_overrun` is never reached on the
  historical branch, so the one number that says whether a bet landed inside its
  cycle is `None` for exactly the records that could answer. It is computed there
  too.
- **The overrun sentence names the right cycle.** The detail page formats
  `record.cycle`, but the number came from `cycle_of(record, by_id)`, which walks
  up to the pitch holding the bet. Tasks carry no cycle of their own, so four seed
  task pages read **"▲ overruns cycle None by 4.7 weeks"** — the one sentence that
  says a bet did not fit its box, unreadable. Hidden from the tests because 11 of
  15 corpus tasks happen to carry their own `cycle:`. The measured cycle travels
  on the span beside the number, so the display and the computation cannot pick
  different ones.

## 5. What a cycle delivered

`counts_in` returns False for `done` and `shelved` on its first line, and it is
the only gate in `Index.load` and `carried_into`. So opening cycle 37's page after
the review shows every person at `0.0 wk of 4.0`: the work they did all cycle
stopped counting the moment it was marked done, and the over-capacity flag can
only ever be true about the future.

**`counts_in` is not widened.** It answers "what are this person's next weeks
spent on", which is a forward-looking question and is read by the load bars and
the capacity percentages. Widening it would change what every one of those numbers
means.

Instead the cycle page gains a **delivered** block: the done records whose
recorded end fell inside this cycle's window, each with the bet it was made at,
the date it ended, and whether it ran past its cycle. The planned figures above it
keep their present meaning.

```
Cycle 37
  Planned    jcanton  2.0 / 4.0 wk
  ─────────────────────────────────────────────
  Delivered  pitch-370004   bet 8.0 · ended 14 Oct
                            ▲ 3 wk past its cycle
```

**What this still cannot answer, and why that is honest.** An end date gives
elapsed calendar time, not effort. An appetite is in *person*-weeks. So "we bet
four weeks and it took seven" remains unanswerable, because nothing records what
was actually spent. An `actual_weeks` field was considered and deferred: it is a
second number to keep true, and the date is the one somebody will actually type.
The delivered block says what shipped and when, and does not pretend to say what
it cost.

## 6. Dates are never compared to dates

`validate_all` has no date-versus-date rule and takes no `today`. At the door,
`_reject_bad_types` checks only that two fields are numeric, and the date coercion
accepts any parseable ISO date with no range check — the only date-range check in
the application is the one for cycle files.

So `2025-09-11` typed for `2026-09-11` commits with a 200, and then
`span.start <= window[1] and span.end >= window[0]` can never be true, so the
record silently drops out of `counts_in`, out of `Index.load` and out of
`carried_into` for every cycle, while `openproj check` reports the plan clean. A
cycle quietly loses a person's work with no error to chase.

§1b puts the first date-versus-date rule in place. This section is the general
one: a date more than a configured distance outside the plan's own cycle windows
is refused at the door and warned about in `check`, on the same one-predicate-two-
callers shape.

## 7. The plan repository, in lockstep

Nineteen files in icon4py-plan carry `assigned_on`. Two repositories, two deploys,
and it cannot be atomic — so the question is which side goes red for the length of
the window.

- **Plan first.** The old code ignores an unknown `start_date`, so nineteen files
  lose their date to the old scheduler: twelve `in_progress` records go dateless
  and snap to today's floor. Nothing turns red.
- **Deploy first.** Every one of those twelve becomes a blocker — "work in
  progress needs the date it was assigned" — sitting directly above a visible
  `assigned_on:` line in the same file. `openproj check` exits 1 and the plan
  shows a red banner.

Grandfathering cannot soften the second: the rule is version 1 and every plan file
carries `created_schema_version: 2`, and grandfathering requires the rule to be
*newer* than the file.

**Plan first**, therefore, and the window is minutes: the plan repository's rewrite
is a scripted rename plus the `schema_version` bump, pushed immediately before the
deploy. A dateless window is quiet and self-healing; a red window teaches people to
ignore a red banner.

## What is deliberately not in this change

- **`actual_weeks`.** See §5.
- **Re-betting as a record of its own.** A standing item bet again each cycle
  still reads as a permanent overrun, because `cycle:` records where the bet was
  first made and is never re-stamped. The fix is a second record, not a re-stamp,
  and it is its own design.
- **Widening `counts_in`.** See §5.
- **Any change to `_duration_weeks`.** Staffing still shortens a bar. jcanton
  asked that assignee count stop counting towards a rolled-up appetite, and
  reading settled it: `_weighed` takes `person_weeks` undivided, and a pitch with
  children never reaches `_duration_weeks` at all — it rolls up its children's
  dates and returns first. The clause was already true. `GOLDEN_SPANS` is
  untouched by this whole change, which is the outcome worth having.
