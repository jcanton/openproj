---
id: task-53a9f0
kind: task
title: Reproduce the 2-GPU equator artefact
parent: pitch-5e7b1c
status: wip
owner: msimberg
reviewers: [jcanton]
effort_weeks: 2
assignees: []
assigned_on: 2026-08-13
cycle: 36
priority: 2
depends_on: []
tags: [icon4py, standalone-driver, distributed, gpu]
prs: []
---

From the Progress list of *[ICON4Py] Distributed driver*
(<https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA>), verbatim:

- [ ] reproduce chia rui's results
  - [x] run standalone driver with **2 and 4 ranks** (to see if the domain decomposition makes a
    difference (equator only or "cross"?)) on gpus, using branch
    <https://github.com/C2SM/icon4py/tree/scientific_validation_distributed_driver>
    - (Mikael): no funny line at equator with gtfn_gpu and gtfn_cpu
  - run with main (or main merged into `scientific_validation_distributed_driver`)

Context: @ChiaRuiOng reported an artefact at the equator when running with 2 GPUs for 7 days.

Migration notes:

- `status: wip` because the parent bullet is unchecked while its first sub-item is checked.
- `assignees: []` — the note attributes the completed sub-item to Mikael (`msimberg`) but never
  assigns the task itself; not promoted to the field.
- `effort_weeks: null` — no per-task effort is stated anywhere in the source (the task table fills
  effort on 0 of 38 rows).
- `priority: 2` is the schema default; the source states no per-task priority.
