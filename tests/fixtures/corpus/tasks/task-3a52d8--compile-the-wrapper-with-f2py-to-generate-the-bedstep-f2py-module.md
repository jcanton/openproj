---
id: task-3a52d8
kind: task
title: Compile the wrapper with f2py to generate the bedstep_f2py module
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
depends_on:
  - task-3e07b2
tags:
  - griddle
  - throughflow
  - f2py
prs: []
---

Step 2 of the four numbered solution steps in the throughflow bindings pitch.

> Compile the wrapper with `f2py` to generate the `bedstep_f2py` module. This module can be
> imported directly into `kiln4py`.

Detail from the note: with the wrapper Fortran in place, `f2py` compiles it into a Python
extension module — `bedstep_f2py` — which is imported as `import bedstep_f2py as bs`. The module
gives Python-callable entry points to the Fortran and handles the conversion between NumPy arrays
and Fortran arrays underneath.

`depends_on: [task-3e07b2]` is stated by the note rather than inferred: "with the wrapper Fortran
code in place". No effort is recorded for this step. The `done` status follows from the board
entry and from the later pitch confirming that the CPU bindings exist and run.
