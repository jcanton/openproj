---
id: pitch-0a0001
kind: pitch
title: Testing MPI reproducibility
parent: proj-000001
status: wip
owner: msimberg
assignees: [msimberg, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: []
tags: [icon4py, standalone-driver, distributed, bitwise-reproducibility, ci]
prs: ["C2SM/icon4py#1368"]
created_schema_version: 2
appetite_weeks: 6.0
shaped_by: jcanton
---

## Problem

The standalone driver is still not bit-identical between single- and multi-rank runs on every
backend/configuration we care about, and the tests we have hide that rather than report it.

Two distinct failure modes, repeatedly confused for each other:

1. **CPU: FMA contraction.** `test_standalone_driver_compare_single_multi_rank` on `gtfn_cpu` is
   bitwise only with `CXXFLAGS=-ffp-contract=off`. Mikael narrowed a long flag list down to exactly
   that one (`ef37610f1`). `ci/base.yml` sets it together with
   `ICON4PY_TEST_EXPECT_MPI_REPRODUCIBLE=1` (atol=rtol=0) **only** for `LEVEL == validation`. At
   `LEVEL=integration` we compile *with* contraction and fall back to a hand-fitted
   `atol=1e-13, rtol=1e-14`. That number was never derived from anything; any codegen change (adding
   a `concat_where`, say) reshuffles roundoff and tips a marginal element over. It is a tripwire
   that fires on the wrong events.
2. **GPU: static-data seed.** `--fmad=false` removes the contraction part but a ~1.3e-12/step `vn`
   diff survives, repeating to 17 digits across formula variants and both backends — so not
   scheduling noise. Root-caused in #1368 to the batched `cupy.linalg.solve` in
   `rbf_interpolation.py`: batch extent is the rank-local vertex count, and the 6x6 vertex and cell
   systems are ill-conditioned enough that assembly, solve *and* the axis-1 normalisation reductions
   are all batch-dependent. Edge RBF (4x4) is clean, which is why the dycore looked innocent.

Still open on top of that: Chia Rui's 2-GPU equator artefact after 7 days, never reproduced by
anyone else; numpy 2.3.0 changing pairwise-summation blocksizes and therefore global sums (2.2.6 is
still fine); and the fact that we compare fields against one blanket tolerance instead of knowing
which fields actually move.

## Appetite

Six weeks, two people. This is the cycle-37 continuation of the distributed-driver work; if it is
not closed by the end of cycle 37 we ship what asserts and document the rest.

## Solution

Two threads. First, make CI assert instead of print: drop
`ICON4PY_DALLCLOSE_PRINT_INSTEAD_OF_FAIL` where it is safe, so a bitwise regression fails the
pipeline. Second, remove the remaining sources of rank-dependent arithmetic — deterministic global
means/sums, so the answer does not depend on how the reduction tree was cut. Where exactness is not
reachable, replace the blanket 1e-13 with measured per-field deltas so the tolerance is evidence,
not a guess.

## Rabbit holes

- **dace.** The repro block in `ci/base.yml` sets its flags regardless of backend, and dace has its
  own nondeterminism (`test_parallel_interpolation` metrics still carry `atol=2e-13` with a "dace
  undeterministic" TODO). `ICON4PY_DETERMINISTIC_RBF_COEFFS` fixes RBF, not dace kernels. Gate the
  hard assertion on gtfn before flipping it.
- **Chasing FP noise on a laptop.** np={2,4} x contraction on/off is bitwise 0.0 on this mac; Apple
  clang makes different contraction decisions than CI's aarch64/GCC. Go straight to
  `LEVELS=validation` and stop burning 35 minutes a run.
- **gt4py cache keys.** The build cache key does not include `CXXFLAGS`. Separate cache roots per
  flag set, or you silently benchmark the wrong binary.

## No-gos

- No change to the production path. Determinism switches stay opt-in via env flag; cupy stays the
  default for RBF coefficients.
- Not certifying diffusion here. `kh_smag_e` is clamped to 0 in the JW test, so the smag path is
  inert and only the nabla4 term is exercised. A config with active smag is a separate bet.
- No rewrite of the halo-exchange machinery beyond the `z_nabla2_e` exchange already kept from #1368.
