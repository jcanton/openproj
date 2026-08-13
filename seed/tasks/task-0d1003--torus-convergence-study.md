---
id: task-0d1003
kind: task
title: Convergence study on the torus grid
parent: pitch-0d0001
status: todo
owner: jcanton
assignees: [jcanton, OngChia]
reviewers: [OngChia, ajocksch]
review_waived: false
assigned_on: 2026-08-17
cycle: 37
priority: 1
depends_on: [task-0d1002]
tags: [greenline, tracer-advection, convergence, torus, testing]
prs: []
created_schema_version: 2
effort_weeks: 2.5
---

# Convergence study on the torus grid

## Problem

We claim the horizontal advection is second order. Nothing in the test suite demonstrates it.
A spatial convergence study on a doubly-periodic torus is the cheapest test that would catch an
order loss without a Fortran oracle — advect a smooth bump at constant velocity, refine, fit a
slope to the L1 and L-infinity errors, and expect 2 within a band of 0.4.

The first attempts at this did not produce a slope, they produced a lottery. Jittering the mean
edge length by 0.2 % swung the fit anywhere over 0.21 to 2.29. Both causes turned out to be in
the test rather than in the scheme, and both are the kind of thing that will come straight back
if this is rebuilt carelessly.

## Appetite

Two and a half weeks, and it will run past the end of the cycle it was bet in. The measurement
harness is most of the work; the runs themselves are minutes.

## Solution

**Fix the reference time.** The driver computes `n_time_steps = int(relative / dtime)` — a
floor, no partial final step — while the analytical reference was built at the nominal
integration time. Since `dtime` scales with the mean edge length, the leftover `r = T - n·dt`
is an O(h) phase error whose value is the fractional part of `T/dt`, i.e. noise. On the finest
grid it was roughly fifteen times the true error. Build the reference at `n_time_steps *
dtime_in_seconds` instead. With that fixed the slope is flat in integration time, and the old
folk belief that "the order is fine as long as the tracer does not cross the seam" evaporates —
short runs simply happened to land on a small `r`.

**Fix the initial condition.** The minimum-image Gaussian is only C0 on the torus:
`minimum_image_separation` clips `dx` to `[-L/2, L/2]`, which puts a slope kink on the
half-domain line. The 2D branch uses a decay of `((L+H)/2)^-1.65`, so the bump is still at 6.6 %
of peak at the kink and sheds a dispersive wake off it; the 1D branch is 136 times weaker there
and looks clean, which is the whole "reflected waves in 2D but not 1D" report. Replace the
min-image Gaussian with a periodic sum over the +/-2 images. The off-centre variant is worse
still, because it shifts `dy` after the min-image reduction and turns the seam into a genuine
jump.

**Generate the grids.** Use the `icon-grid-generator` package through a session-scoped fixture
parametrized on `(n_rows, n_cols, edge_length)`, `n_rows` even and >= 4, `n_cols` >= 3. Pass
`periodic_layout="rectangular"` explicitly.

## Rabbit holes

- **The non-periodic reference-data quirk.** ICON's `plane_torus_distance` never actually wraps
  for the idealized torus testcases: callers pre-divide coordinates by the feature width while
  the threshold stays dimensional, so the wrap branch fires only if the feature width is below
  about 2 m — the domain length cancels. Serialized reference data therefore contains
  corner-clipped, non-periodic features. Our distance helper takes `wrap` as a required keyword
  for exactly this reason, and the existing call sites pass `wrap=False` on purpose. Adding a
  "correct" wrap moves the footprint by ~2.5 % and breaks the datatest. Do not fix it here.
- **Already ruled out with evidence, do not re-investigate:** the MIURA stencil chain, the torus
  branch of the coefficient computation, the tangent-plane projection, the h_grid zones, the
  positive-definite limiter, the quadrature initial condition, the buffer swap.

## No-gos

- Retuning the 2D decay factor. That sweep is already measured and handed over.
- Asserting an L-infinity order for the discontinuous case. A discontinuity does not converge in
  the max norm; assert L1 only, and expect it to clear a first-order floor by very little.
