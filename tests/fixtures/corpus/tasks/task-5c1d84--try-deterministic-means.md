---
id: task-5c1d84
kind: task
title: Try deterministic means
parent: pitch-5e7b1c
status: ready
owner: sanderlingly
reviewers: [mudlarkish]
person_weeks: 4
assignees: []
assigned_on: null
cycle: 36
priority: medium
depends_on: [task-5a4e39]   # synthetic, see seed/README.md
tags: [kiln4py, distributed, reductions, bitwise-reproducibility]
prs: []
---

From the Progress list of the distributed driver pitch, verbatim:

- [ ] try with deterministic means (branch `deterministic-means`; may need more changes before it is usable)

The reference in the note is a branch comparison rather than a pull request, so it was not put in
`prs`.

The same note remarks that the numpy downgrade item, `task-5f062b`, "in theory does not matter if
we're using deterministic means". That is an aside about what might become moot, not a stated
dependency, so no `depends_on` edge was recorded in either direction.

Neither an effort nor a priority is stated in the source.
