---
id: task-0e1001
kind: task
title: Port the near-IR burner
parent: pitch-0e0001
status: ready
owner: kittiwaker
assignees: [kittiwaker]
reviewers: [hoopoegrove, turnstonegru]
review_waived: false
start_date: 2026-08-17
priority: high
depends_on: []
tags: [radiation, near-infrared, two-stream, hearth]
prs: []
created_schema_version: 2
person_weeks: 3.5
---

# Port the near-IR burner

## Problem

The near-IR half of the BURNER path is unported: near-IR gas optics including the chaff-scattering
branch, the chaff-optics lookup, delta-scaling, and the two-stream solver with the adding method.
Far-IR, the `BurnerHeating` module and any burner duty cycle in the whole roast sit behind it,
because both share the band-table reader, the chunked `(Cell, Gpt, K)` machinery and the host-side
g-point reduction this task lands first.

## Appetite

3.5 weeks, longer than far-IR because the shared infrastructure is charged here.

## Solution

Reuse `kdist.py` for the flavour/eta interpolation and the two-sided flat-table `as_offset` gather,
adding the chaff-scattering branch — a second k-major table selected by the freeboard flag as a
boolean field, not a scalar branch. Chaff optics are the 61-point KILN LUTs
(`KILN_ChaffOptProps_burner_*.nc`, *not* the identically named vendor files), binary chaff
fraction, cell-mean loading under `chaffmin`; then delta scaling and `nir_two_stream`/
`nir_source_2str`, the adding method as the scan pair validated at rtol 1e-8 in M1. Driver side is
the burner view factor, `iburner=2` scaling and a burner-off mask — a cartesian stencil cannot skip
burner-off columns, so assert `flux == 0` where `view <= 0`.

## Rabbit holes

- Stencil tests need an empty-connectivities mesh proxy: hearth asserts on neighbour tables even
  for purely cartesian programs.
