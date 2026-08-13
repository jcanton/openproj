---
id: pitch-0c0001
kind: pitch
title: Porting land
parent: proj-000001
status: todo
owner: muellch
assignees: [muellch, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: [pitch-0b0001]
tags: [jsbach, icon-land, land-surface, gt4py, tmx-coupling, icon4py]
prs: []
created_schema_version: 2
appetite_weeks: 5.0
shaped_by: muellch
---

# Porting land

## Problem

The turbulence port left land out on purpose. The tmx surface granule today takes the land
tile as *prescribed*: it reads `land_tskin`, `rough_m`, `qsat_star`, `evapotrans`,
`sensible_hflx` and `q_snocpymlt` from serialized input and computes bulk stress only. So
warm_bubble with land is not a thing we can run in icon4py — the land column of the surface
seam is a hole with the right shape but nothing behind it. Filling it means porting
ICON-Land (JSBACH) from Fortran to GT4Py, which is the follow-on we deferred when we scoped
the turbulence work.

Two independent scouting passes (framework/whole-scope with a machine-readable field catalog
of 1152 variables, and a narrow in-ICON target study) converged on the same enabling fact:
JSBACH's dynamic dispatch is a Fortran idiom, not real runtime polymorphism. For a fixed
usecase it resolves to a static flattened pipeline, which is exactly what lowers to GT4Py.
NVIDIA relied on the same property when they wrapped it in CUDA graphs.

## Appetite

Five weeks. That buys one real vertical slice coupled in-ICON, not a land model.

## Solution

- **In-ICON coupling is the product**, not an offline standalone driver. The tmx seam already
  exists and already prescribes the six fields above; tmx passes `t_acoef = q_acoef = 0`, so
  tmx keeps ownership of the implicit vertical solve and land only has to hand back surface
  state. That is a narrow, testable contract.
- **Target usecase `jsbach_lite` + tmx** (`init_usecase_lite_tmx`), 8 processes, a single land
  leaf. No tile hierarchy.
- **SSE (soil_snow_energy) is the first slice.** It is a tridiagonal scan, almost no
  transcendental content, and therefore a fair bit-exact gate.
- **Two-tier oracle.** Tier 1 is an offline single-column golden I/O harness — fast, kernel
  level. Tier 2 is the in-ICON experiment `exp.aes_bubble_land_tmx`, the only dataset we have
  with land in it, and the only thing that validates the tmx seam itself. No jsbach savepoints
  exist yet; instrumentation fetches jsbach memory by name (`sse_*`, `seb_t_srf`) and must stay
  behind `#ifndef __NO_JSBACH__`.
- Package lands at `model/land/jsbach` (`icon4py.model.land.jsbach`, dist
  `icon4py-land-jsbach`), a new top-level `model/land/` tree mirroring microphysics.
- Grid: run on `Torus_Triangles_20x4_5000m`, for which land ic/bc already exist in the pool,
  and register that grid plus the new savepoint dataset in `definitions.py`.

## Rabbit holes

- **Validation preconditions before numerics.** The exit state only matches a kernel when
  `l_freeze = .FALSE.`, the cell is snow-free, and the step is not the lstart step. Otherwise
  it matches *neither* kernel and you will spend days chasing a bug that is a namelist.
- **The prognostic state set.** The extracted field catalog's prognostic flag is roughly 90%
  right and mislabels `t_soil_sl`. This needs a human who owns the Fortran, not another script.
- **Serialbox version squeeze.** The 2.6.3-vs-2.6.0 `fs_write_field` generic mismatch breaks
  pre-existing savepoints identically, so it is not ours. Do not fix it locally; run Fortran
  and serialization on the supercomputer.
- **"Standalone ICON-Land" is a misnomer** — the driver USEs 92 ICON infra modules. Standalone
  means land without an atmosphere, still inside the ICON tree.
- The tmx-surface seam is still a WIP branch and main has moved. That merge is real work; do
  not attempt it in the middle of the SSE slice.

## No-gos

- No offline standalone driver as the deliverable.
- No freeze/melt, no snow kernel, no multiple land tiles inside this appetite.
- No re-derivation of JSBACH physics. Fortran fidelity first, tidy second.
- Do not move the implicit solve out of tmx.
