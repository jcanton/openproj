---
id: t-5c1d84
kind: task
title: Try deterministic means
parent: p-5e7b1c
status: todo
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
effort_weeks: null
assignees: []
assigned_on: null
cycle: 36
priority: 2
depends_on: []
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
- The parent note remarks that the numpy downgrade item (`t-5f062b`) "in theory does not matter if
  we're using deterministic means". That is a conditional aside, not a stated dependency, so no
  `depends_on` edge was recorded in either direction.
- `effort_weeks: null`, `priority: 2` (default): neither is stated in the source.
