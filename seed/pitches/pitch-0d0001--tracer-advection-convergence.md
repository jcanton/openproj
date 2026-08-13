---
id: pitch-0d0001
kind: pitch
title: Tracer advection convergence
parent: proj-000001
status: wip
owner: OngChia
assignees: [OngChia, nfarabullini, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: 1
depends_on: []
tags: [greenline, warm-bubble, tracer-advection, miura, torus, convergence]
prs: []
created_schema_version: 2
appetite_weeks: 6.0
shaped_by: nfarabullini
---

# Tracer advection convergence

## Problem

The horizontal advection granule uses the second-order MIURA scheme with a linear local
reconstruction over the `C2E2C` patch. We have the port, we have datatests against serialized
ICON output, and none of that tells us the scheme is actually second order. A datatest only says
"same numbers as Fortran at one resolution" — it passes just as happily if both codes are first
order because of a botched reconstruction, a mis-sized least-squares stencil, or a halo that is
one row too thin.

Three things are unfinished and they are entangled, which is why they are one pitch and not three:

1. The least-squares pseudo-inverse coefficients (`lsq_pseudoinv_1`, `lsq_pseudoinv_2`) that the
   reconstruction depends on.
2. Halo exchanges in the granule. `p_tracer_new` is the one field that will not validate under
   MPI — it sits above 2e-5, everything else is at roundoff.
3. A spatial convergence study on a doubly-periodic torus, which is the only test that would have
   caught either of the above independently of Fortran.

Without (3) we cannot tell a real order loss from an interpolation-coefficient bug, and without
(1) and (2) a convergence run on more than one rank is meaningless.

## Appetite

Six weeks. This started in cycle 36 and the convergence study is going to slip into 37 — that is
accepted, not a surprise. If it needs more than six weeks of actual work we stop and re-shape,
because at that point the problem is the scheme and not the test.

## Solution

Land the coefficients first (done, cycle 34), then the exchange, then the study. The study runs
the `linear_2nd_order` MIURA flux on a torus at a base resolution with refinement factors
1/2/4/8 and fits a slope to the L1 and L-infinity errors against an analytic reference, with a
tolerance band of 0.4 around the nominal order. Grids come from the `icon-grid-generator`
package rather than the downloaded `TORUS_1000X1000_*` files, because those do not all
discretise the same continuous problem: `domain_height` is 1039.23 for the 100M/50M grids and
995.93 for 25M/12M, since MPI-M's `fit_resolution()` adjusts the height when it converts a
domain size into row and column counts. Refining across that family compares two different
domains and the fitted slope is meaningless.

## Rabbit holes

- **The test harness lies before the scheme does.** Two separate order-killing bugs so far were
  both in the test, not in MIURA or in torus geometry. Budget for that; suspect the reference
  and the initial condition before the stencil chain.
- **Torus periodicity in the coefficients.** Already checked to 3e-15 on seam cells. Do not
  re-derive it.
- **Grid generator periodic layout.** Upstream's skew fundamental domain versus ICON's per-axis
  minimum image. Resolved in `icon-grid-generator>=0.8.0`; pass `periodic_layout="rectangular"`
  explicitly anyway.

## No-gos

- WENO (`ihadv_tracer` 102/103). That port is complete on its own branch and is not in scope
  here; a WENO convergence study is a separate bet.
- Higher-order least-squares reconstruction. `lsq_high_ord=3` mis-sizes the linear LSQ state
  through the interpolation factory and the warm bubble does not need it.
- `test_vertical_advection_convergence`. It has three real call-signature errors that mypy
  already flags. Pre-existing, untouched, and fixing it is not what this pitch is for.
