---
id: task-58d7c6
kind: task
title: Per-field deltas instead of a blanket 1e-13 tolerance
parent: pitch-5e7b1c
status: ready
owner: halungge
reviewers: [iomaganaris]
effort_weeks: 1
assignees: []
assigned_on: null
cycle: 36
priority: medium
depends_on: [task-5c1d84, task-5f062b]   # synthetic, see seed/README.md
tags: [icon4py, standalone-driver, distributed, validation]
prs: []
---

From the Progress list of *[ICON4Py] Distributed driver*
(<https://hackmd.io/nHBlhnlfRCeAbwQRBLDydA>), verbatim:

- [ ] check which fields have non zero deltas instead of applying the same 1e-13 tolerance on all

Context: the parent pitch's goal is bit-identical single- vs multi-rank runs; knowing *which* fields
diverge is the fallback result if full bit-identity is not reachable. The cycle-37 continuation note
(<https://hackmd.io/wwTnvD2tR1ijrZD1sxbdDg>) makes the same point in its Rabbit holes section.

Migration notes:

- `effort_weeks: null`, `priority: medium` (default): neither is stated in the source.
