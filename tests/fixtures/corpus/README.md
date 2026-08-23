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
