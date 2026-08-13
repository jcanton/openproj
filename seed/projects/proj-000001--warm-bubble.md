---
id: proj-000001
kind: project
title: warm_bubble
parent: null
status: wip
owner: jcanton
assignees: [jcanton, havogt, halungge]
reviewers: [halungge, havogt]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: 0
depends_on: []
tags: [warm-bubble, torus, coupled-validation, aes-physics, milestone]
prs: ["C2SM/icon4py#1354"]
created_schema_version: 2
---

# warm_bubble

## Problem

Every icon4py subsystem is validated alone and none of them together — dycore serialbox datatests
against JW/R02B04, analytic torus convergence for advection, 97 TMX datatests against APE AES —
each a different Fortran experiment in a differently-numbered archive. That is how `exclaim_ape_aesPhys_v06` was regenerated in place with muphys instrumentation
and silently took the tmx savepoints with it. The reference is thin too: at all three dates in
`test_muphys_granule` every condensate is identically zero.

## Appetite

Two cycles, 36 and 37. If the coupled run is not integrating by the end of 37, cut physics.

## Solution

One idealised experiment on the doubly-periodic `Torus_Triangles_20x4_5000m` torus — chosen because
the ICON-Land pool already carries land boundary conditions for it — a warm perturbation into a
stably stratified atmosphere, driven by the standalone driver with tracer advection, TMX turbulence
and a land surface on. Five pitches feed it, MPI reproducibility first as the harness, radiation
last. Done means one archive version behind `exp.aes_bubble_land_tmx`, a datatest per granule, 1-
and 12-rank output bitwise identical at `LEVELS=validation`, and condensate that is not zero.

## No-gos

No spherical grid, no orography, no aerosol, no ocean coupling. No performance work until the run is
green. Never regenerate an archive in place.
