---
id: task-53a9f0
kind: task
title: Reproduce the 2-GPU seam artefact
parent: pitch-5e7b1c
status: in_progress
owner: merganserly
reviewers: [jackdawrie]
person_weeks: 2
assignees: []
assigned_on: 2026-08-13
cycle: 36
priority: medium
depends_on: []
tags: [kiln4py, standalone-driver, distributed, gpu]
prs: []
---

From the Progress list of the distributed driver pitch, verbatim:

- [ ] reproduce Oxpecker's result
  - [x] run the standalone driver on GPUs with **2 and 4 ranks** (to see whether the domain
    decomposition makes a difference — drum seam only, or a "cross"?), on branch
    <https://github.com/kilnlab/kiln4py/tree/validation_distributed_driver>
    - (Merganser): no funny line at the seam with hearth_gpu and hearth_cpu
  - run with main, or with main merged into `validation_distributed_driver`

Context: @Oxpeckerly reported an artefact along the drum seam when driving a roast on 2 GPUs.

`status: in_progress` because the parent point is unticked while its first sub-point is ticked.
`assignees: []` — the note credits the finished sub-point to Merganser but never assigns the task
itself, so it was not promoted into the field. No per-task effort or priority is stated in the
source.
