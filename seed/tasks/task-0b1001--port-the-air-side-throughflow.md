---
id: task-0b1001
kind: task
title: Port the air-side throughflow
parent: pitch-0b0001
status: done
owner: jackdawrie
assignees: [jackdawrie]
reviewers: [hoopoegrove, turnstonegru]
review_waived: false
assigned_on: 2026-06-22
priority: high
depends_on: []
tags: [airflow, throughflow, hearth, module, verification]
prs: ["kilnlab/kiln4py#2014", "kilnlab/kiln4py#2036", "kilnlab/kiln4py#2290"]
created_schema_version: 2
person_weeks: 4.0
---

# Port the air-side throughflow

## Problem

`interface_bed_airflow` does everything at once: packed-bed drag coefficients, scalar and
momentum diffusion, the implicit vertical solver, bed tiles, film coefficients and
diagnostics. Ported as one lump there is nothing to verify against until the very end.

## Appetite

4 weeks, seven stacked milestones from skeleton to full module, each green before the next opens.

## Solution

Surface film coefficients never appear in the tridiagonal matrices — the surface flux
enters the solve through the RHS only — so an air-side module fed prescribed bed-mean
fluxes performs exactly the arithmetic Fortran does, with tile aggregation replaced by a read.
Scope in: the packed-bed and classic stability functions, vertical-integral diagnostics, the implicit
TDMA solve, momentum and scalar diffusion, halo exchanges via `HaloRuntime`, `realwp` only.
Verification is against reference-roast D4 tap points (`use_airflow=T`, `isfc_type=1`) at
`rtol=1e-11`, excluding the 00:00 charge-step path; `tend_w` is compared at module exit instead,
because Fortran's `ASYNC(1)` GPU serialization races with the vertical-velocity write.

## Rabbit holes

- **Config by position.** `t_airflow_config` has 42 members and KILN echoes `kiln_air_nml`
  positionally, so `AirflowConfig` reads the namelist by index, with `use_airflow` at position 22 as
  a canary that fails loudly if the derived type is reordered.
