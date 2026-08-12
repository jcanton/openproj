---
id: t-3e07b2
kind: task
title: Generate Python bindings with f2py for turbdiff_setup_config and turbdiff_run
parent: p-3c9a41
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
effort_weeks: null
assignees:
  - yiluchen1066
assigned_on: null
cycle: 28
priority: 1
depends_on: []
tags:
  - greenline
  - turbulence
  - f2py
prs: []
---

Step 1 of the four numbered solution steps in `[Greenline] Python bindings on Turbulence granule` (https://hackmd.io/@gridtools/S1airZWAJx).

> Create wrappers for `turbdiff_setup_config` and `turbdiff_run`, since `f2py` does not directly support `pointer` or `target` attributes.

Detail from the note: direct usage of `f2py` on the original granule routines is not feasible because they use `pointer` and `target` attributes. The workaround is to expose those pointer arguments as regular NumPy arrays in the wrapper interface; these arrays can then be converted to GT4Py fields and internally associated with Fortran pointers within the wrapper. The wrappers for `turbdiff_setup_config` and `turbdiff_run` are to be combined into one wrapper.

**Migration notes.** The source states no effort estimate for this step (the task table's effort column is empty on every row, and the note's Progress checklist was left as the unfilled template) — `effort_weeks: null`. Status `done` follows from the parent row 22 being marked Done and from the cycle-34 pitch confirming the CPU `f2py` bindings work. Assignee inherited from the pitch's single named developer (Who = `Y` = Yilu Chen); no per-task assignment date is stated, so `assigned_on` is null.
