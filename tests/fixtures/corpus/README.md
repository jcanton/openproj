# Seed corpus

Converted from the six shortest self-contained rows of the icon4py HackMD task table
(`hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg`), spanning `done` / `wip` / `todo` / `shelved` across five
subsystems. This is the Phase 1 test fixture and the working example set — **not the team's real
plan.**

## What is real

Titles, statuses, subsystem grouping, PR references, and the body text of every entity. Bodies were
taken from the linked shaping documents where one existed; where none did, the body says so plainly
rather than inventing one.

## What is synthetic — do not read this as the plan

| Field | Status |
|---|---|
| `person_weeks` | Supplied by jcanton, 2026-08-12. Real intent, not measured. |
| `owner` / `reviewers` on `pitch-1b3f9a`, `task-53a9f0`, `task-5a4e39` | Chosen by jcanton. |
| `owner` / `reviewers` on the other five | **Drawn at random from `C2SM/icon4py` contributors.** Nobody has agreed to any of this. |
| `depends_on` marked `# synthetic` | **Invented** to exercise the scheduler. |
| `parent: proj-7e57a0` | Placeholder. See `projects/proj-7e57a0--testing.md`. |
| `proj-7e57a0` itself | Entirely fabricated. |

The four `done` entities still have no size. That is deliberate: they exercise the grandfathering
path, where an entity created before a rule existed produces a warning rather than a blocker.

## The shape it exercises

The invented edges form a **diamond** in the distributed-driver group —
`task-5a4e39` → {`task-5c1d84`, `task-5f062b`} → `task-58d7c6` — which the validator flagged as the
structure the real data lacked. `task-2b6c94` depends on `task-31f6c4`, which is `done`, so the
corpus also covers a live item blocked by completed work. That edge originally pointed at
`pitch-2a7f3e` — `task-2b6c94`'s own parent — which is circular by construction and is now a
validation rule in its own right (spec §5.1).

## Before this becomes real data

Replace every row in the synthetic table above with something a human has agreed to, and delete this
section. A fixture that quietly graduates into a plan is how a tracker starts lying.
