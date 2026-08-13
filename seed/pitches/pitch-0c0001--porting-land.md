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

The tmx surface granule takes the land tile as *prescribed*: it reads `land_tskin`, `rough_m`,
`qsat_star`, `evapotrans`, `sensible_hflx` and `q_snocpymlt` from serialized input and computes
bulk stress only. So warm_bubble with land is not something we can run in icon4py. Scouting found
the enabling fact: JSBACH's dynamic dispatch is a Fortran idiom, not runtime polymorphism — for a
fixed usecase it resolves to a static flattened pipeline, which lowers to GT4Py.

## Appetite

Five weeks — one vertical slice coupled in-ICON, not a land model.

## Solution

In-ICON coupling is the product, not an offline standalone driver: tmx passes
`t_acoef = q_acoef = 0`, so it keeps ownership of the implicit vertical solve and land only hands
back surface state. Target `jsbach_lite` + tmx (`init_usecase_lite_tmx`), 8 processes, a single
land leaf, with soil_snow_energy first — a tridiagonal scan with almost no transcendental content,
so a fair bit-exact gate. The package lands at `model/land/jsbach`, runs on
`Torus_Triangles_20x4_5000m`, and validates against `exp.aes_bubble_land_tmx`.

## Rabbit holes

- **Validation preconditions before numerics.** The exit state only matches a kernel when
  `l_freeze = .FALSE.`, the cell is snow-free, and the step is not the lstart step. Otherwise it
  matches *neither*, and you lose days to a namelist.
