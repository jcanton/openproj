---
id: task-0d1002
kind: task
title: Halo exchanges in the advection granule
parent: pitch-0d0001
status: wip
owner: OngChia
assignees: [OngChia, nfarabullini]
reviewers: [nfarabullini, halungge]
review_waived: false
assigned_on: 2026-06-29
cycle: 36
priority: 0
depends_on: [task-0d1001]
tags: [greenline, tracer-advection, halo-exchange, mpi, icon4py]
prs: ["C2SM/icon4py#1050"]
created_schema_version: 2
effort_weeks: 2.0
---

# Halo exchanges in the advection granule

## Problem

The advection granule almost validates under MPI: every field except `p_tracer_new` matches the
single-rank run to roundoff, and that one needs a tolerance above 2e-5. That is neither roundoff
nor FMA contraction noise — it is a stale halo, either a missing exchange or one issued at the
wrong point in the substep. Second order is what changes this: first-order upwind
only needs the donor cell, so its halo width need not survive a reconstruction over the whole
`C2E2C` patch and a flux gathering over `E2C`.

## Appetite

Two weeks — a bounded question: which field, which halo width, which point in the substep.

## Solution

Instrument the comparison to report the max difference per field and per region instead of
aborting on the first mismatch; `assert_dallclose` raises immediately and early `vn`-style
fields mask everything after them. Per-region deltas separate a missing exchange from a
mis-ordered one; then audit the granule's exchange calls against the stencil access pattern.

## Rabbit hole

- **FP noise versus a halo bug.** Anything at 1e-13 is contraction, anything at 2e-5 is data;
  assert bitwise where the build turns FMA contraction off. The drift does not reproduce on an
  arm64 mac.
