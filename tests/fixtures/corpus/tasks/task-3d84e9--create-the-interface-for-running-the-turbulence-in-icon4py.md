---
id: task-3d84e9
kind: task
title: Create the interface for running the turbulence in icon4py
parent: pitch-3c9a41
status: shelved
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
effort_weeks: null
assignees:
  - yiluchen1066
assigned_on: null
cycle: 28
priority: medium
depends_on:
  - task-31f6c4
tags:
  - greenline
  - turbulence
  - icon4py
prs: []
---

Step 4 — the explicitly conditional step — of the four numbered solution steps in `[Greenline] Python bindings on Turbulence granule` (https://hackmd.io/@gridtools/S1airZWAJx).

> Expose the interface for use in `icon4py` **(If time permits)** — port the `turbdiff` interface.

**Migration notes.**
- `priority: medium` (could) rather than the row's `High` → 1, because the source marks this step "If time permits" while the other three are unconditional.
- `status: shelved` rather than `done`: the scope was not delivered inside this pitch and was carried into later pitches. The cycle-34 pitch `[Greenline] Warm Bubble: Turbulence granule integration` (https://hackmd.io/@gridtools/HkHMquJUbl) opens with "Now we want to integrate it into the physics driver in Icon4py… construct the `turbulence_interface` on the Icon4py side", and `[ICON4Py] plug in turbulence` (cycle 37, https://hackmd.io/@gridtools/H1y7pmbXze) continues it. Neither of those is table row 22, so this step is marked set-aside here rather than done. If the migration later creates entities for those pitches, this task is a candidate for merging into them.
- `depends_on: [task-31f6c4]` follows the note's stated ordering (it is the last of the numbered steps and needs the verified module); the note does not spell the edge out in prose, so this is the weakest of the three intra-pitch edges.
- No effort estimate anywhere → `effort_weeks: null`.
