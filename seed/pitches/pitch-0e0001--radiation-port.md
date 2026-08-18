---
id: pitch-0e0001
kind: pitch
title: Radiation port
parent: proj-000001
status: ready
owner: halungge
assignees: [halungge, kotsaloscv]
reviewers: [jcanton, tehrengruber]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: high
depends_on: [pitch-0a0001]
tags: [radiation, rte-rrtmgp, aes-physics, gt4py, port]
prs: []
created_schema_version: 2
person_weeks: 6.0
shaped_by: jcanton
---

# Radiation port

> Promoted from note-55cc66 — a note by dastrm on 2026-07-06.

## Problem

The warm-bubble driver runs with radiation off: no radiative cooling, no destabilisation, a hole
where the largest free-tropospheric tendency belongs. What we port is ICON's AES `rte_rrtmgp` path,
not ecRad, and the hard part is attribution. Every flux sums over 112/128 g-points and what we
validate is the vertical divergence of net flux — two O(100 W/m^2) numbers differenced into
O(1e-5) K/s — so reduction order lands in the signal. Hence the dependency on pitch-0a0001.

## Appetite

Six weeks, two people: SW and LW validated against the numpy references and the APE savepoints, no
integration into `physics_driver_l2`.

## Solution

Full-DSL port in `model/atmosphere/subgrid_scale_physics/radiation`: cartesian `(Cell, Gpt, K)`
stencils, no connectivities, flat-table gathers via `as_offset`, chunked over cells since a
g-point-resolved field is ~1.3 GB at full grid. Two granules mirror ICON: `RteRrtmgpRadiation` on
`dt_rad`, `Radheating` every step. M0-M2 are done on `port_radiation`; this is M3/M4, the solvers.

## Rabbit holes

- **Vacuous reference data.** The APE archive from the JW initial condition has RH_max = 0.503 and
  never condenses, so a cloud-optics test on it asserts the scheme is a no-op on a dry column. Run
  `./scripts/run inspect-savepoints stats` first; unless it has been regenerated with
  `ztmc_ape=50`, validate clear-sky only.
