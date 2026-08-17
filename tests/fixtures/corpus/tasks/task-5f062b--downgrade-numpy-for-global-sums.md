---
id: task-5f062b
kind: task
title: Downgrade numpy for stable global sums
parent: pitch-5e7b1c
status: ready
owner: egparedes
reviewers: [abishekg7]
person_weeks: 1
assignees: []
assigned_on: null
cycle: 36
priority: medium
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
- `person_weeks: null`, `priority: medium` (default): neither is stated in the source.
