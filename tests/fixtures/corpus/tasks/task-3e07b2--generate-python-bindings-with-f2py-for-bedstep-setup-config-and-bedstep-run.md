---
id: task-3e07b2
kind: task
title: Generate Python bindings with f2py for bedstep_setup_config and bedstep_run
parent: pitch-3c9a41
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: null
assignees:
  - yellowhammer7
start_date: null
cycle: 28
priority: high
depends_on: []
tags:
  - griddle
  - throughflow
  - f2py
prs: []
---

Step 1 of the four numbered solution steps in the throughflow bindings pitch.

> Create wrappers for `bedstep_setup_config` and `bedstep_run`, since `f2py` does not support
> `pointer` or `target` attributes.

Detail from the note: running `f2py` directly on the original module routines is not workable,
because those routines take `pointer` and `target` arguments. The way round it is to expose the
pointer arguments as plain NumPy arrays in the wrapper's own interface; inside the wrapper the
arrays are handed to `hearth` fields and associated with the Fortran pointers there. The two
wrappers, for `bedstep_setup_config` and `bedstep_run`, are to be built as one.

No effort is recorded for this step — the board has no effort column and the note's Progress
checklist was left as the empty template. The `done` status follows from the board entry and from
the cycle-34 pitch confirming the CPU `f2py` bindings work. The assignee is the pitch's single
named developer; no per-task start date is stated, so `start_date` is null.
