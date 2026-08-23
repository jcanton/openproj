---
id: pitch-6f2d18
kind: pitch
title: Scan operator on the GPU backend
parent: proj-9a4c25
status: in_progress
owner: redpollard
assignees: [redpollard, chiffchaffy]
reviewers: [Whimbrelson]
review_waived: false
assigned_on: 2026-08-13
cycle: 37
priority: high
depends_on: []
tags: [hearth, scan-operator, gpu]
prs: ["kilnlab/hearth#802"]
created_schema_version: 2
person_weeks: 2.0
shaped_by: Whimbrelson
---

# Scan operator on the GPU backend

> Promoted from note-a03c59 — a note by Whimbrelson on 2026-07-08.

## Problem

`scan_operator` has one lowering and it is the sequential one. Every backend gets a loop over the
vertical dimension that carries the accumulator forward, which is correct everywhere and fast on
exactly one target. Measured on the bed solve at `Drum_Hex_20x4_50mm`, the forward elimination is
6.1x slower on `hearth_gpu` than on `hearth_cpu`, and the profile is not a mystery: 80 dependent
steps per column, one column per thread, the rest of the warp idle for all of them.

## Appetite

Two person-weeks in cycle 37, two people. That is enough for the associative case and a benchmark
that says whether it was worth it. It is not enough for the general case, and the shaping below
turns on that being an acceptable answer.

## Solution

A scan whose combining function is associative is a prefix sum, and a prefix sum on a GPU is a
solved problem: a block-wide Hillis-Steele pass over `KDim` with the carry between blocks handled
by a second, tiny scan. So we add a lowering that emits that, and a check in the emitter that
decides whether it may: the operator's body is walked, and if every operation in it is drawn from
the associative set the fast path is taken, otherwise the sequential loop is emitted exactly as
today.

The bed solve's forward elimination qualifies. The first-crack branch does not, and must keep
working unchanged — which is the real reason the choice is made per operator rather than per
backend.

## Rabbit holes

- **The check is the work, not the kernel.** Deciding associativity from a stencil body is where
  this becomes a research project if we let it. The rule is a whitelist of operations, not an
  analysis: add, multiply, min, max, and nothing else until somebody needs more.
- **Reduction order is not the same order.** A tree scan sums a column in a different sequence
  from a loop, so the two lowerings are not bitwise equal and never will be. That is a fact to
  measure and write down, not a bug to chase — see `issue-9f2b48`.

## No-gos

No change to the frontend, no attribute on the operator asking for the fast path, and no work on
the first-crack branch. Multi-node is somebody else's cycle.
