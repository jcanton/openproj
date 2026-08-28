---
id: task-0f1002
kind: task
title: Bench the scan against the CPU reference
parent: pitch-0f0001
status: ready
owner: siskinbury
assignees: [siskinbury]
reviewers: [firecresta, avocetline]
review_waived: false
start_date: 2026-08-17
priority: high
depends_on: []
tags: [hearth, scan-operator, benchmark, gpu]
prs: []
created_schema_version: 2
person_weeks: 1.0
---

# Bench the scan against the CPU reference

## Problem

The 6.1x in the pitch is one measurement, taken once, by hand, on one mesh, by the person who
wanted the answer to be large. It is enough to justify the work and nowhere near enough to accept
it: when the second lowering lands, "it is faster" has to be a number somebody else can reproduce
without asking how it was taken, and "it is still correct" has to be a per-field delta rather than
a green tick from a tolerance that was widened to fit.

The two lowerings do not sum a column in the same order and will not be bitwise equal. That is
expected and it is exactly why an unexplained delta must not be allowed to hide behind an
expected one.

This carries no `depends_on` edge to `task-0f1001`, and that is the shape the betting table
asked for: the meshes, the harness and the CSV writer are most of the work and none of them needs
the second lowering to exist. Only the last two boxes below do, and by then the lowering is on a
branch somebody can point the harness at. A hard edge here would have parked Siskin for a
fortnight to no purpose.

## Solution

One benchmark under `benchmarks/scan_prefix.py`, three meshes — `Drum_Hex_20x4_50mm`,
the 80-level drum and a single-column degenerate case — three backends, both lowerings, five
repeats, median reported with the spread beside it. It writes a CSV next to the run rather than
printing, so two runs a month apart can be diffed by somebody who was not there for either.

Correctness in the same harness and from the same runs: for every field the operator touches,
report max absolute and max relative delta between the loop lowering and the prefix lowering,
per level. The pass condition is that the delta is bounded by the accumulated rounding of the
tree order — roughly `log2(nlev)` ulp — and that no level is an outlier against its neighbours. A
carry dropped at a chunk boundary shows up as a step, not as noise, which is how `issue-b3c4d5`
should have been caught the first time.

## Progress

- [x] mesh fixtures and the CSV writer, reusable by the transport benchmark that will want them
- [ ] the delta report, per field per level
- [ ] a first run on both lowerings once `task-0f1001` merges
- [ ] the numbers written into the pitch, replacing the 6.1x
