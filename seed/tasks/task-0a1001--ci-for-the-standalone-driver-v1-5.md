---
id: task-0a1001
kind: task
title: CI for the standalone driver v1.5
parent: pitch-0a0001
status: wip
owner: jcanton
assignees: [jcanton, nfarabullini]
reviewers: [msimberg, iomaganaris]
review_waived: false
assigned_on: 2026-06-29
cycle: 37
priority: 1
depends_on: []
tags: [icon4py, standalone-driver, distributed, ci, gpu]
prs: ["C2SM/icon4py#1303"]
created_schema_version: 2
effort_weeks: 3.5
---

## Problem

The distributed version of the standalone-driver CI job exists and runs, but it does not yet do the
one thing it was built for: fail when single- and multi-rank results diverge. #1303 added the 7-day
validation test asserting bitwise-identical output between 1 and 4 ranks, but only for CPU backends
and only with `CXXFLAGS=-ffp-contract=off`. #1368 extended bitwise checks to the GPU statics and the
driver. What is left is the plumbing that turns those checks into a gate.

Concretely, three things are wrong today:

- The repro block in `ci/base.yml` only applies at `LEVEL == validation`. At `integration` the job
  compiles with FMA contraction and compares against a hand-fitted `atol=1e-13, rtol=1e-14`, so the
  job that runs on most PRs is the one that cannot see a reproducibility regression.
- `ICON4PY_DALLCLOSE_PRINT_INSTEAD_OF_FAIL=1` is set, so the pipeline reports max diffs and stays
  green. It was the right call while measuring — `assert_dallclose` raises on the first mismatch and
  `vn` is first in the field loop, so a `vn` failure meant `w`, `exner`, `theta_v`, `rho` were never
  compared at all — but it is now hiding exactly what we want asserted.
- Chia Rui's 2-GPU equator artefact after 7 days has never been reproduced. Runs with 2 and 4 ranks
  on `gtfn_gpu` and `gtfn_cpu` off the `scientific_validation_distributed_driver` branch show no
  funny line at the equator, so either the branch already fixed it or the decomposition in the
  original run differed. Until we can reproduce it on main we do not know what the job should catch.

## Appetite

3.5 weeks. This carried over from cycle 36 and is the long pole of the pitch; it is what pushes the
pitch past the end of cycle 37 if it slips again.

## Solution

1. Reproduce (or formally retire) the equator artefact: run the driver on main, and on main merged
   into `scientific_validation_distributed_driver`, with 2 and 4 ranks on GPU, checking whether the
   artefact tracks the decomposition boundary (equator only) or forms a cross.
2. Promote the repro flags out of `LEVELS=validation` so the flag set that asserts bitwise is the
   one that runs on merges, not only on the nightly.
3. Drop `PRINT_INSTEAD_OF_FAIL` for gtfn backends and let the job fail.
4. Keep the trigger documented in the job description:
   `cscs-ci run default;SESSIONS=model_mpi;MODEL_MPI_SUBPACKAGES=standalone_driver;BACKENDS=gtfn_cpu;LEVELS=validation`.

## Rabbit holes

- **Per-rank build caches.** `GT4PY_BUILD_CACHE_DIR` must be keyed on `OMPI_COMM_WORLD_RANK`; CI
  gets this free from nox's per-rank envdir, local runs do not. The cache key ignores `CXXFLAGS`, so
  a shared cache root silently reuses contraction-on binaries for a contraction-off run.
- **The fork's auto-CI.** Project 83052503 runs the full matrix on push and has pre-existing flaky
  failures (microphysics stencils, dace) unrelated to this work. Read the targeted `model_mpi`
  pipeline, not that one.
- **Runtime.** A 7-day validation run is ~40 minutes. Do not put it on every PR; nightly plus a
  label.

## No-gos

- Do not enable the hard assertion for `dace_gpu` in this task. dace kernel nondeterminism is not
  covered by `ICON4PY_DETERMINISTIC_RBF_COEFFS` and would make the gate flaky on day one.
- No new experiment configurations. JW / R02B04 stays the reference case here.
