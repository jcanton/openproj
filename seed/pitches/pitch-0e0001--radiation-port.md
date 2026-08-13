---
id: pitch-0e0001
kind: pitch
title: Radiation port
parent: proj-000001
status: todo
owner: halungge
assignees: [halungge, kotsaloscv]
reviewers: [jcanton, tehrengruber]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: [pitch-0a0001]
tags: [radiation, rte-rrtmgp, aes-physics, gt4py, port]
prs: []
created_schema_version: 2
appetite_weeks: 6.0
shaped_by: jcanton
---

# Radiation port

*(The task table still calls this row "ecRad". The code we actually port is ICON's AES
`rte_rrtmgp` path — same physics slot in the interface, different library. Ground truth is
`icon-nwp` master, which diverges from `icon-mpim` for real in `mo_rte_rrtmgp_interface.f90`:
grid-cell condensate + `ccwmin` versus in-cloud/`cld_frc`, and `isolrad` in {1,2}.)*

## Problem

The warm-bubble driver runs today with radiation switched off. That is fine for a dry dycore
test and wrong for anything with a diurnal cycle: without radiative cooling there is no
destabilisation, and the physics interface has a hole where the largest tendency in the free
troposphere should be. We need the full AES radiation path in icon4py: LW and SW gas optics,
cloud optics, aerosol optics, the two solvers, and the ICON-side driver logic (zenith angle,
`dt_rad` slow call versus the per-step heating in `interface_aes_rht`).

The hard part of this port is not the physics, it is attribution. Radiation is a spectral
scheme: every flux is a sum over 112/128 g-points, and the quantity we actually validate is
the heating rate, i.e. the vertical divergence of net flux — a difference of two O(100 W/m^2)
numbers producing O(1e-5) K/s. Reduction order therefore lands directly in the signal. Where
the driver asserts bitwise MPI equality (today only at `LEVELS=validation`, with
`CXXFLAGS=-ffp-contract=off`; at `integration` we fall back to a hand-fitted `atol=1e-13,
rtol=1e-14`), a heating-rate mismatch is diagnostic. Where it does not, the same mismatch is
ambiguous: real bug, or summation noise reshuffled by a codegen change. Plan the validation
around that. Single-rank g-point reduction on the host is the reference; multi-rank
comparisons are read as advisory until the reproducibility work makes them exact. That is why
this pitch depends on pitch-0a0001: without deterministic reductions a heating-rate diff cannot
distinguish a porting bug from reduction-order noise, so validating the port before that work
lands would produce numbers nobody could act on. We
budget for re-fitting tolerances rather than assuming they hold.

## Appetite

Six weeks, two people. That covers shortwave and longwave to validated stencils against the
numpy references and the APE savepoints. It does not cover integration into
`physics_driver_l2`.

## Solution

Approach A, full-DSL port, in `model/atmosphere/subgrid_scale_physics/radiation`. Cartesian
`(Cell, Gpt, K)` stencils and no connectivities anywhere; flattened-table gathers via
`as_offset`; chunked execution over cells (an `nproma_sub` analog — a g-point-resolved field is
~1.3 GB at full grid, so nothing lives in memory whole). Two granules, mirroring ICON:
`RteRrtmgpRadiation` on `dt_rad` and `Radheating` every step.

M0-M2 are already done on branch `port_radiation`: the pattern survey, `kdist.py` and
`cloud_optics_tables.py` with 18 unit tests against normative values, and the Fortran savepoints
(`radiation-entry/exit`, `radiation-profiles-exit`, `radheating-entry/exit`) on
`serialize_rrtmgp`. This pitch is M3/M4: the solvers.

Validation is three-legged: numpy reference ports (`rrtmgp/reference/`) for stencil-level
agreement, APE AES serialbox savepoints for the assembled granule, and pyRTE-RRTMGP as an
independent oracle for the g-point-resolved internals that are never serialized.

## Rabbit holes

- **Plain-dim reductions.** The g-point sum is the one gt4py gap. It stays host-side; the
  DSL fake-connectivity workaround measured 480x slower and is rejected. Band expansion is
  likewise host-side `np.take`. Do not reopen this.
- **Vacuous reference data.** The muphys post-mortem applies verbatim: the APE archive from the
  JW initial condition has RH_max = 0.503 and never condenses, so a cloud-optics test on it
  asserts that the scheme is a no-op on a dry column. Run
  `./scripts/run inspect-savepoints stats` before trusting any green test, and remember cell
  fields are nproma-padded (30720 slots for 20480 cells, so healthy caps at 0.667 nonzero).
  If the archive has not been regenerated with `ztmc_ape=50`, validate clear-sky only and say so.
- **`irad_o3=0`** in the serialization experiment avoids the pool-file dependency. Ozone
  climatology is a separate fight.

## No-gos

- No McICA and no reduced radiation grid — the AES path has neither; binary cloud fraction and
  hardcoded LUT cloud optics is the target, not a stepping stone.
- No integration into `physics_driver_l2` this cycle. Keep the granule signature compatible and
  wire it later, same as TMX.
- No GPU tuning. Correctness on `gtfn_cpu` first.
