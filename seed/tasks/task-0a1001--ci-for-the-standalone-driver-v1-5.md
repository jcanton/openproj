---
id: task-0a1001
kind: task
title: CI for the standalone driver v1.5
parent: pitch-0a0001
status: in_progress
owner: jackdawrie
assignees: [jackdawrie, merganserly]
reviewers: [nightjarelli, ibisbillie]
review_waived: false
start_date: 2026-08-17
priority: high
depends_on: []
tags: [kiln4py, standalone-driver, distributed, ci, gpu]
prs: ["kilnlab/kiln4py#2211"]
created_schema_version: 2
person_weeks: 3.0
---

## Problem

The distributed standalone-driver CI job runs, but not the one thing it was built for: failing when
single- and multi-rank results diverge. The 7-day validation test asserts bitwise-identical output
between 1 and 4 ranks, but only on CPU backends and only with
`CXXFLAGS=-ffp-contract=off`, which `ci/base.yml`'s repro block applies at `LEVEL == validation`
only — so the job that runs on most PRs compiles with FMA contraction against a hand-fitted
`atol=1e-13, rtol=1e-14`. And `KILN4PY_COMPARE_PRINT_INSTEAD_OF_FAIL=1` keeps it green whatever it
measures: needed while measuring, since `assert_allclose_dist` raises on the first mismatch and `vel`
is first in the field loop, but now it hides the regression.

## Appetite

Three weeks, two people; the long pole of the pitch.

## Solution

Reproduce or formally retire Oxpecker's 2-GPU seam artefact, running the driver on main and on
`validation_distributed_driver` with 2 and 4 ranks on GPU. Promote the repro flags out of
`LEVELS=validation` so the asserting flag set runs on merges, and drop `PRINT_INSTEAD_OF_FAIL` for
hearth backends. Trigger stays documented:
`plant-ci run default;SESSIONS=kiln_mpi;KILN_MPI_SUBPACKAGES=standalone_driver;BACKENDS=hearth_cpu;LEVELS=validation`.

## Rabbit holes

- **Per-rank build caches.** `HEARTH_BUILD_CACHE_DIR` must be keyed on `OMPI_COMM_WORLD_RANK`, and
  the key ignores `CXXFLAGS` — a shared cache root silently reuses contraction-on binaries for a
  contraction-off run.
