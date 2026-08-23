---
id: task-5f062b
kind: task
title: Downgrade numpy for stable global sums
parent: pitch-5e7b1c
status: ready
owner: eveningtern
reviewers: [accentor9]
person_weeks: 1
assignees: []
assigned_on: null
cycle: 36
priority: medium
depends_on: [task-5a4e39]   # synthetic, see seed/README.md
tags: [kiln4py, distributed, numpy, reductions, bitwise-reproducibility]
prs: []
---

From the Progress list of the distributed driver pitch, verbatim:

- [ ] downgrade numpy (2.3.0 changed the blocksizes and the rounding for global sums; 2.2.6 should
  still be fine) ((in theory this does not matter if we are using deterministic means))
  - [ ] find out, just for fun, whether the GPUs always had this as an "issue"

The sub-point was kept inside this task rather than split out: the source marks it "just for fun"
and it has no deliverable of its own.

Neither an effort nor a priority is stated in the source.
