---
id: task-5f062b
kind: task
title: Downgrade numpy for stable global sums
parent: pitch-5e7b1c
status: todo
owner: egparedes
reviewers: [abishekg7]
effort_weeks: 1
assignees: []
assigned_on: null
cycle: 36
priority: 2
depends_on: [task-5a4e39]   # synthetic, see seed/README.md
tags: [icon4py, distributed, numpy, reductions, bitwise-reproducibility]
prs: []
---

From the Progress list of *[ICON4Py] Distributed driver*
(<https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA>), verbatim:

- [ ] downgrade numpy (2.3.0 introduces different blocksizes and different rounding for global sums,
  2.2.6 should still be ok) ((in theory this does not matter if we're using deterministic means))
  - [ ] find out just for fun if the GPUs always had this as "issue"

Migration notes:

- The sub-item was kept inside this task rather than split out; the source marks it "just for fun"
  and it has no independent deliverable.
- `effort_weeks: null`, `priority: 2` (default): neither is stated in the source.
