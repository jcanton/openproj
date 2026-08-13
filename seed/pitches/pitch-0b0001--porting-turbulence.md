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
prs: ["C2SM/icon4py#1442"]
created_schema_version: 2
appetite_weeks: 7.5
shaped_by: jcanton
---

# Porting turbulence

## Problem

The AES TMX turbulence scheme (Smagorinsky, Fortran entry `interface_aes_tmx`) is the last
large physics block in the warm-bubble configuration that icon4py cannot run natively. What we
have today is the 1D NWP turbulence reachable through `f2py` bindings around
`turbdiff_setup_config` / `turbdiff_run`. Those bindings work, but they are a dead end for us:
they hand NumPy arrays to a Fortran object that keeps its own state, they cannot pass GPU
pointers, and the DSL toolchain sees an opaque call. Anything we want downstream — fusion with
the dycore's TDMA, a single halo-exchange strategy, DaCe — stops at that boundary.

## Appetite

7.5 weeks, bet in cycle 36. That is deliberately more than a cycle: the surface half is
expected to spill into 37, and we would rather admit that up front than pretend the granule
lands in eight weeks.

## Solution

A native GT4Py granule in a new package, `model/atmosphere/subgrid_scale_physics/tmx`, built
diffusion-style: config object, `__init__` that allocates and precomputes, `run` that takes
prognostic state. Halo exchanges go in from the start via `ExchangeRuntime` rather than being
retrofitted. `wpfloat` throughout — no mixed precision on the first pass.

The port splits into two tasks along a real physical seam. Atmosphere and solver come first,
because surface-level exchange coefficients never enter the tridiagonal matrices — the surface
flux enters through the RHS only. That makes an atmosphere-only granule genuinely
self-consistent: it takes prescribed grid-mean surface fluxes (`shfl`, `evapotrans`, `ustress`,
`vstress`, `q_snocpymlt`) as inputs and reproduces Fortran exactly. Surface tiles, exchange
coefficients and `ice_fast` follow as a second task inside the same package.

Work lands as stacked PRs per milestone (skeleton, pattern proofs, serialization, diagnostics,
scalar diffusion, momentum, full granule) so review stays tractable.

Ground truth is serialbox. The instrumentation lives on the icon-nwp branch `add_exp_ape_aes`
(`mo_icon4py_verification.f90`), driven by an APE AES R02B04 run with `use_tmx=T`. Every
milestone is green against savepoints before the next one starts.

## Rabbit holes

- **Reviving `f2py`.** Making the existing wrapper pass GPU pointers is a separate problem and
  not this bet. If the native granule works, the wrapper is dead code.
- **Reference-data version collisions.** The `exclaim_ape_aesPhys_v06` archive was once
  regenerated in place with muphys instrumentation and silently lost every `tmx-*` savepoint,
  stranding the whole test suite. Pin an archive version that no other port also claims, and
  keep `ICON4PY_ENABLE_TESTDATA_DOWNLOAD=false` in the local workflow.
- **GT4Py sharp edges.** `concat_where` on the `KDim == nlev-1` boundary needs a workaround
  (gt4py#2205). Document it in `tmx/docs/gt4py_patterns.md` and move on; do not fix GT4Py here.
- **Common-code dedup.** Tangential wind, TDMA scans and vertical integrals all already exist
  somewhere in `common`. Hoisting them is right, but timebox it — it is a cleanup branch after
  the granule is green, not a prerequisite.

## No-gos

- CO2 diffusion.
- 2m/10m diagnostics.
- Full JSBACH land — the granule consumes cut fluxes; the real land model is its own pitch.
- DaCe and any performance tuning. Correctness against Fortran first.
- Local Fortran builds. Instrumented runs happen where ICON already builds.
