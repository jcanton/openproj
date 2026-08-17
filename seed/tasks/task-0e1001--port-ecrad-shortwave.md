---
id: task-0e1001
kind: task
title: Port ecRad shortwave
parent: pitch-0e0001
status: ready
owner: kotsaloscv
assignees: [kotsaloscv]
reviewers: [halungge, tehrengruber]
review_waived: false
assigned_on: 2026-08-17
priority: high
depends_on: []
tags: [radiation, shortwave, two-stream, gt4py]
prs: []
created_schema_version: 2
person_weeks: 3.5
---

# Port ecRad shortwave

## Problem

The shortwave half of the AES radiation path is unported: SW gas optics including Rayleigh, the
cloud-optics lookup, delta-scaling, and the two-stream solver with the adding method. Longwave, the
`Radheating` granule and any diurnal cycle in the warm bubble sit behind it, because both share the
k-distribution reader, the chunked `(Cell, Gpt, K)` machinery and the host-side g-point reduction
this task lands first.

## Appetite

3.5 weeks, longer than longwave because the shared infrastructure is charged here.

## Solution

Reuse `kdist.py` for the flavour/eta interpolation and the two-sided flat-table `as_offset` gather,
adding the Rayleigh branch — a second k-major table selected by the troposphere flag, carried as a
boolean field, not a scalar branch. Cloud optics are the ECHAM6 61-point LUTs
(`ECHAM6_CldOptProps_rrtmgp_*.nc`, *not* the identically named AER files), binary cloud fraction,
grid-cell condensate under `ccwmin`; then delta scaling and `sw_two_stream`/`sw_source_2str`, the
adding method as the scan pair validated at rtol 1e-8 in M1. Driver side is the cosine zenith angle,
`isolrad=2` scaling and a night mask — a cartesian stencil cannot skip night columns, so assert
`flux == 0` where `mu0 <= 0`.

## Rabbit holes

- Stencil tests need an empty-connectivities grid proxy: gtfn asserts on neighbour tables even for
  purely cartesian programs.
