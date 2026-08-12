---
id: p-1b3f9a
kind: pitch
title: MPI on CI verify with serial
parent: null
status: todo
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
appetite_weeks: null
assignees: []
assigned_on: null
cycle: null
priority: 3
depends_on: []
tags:
  - greenline
  - mpi
  - ci
prs: []

---

# MPI on CI verify with serial

**Shaping doc not located during migration.** This entity is a stub built from the task-table row alone.

## What the source says

The only source is row `9b` of the `[Greenline] Open projects TABLE`
(https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg), verbatim:

> | 9b | MPI on CI verify with serial | Low | | | | | | Get the tests to verify with mpitask1 instead of mpitask2/4 |

Every other cell of the row is empty: no Status, no Who, no Depends-on, no PR, no Shape doc.
The blank Status cell reads as not started, hence `status: todo`. Priority cell reads `Low`.

## Scope, as far as the source defines it

`mpitask{1,2,4}` are the serialized-reference-data directories used by the icon4py datatests;
the corpus documents the layout as
`icon4py/testdata/ser_icondata/mpitask{1,2,4}/mch_ch_r04b09_dsl/ser_data`
(from `[Greenline] CI for datatests`, https://hackmd.io/@gridtools/SJkkX2wzp).
`mpitask1` is therefore the single-rank (serial) reference dataset, `mpitask2`/`mpitask4` the
2- and 4-rank ones. The row asks for the MPI tests to verify against the serial reference data
instead of the rank-count-matched data.

That one sentence is the entire specified scope. No sub-tasks are enumerated anywhere, so no task
entities were created.

## Search performed (negative result)

Searched all 730 notes listed for the GridTools HackMD team plus the three notes known to be
reachable only by direct URL. The string `mpitask` appears in exactly three corpus bodies: this
task table, a copy of it, and the `CI for datatests` note quoted above — none of which is a shaping
document for this row. No note title or body describes verifying MPI tests against serial data.

Related but distinct notes found (recorded here as context, **not** as this row's shaping doc):

- `[Greenline] Distributed tests in CI` — https://hackmd.io/O4Fymu1dTxqTZSC8rdiVVw — the table's
  `[MPI CI project]` link, attached to row **9**, not 9b. Its open-task list covers rank counts
  ("run with 2 ranks and 4 ranks (currently only 4 ranks)") and "enable testing with weisman klemp
  experiment (distributed and single-rank)", but never the mpitask1-as-reference idea. Its
  `## Appetite` section is empty.
- `[ICON4Py] Standalone driver single- vs multi-rank debugging` (cycle 36) —
  https://hackmd.io/@gridtools/SyAIH-7lzl — an unfilled template whose Problem statement is
  "Single- and multi-rank runs don't agree fully." Concerns the standalone driver, not CI test
  verification data.

## Fields left null and why

- `appetite_weeks`: no appetite is stated for this row anywhere — not in the table, not in any
  note. Left null rather than guessed.
- `assignees` / `assigned_on`: the Who cell is empty; no date is stated anywhere.
- `cycle`: no shaping doc, therefore no cycle tag to read.
- `depends_on`: the Depends-on cell is empty. Note that row 9b is printed immediately beneath row 9
  (`MPI on CI`, Done) inside the MPI block of the table, but the source declares no dependency and
  none was invented; no other row depends on 9b either.
- `prs`: the PR cell is empty.
- `hackmd`: no shaping doc exists to point at.

