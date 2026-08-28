---
id: task-58d7c6
kind: task
title: Per-field deltas instead of a blanket 1e-13 tolerance
parent: pitch-5e7b1c
status: ready
owner: hoopoegrove
reviewers: [ibisbillie]
person_weeks: 1
assignees: []
start_date: null
cycle: 36
priority: medium
depends_on: [task-5c1d84, task-5f062b]   # synthetic, see seed/README.md
tags: [kiln4py, standalone-driver, distributed, validation]
prs: []
---

From the Progress list of the distributed driver pitch, verbatim:

- [ ] check which fields have non-zero deltas instead of applying the same 1e-13 tolerance to all

Context: the pitch's goal is a bit-identical single-rank and multi-rank run, so knowing *which*
fields diverge is the fallback result if full bit-identity turns out not to be reachable. The
cycle-37 continuation makes the same point in its Rabbit holes section.

Neither an effort nor a priority is stated in the source.
