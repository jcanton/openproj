---
id: task-0c1001
kind: task
title: Port JSBACH
parent: pitch-0c0001
status: todo
owner: jcanton
assignees: [jcanton]
reviewers: [muellch, halungge]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: []
tags: [jsbach, soil-snow-energy, scan-operator, savepoints, gt4py, icon4py]
prs: []
created_schema_version: 2
effort_weeks: 4.0
---

# Port JSBACH

## Problem

We need the first slice of ICON-Land running in icon4py and validated against Fortran, on the
`jsbach_lite` + tmx usecase. Slice = soil_snow_energy (SSE): soil thermal properties, the
tridiagonal soil-temperature solve, and the surface-energy-balance coupling that hands
`land_tskin` back to the tmx surface granule.

The skeleton already exists: worktree `.worktrees/port_jsbach`, branch `port_jsbach` off
`origin/main`, package `model/land/jsbach`. The soil-temperature back-substitution is
committed as a forward KDim `scan_operator` in `stencils/soil_temperature.py`, TDD'd against a
numpy reference and green on `embedded` and `gtfn_cpu`. `docs/sse_port_spec.md` carries the
verified state set, the aggregation rules and the kernel line-map. Geometry and FAO soil
properties are wired in `soil_thermal_properties.py`. What is missing is the other half of the
solve, and — more importantly — any validation against real ICON output.

## Appetite

Four weeks.

## Solution

1. Finish the forward-elimination half of the SSE solve so the three kernels form a closed
   pipeline, and keep the freeze/melt branch stubbed behind the `l_freeze = .FALSE.` path we
   validate under.
2. Run the instrumented ICON on the supercomputer (branch `serialize_jsbach_sse`, call sites in
   `update_land`) to emit `sse-entry` / `sse-exit` / `sse-geometry` savepoints on
   `Torus_Triangles_20x4_5000m`, and upload the archive under a version nothing else claims.
3. Register the 20x4 grid and the new experiment in `definitions.py`.
4. Write the datatest that drives the three kernels from `sse-entry` and compares against
   `sse-solve-exit`, per the checklist in `JSBACH_SSE_VALIDATION.md`.

## Rabbit holes

- **Archive versioning.** We have already lost one reference dataset to a same-version,
  different-instrumentation collision. Publish under a fresh version and add the local marker
  file. Run tests with `ICON4PY_ENABLE_TESTDATA_DOWNLOAD=false`.
- **Do not write a fourth TDMA.** The tridiagonal scans moved to `common/math/tridiagonal.py`
  during the turbulence cleanup; reuse them or extend them there.
- **numpy in `src/`.** The moment a source module imports numpy directly it has to be added to
  the jsbach `pyproject` *and* to the tach graph, or the layering test fails in CI rather than
  locally.
- Adversarial verification caught it once already: if the exit state matches neither kernel,
  check the run conditions before the code.
- House style: plain `#` comments, terse `Port of <fortran routine>` provenance docstrings,
  keyword-only args except in `@field_operator` / `@program`.

## No-gos

- No freeze/melt, no snow kernel — deferred by the pitch.
- No DaCe, no GPU tuning, no performance work. Correctness gate first.
- No refactor of the tmx surface seam from this branch; that merge is tracked separately.
