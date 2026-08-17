---
id: task-0c1001
kind: task
title: Port JSBACH
parent: pitch-0c0001
status: ready
owner: jcanton
assignees: [jcanton]
reviewers: [muellch, halungge]
review_waived: false
assigned_on: 2026-08-17
priority: high
depends_on: []
tags: [jsbach, soil-snow-energy, scan-operator, savepoints, gt4py, icon4py]
prs: []
created_schema_version: 2
person_weeks: 4.0
---

# Port JSBACH

## Problem

The first slice of ICON-Land has to run in icon4py and validate against Fortran on the
`jsbach_lite` + tmx usecase. Slice = soil_snow_energy (SSE): soil thermal properties, the
tridiagonal soil-temperature solve, and the surface-energy-balance coupling that hands
`land_tskin` back to the tmx surface granule. The back-substitution is already committed as a
forward KDim `scan_operator` in `stencils/soil_temperature.py`, green on `embedded` and
`gtfn_cpu`, and geometry plus FAO soil properties are wired in `soil_thermal_properties.py`.
Missing: the other half of the solve, and any validation against real ICON output.

## Appetite

Four weeks.

## Solution

Finish the forward-elimination half so the three kernels form a closed pipeline, keeping the
freeze/melt branch stubbed behind the `l_freeze = .FALSE.` path we validate under. Run the
instrumented ICON on the supercomputer (branch `serialize_jsbach_sse`, call sites in
`update_land`) to emit `sse-entry` / `sse-exit` / `sse-geometry` savepoints on
`Torus_Triangles_20x4_5000m`, and register that grid and the new experiment in `definitions.py`.
Then write the datatest that drives the three kernels from `sse-entry` and compares against
`sse-solve-exit`.

## Rabbit holes

- **Do not write a fourth TDMA.** The tridiagonal scans moved to `common/math/tridiagonal.py`
  during the turbulence cleanup; reuse them or extend them there.
