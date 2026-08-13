---
id: task-5c1d84
kind: task
title: Try deterministic means
parent: pitch-5e7b1c
status: ready
owner: samkellerhals
reviewers: [muellch]
effort_weeks: 4
assignees: []
assigned_on: null
cycle: 36
priority: medium
depends_on: [task-5a4e39]   # synthetic, see seed/README.md
tags: [icon4py, distributed, reductions, bitwise-reproducibility]
prs: []
---

From the Progress list of *[ICON4Py] Distributed driver*
(<https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA>), verbatim:

- [ ] try with deterministic means
  (<https://github.com/C2SM/icon4py/compare/main...msimberg:icon4py:deterministic-means>;
  may need more changes before it's usable)

Migration notes:

- The linked reference is a branch comparison, not a pull request, so it was not put in `prs`.
- The parent note remarks that the numpy downgrade item (`task-5f062b`) "in theory does not matter if
  we're using deterministic means". That is a conditional aside, not a stated dependency, so no
  `depends_on` edge was recorded in either direction.
- `effort_weeks: null`, `priority: medium` (default): neither is stated in the source.
