---
id: proj-000002
kind: project
title: scan_backend
parent: prod-0f0002
status: in_progress
owner: firecresta
assignees: [firecresta, siskinbury]
reviewers: [jackdawrie, hoopoegrove]
review_waived: false
start_date: 2026-06-22
priority: high
depends_on: []
tags: [hearth, scan-operator, backend, dsl, milestone]
prs: ["kilnlab/hearth#412"]
created_schema_version: 2
---

# scan_backend

> The shape of this milestone came out of `note-66dd77`, written the week the bed port first ran
> on a GPU and was slower than it had been on the CPU.

## Problem

hearth lowers a `scan_operator` the same way on every backend: a serial loop over `KDim` carrying
one value from level to level. That is what the Fortran did, it is correct everywhere, and it is
fast on exactly one target. The bed solver is the first subsystem in the port whose hot loop is a
scan, and on `hearth_gpu` it is one thread per column running eighty dependent steps while the
rest of the warp waits — so the bed solve is slower on the GPU that was bought to unblock it.

Nothing in kiln4py can work around this. The serialisation is in the lowering, not in the stencil,
which is why this is a milestone in the DSL and not a rabbit hole in the bed pitch.

## Appetite

Two cycles, 37 and 38, and a hard edge on the second: if the fast lowering is not merged by the
review of 37, the tap-deck work stays shelved and the milestone ends at whatever the benchmark
says.

## Solution

Three pitches, one of them parked. Give the scan a second lowering on the GPU backend and let the
emitter choose between them from the operator's own shape; measure both against the CPU reference
so the choice can be defended; and leave the tap-deck rewrite on the shelf until the first two are
done, because it is the piece that can be dropped without the milestone failing.

Done means the bed solve's forward elimination is no slower on `hearth_gpu` than on `hearth_cpu`,
with the per-field deltas between the two lowerings written down rather than asserted away.

## No-gos

No new frontend syntax: a stencil must not have to ask for the fast path. No multi-node. No work
on the first-crack branch, which is not associative and keeps the loop it has.
