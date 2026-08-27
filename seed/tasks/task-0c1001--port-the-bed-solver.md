---
id: task-0c1001
kind: task
title: Port the bed solver
parent: pitch-0c0001
status: ready
owner: jackdawrie
assignees: [jackdawrie]
reviewers: [mudlarkish, hoopoegrove]
review_waived: false
start_date: 2026-08-17
priority: high
depends_on: [task-0f1001]
tags: [drumbed-core, bed-heat, scan-operator, tap-points, hearth, kiln4py]
prs: []
created_schema_version: 2
person_weeks: 4.0
---

# Port the bed solver

## Problem

The first slice of DRUMBED has to run in kiln4py and validate against Fortran on the
`drumbed_lite` + AIRFLOW usecase. Slice = `bed_heat` (BHE): bed thermal properties, the
tridiagonal bed-temperature solve, and the energy balance that hands
`bed_tskin` back to the AIRFLOW surface module. The back-substitution is already committed as a
forward KDim `scan_operator` in `stencils/bed_temperature.py`, green on `embedded` and
`hearth_cpu`, and geometry plus measured bed properties are wired in `bed_thermal_properties.py`.
Missing: the other half of the solve, and any validation against real KILN output.

## Appetite

Four weeks.

## Solution

Finish the forward-elimination half so the three kernels form a closed pipeline, keeping the
first-crack branch stubbed behind the `l_crack = .FALSE.` path we validate under. Run the
instrumented KILN on Firebrick (branch `serialize_drumbed_bhe`, call sites in
`update_bed`) to emit `bed-entry` / `bed-exit` / `bed-geometry` tap points on
`Drum_Hex_20x4_50mm`, and register that mesh and the new experiment in `definitions.py`.
Then write the datatest that drives the three kernels from `bed-entry` and compares against
`bed-solve-exit`.

## Rabbit holes

- **Do not write a fourth TDMA.** The tridiagonal scans moved to `common/math/tridiagonal.py`
  during the throughflow cleanup; reuse them or extend them there.
