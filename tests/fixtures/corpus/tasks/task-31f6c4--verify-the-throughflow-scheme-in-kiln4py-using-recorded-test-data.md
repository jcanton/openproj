---
id: task-31f6c4
kind: task
title: Verify the throughflow scheme in kiln4py using recorded test data
parent: pitch-3c9a41
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: null
assignees:
  - yellowhammer7
assigned_on: null
cycle: 28
priority: high
depends_on:
  - task-3a52d8
tags:
  - griddle
  - throughflow
  - verification
prs: []
---

Step 3 of the four numbered solution steps in the throughflow bindings pitch.

> Verify the throughflow scheme in `kiln4py` using recorded test data.

Detail from the note:
- The recorded data does not need to be regenerated — it was already captured for the Fortran
  verification and is stored beside it.
- Read the tap point `airflow-verify-entry` as the input.
- Compare the output against the tap point `airflow-verify-bedstep-exit`.

`depends_on: [task-3a52d8]` because the verification consumes the `bedstep_f2py` module that
step 2 produces, which the note says can be imported straight into `kiln4py`. No effort is
recorded anywhere for this step. The `done` status comes from the board entry; the note itself
records no per-step outcome.
