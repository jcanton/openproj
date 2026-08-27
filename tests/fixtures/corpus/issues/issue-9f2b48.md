---
id: issue-9f2b48
kind: issue
title: Reduction order is not pinned in the driver comparison
status: ready
reported_by: merganserly
opened_on: 2026-06-02
tags: [reductions, distributed]
pitched_into: [task-31f6c4, task-5c1d84]
created_schema_version: 2
---

Written in the first week of cycle 36, while reproducing the 2-GPU seam artefact, and deliberately
kept off that row: the seam is a wrong field on one rank, this is two right answers that differ.

The comparison sums over the vertical before it compares, and the sum runs in whatever order the
backend hands the cells over. One rank and twelve ranks therefore disagree in the last two digits
of a quantity the datatest compares at `rtol=1e-11`. Neither number is wrong. The test is.

The distributed driver pitch treats this as part of "set up bit-identical tests for code
validation" and never separates it out, which is why it is here as an issue rather than as a sixth
task under that pitch: it is the reason two of the existing tasks exist, not a piece of work
beside them.

## What it was pitched into

- `task-31f6c4`, the throughflow verification, because that is where the comparison itself lives.
  It is `done`.
- `task-5c1d84`, the deterministic-means attempt, because that is the candidate fix. It is `ready`
  and has been for a cycle.

One done and one not, so this reads `in_progress` — which is the state the source describes in
prose ("there is a test and it is wrong") without ever having a word for.

## It is also named from the plan

`task-7d9f52` lists this issue in its `depends_on`. That edge points from a scheduled record at
something the scheduler never dates, which is legal and is the only such edge in this corpus: the
suite cannot honestly be rerun until the comparison is pinned, and saying so is worth more than
the date the edge cannot supply. The task's start comes from its own `start_date` and from
`task-7c8e40`; this issue contributes nothing to it but the sentence.
