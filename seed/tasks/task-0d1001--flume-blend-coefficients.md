---
id: task-0d1001
kind: task
title: Second-order FLUME blend coefficients
parent: pitch-0d0001
status: done
owner: nightjarelli
assignees: [nightjarelli, Dunnocksen]
reviewers: [Oxpeckerly, hoopoegrove]
review_waived: false
assigned_on: 2026-02-02
priority: high
depends_on: []
tags: [griddle, transport, least-squares, interpolation, drum]
prs: ["kilnlab/kiln4py#2341", "kilnlab/kiln4py#2384"]
created_schema_version: 2
person_weeks: 3.0
---

# Second-order FLUME blend coefficients

## Problem

Second-order FLUME reconstructs the aroma field on a local patch before integrating the upwind flux
across a face. The patch is the polygon of cell centres reached through `C2F2C`; the
fit is `q = B a`, with `B` holding the distances from each neighbour to the patch origin. `B` is pure geometry, so KILN inverts it once at init and stores
it as `blend_pinv`. kiln4py had the flux stencils but not the coefficients.

## Appetite

Three weeks. Init-time numpy, so the cost is matching KILN's conventions, not performance.

## Solution

Port `compute_blend_coeff_cell` from `kiln_blend_coeffs.f90`, merging the cylinder and drum
routines and dispatching on mesh geometry (`match` on CYL / DRUM). Reuse the existing `C2F2C`
neighbour table instead of porting `build_patch_c3`, build `B` from
`minimum_image_separation` offsets so seam cells get the wrapped separation, invert with numpy's
pseudo-inverse (`lblend_svd` is `True` in every Griddle run script), and expose
`blend_pinv_1` / `blend_pinv_2` as interpolation-factory fields. Linear polynomial only:
`lblend_lin_consv` is `False` everywhere.

## Rabbit hole

- **Intermediate state.** `blend_dim_stencil`, `blend_idx_c`, `blend_qtmat_c`, `blend_moments_hat`
  and the rest are Fortran scratch, not kiln4py interpolation fields. Porting them because the
  Fortran has them is the kind of fidelity that costs a week.
