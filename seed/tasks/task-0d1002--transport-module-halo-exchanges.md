---
id: task-0d1002
kind: task
title: Halo exchanges in the transport module
parent: pitch-0d0001
status: in_progress
owner: Oxpeckerly
assignees: [Oxpeckerly, nightjarelli]
reviewers: [nightjarelli, hoopoegrove]
review_waived: false
assigned_on: 2026-06-29
priority: high
depends_on: [task-0d1001]
tags: [griddle, transport, halo-exchange, mpi, kiln4py]
prs: ["kilnlab/kiln4py#2108"]
created_schema_version: 2
person_weeks: 2.0
---

# Halo exchanges in the transport module

## Problem

The transport module almost validates under MPI: every field except `q_aroma_new` matches the
single-rank run to roundoff, and that one needs a tolerance above 2e-5. That is neither roundoff
nor FMA contraction noise — it is a stale halo, either a missing exchange or one issued at the
wrong point in the substep. Second order is what changes this: first-order upwind
only needs the donor cell, so its halo width need not survive a reconstruction over the whole
`C2F2C` patch and a flux gathering over `F2C`.

## Appetite

Two weeks — a bounded question: which field, which halo width, which point in the substep.

## Solution

Instrument the comparison to report the max difference per field and per region instead of
aborting on the first mismatch; `assert_allclose_dist` raises immediately and early `vel`-style
fields mask everything after them. Per-region deltas separate a missing exchange from a
mis-ordered one; then audit the module's exchange calls against the stencil access pattern.

## Rabbit hole

- **FP noise versus a halo bug.** Anything at 1e-13 is contraction, anything at 2e-5 is data;
  assert bitwise where the build turns FMA contraction off. The drift does not reproduce on an
  arm64 mac.
