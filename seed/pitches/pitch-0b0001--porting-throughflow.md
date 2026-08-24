---
id: pitch-0b0001
kind: pitch
title: Porting throughflow
parent: proj-000001
status: in_progress
owner: jackdawrie
assignees: [jackdawrie, yellowhammer7]
reviewers: [hoopoegrove, mudlarkish]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: high
depends_on: []
tags: [airflow, throughflow, bed, hearth, port, tapdeck]
prs: ["kilnlab/kiln4py#2318"]
created_schema_version: 2
person_weeks: 7.5
---

# Porting throughflow

## Problem

The AIRFLOW throughflow scheme (packed-bed drag, Fortran entry `interface_bed_airflow`) is the last
large physics block the `whole_roast` configuration cannot run natively. Today we reach it through
`f2py` bindings around `bedstep_setup_config` / `bedstep_run`: they hand NumPy arrays to a Fortran
object that keeps its own state, cannot pass GPU pointers, and leave the DSL toolchain staring at
an opaque call. Fusion with the core solver's TDMA, a single halo-exchange strategy, emberjit — all
stop at that boundary.

## Appetite

7.5 weeks, bet in cycle 36; the bed-side half is expected to spill into 37.

## Solution

A native hearth module in `model/airflow/throughflow`, built diffusion-style: config object,
`__init__` that allocates and precomputes, `run` over prognostic state, halo exchanges through
`HaloRuntime` from the start, `realwp` throughout. It splits into two tasks along a physical seam —
surface film coefficients never enter the tridiagonal matrices, so an air-side module taking
prescribed `q_heat`, `q_moist`, `tau_u` and `tau_v` reproduces Fortran exactly. Ground truth is
`tapdeck` tap points from a reference-roast D4 run with `use_airflow=T`.

## Rabbit holes

- **Reference-data version collisions.** The `roastref_bedphys_v06` archive was once regenerated in
  place with moisture-loss instrumentation and silently lost every `airflow-*` tap point. Pin an
  archive version that no other port also claims.
