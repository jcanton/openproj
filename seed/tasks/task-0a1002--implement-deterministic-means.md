---
id: task-0a1002
kind: task
title: Implement deterministic means
parent: pitch-0a0001
status: todo
owner: samkellerhals
assignees: [samkellerhals]
reviewers: [msimberg, egparedes]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 2
depends_on: []
tags: [icon4py, distributed, reductions, numpy, bitwise-reproducibility]
prs: []
created_schema_version: 2
effort_weeks: 2.5
---

## Problem

Global means and sums in icon4py are order-dependent, so their result is a function of the domain
decomposition. Two paths feed the same bug:

- **Reduction order across ranks.** A global sum assembled as a tree over rank-local partial sums
  gives a different last bit for 1, 2, 4 and 12 ranks. Nothing in the current code pins the order in
  which partials are combined, so single- vs multi-rank comparison can never be exactly zero for any
  diagnostic that goes through a mean.
- **numpy's blocksizes.** numpy 2.3.0 changed the pairwise-summation blocking, which changes the
  rounding of the rank-local partial itself; 2.2.6 still produces the old answer. So a lockfile bump
  can move a "bitwise" result without a single line of our code changing. We currently handle this
  by not upgrading, which is not a strategy.

This is the same class of bug as the RBF-coefficient seed found in #1368 — there the batch extent of
`cupy.linalg.solve` was the rank-dependent quantity, and the fix was to make the whole computation
batch-independent rather than to widen a tolerance. Global means want the same treatment.

## Appetite

2.5 weeks. There is a starting point already:
`main...msimberg:icon4py:deterministic-means`. It needs more work before it is usable, but it is not
a blank page.

## Solution

Give the reduction a fixed, decomposition-independent summation order and use it everywhere a global
mean or global sum is taken.

The cheap version is a fixed-order accumulation over a canonical global index ordering; the accurate
version is a compensated or fixed-point accumulator (pre-scaling to a common exponent so that
integer addition is exact and therefore associative). Anurag's IPDPS 2014 paper is the reference for
the fixed-point variant and is worth reading before choosing — the cost of a reproducible reduction
is usually one extra pass, not an order of magnitude.

Deliverable: deterministic mean/sum used by the driver diagnostics and by anything the MPI
comparison test touches, plus a test that the same field reduced on 1, 2, 4 and 12 ranks gives
bit-identical results. If that lands, the numpy pin stops mattering, which is the real prize — the
current constraint of "do not upgrade past 2.2.6" is invisible to anyone who did not live through it.

## Rabbit holes

- **Doing this on the GPU first.** cupy reductions have the same batch-extent sensitivity as the RBF
  solve. Get the host path right and tested, then decide whether the GPU version is a fixed-chunk
  reduction or a host round-trip. Do not chunk-tune before there is a reference answer to compare
  against.
- **Turning every reduction deterministic.** Only the ones that enter the comparison or the printed
  diagnostics need it. A deterministic reduction inside a hot solver loop is a performance decision,
  not a correctness one, and belongs to a different conversation.
- **Chasing numpy.** Do not audit numpy's summation internals. Pin the version, write the test that
  would have caught the 2.3.0 change, and move on.

## No-gos

- No change to the default numeric path in production runs until the cost is measured. If the
  deterministic reduction is slower, it goes behind a flag like `ICON4PY_DETERMINISTIC_RBF_COEFFS`
  did, defaulting off.
- Not touching the halo-exchange implementation. This is about how partials are combined, not about
  how they are communicated.
