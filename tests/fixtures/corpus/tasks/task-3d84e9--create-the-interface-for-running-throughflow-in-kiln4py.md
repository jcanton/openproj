---
id: task-3d84e9
kind: task
title: Create the interface for running throughflow in kiln4py
parent: pitch-3c9a41
status: shelved
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: null
assignees:
  - yellowhammer7
start_date: null
cycle: 28
priority: medium
depends_on:
  - task-31f6c4
tags:
  - griddle
  - throughflow
  - kiln4py
prs: []
---

Step 4 — the one the note marks conditional — of the four numbered solution steps in the
throughflow bindings pitch.

> Expose the interface for use in `kiln4py` **(if time permits)** — port the `bedstep`
> interface.

`priority: medium` rather than the board's High, because the source marks this step "if time
permits" while the other three are unconditional.

`status: shelved` rather than `done`. The scope was not delivered inside this pitch and was
carried into later ones: the cycle-34 pitch on integrating the module opens with "now we want to
plug it into the physics driver in kiln4py … build the `throughflow_interface` on the kiln4py
side", and the cycle-37 continuation picks that up again. Neither of those is this board entry,
so this step is marked set-aside here rather than done. If records are ever created for those
pitches, this task is the obvious candidate to merge into them.

`depends_on: [task-31f6c4]` follows the note's ordering — it is the last of the numbered steps and
it needs the verified module. The note does not spell the edge out in prose, so it is the weakest
of the three edges inside this pitch. No effort is recorded anywhere.
