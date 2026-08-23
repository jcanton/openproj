# Seed corpus

Converted from six rows of the Griddle programme's open-projects board, spanning `done` / `wip` /
`todo` / `shelved` across five subsystems. This is the Phase 1 test fixture and the working
example set — **not anybody's real plan.**

## Everything here is invented

The domain, the people, the pull requests and the calendar are all made up. What is meant to be
real is the *shape*: titles, statuses, subsystem grouping, PR references and body text hang
together the way they would on a live plan, because a fixture that does not is a fixture that
proves nothing. Where a record had no shaping document behind it, the body says so plainly rather
than inventing one.

## What is synthetic — do not read this as a plan

| Field | Status |
|---|---|
| `person_weeks` | Typed to exercise the roll-up. Plausible, never measured. |
| `owner` / `reviewers` on `pitch-1b3f9a`, `task-53a9f0`, `task-5a4e39` | Chosen to give the scheduler somebody to serialise. |
| `owner` / `reviewers` on the other five | Drawn from the same invented roster. Nobody has agreed to any of this, because nobody here exists. |
| `depends_on` marked `# synthetic` | **Invented** to exercise the scheduler. |
| `parent: proj-7e57a0` | Placeholder. See `projects/proj-7e57a0--testing.md`. |
| `proj-7e57a0` itself | Entirely fabricated. |

The four `done` records still have no size. That is deliberate: they exercise the grandfathering
path, where a record created before a rule existed produces a warning rather than a blocker.

## It grew once, and what the second half is for

Everything above describes the seventeen records this corpus started as. On 2026-08-23 it grew to
thirty, and the thirteen added are a second, deliberately separate island: two **products**
(`prod-6d1a70`, `prod-7c2b81`), the project `proj-9a4c25` under one of them, two pitches, four
tasks, two issues, two notes and the cycle records `0037.md` and `0038.md`. It was grown because
four of the six rungs had no file at all here — no products, no issues, no notes, no cycles — so
the promotion graph that `docs/data-model.md` is built around was untested.

**The island shares no worker and no ancestor with the original seventeen**, and that is not a
stylistic choice. `GOLDEN_SPANS` in `tests/test_schedule.py` is derived by hand against the spec's
algorithm and is the only thing in the repository asserting that the scheduler computes the *right*
dates rather than merely agreeing with itself. The scheduler property
`test_property_adding_an_item_that_shares_no_worker_and_no_ancestor_never_moves_that_items_span` is
exactly as narrow as it needs to be to let a corpus grow without moving an existing span — so a new
planned record introduces new people (`redpollard`, `chiffchaffy`, `Whimbrelson`, `stonechatty`) and
hangs under a new ancestor. Issues and notes never reach the scheduler and are free.

If you add to this corpus, do the same thing, and derive any new span by hand *before* comparing it
with a run. The working for the seven island spans is written out under `THE HEARTH ISLAND` in
`tests/test_schedule.py`.

Three files here are wrong **on purpose** and are asserted to be, so do not tidy them:

| File | What is wrong | Why |
|---|---|---|
| `products/prod-7c2b81--hearth.md` | `person_weeks`, `depends_on`, `owner` | The only document in either corpus the three `unread_fields` rules fire on. Two blockers and a warning. |
| `notes/note-b14d6a.md` | `became: [pitch-000000]` | A promotion link that opens nothing, so `state()` falls back to `thinking` instead of claiming a promotion. |
| `cycles/0037.md` | no `reviews_on` | The resolver assumes a four-week build and says so — what a half-filled cycle record looks like. |

`cycles/0038.md` is the one record that has to know about Christmas: eight calendar weeks holding
7.2 build weeks, because four weekday holidays fall inside it.

## The shape it exercises

The invented edges form a **diamond** in the distributed-driver group —
`task-5a4e39` → {`task-5c1d84`, `task-5f062b`} → `task-58d7c6` — which the validator flagged as the
structure the corpus otherwise lacked. `task-2b6c94` depends on `task-31f6c4`, which is `done`, so
the corpus also covers a live item blocked by completed work. That edge originally pointed at
`pitch-2a7f3e` — `task-2b6c94`'s own parent — which is circular by construction and is now a
validation rule in its own right (spec §5.1).

## Before this becomes real data

Replace every row in the synthetic table above with something a human has agreed to, and delete this
section. A fixture that quietly graduates into a plan is how a tracker starts lying.
