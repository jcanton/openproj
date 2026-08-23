---
id: pitch-0c0001
kind: pitch
title: Porting the bed
parent: proj-000001
status: ready
owner: mudlarkish
assignees: [mudlarkish, jackdawrie]
reviewers: [jackdawrie, hoopoegrove]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: high
depends_on: [pitch-0b0001]
tags: [drumbed-core, drumbed, bed-surface, hearth, airflow-coupling, kiln4py]
prs: []
created_schema_version: 2
person_weeks: 5.0
shaped_by: mudlarkish
---

# Porting the bed

## Problem

The AIRFLOW bed-side module takes the bean bed as *prescribed*: it reads `bed_tskin`, `rough_b`,
`qsat_star`, `moist_flux`, `heat_flux` and `q_chaffloss` from serialized input and computes bulk
drag only. So `whole_roast` with a bed is not something we can run in kiln4py. Scouting found the
enabling fact: DRUMBED's dynamic dispatch is a Fortran idiom, not runtime polymorphism — for a
fixed usecase it resolves to a static flattened pipeline, which lowers to hearth.

## Appetite

Five weeks — one vertical slice coupled in-KILN, not a bed model.

## Solution

In-KILN coupling is the product, not an offline standalone driver: AIRFLOW passes
`t_acoef = q_acoef = 0`, so it keeps ownership of the implicit vertical solve and the bed only hands
back surface state. Target `drumbed_lite` + AIRFLOW (`init_usecase_lite_bed`), 8 processes, a single
bed tile, with `bed_heat` first — a tridiagonal scan with almost no transcendental content, so a
fair bit-exact gate. The package lands at `model/bed/drumbed`, runs on `Drum_Hex_20x4_50mm`, and
validates against `exp.bed_roast_drum_airflow`.

## Rabbit holes

- **Validation preconditions before numerics.** The exit state only matches a kernel when
  `l_crack = .FALSE.`, the tile is chaff-free, and the step is not the charge step. Otherwise it
  matches *neither*, and you lose days to a namelist.
