---
id: task-0e1002
kind: task
title: Port ecRad longwave
parent: pitch-0e0001
status: todo
owner: yiluchen1066
assignees: [yiluchen1066]
reviewers: [kotsaloscv, halungge]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 2
depends_on: [task-0e1001]
tags: [radiation, longwave, no-scatter-solver, planck-source, gt4py]
prs: []
created_schema_version: 2
effort_weeks: 2.5
---

# Port ecRad longwave

## Problem

Longwave is what actually cools the atmosphere, so without it the granule produces a one-sided
heating rate and the `Radheating` tendency cannot be compared against `radheating-exit`. AES uses
the cheapest solver in the library, `1scl`: no scattering, one angle at diffusivity D = 1.66. The
physics is simpler than shortwave; the work is the Planck sources and two-sweep transport.

## Appetite

2.5 weeks, chained behind `task-0e1001` for its `kdist.py`, chunked `(Cell, Gpt, K)` handling and
host-side g-point reduction.

## Solution

The same `kdist.py` interpolation minus Rayleigh, plus the major/minor absorber contributions LW
uses; `lay_source`, `lev_source` at both interfaces and `sfc_source` from surface temperature and
emissivity via the `totplnk` table, band-to-g-point expansion host-side (`np.take`). Then the
no-scattering solver — `tau_loc = D * tau`, `exp(-tau_loc)`, and the small-tau Padé/Taylor branch as
a `where` on a computed field, never a Python-level `if`, or the definedness analysis rejects it —
then the TOA-down and surface-up sweeps as the M1 scan pair.

## Rabbit holes

- **Sign and level conventions.** RRTMGP indexes levels top-down and ICON's interface flips some of
  them; `mo_rte_rrtmgp_interface.f90` on icon-nwp master is the authority, not the library's test
  driver. Getting `lev_source_inc`/`lev_source_dec` backwards shows up as a heating rate right in
  magnitude and wrong in sign near the tropopause.
