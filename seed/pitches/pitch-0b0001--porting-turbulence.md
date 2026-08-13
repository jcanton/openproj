---
id: pitch-0b0001
kind: pitch
title: Porting turbulence
parent: proj-000001
status: wip
owner: jcanton
assignees: [jcanton, yiluchen1066]
reviewers: [halungge, muellch]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: 1
depends_on: []
tags: [tmx, turbulence, aes, gt4py, port, serialbox]
prs: ["C2SM/icon4py#1364"]
created_schema_version: 2
appetite_weeks: 7.5
shaped_by: jcanton
---

# Porting turbulence

## Problem

The AES TMX turbulence scheme (Smagorinsky, Fortran entry `interface_aes_tmx`) is the last large
physics block the warm-bubble configuration cannot run natively. Today we reach it through `f2py`
bindings around `turbdiff_setup_config` / `turbdiff_run`: they hand NumPy arrays to a Fortran
object that keeps its own state, they cannot pass GPU pointers, and the DSL toolchain sees an
opaque call. Fusion with the dycore's TDMA, a single halo-exchange strategy, DaCe — all stop at
that boundary.

## Appetite

7.5 weeks, bet in cycle 36; the surface half is expected to spill into 37.

## Solution

A native GT4Py granule in `model/atmosphere/subgrid_scale_physics/tmx`, built diffusion-style:
config object, `__init__` that allocates and precomputes, `run` over prognostic state, halo
exchanges through `ExchangeRuntime` from the start, `wpfloat` throughout. It splits into two tasks
along a physical seam — surface-level exchange coefficients never enter the tridiagonal matrices,
so an atmosphere-only granule taking prescribed `shfl`, `evapotrans`, `ustress` and `vstress`
reproduces Fortran exactly. Ground truth is serialbox savepoints from an APE AES R02B04 run with
`use_tmx=T`, and every milestone is green before the next one starts.

## Rabbit holes

- **Reference-data version collisions.** The `exclaim_ape_aesPhys_v06` archive was once
  regenerated in place with muphys instrumentation and silently lost every `tmx-*` savepoint. Pin
  an archive version that no other port also claims.
