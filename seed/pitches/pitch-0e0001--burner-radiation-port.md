---
id: pitch-0e0001
kind: pitch
title: Burner radiation port
parent: proj-000001
status: ready
owner: hoopoegrove
assignees: [hoopoegrove, kittiwaker]
reviewers: [jackdawrie, turnstonegru]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: high
depends_on: [pitch-0a0001]
tags: [radiation, burner, bed-physics, hearth, port]
prs: []
created_schema_version: 2
person_weeks: 6.0
shaped_by: jackdawrie
---

# Burner radiation port

> Promoted from note-55cc66 — a note by dabchickly on 2026-07-06.

## Problem

The `whole_roast` driver runs with the burner off: no radiative heating off the drum wall, no
exotherm, a hole where the largest free-bed tendency belongs. What we port is KILN's own BURNER
path, not the vendor library, and the hard part is attribution. Every flux sums over 112/128
g-points and what we validate is the vertical divergence of net flux — two O(100 W/m^2) numbers
differenced into O(1e-5) K/s — so reduction order lands in the signal. Hence the dependency on
pitch-0a0001.

## Appetite

Six weeks, two people: near-IR and far-IR validated against the numpy references and the
reference-roast tap points, no integration into `plant_driver_l2`.

## Solution

Full-DSL port in `model/bed_physics/burner`: cartesian `(Cell, Gpt, K)` stencils, no
connectivities, flat-table gathers via `as_offset`, chunked over cells since a g-point-resolved
field is ~1.3 GB at full mesh. Two modules mirror KILN: `BurnerRadiation` on `dt_burner`,
`BurnerHeating` every step. M0-M2 are done on `port_burner`; this is M3/M4, the solvers.

## Rabbit holes

- **Vacuous reference data.** The reference archive taken from the cold-charge initial condition
  has a peak bed moisture of 0.503 and never releases aroma, so a chaff-optics test on it asserts
  the scheme is a no-op on a dry bed. Run `./scripts/run inspect-tappoints stats` first; unless it
  has been regenerated with `zchaff_ref=50`, validate clear-bed only.
