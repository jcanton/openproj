---
id: task-0d1001
kind: task
title: Second-order Miura least-squares coefficients
parent: pitch-0d0001
status: done
owner: nfarabullini
assignees: [nfarabullini, DropD]
reviewers: [OngChia, halungge]
review_waived: false
assigned_on: 2026-02-02
cycle: 34
priority: high
depends_on: []
tags: [greenline, tracer-advection, least-squares, interpolation, torus]
prs: ["C2SM/icon4py#1379", "C2SM/icon4py#1410"]
created_schema_version: 2
effort_weeks: 3.0
---

# Second-order Miura least-squares coefficients

## Problem

Second-order MIURA reconstructs the tracer on a local patch before integrating the upwind flux
across an edge. The patch is the polygon of cell centres reached through `C2E2C`; the
fit is `q = B a`, with `B` holding the distances from each neighbour to the patch origin. `B` is pure geometry, so ICON inverts it once at init and stores
it as `lsq_pseudoinv`. icon4py had the flux stencils but not the coefficients.

## Appetite

Three weeks. Init-time numpy, so the cost is matching ICON's conventions, not performance.

## Solution

Port `lsq_compute_coeff_cell` from `mo_intp_coeffs_lsq_bln.f90`, merging the sphere and torus
routines and dispatching on grid geometry (`match` on ICO / TORUS). Reuse the existing `C2E2C`
neighbour table instead of porting `create_stencil_c3`, build `B` from
`minimum_image_separation` offsets so seam cells get the wrapped separation, invert with numpy's
pseudo-inverse (`llsq_svd` is `True` in every EXCLAIM run script), and expose
`lsq_pseudoinv_1` / `lsq_pseudoinv_2` as interpolation-factory fields. Linear polynomial only:
`llsq_lin_consv` is `False` everywhere.

## Rabbit hole

- **Intermediate state.** `lsq_dim_stencil`, `lsq_idx_c`, `lsq_qtmat_c`, `lsq_moments_hat` and
  the rest are Fortran scratch, not icon4py interpolation fields. Porting them because the
  Fortran has them is the kind of fidelity that costs a week.
