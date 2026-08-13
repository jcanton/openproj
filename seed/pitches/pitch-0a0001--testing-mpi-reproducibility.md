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

The standalone driver is not bit-identical between single- and multi-rank runs, and the tests we
have hide that rather than report it. Two failure modes keep getting confused for each other. On
CPU, `test_standalone_driver_compare_single_multi_rank` is bitwise on `gtfn_cpu` only with
`CXXFLAGS=-ffp-contract=off`, and `ci/base.yml` sets that flag only for `LEVEL == validation`; at
`integration` we compile with FMA contraction and compare against a hand-fitted `atol=1e-13,
rtol=1e-14` that was never derived from anything. On GPU, `--fmad=false` still leaves a
~1.3e-12/step `vn` diff, root-caused to the batched `cupy.linalg.solve` in `rbf_interpolation.py`:
the batch extent is the rank-local vertex count, and the 6x6 vertex and cell systems are
ill-conditioned enough that assembly, solve and the axis-1 normalisation reductions are all
batch-dependent. Edge RBF (4x4) is clean, which is why the dycore looked innocent.

## Appetite

Six weeks, two people — the cycle-37 continuation of the distributed-driver work.

## Solution

Make CI assert instead of print: drop `ICON4PY_DALLCLOSE_PRINT_INSTEAD_OF_FAIL` where it is safe, so
a bitwise regression fails the pipeline. Then remove the remaining rank-dependent arithmetic with
deterministic global means and sums, so the answer does not depend on how the reduction tree was
cut. Where exactness is not reachable, replace the blanket 1e-13 with measured per-field deltas.

## Rabbit holes

- **dace.** The repro block in `ci/base.yml` sets its flags regardless of backend, and dace has its
  own nondeterminism — `test_parallel_interpolation` metrics still carry `atol=2e-13`.
  `ICON4PY_DETERMINISTIC_RBF_COEFFS` fixes RBF, not dace kernels. Gate the hard assertion on gtfn
  before flipping it.
