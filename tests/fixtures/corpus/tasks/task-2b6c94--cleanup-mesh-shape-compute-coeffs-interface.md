---
id: task-2b6c94
kind: task
title: Cleanup the mesh-shape interface to compute_coeffs
parent: pitch-2a7f3e
status: ready
owner: Oxpeckerly
reviewers: [eiderdowny]
person_weeks: 0.5
assignees: []
start_date: null
cycle: 34
priority: medium
depends_on: [task-31f6c4]   # synthetic, see seed/README.md
tags:
  - griddle
  - whole-roast
  - transport
prs: []
---

# Cleanup the mesh-shape interface to compute_coeffs

The single unchecked item on the Progress list of the blend-weight coefficients pitch, verbatim:

> - [ ] cleanup the mesh-shape lat/lon + cart_x/y interface to compute_coeffs

The seven other Progress items are ticked and the board entry is marked Done, so this leftover
tidy-up is the only piece of the pitch anything still shows as open. It is carried as a task to
preserve that fact; nobody has written more about it than the line above.

## What is left

`compute_coeffs` still takes the mesh shape twice: once as lat/lon and once as `cart_x`/`cart_y`,
and converts one into the other inside the call. There is more than one caller now, and two of
them build the Cartesian pair only to satisfy this signature.

The shape of the fix is agreed: take the mesh in one representation, convert at the edge, and let
the coefficient code see one thing. What is not agreed is which representation wins. Lat/lon is
what the mesh file holds; the Cartesian pair is what every stencil under this actually reads.

No size is recorded: the pitch never sized its own items. `cycle: 34` is inherited from the pitch.
