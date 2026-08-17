---
id: task-3a52d8
kind: task
title: Compile the wrapper with f2py to generate the turbdiff_f2py module
parent: pitch-3c9a41
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: null
assignees:
  - yiluchen1066
assigned_on: null
cycle: 28
priority: high
depends_on:
  - task-3e07b2
tags:
  - greenline
  - turbulence
  - f2py
prs: []
---

Step 2 of the four numbered solution steps in `[Greenline] Python bindings on Turbulence granule` (https://hackmd.io/@gridtools/S1airZWAJx).

> Compile the wrapper with f2py to generate the `turbdiff_f2py` module. This module can be imported directly into `icon4py`.

Detail from the note: "With the wrapper Fortran code in place, we use `f2py` to compile and generate a Python extension module (e.g., `turbdiff_f2py`)", importable as `import turbdiff_f2py as td`. The module provides Python-callable interfaces to the Fortran logic and handles the conversion between NumPy arrays and Fortran arrays under the hood.

**Migration notes.** `depends_on: [task-3e07b2]` is stated by the source ("With the wrapper Fortran code in place…"), not inferred. No effort estimate anywhere → `person_weeks: null`. Status `done` follows from row 22 being Done and from the cycle-34 pitch's statement that the granule with F2Py Python bindings exists and runs on CPU.
