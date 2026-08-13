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
prs: []
created_schema_version: 2
---

# warm_bubble

## Problem

Every icon4py subsystem is validated alone and none of them are validated together.
The dycore has serialbox datatests against JW/R02B04. Tracer advection has analytic
convergence tests on a torus. TMX turbulence has 97 datatests against APE AES. JSBACH
is a single SSE kernel on a branch. Each of those oracles is a different Fortran
experiment, on a different grid, from a different instrumentation branch, in a
differently-numbered archive — which is how `exclaim_ape_aesPhys_v06` came to be
regenerated in place with muphys instrumentation and silently take the tmx savepoints
with it. Worse, the reference we do lean on is thin: at all three dates used by
`test_muphys_granule` every condensate is identically zero, so the microphysics test
asserts that the scheme is a no-op on a dry column.

We cannot currently answer the question anyone actually asks. Does icon4py integrate a
moist, turbulent, land-coupled atmosphere for a day and produce what ICON produces?

`warm_bubble` is the milestone that makes that answerable. One idealised experiment: a
warm perturbation released into a stably stratified atmosphere on a doubly-periodic
torus — `Torus_Triangles_20x4_5000m`, chosen because the ICON-Land pool already carries
land boundary conditions for it — driven by the standalone driver with tracer advection,
TMX turbulence and a land surface all switched on. Nothing about it is realistic. Every
part of it is coupled, it saturates, and the surface talks back.

## Appetite

Two cycles of real work (36 and 37) and no more. If the coupled run is not integrating
by the end of cycle 37 the answer is to cut physics, not to extend.

## How the five pitches fit

- **Testing MPI reproducibility** is the harness the rest stands on. Bitwise
  single-vs-multi-rank equality already holds on CPU only under `-ffp-contract=off`, and
  only at `LEVELS=validation`; on GPU it took making the RBF coefficient computation
  batch-independent. Nothing below is trustworthy until adding a granule cannot quietly
  reshuffle roundoff past a hand-fitted `atol=1e-13`.
- **Porting turbulence** delivers TMX atmosphere plus surface. The atmosphere granule is
  done and validated; the surface tiles are the seam land plugs into.
- **Porting land** is JSBACH behind that seam, and it depends on turbulence for exactly
  that reason: tmx prescribes `land_tskin`, `rough_m`, `qsat_star`, `evapotrans`,
  `sensible_hflx` and owns the implicit solve, so the surface interface must exist first.
- **Tracer advection convergence** proves the transport the bubble's moisture rides on is
  second-order on this torus and not accidentally first-order through a C⁰ initial
  condition or a floor'd timestep count.
- **Radiation port** is the physics the bubble needs last, sequenced behind the
  reproducibility work because ecRad is where "the same answer twice" stops being free.

## Done means

A single instrumentation branch and a single archive version behind an
`exp.aes_bubble_land_tmx` run on the 20x4 torus; a savepoint-backed datatest for every
granule in the chain; single- and 12-rank output bitwise identical at
`LEVELS=validation`; and condensate that is not zero.

## Rabbit holes

Do not chase FP noise locally — this mac cannot reproduce the CI drift at all, and 35
minutes a run buys nothing. Do not regenerate any archive in place. Do not let the
grid become a research topic: `icon-grid-generator>=0.8.0` with
`periodic_layout="rectangular"` is settled.

## No-gos

No spherical grid. No real orography, no aerosol, no ocean coupling. No performance
work — DaCe and tuning are out until the coupled run is green.
