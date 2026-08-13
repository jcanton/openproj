---
id: task-0b1001
kind: task
title: Port turbulence atmosphere
parent: pitch-0b0001
status: done
owner: jcanton
assignees: [jcanton]
reviewers: [halungge, tehrengruber]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: 0
depends_on: []
tags: [tmx, turbulence, gt4py, granule, verification]
prs: ["C2SM/icon4py#1442", "C2SM/icon4py#1449", "C2SM/icon4py#1455"]
created_schema_version: 2
effort_weeks: 4.0
---

# Port turbulence atmosphere

## Problem

`interface_aes_tmx` in Fortran does everything at once: Smagorinsky diffusion coefficients,
scalar and momentum diffusion, the implicit vertical solver, surface tiles, exchange
coefficients and diagnostics. Porting that as one lump gives us nothing to verify against until
the very end. We need the atmosphere and solver half standing on its own, bit-comparable to
Fortran, before the surface half is touched.

## Appetite

4 weeks. Seven stacked milestones, each green against serialized data before the next opens:
skeleton, GT4Py pattern proofs, serialization plumbing, diagnostics, scalar diffusion, momentum,
full granule.

## Solution

The key fact that makes this splittable: surface-level exchange coefficients never appear in
the tridiagonal matrices. The surface flux enters the solve through the RHS only. So an
atmosphere-only granule that accepts prescribed grid-mean fluxes as inputs is not an
approximation — it is the exact same arithmetic Fortran performs, with the tile aggregation
replaced by a read.

Scope in: Louis and classic stability functions, vertical-integral diagnostics, the full
implicit TDMA solve, momentum and scalar diffusion, halo exchanges via `ExchangeRuntime`.
`wpfloat` only.

Config is the awkward part. `t_vdiff_config` has 42 members and ICON echoes `aes_vdf_nml`
positionally rather than by name, so `TmxConfig` is built by reading the echoed namelist by
index, with positions pinned in annotations and `use_tmx` at position 22 used as a canary that
fails loudly if the Fortran derived type is reordered. This machinery is reusable for the other
AES derived-type namelists, which is why it is worth doing properly here.

Verification is against serialbox savepoints from an APE AES R02B04 run (`use_tmx=T`,
`isrfc_type=1`). Comparison is strict: `rtol=1e-11`, `atol=1e-9 * max|desired|`, parametrized
over both post-init timesteps; the 00:00 call is the init-step path and is excluded. One
exception: `tend_wa` is compared against the granule-exit savepoint rather than the vertical
wind savepoint, because Fortran's `ASYNC(1)` GPU serialization races with the write.

## Rabbit holes

- **Thermodynamic helpers.** `mo_thdyn_functions.f90` and `mo_aes_thermo.f90` are near-twins.
  Do not try to unify them; port the one TMX actually calls and name it so the provenance is
  unambiguous.
- **Dedup against `common`.** Tangential wind exists in three places, the TDMA scan in two.
  Worth hoisting, but only after the granule is green, on its own branch.
- **Backend sweeps.** Use `gtfn_cpu` locally — seconds instead of minutes on roundtrip. Let CI
  cover the rest instead of waiting for it.

## No-gos

- Surface tiles, exchange coefficients, `ice_fast` — next task.
- JSBACH, CO2 diffusion, 2m/10m diagnostics.
- DaCe and performance work.
