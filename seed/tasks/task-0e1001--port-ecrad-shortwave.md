---
id: task-0e1001
kind: task
title: Port ecRad shortwave
parent: pitch-0e0001
status: todo
owner: kotsaloscv
assignees: [kotsaloscv]
reviewers: [halungge, tehrengruber]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: []
tags: [radiation, shortwave, two-stream, gt4py]
prs: []
created_schema_version: 2
effort_weeks: 3.5
---

# Port ecRad shortwave

## Problem

The shortwave half of the AES radiation path is unported: SW gas optics (including the Rayleigh
contribution), the cloud-optics lookup, delta-scaling, and the two-stream solver with the adding
method. Everything downstream — the longwave sweep, the `Radheating` granule, any diurnal cycle
in the warm bubble — sits behind it, because both solvers share the k-distribution reader, the
chunked `(Cell, Gpt, K)` domain machinery and the host-side g-point reduction that this task
puts in place first.

## Appetite

3.5 weeks. Longer than longwave because the shared infrastructure is charged here.

## Solution

Follow the M0/M1 patterns already proven on `port_radiation`:

1. **SW gas optics.** Reuse `kdist.py` for the flavour/eta interpolation; the two-sided
   temperature/pressure gather is the flat-table `as_offset` pattern (proven gtfn-only; embedded
   skips). Add the Rayleigh branch, which in RRTMGP is a second k-major table selected by the
   troposphere flag — a bare boolean carried as a field, not a branch on a scalar.
2. **Cloud optics.** ECHAM6 61-point LUTs (`ECHAM6_CldOptProps_rrtmgp_*.nc`, linked as
   `rrtmgp-cloud-optics-coeffs-*.nc` — *not* the identically named AER files). Binary cloud
   fraction, grid-cell condensate with `ccwmin` per icon-nwp master.
3. **Delta scaling**, then the **two-stream solver**: `sw_two_stream` reflectance/transmittance
   per layer, `sw_source_2str` for the direct beam, and the adding method as a scan pair
   (downward accumulation then upward), the same carry pattern validated at rtol 1e-8 against
   numpy in M1. Note `field(dims.Koff[-1])` does not lower — use bare `KDim - 1` and pass
   `offset_provider={}`.
4. **Driver side.** Cosine zenith angle and the solar constant scaling (`isolrad=2`), plus the
   night mask. A cartesian stencil cannot skip night columns, so we mask and eat the cost;
   compaction is a performance question for later, but assert `flux == 0` where `mu0 <= 0` so
   the mask itself is tested.

Validate stencil-by-stencil against `rrtmgp/reference/gas_optics_ref.py` and `solvers_ref.py`,
then the assembled granule against the `radiation-entry` / `radiation-profiles-exit` savepoints,
with pyRTE-RRTMGP as the oracle for the g-point-resolved intermediates that are never
serialized.

## Rabbit holes

- The g-point sum stays host-side. Settled in M1 (fake-connectivity DSL reduction: 480x slower).
- Stencil tests need an empty-connectivities grid proxy — gtfn asserts on neighbour tables even
  for purely cartesian programs.
- Do not chase the clear-sky fields here. `lclrsky` is allocated only when the output namelist
  requests it; pyRTE covers clear-sky for now.

## No-gos

- No aerosol optics in this task. `irad_o3=0` and no aerosols in the serialization experiment;
  an aerosols-on APE run is an optional later dataset.
- No spectral-dimension abstraction layer. `Gpt` is a plain cartesian dimension; if a future
  scheme needs bands as first-class, that is a different port.
