---
id: task-0b1002
kind: task
title: Port turbulence surface
parent: pitch-0b0001
status: in_progress
owner: yiluchen1066
assignees: [yiluchen1066, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-07-13
cycle: 36
priority: high
depends_on: [task-0b1001]
tags: [tmx, turbulence, surface, sea-ice, gt4py, verification]
prs: ["C2SM/icon4py#1280"]
created_schema_version: 2
effort_weeks: 3.5
---

# Port turbulence surface

## Problem

The atmosphere granule runs on prescribed grid-mean surface fluxes. That was the right seam, but
it leaves the whole tiled surface layer of TMX — `t_vdf_sfc`, the ocean, land and sea-ice
tiles, and the exchange-coefficient solve that produces those fluxes — Fortran-only. Until it is
ported, icon4py cannot close the turbulence loop.

## Appetite

3.5 weeks, behind the atmosphere task in cycle 36; realistically finishes in 37.

## Solution

A `surface/` submodule inside the existing tmx package, in four stages: Charnock roughness plus
the 5-iteration Businger exchange solve, as a first-guess program and five step programs rather
than one unrolled DSL expression; prescribed JSBACH-cut land fluxes, bulk stress only;
Semtner zero-layer `ice_fast` with scheme-1 albedo, its one-step-lagged forcing carried in
`SurfaceState` because the lag is in the Fortran; and four savepoints (surface entry, exchange,
ice exit, per-tile fluxes) from instrumentation on its own branch. Ocean, land and ice are
committed, and the exchange stage validates at `rtol=1e-9` on both backends.

## Rabbit holes

- **The archive runs the bypass path.** `nh_test_name='APE_aes'` yields one ocean tile, and with
  `isrfc_type=1` TMX takes the prescribed-flux bypass (`mo_tmx_surface.f90:802`), so the real
  bulk-flux path is never exercised; flux validation needs an `isrfc_type=0` rerun into a
  separate archive.
