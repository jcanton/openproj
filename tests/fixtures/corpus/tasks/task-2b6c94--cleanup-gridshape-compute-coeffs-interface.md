---
id: task-2b6c94
kind: task
title: Cleanup gridShape lat/lon + cart_x/y interface to compute_coeffs
parent: pitch-2a7f3e
status: todo
owner: OngChia
reviewers: [edopao]
effort_weeks: 0.5
assignees: []
assigned_on: null
cycle: 34
priority: 2
depends_on: [task-31f6c4]   # synthetic, see seed/README.md
tags:
  - greenline
  - warm-bubble
  - tracer-advection
prs: []
---

# Cleanup gridShape lat/lon + cart_x/y interface to compute_coeffs

The single unchecked item on the Progress list of *[Greenline] Warm Bubble: Least-Squares Coefficients in Tracer Advection* (<https://hackmd.io/z84FEYwkToCiqNicr3K5jQ>), verbatim:

> - [ ] cleanup gridShape lat/lon + cart_x/y interface to compute_coeffs

The seven other Progress items are checked off, and table row 16 is marked **Done**, so this leftover cleanup is the only piece of the pitch the source still shows as open. It is carried as a task purely to preserve that fact — the source says nothing more about it than the line above.

## Migration notes

- `effort_weeks` is null: the source states no effort for this item (effort is filled on 0 of the 38 table rows).
- `assignees` is empty: the checklist item names nobody. The parent pitch's Who string is "N+Rico" (`nfarabullini`, `DropD`); attributing this specific item to either would be a guess.
- `priority: 2` is the schema default, not a sourced value — the "High" in the table applies to row 16 as a whole, which is already recorded on the parent pitch.
- `cycle: 34` is inherited from the source note's tag (`cycle 34 02/26`); the item itself carries no cycle of its own and may well have slipped past cycle 34.
