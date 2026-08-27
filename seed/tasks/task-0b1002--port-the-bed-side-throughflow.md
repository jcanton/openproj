---
id: task-0b1002
kind: task
title: Port the bed-side throughflow
parent: pitch-0b0001
status: in_progress
owner: yellowhammer7
assignees: [yellowhammer7, jackdawrie]
reviewers: [jackdawrie, hoopoegrove]
review_waived: false
start_date: 2026-07-13
priority: high
depends_on: [task-0b1001]
tags: [airflow, throughflow, surface, chaff, hearth, verification]
prs: ["kilnlab/kiln4py#2247"]
created_schema_version: 2
person_weeks: 3.5
---

# Port the bed-side throughflow

## Problem

The air-side module runs on prescribed bed-mean surface fluxes. That was the right seam, but
it leaves the whole tiled surface layer of AIRFLOW — `t_bed_sfc`, the bean, chaff and
drum-wall tiles, and the film-coefficient solve that produces those fluxes — Fortran-only. Until it
is ported, kiln4py cannot close the throughflow loop.

## Appetite

3.5 weeks, behind the air-side task in cycle 36; realistically finishes in 37.

## Solution

A `surface/` submodule inside the existing airflow package, in four stages: the roughness
closure plus the five-iteration film-coefficient solve, as a first-guess program and five step
programs rather than one unrolled DSL expression; prescribed DRUMBED-cut fluxes, bulk drag
only; the zero-layer chaff model with scheme-1 emissivity, its lagged forcing carried in
`SurfaceState` because the lag is in the Fortran; and four tap points (surface entry, exchange,
chaff exit, per-tile fluxes) off our own branch. Drum wall, bean and chaff are committed, and the
exchange stage validates at `rtol=1e-9` on both backends.

## Rabbit holes

- **The archive runs the bypass path.** `roast_case='REF_bed'` yields one drum-wall tile, and with
  `isfc_type=1` AIRFLOW takes the prescribed-flux bypass (`kiln_bed_surface.f90:802`), so the real
  bulk-flux path is never exercised; flux validation needs an `isfc_type=0` rerun into a
  separate archive.
