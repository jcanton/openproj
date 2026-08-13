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
prs: []
created_schema_version: 2
effort_weeks: 2.0
---

# Halo exchanges in the advection granule

## Problem

The advection granule almost validates under MPI. Every field except one matches the
single-rank run to roundoff; `p_tracer_new` does not, and it needs a tolerance above 2e-5 to
pass. 2e-5 is not roundoff and it is not FMA contraction noise — it is a stale halo. Either an
exchange is missing, or one is issued at the wrong point in the substep and the second-order
MIURA reconstruction reads a neighbour value from before the update.

That failure mode is specific to second-order advection. First-order upwind only needs the
donor cell, so the halo width that was correct for it is not necessarily correct once the
reconstruction pulls in the whole `C2E2C` patch and the flux gathers over `E2C`. This is why
the item sits after the least-squares coefficients: the reconstruction has to exist before its
halo requirement is real.

## Appetite

Two weeks. It is a bounded question — which field, which halo width, which point in the
substep — and if it is still open after two weeks the answer is that the granule's exchange
structure needs re-shaping rather than patching.

## Solution

Work backwards from the field. Instrument the comparison so it reports the max difference per
field and per region instead of aborting on the first mismatch — `assert_dallclose` raises
immediately and `vn`-style early fields mask everything after them, so a run that "fails on
one field" may never have compared the rest. With per-region deltas we can see whether the
error lives in the halo rows or leaks into the interior, which distinguishes a missing exchange
from a wrong one.

Then audit the granule's exchange calls against the stencil access pattern: which fields the
reconstruction reads over `C2E2C`, which the flux reads over `E2C` plus `rel_idx`, and where
each is written. Add the exchange the audit demands, then re-run and expect the tolerance to
collapse to zero.

## Rabbit holes

- **Exchange is a black box, sometimes.** Do not start by reading the exchange implementation.
  Start by proving which field and which region is stale.
- **Confusing FP noise with a halo bug.** Bitwise MPI equality only holds when the build turns
  FMA contraction off; at integration level the comparison falls back to a hand-fitted
  `atol=1e-13, rtol=1e-14`. Anything at 1e-13 is contraction, anything at 2e-5 is data. Assert
  bitwise where it is available so the two never get mixed up.
- **Reproducing locally.** The CPU single-versus-multi-rank drift does not reproduce on an
  arm64 mac — all rank counts and both contraction settings come out bitwise identical there,
  because contraction decisions are compiler-specific. Local runs are still fine for
  correctness and crash checks; do not spend half an hour a run chasing the tolerance locally.
- **Per-rank build cache.** The gt4py cache key does not include `CXXFLAGS`, so a flag change
  without a separate cache root silently reuses the wrong binaries.

## No-gos

- Rewriting the granule's exchange scheduling to overlap communication with computation. That
  is a performance bet and this is a correctness one.
- Loosening the tolerance to make the test green.
