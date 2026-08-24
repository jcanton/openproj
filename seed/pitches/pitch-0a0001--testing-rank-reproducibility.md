---
id: pitch-0a0001
kind: pitch
title: Testing rank reproducibility
parent: proj-000001
status: in_progress
owner: merganserly
assignees: [merganserly, jackdawrie]
reviewers: [jackdawrie, hoopoegrove]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: high
depends_on: []
tags: [kiln4py, standalone-driver, distributed, bitwise-reproducibility, ci]
prs: ["kilnlab/kiln4py#2325"]
created_schema_version: 2
person_weeks: 6.0
---

## Problem

The standalone driver is not bit-identical between single- and multi-rank runs, and the tests hide
that. On CPU, `test_standalone_driver_compare_single_multi_rank` is bitwise on `hearth_cpu` only with
`CXXFLAGS=-ffp-contract=off`, which `ci/base.yml` sets only for `LEVEL == validation`; at
`integration` we compile with FMA contraction and compare against a hand-fitted `atol=1e-13,
rtol=1e-14` derived from nothing. On GPU, `--fmad=false` still leaves a ~1.3e-12/step `vel` diff,
root-caused to the batched `cupy.linalg.solve` in
`blend_interpolation.py`: the batch extent is the rank-local corner count, and the 6x6 corner and cell
systems are ill-conditioned enough that assembly, solve and the axis-1 normalisation reductions are
all batch-dependent. Face blends (4x4) are clean, hence the core solver looked innocent.

## Appetite

Six weeks, two people — the cycle-37 continuation of the distributed-driver work.

## Solution

Make CI assert instead of print: drop `KILN4PY_COMPARE_PRINT_INSTEAD_OF_FAIL` so a bitwise
regression fails the pipeline. Remove the remaining rank-dependent arithmetic with deterministic
global means and sums. Where exactness is unreachable, replace the blanket 1e-13 with measured
per-field deltas.

## Rabbit holes

- **emberjit.** The repro block in `ci/base.yml` sets its flags regardless of backend, and emberjit
  has its own nondeterminism: `test_parallel_interpolation` still carries `atol=2e-13`, and
  `KILN4PY_DETERMINISTIC_BLEND_COEFFS` fixes the blend weights, not emberjit kernels. Gate the
  assertion on hearth.
