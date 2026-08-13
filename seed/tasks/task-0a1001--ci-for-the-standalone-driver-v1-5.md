---
id: task-0a1001
kind: task
title: CI for the standalone driver v1.5
parent: pitch-0a0001
status: in_progress
owner: jcanton
assignees: [jcanton, nfarabullini]
reviewers: [msimberg, iomaganaris]
review_waived: false
assigned_on: 2026-06-29
cycle: 37
priority: high
depends_on: []
tags: [icon4py, standalone-driver, distributed, ci, gpu]
prs: ["C2SM/icon4py#1223"]
created_schema_version: 2
effort_weeks: 3.5
---

## Problem

The distributed standalone-driver CI job runs, but not the one thing it was built for: failing when
single- and multi-rank results diverge. The 7-day validation test asserts bitwise-identical output
between 1 and 4 ranks, but only on CPU backends and only with
`CXXFLAGS=-ffp-contract=off`, which `ci/base.yml`'s repro block applies at `LEVEL == validation`
only — so the job that runs on most PRs compiles with FMA contraction against a hand-fitted
`atol=1e-13, rtol=1e-14`. And `ICON4PY_DALLCLOSE_PRINT_INSTEAD_OF_FAIL=1` keeps it green whatever it
measures: needed while measuring, since `assert_dallclose` raises on the first mismatch and `vn` is
first in the field loop, but now it hides the regression.

## Appetite

3.5 weeks, carried over from cycle 36; the long pole of the pitch.

## Solution

Reproduce or formally retire Chia Rui's 2-GPU equator artefact, running the driver on main and on
`scientific_validation_distributed_driver` with 2 and 4 ranks on GPU. Promote the repro flags out of
`LEVELS=validation` so the asserting flag set runs on merges, and drop `PRINT_INSTEAD_OF_FAIL` for
gtfn backends. Trigger stays documented:
`cscs-ci run default;SESSIONS=model_mpi;MODEL_MPI_SUBPACKAGES=standalone_driver;BACKENDS=gtfn_cpu;LEVELS=validation`.

## Rabbit holes

- **Per-rank build caches.** `GT4PY_BUILD_CACHE_DIR` must be keyed on `OMPI_COMM_WORLD_RANK`, and
  the key ignores `CXXFLAGS` — a shared cache root silently reuses contraction-on binaries for a
  contraction-off run.
