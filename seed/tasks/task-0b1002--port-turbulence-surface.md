---
id: task-0b1002
kind: task
title: Port turbulence surface
parent: pitch-0b0001
status: wip
owner: yiluchen1066
assignees: [yiluchen1066, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-07-13
cycle: 36
priority: 1
depends_on: [task-0b1001]
tags: [tmx, turbulence, surface, sea-ice, gt4py, verification]
prs: []
created_schema_version: 2
effort_weeks: 3.5
---

# Port turbulence surface

## Problem

The atmosphere granule runs on prescribed grid-mean surface fluxes. That was the right seam to
cut for the first half, but it means the whole tiled surface layer of TMX — `t_vdf_sfc`, ocean
and land and sea-ice tiles, the exchange-coefficient solve that produces those fluxes — is still
Fortran-only. Until it is ported, icon4py cannot close the turbulence loop on its own.

## Appetite

3.5 weeks. Bet in cycle 36 behind the atmosphere task; realistically finishes in 37.

## Solution

A `surface/` submodule inside the existing tmx package — same tach node, no new package. Four
stages:

- **Ocean.** Charnock roughness plus the 5-iteration Businger exchange solve, split into a
  first-guess program and five step programs rather than unrolled into a single DSL expression.
  The unrolled form is unreadable and does not compile faster.
- **Land.** Prescribed JSBACH-cut fluxes, bulk stress only. This is the placeholder that the
  land pitch later replaces.
- **Sea ice.** Semtner zero-layer `ice_fast`, scheme-1 albedo, sublimation fluxes. Forcing is
  one step lagged, carried in `SurfaceState` — that lag is in the Fortran and must be
  reproduced, not smoothed away.
- **Verification.** Four savepoints — surface entry, exchange, ice exit, per-tile fluxes —
  written by instrumentation kept on a branch separate from the atmosphere instrumentation, so
  the atmosphere archives stay valid.

Status: ocean, land and ice are committed, readers are in, and the **exchange stage validates at
`rtol=1e-9` on both backends** with the Charnock lag seeding ocean `km` from the previous step.

## Rabbit holes

- **The archive is running the bypass path.** The reference run uses `nh_test_name='APE_aes'`,
  which yields one ocean tile, and with `isrfc_type=1` TMX takes the prescribed-flux bypass
  (`mo_tmx_surface.f90:802`). So `ustress`/`vstress` are zero and `evap`/`shfl` are prescribed:
  the real bulk-flux path is simply not exercised by the data we have. Flux, end-to-end and
  coupling validation are blocked on an `isrfc_type=0` rerun — one namelist line, but it must go
  to a **separate archive**, because flipping it invalidates the atmosphere-granule data. The
  exchange solve, being the hard part, needed no rerun.
- **Tile count has no namelist knob.** It is driven only by `nh_test_name`. Sea ice needs
  `nsfc_type>=2`, which means `nh_test_name='APEi'`, a freezing `ape_sst_case`, and a one-line
  registration in `mo_nh_testcases.f90`. Do not go looking for a switch that does not exist.
- **Constant mismatch.** Sea-ice `ci=2106` in `SeaIceConstants` differs from thermodynamic
  `ci=2108`. This is a real inconsistency in ICON; preserve it, do not tidy it.

## No-gos

- Real JSBACH land physics — that is the land pitch, and this task hands it an interface.
- Ocean coupling, 2m/10m diagnostics.
- Any performance work before the flux stage validates.
