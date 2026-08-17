---
id: task-0a1002
kind: task
title: Implement deterministic means
parent: pitch-0a0001
status: ready
owner: samkellerhals
assignees: [samkellerhals]
reviewers: [msimberg, egparedes]
review_waived: false
assigned_on: 2026-08-17
priority: medium
depends_on: []
tags: [icon4py, distributed, reductions, numpy, bitwise-reproducibility]
prs: []
created_schema_version: 2
person_weeks: 2.5
---

## Problem

Global means and sums in icon4py are order-dependent, so their result is a function of the domain
decomposition. Nothing pins the order in which rank-local partial sums are combined, so a global sum
gives a different last bit for 1, 2, 4 and 12 ranks, and single- vs multi-rank comparison can never
be exactly zero for a diagnostic that goes through a mean. Underneath that, numpy 2.3.0 changed the
pairwise-summation blocking, moving the rounding of the rank-local partial itself; 2.2.6 still gives
the old answer, and we handle that by not upgrading.

## Appetite

2.5 weeks; `main...msimberg:icon4py:deterministic-means` is a starting point, not a blank page.

## Solution

Give the reduction a fixed, decomposition-independent summation order, used everywhere a global mean
or sum is taken: cheap version, fixed-order accumulation over a canonical global index ordering;
accurate version, a fixed-point accumulator pre-scaled to a common exponent so integer addition is
exact and therefore associative. Ship it with a test that the same field reduced on 1, 2, 4 and 12
ranks is bit-identical.

## No-gos

- No change to the default numeric path until the cost is measured. If the deterministic reduction
  is slower it goes behind a flag, as `ICON4PY_DETERMINISTIC_RBF_COEFFS` did, defaulting off.
