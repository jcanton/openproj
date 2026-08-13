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
prs: ["C2SM/icon4py#835", "C2SM/icon4py#943", "C2SM/icon4py#1329"]
created_schema_version: 2
effort_weeks: 4.0
---

# Port turbulence atmosphere

## Problem

`interface_aes_tmx` does everything at once: Smagorinsky diffusion coefficients, scalar and
momentum diffusion, the implicit vertical solver, surface tiles, exchange coefficients and
diagnostics. Ported as one lump there is nothing to verify against until the very end.

## Appetite

4 weeks, seven stacked milestones from skeleton to full granule, each green before the next opens.

## Solution

Surface-level exchange coefficients never appear in the tridiagonal matrices — the surface flux
enters the solve through the RHS only — so an atmosphere-only granule fed prescribed grid-mean
fluxes performs exactly the arithmetic Fortran does, with tile aggregation replaced by a read.
Scope in: Louis and classic stability functions, vertical-integral diagnostics, the full implicit
TDMA solve, momentum and scalar diffusion, halo exchanges via `ExchangeRuntime`, `wpfloat` only.
Verification is against APE AES R02B04 savepoints (`use_tmx=T`, `isrfc_type=1`) at `rtol=1e-11`,
excluding the 00:00 init-step path; `tend_wa` is compared at granule exit instead, because
Fortran's `ASYNC(1)` GPU serialization races with the vertical-wind write.

## Rabbit holes

- **Config by position.** `t_vdiff_config` has 42 members and ICON echoes `aes_vdf_nml`
  positionally, so `TmxConfig` reads the namelist by index, with `use_tmx` at position 22 as a
  canary that fails loudly if the derived type is reordered.
