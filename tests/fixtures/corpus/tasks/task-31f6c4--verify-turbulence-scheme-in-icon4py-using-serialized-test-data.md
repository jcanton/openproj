---
id: task-31f6c4
kind: task
title: Verify turbulence scheme in icon4py using serialized test data
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
  - task-3a52d8
tags:
  - greenline
  - turbulence
  - verification
prs: []
---

Step 3 of the four numbered solution steps in `[Greenline] Python bindings on Turbulence granule` (https://hackmd.io/@gridtools/S1airZWAJx).

> Verify turbulence scheme in `icon4py` using serialized test data.

Detail from the note:
- The serialized data does not need to be regenerated — "it has been generated and stored for the Fortran verification".
- Read the data under savepoint `icon-turbulence-verify-entry` as the input.
- Compare the output with the data under savepoint `icon-turbulence-verify-turbdiff-exit`.

**Migration notes.** `depends_on: [task-3a52d8]` — the verification consumes the `turbdiff_f2py` module produced by step 2, which the note says "can be imported directly into `icon4py`". No effort estimate anywhere → `person_weeks: null`. Status `done` is inherited from row 22's Done status; the note itself records no per-step outcome (its Progress checklist was left as the unfilled template).
