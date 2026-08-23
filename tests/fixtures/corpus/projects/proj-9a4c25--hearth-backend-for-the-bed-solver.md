---
id: proj-9a4c25
kind: project
title: Hearth backend for the bed solver
parent: prod-7c2b81
status: in_progress
owner: redpollard
assignees: [redpollard]
reviewers: [Whimbrelson]
review_waived: false
assigned_on: 2026-08-13
cycle: null
priority: high
depends_on: []
tags: [hearth, scan-operator, backend]
prs: ["kilnlab/hearth#801"]
created_schema_version: 2
---

# Hearth backend for the bed solver

## Problem

The bed solver is the first subsystem in the model whose hot loop is a `scan_operator`, and hearth
lowers a scan the same way on every backend: a serial loop over `KDim` carrying one value from
level to level. On the CPU that is what the Fortran did and the numbers agree. On `hearth_gpu` it
is one thread per column doing 80 dependent steps while the other 63 lanes of its warp wait, and
the bed solve is then slower on a GPU than on the CPU it was meant to unblock. Nobody in the model
can work around this, because the serialisation is in the lowering and not in the stencil.

## Appetite

Cycles 37 and 38, one pitch each: the operator itself while the bed port is still warm, then the
hardening the year-end shutdown forces on us anyway. This project is not bet — its pitches are,
and its dates are their rollup.

## Solution

Give the scan a second lowering on the GPU backend and let the emitter choose between them, then
freeze the backend API that choice is expressed through before the shutdown so that the model side
can be written against something that will still be there in January.

## No-gos

No new frontend syntax. A stencil that wants the fast lowering must not have to say so: if the
choice cannot be made from the operator's own shape, the answer is that we do not understand the
operator well enough yet.
