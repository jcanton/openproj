---
id: pitch-0f0001
kind: pitch
title: Scan operator on the GPU backend
parent: proj-000002
status: in_progress
owner: firecresta
assignees: [firecresta, siskinbury]
reviewers: [jackdawrie, Ptarmigant]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: high
depends_on: []
tags: [hearth, scan-operator, gpu, dsl, backend]
prs: ["kilnlab/hearth#437"]
created_schema_version: 2
person_weeks: 5.0
shaped_by: firecresta
---

# Scan operator on the GPU backend

> Promoted from note-66dd77 — a note by firecresta on 2026-06-02.

## Problem

`scan_operator` has one lowering and it is the sequential one. The emitter writes a loop over the
vertical dimension carrying the accumulator forward, for every backend, and nothing about the
operator changes that. Measured on the bed solver's forward elimination at `Drum_Hex_20x4_50mm`,
`hearth_gpu` is 6.1x slower than `hearth_cpu`: eighty dependent steps per column, one column per
thread, sixty-three lanes of each warp idle for all of them.

Three things sit behind it. The bed port cannot land its solver on GPU, the transport module's
vertical sums are written as loops to avoid the operator entirely, and every new stencil that
wants a carry is being talked out of one in review.

## Appetite

Five person-weeks in cycle 37, two people. That covers the associative case, a benchmark that can
be re-run by somebody else, and the tap-deck writer that has been waiting on a stable emitter
interface. It does not cover the general case, and this pitch is shaped on that being the right
answer rather than a compromise.

## Solution

A scan whose combining function is associative is a prefix sum, and a prefix sum on a GPU is a
solved problem. Add a second lowering that emits a block-wide Hillis-Steele pass over `KDim` with
a second, tiny pass carrying the block boundaries, and put the choice between it and the existing
loop in the emitter: walk the operator body against a whitelist of associative operations — add,
multiply, min, max — and take the fast path only if every operation in it is on the list.

The bed solve's forward elimination qualifies. The first-crack branch does not, and keeps the loop
it has today, unchanged and untouched. That is why the decision is per operator and not per
backend.

## Rabbit holes

- **The whitelist is the work, and it must stay a whitelist.** Deciding associativity by analysing
  a body is where this becomes a research project. Four operations, extended when somebody has a
  stencil that needs a fifth, never inferred.
- **A tree scan is not the same arithmetic as a loop.** The two lowerings sum a column in
  different orders and will not be bitwise equal. `issue-b3c4d5` is the first thing that fell out
  of that, and it is a carry dropped at a chunk boundary rather than a rounding difference — read
  it before assuming any delta is floating-point.

## No-gos

No frontend change: a stencil must never have to ask for the fast path. No multi-node scan. No
work on the first-crack branch. No performance work anywhere else in the emitter while this is
open, however tempting the profile looks.

## For later

Two-dimensional scans, which the chaff-optics work in `pitch-0f0002` will eventually want, and the
same treatment for `reduce_over`, which has the identical problem and no complaining consumer yet.
Both were cut to fit five weeks.
