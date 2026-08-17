# Cycles, betting and capacity — design

**Status:** all three slices implemented, 2026-08-16. Open questions Q1–Q3 answered.
**Proposal by:** jcanton, 2026-08-16. Decisions D-C1 … D-C4 taken 2026-08-16.
**Method:** five independent analyses of the codebase followed by three adversarial critiques,
then two rounds of correction from jcanton. Every claim about the code was verified by hand.

---

## 0. The correction that reframes everything

**D-C4 (decided): `appetite_weeks` and `effort_weeks` are PERSON-weeks — the work one person
would need — and assignees divide them.**

This overturns **D1** of the original spec, which says the opposite:

> | D1 | `appetite_weeks` means **elapsed weeks at nominal availability**, not person-weeks |

D1 was wrong about how the team actually estimates. It was not a small error, and three things
fall out of it:

**1. The scheduler's durations are wrong today, in two compounding ways.** `_duration_weeks`
returns the stated size as elapsed time, and `_place` then books *every* assignee for that whole
span. A pitch with appetite 6 and three assignees is currently drawn as 6 elapsed weeks and
charges 18 person-weeks of calendar. Under D-C4 it is **2 elapsed weeks and 6 person-weeks**. The
seed corpus has 11 entities with more than one assignee, so this is not a corner case.

With exactly one assignee at full availability the two models agree, which is why nothing ever
looked wrong.

**2. Availability *does* belong in the duration.** I previously advised — from D1 — that
availability must affect capacity and never dates. Under D-C4 that advice is wrong:

```
elapsed_weeks = appetite ÷ Σ availability(assignee)
```

One person at 60% takes a 3-week bet 5 weeks. **That is the correct answer**, not the bug the
old spec calls out at line 362. The old draft's `size / availability` was only a bug under D1's
definition; it is right under D-C4. The dead `x/x` ratio in `_duration_weeks` becomes a live
computation rather than a deletion.

**3. Adding people makes work finish sooner** — which is what the room believes when it staffs a
pitch with three names, and what the tool has never modelled.

### What this costs

`GOLDEN_SPANS` in `tests/test_schedule.py` moves. That is correct and expected: the goldens pin
the current, wrong, semantics. They get re-derived once, by hand, with the new definition stated
in the file.

---

## 1. The other decisions

**D-C1 (decided): `cycle:` means where it was bet.** Never overwritten on carryover, so the
overrun flag keeps accusing. Carryover is shown by `cycle == N or (in_progress and cycle < N)`,
never by re-stamping. This is the single thing protecting the tool's one date judgement.

**D-C2 (answered rather than decided): capacity is charged to whatever carries assignees.**
The question was: a pitch says appetite 6, its three tasks say 2 + 2 + 2 — do you count 6, or 6,
or 12? The rule needs no decision because assignment answers it:

- You assign people to a **task** → the task is charged.
- A pitch whose children carry the assignees charges **nothing itself** — its appetite is a
  rollup, and charging both double-counts.
- A pitch with no tasks yet, staffed directly, charges its own appetite.

This is the same rule `schedule()` already uses for spans (`schedule.py:191-199`: a parent with
children is a rollup and never books capacity), so both screens agree by construction.

**D-C3 (decided): over-capacity is a warning on the cycle page, with numbers.** Not a `Problem`,
not a CI blocker. A blocker here fails the build on whoever honestly declared they were busy, and
`cli.py:7` already says a warning that fails the build is a rule that gets reverted.

---

## 2. What the team does today

From the cycle-37 sheet (hackmd.io/GGkElar4QK-33TXRhbKxAg):

```
Length: 4 weeks
Betting table: 14.07.2026        Review meeting: 11.08.2026 - 11:00

## Available people:
Christos: 100%      Edoardo: 3 weeks       Hannes: half cycle
Ioannis: 60% of half cycle                 Mikael: 50%

## Goal
## Tasks
Title                          | Appetite   | Developers                 | Support
[CWP] STAC Browser             | full cycle | Christos 50% + Kostantinos | Nikki
[GT4Py] Development work       | full cycle | Till & Hannes & Sara       | Enrique
[ICON4Py] GPU bitwise reprod.  | 1-2 weeks  | Mikael                     | Jacopo
```

Four things this tells us:

- **There are no totals.** The sheet records availability and staffing and never adds them up.
  The computed number is the whole value openproj adds; everything else is transcription.
- **Availability is free text**, and inconsistent: `100%`, `3 weeks`, `half cycle`,
  `60% of half cycle`. A number in a form is a real improvement, not bureaucracy.
- **Appetite is prose** — `full cycle`, `1-2 weeks`. openproj already forces a number.
- **`Support` is a role openproj does not have.** Distinct from reviewer — the sheet has both
  concepts, and openproj has owner / assignees / reviewers / shaped_by. Open question below.

---

## 3. The plan

The table stays what it is: the overview of everything. The betting table gets its own page,
because a betting table needs the one thing an overview cannot show — how much of each person
is spoken for.

### Slice 1 — make the arithmetic mean what the team means

No new page, no new record. This is the foundation both screens stand on.

1. `_duration_weeks` becomes `appetite ÷ Σ availability(assignees)`, defaulting every unlisted
   person to 1.0, and floored so an all-zero roster cannot divide by zero.
2. `_place` charges each assignee `appetite ÷ n_assignees` rather than booking all of them for
   the whole span.
3. Re-derive `GOLDEN_SPANS` and `GOLDEN_OVERRUNS`, with D-C4 written into the test file.
4. Rewrite D1 in the original spec and mark it superseded, with the date and the reason. A spec
   that quietly contradicts the code is worse than no spec.
5. While in here, three verified defects that sit directly underneath: `_overrun` measures
   against the end of cool-down rather than the end of build; `web.py:69` never loads
   `people.yaml`, so the roster check is off in the UI and on in CI; and an undated cycle number
   silently disables the overrun check (`schedule.py:100` uses `.get()`) — one warning fixes it.

### Slice 2 — the cycle record

`cycles/37.md`, a file with frontmatter and a body, **not** an `Entity`. It reuses the whole
existing write path — `patch_text`, per-key frontmatter merge, scoped compare-and-swap — and the
body is where the sheet's `## Goal` goes.

```markdown
---
cycle: 37
starts_on: 2026-07-14      # the betting table, and the first day of build
reviews_on: 2026-08-11     # the review meeting; build ended the working day before
# Fraction of the BUILD weeks, not of the whole window. 0.5 on a 4-week
# cycle is 2 weeks of capacity.
availability:
  jcanton: 0.5
  msimberg: 1.0
  halungge: 0.5
---

## Goal

Reproducibility and the land port are the two that cannot slip.
```

**Amended 2026-08-17.** This slice shipped with `build_weeks` and `cooldown_weeks` and they are
gone: the two boundaries are meetings somebody puts in a calendar, and a length is a prediction of
one. The team's cadence says so plainly — the end of build is the brainstorm for the next cycle,
and the end of cool-down is the next cycle's betting table — so both are dates that exist whether
or not they are four and two weeks apart. Everything else is derived in `Config.with_plans`: the
last build day, the cool-down end (the next cycle's `starts_on`, stored once), and the length in
**working** weeks with the holidays taken out, which is what `capacity` is charged against.

Not an `Entity` because of what `Entity` would drag in: a cycle has no `status` that is not
derivable from its dates, `depends_on` between cycles is temporal rather than a dependency and
would put cycles in the scheduler DAG and on the graph, and `assignees: list[str]` cannot carry
a percentage — which is the number the whole feature exists for. It would also reach `_place`
with no size and draw itself a half-week Gantt bar nobody wrote.

`config/cycles.yaml` keeps the dates it already has until every cycle has a record; the loader
prefers the record when one exists. No migration of the 15 files carrying `cycle: <int>`.

### Slice 3 — the page

`/cycle/{n}`, in three parts, matching the sheet the team already keeps:

**Setup** — dates, build and cool-down weeks, and the roster: one row per person with a
percentage. Rendered as `50% · 2.0 weeks` so the number and its meaning are never apart.

**The bet** — every `ready` or `in_progress` entity, exactly as jcanton described, with
assignees and reviewers editable inline and a tick that stamps `cycle: N`. This is the existing
table's row markup, payload, cell editor and people combobox — the same machinery, filtered, with
one extra column.

**Load** — per person: held ÷ available, as a bar, over capacity in red with both numbers shown.
Held is `Σ appetite ÷ n_assignees` over what they are assigned in this cycle, by D-C2. Beside it,
that person's actual scheduled end date out of `index.spans` — because a green capacity bar next
to a timeline that runs into November is the failure that stops a room trusting the tool, and
one column prevents it.

---

## 4. Open questions

**Q1 — answered: no `support` field.** jcanton: *"we don't do support in openproj. we have
reviewer for that and that role includes support, but makes people accountable."*

**Q2 — answered: even split.** One number to maintain instead of one per person per task. The
real sheet's `Christos 50% + Kostantinos` is more faithful and is not worth the typing yet.

**Q3 — answered: per-cycle is what counts.** The cycle record holds the availability; anyone it
does not name works at `nominal_availability`. `config/people.yaml` seeds the *roster* on the
setup page — otherwise a cycle nobody has been bet into yet has no names to set availability
against, and setting them is the first thing you do — but it holds no rates.

---

## 5. Gates

**Gate A** — after slice 1, the timeline redraws with different dates for every multi-assignee
item. Show it in a planning meeting. Continue only if the new dates look *more* right than the
old ones to someone who was not in this conversation.

**Gate B** — after slice 3 has run one real betting meeting, keep the availability field only if
it was filled in before the second meeting. A field nobody maintains is decoration, and the
sheet's `60% of half cycle` shows how much the team is willing to write down when it matters.
