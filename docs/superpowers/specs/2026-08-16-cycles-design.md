# Cycles as more than a label — design

**Status:** analysis complete, three decisions open. Nothing implemented.
**Proposal by:** jcanton, 2026-08-16.
**Method:** five independent analyses of the codebase (data model, capacity semantics,
write semantics, blast radius, lifecycle) followed by three adversarial critiques
(over-building, contradictions, failure-in-use). Every claim below was re-verified by hand
against the working tree.

---

## The proposal

> Make a cycle some sort of entity (not in the graph view). On creation choose the duration
> (4 build + 2 cool-down) and set each dev's availability for that cycle. At the bottom of
> the cycle's page, list every `ready` and `in_progress` item — no `shaping`, no `done` — and
> assign assignees and reviewers to the ones being worked on, stamping them with the cycle.

The instinct is right and the question behind it is the right question: **does this cycle's
bet fit, and who is on the hook.** What follows argues that the answer costs about a tenth of
what the proposal describes, and that three bugs it would build on top of are worth more than
the feature.

---

## 1. What is already broken

Four defects found while analysing the proposal. Three of them mean the tool is currently
saying something untrue, and all four sit directly under the proposed feature.

### 1.1 The corpus already contradicts itself on carryover — **this is the important one**

```
task-0a1001   cycle: 37   2026-08-17 → 2026-09-09   overrun: None
task-0b1002   cycle: 36   2026-09-10 → 2026-10-05   overrun: 7.43 weeks
```

Two identically-situated records: both `in_progress`, both assigned inside cycle 36, both with
jcanton on them, ~3.5 weeks each. One reports late, one reports fine. **The only difference is
which integer somebody typed in the `cycle` field.**

`cycle: int` does two jobs at once — it says *which betting table chose this*, and it says
*which end date the overrun is measured against* (`schedule.py:100`). Re-stamping a carried-over
item silently forgives its overrun.

The proposal makes that re-stamping a one-click gesture, performed at exactly the moment work is
slipping. That is the single thing most likely to make the team stop trusting the dates, and it
fails Gate 1 in the unrecoverable direction: someone says *"that one's been late since June"*,
the screen shows no flag, and both are right — because the record was re-bet that morning.

### 1.2 `_overrun` measures against the end of cool-down

`schedule.py:100-103` compares against `window[1]`, the last day of the whole 6- or 8-week
window. Shape Up says work lands by the end of *build*; cool-down is not build time. Every
overrun is therefore understated by the cool-down length, and some are hidden entirely.

### 1.3 The server never loads `people.yaml`

`web.py:69` hardcodes `("defaults.yaml", "cycles.yaml", "holidays.yaml")`. `model._CONFIG_FILES`
lists four, including `people.yaml`. Verified: `openproj check` sees 17 known people, the server
sees zero — so the roster check that rejects an unknown login is **silently off in the web UI and
on in CI**. One-line fix.

### 1.4 `_duration_weeks` is dead arithmetic

```python
availability = config.nominal_availability
ratio = config.nominal_availability / availability if availability else 1.0
```

`x/x`. Identically 1.0 for every possible config (`schedule.py:85-86`). The test that guards it
runs at `nominal_availability=0.6` and cannot fail, because that field is both numerator and
denominator. Deleting the ratio is not a cleanup: it is what makes *"should availability stretch
the bars?"* an unaskable question rather than a one-line edit away from re-introducing the bug
the spec explicitly names (it stretched every three-week bet to five).

---

## 2. What availability must mean

**Capacity, never duration.** All four analyses that addressed it agreed independently.

- D1 defines appetite as *elapsed weeks at nominal availability* — not person-weeks. If a
  50%-available dev's three-week bet drew as six weeks, appetite would silently change meaning.
- The capacity-1 rule in `_place` already serialises a person's work. Availability does not
  change when a thing lands; it changes **how much fits**.

So the capacity check is:

```
sum of appetite of what a person is bet on   ≤   availability × build_weeks
```

with both sides in elapsed weeks at nominal availability. And a warning in the field's own help
text, not in a design doc: **availability changes what fits, never when it lands.** Otherwise the
first person to set 0.5 and see an unchanged timeline will conclude the field does nothing —
and someone will "fix" it by dividing.

---

## 3. Why a cycle should not be an `Entity`

Of `Entity`'s 17 fields, three are meaningful on a cycle. Several are worse than meaningless:

- **`status`** — a cycle's phase is a function of `today` and its dates. Storing it produces the
  classic lie: `status: active` on cycle 36 that nobody flipped. And any word not in
  `STATUS_ORDER` is a hard blocker (`model.py:376`), while any word *in* it drags in the gates
  demanding an owner, a reviewer and a size.
- **`depends_on`** — "38 follows 37" is temporal, not a dependency. Writing it puts a cycle into
  the scheduler DAG and onto the graph.
- **`assignees: list[str]`** — the field somebody will reach for to hold the roster. It cannot
  carry a percentage, which is the number the whole feature exists for.
- **Silently scheduled.** A cycle entity is not `shelved` and not `done`, so it reaches
  `_place` with no size — `size_weeks` hands back `default_task_effort` and cycle 37 gets a
  half-week Gantt bar that nobody wrote.

The proposal's own instinct — *"which does not appear in the graph view?"* — is the type error
showing through. A record that has to be excluded from a dozen places is not a subtype.

---

## 4. The betting table already exists

```
/?status=ready&status=in_progress          sorted by cycle
```

`apply_filters` is AND-across-fields, OR-within-field (`index.py:172`); the client filters on the
same nine fields; `cycle` is a sortable column; and `cycle`, `assignees` and `reviewers` are all
inline-editable. That URL is the proposal's list, with facets for narrowing by project or owner,
and it writes through the existing `PATCH /api/entity/{id}` — no new write surface, no batching,
no second security review. The audit trail is `git log --since` on the meeting day.

**The delta between that URL and the proposed page is one number:** how much each person is
holding against what they can hold.

---

## 5. The plan

### Slice 1 — now (~10 lines of Python, one config scalar, one data decision)

1. `cooldown_weeks: 2` in `defaults.yaml`, beside `nominal_availability` and
   `default_task_effort`. Build-end is `window[1] − cooldown_weeks` for every cycle in both
   corpora. No per-cycle data entry, no migration, no reshaped `Config.cycles`.
2. Retarget `_overrun` to build-end (§1.2). `GOLDEN_OVERRUNS` gets re-derived by hand;
   `GOLDEN_SPANS` does **not** move — `_overrun` annotates, it does not place.
3. Delete the availability ratio (§1.4), and the 0.6 test that cannot fail with it.
4. Load `people.yaml` in `web.py` (§1.3).
5. One warning: *"cycle N has no dates in config/cycles.yaml"*. Today a typo'd number silently
   disables the overrun check for that record, because `schedule.py:100` uses `.get()`.
6. Fix `task-0a1001` back to `cycle: 36` so the corpus stops contradicting itself.

### Slice 2 — after one real betting meeting

One column on `/people`, which already exists and is already per-person: weeks held in the
current cycle against build weeks, over capacity in red. No availability coefficient yet —
everyone is 1.0.

### Slice 3 — only when somebody asks by name, with a number they have already been keeping

`availability: {login: fraction}` as a plain map inside the existing `config/cycles.yaml`, and
multiply the column by it. Both loaders filter on `Config.model_fields`, so old corpus and old
code keep working. One `Config` field, one multiplication.

### Stays unbuilt unless slice 2 proves otherwise

A `Cycle` type, a `cycles/` directory, `write_many` and batch commits, `/api/cycle/{n}/bets`,
`bet_on`, `bets:`, `cycles: list[int]`, per-cycle `build_weeks`/`cooldown_weeks`,
`created_schema_version` on a cycle, a bespoke page, a nav entry, per-cycle static files, and the
fifteen validation rules the analyses proposed between them.

**Why so aggressive a cut:** `src/openproj/` is at 4,604 lines against the spec's stated ~4,000
budget, which says *"materially larger means scope has escaped and someone should say so out
loud."* The event being tooled happens eight times a year, for twenty people, in one room, with
one driver.

---

## 6. Three decisions that are yours

**D-C1. What does `cycle:` mean?**
*Where it was bet* (never overwritten, so the overrun flag keeps accusing) or *where it is being
worked* (overwritten on carryover, so the flag clears)? Recommendation: **where it was bet.**
It preserves the one date judgement the tool makes. Carryover is then shown by
`cycle == N or (in_progress and cycle < N)`, not by re-stamping.

**D-C2. At which level is capacity charged?**
On the seed corpus, jcanton's cycle-37 load is **10.0 weeks** charged at leaves (matching the
scheduler's rollup rule) or **11.0 weeks** charged at pitch level (matching "we bet fourteen
pitches"). Same person, same instant, a full bet apart. Whichever is chosen, the page must print
the rule under the total.

**D-C3. Is over-capacity a blocker, a warning, or just a number?**
Recommendation: **just a number**, at least until slice 2 has run twice. A blocker here fails CI
on the person who honestly declared they were busy — `cli.py:7` already says a warning that fails
the build is a rule that gets reverted rather than adopted.

---

## 7. Gates

**Gate A** — after slice 1, run one real betting meeting off `/?status=ready&status=in_progress`.
Continue only if somebody asks for the capacity number during the meeting. If nobody does, the
column is decoration.

**Gate B** — after two meetings with the column, continue to slice 3 only if somebody asks to
record a specific person's availability *and already has the number*. A field nobody is
maintaining by hand today will not start being maintained because it has a form.
