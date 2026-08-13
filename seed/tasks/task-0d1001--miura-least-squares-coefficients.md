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
priority: 0
depends_on: []
tags: [greenline, tracer-advection, least-squares, interpolation, torus]
prs: ["C2SM/icon4py#1028", "C2SM/icon4py#1099", "C2SM/icon4py#1103"]
created_schema_version: 2
effort_weeks: 3.0
---

# Second-order Miura least-squares coefficients

## Problem

Second-order MIURA reconstructs the tracer field on a local patch before it integrates the
upwind flux across an edge. The patch is the polygon of cell centres reached through `C2E2C`,
and the reconstruction is a 2D polynomial fit: `q = B a`, with `q` the neighbouring cell-centre
values, `a` the polynomial coefficients, and `B` a matrix of the distances from each neighbour
to the patch origin. `B` depends only on geometry, so ICON inverts it once at init — a
pseudo-inverse when the stencil has more rows than unknowns — and stores it as `lsq_pseudoinv`.
icon4py had the flux stencils but not the coefficients, so the granule had nothing to
reconstruct with.

## Appetite

Three weeks. Coefficient computation is init-time numpy, not a hot loop, so the cost is in
matching ICON's conventions rather than in performance work.

## Solution

Port `lsq_compute_coeff_cell` from `mo_intp_coeffs_lsq_bln.f90`, both branches. The sphere and
torus versions differ enough that a single copy-pasted routine would be wrong, so the port
merges them and dispatches on grid geometry (`match` on ICO / TORUS). Steps:

1. Merge the two Fortran routines and branch on geometry.
2. Reuse the existing `C2E2C` neighbour table rather than porting `create_stencil_c3`.
3. Build `B` from the neighbour offsets — on the torus these come out of
   `minimum_image_separation`, so seam cells get the wrapped separation and not a
   full-domain-wide one.
4. Invert with numpy's pseudo-inverse. `llsq_svd` is `True` in every EXCLAIM run script, so the
   non-SVD branch is not ported.
5. Expose the result as `lsq_pseudoinv_1` and `lsq_pseudoinv_2` factories in the interpolation
   factory.
6. Datatest against serialized ICON coefficients.

Only the linear polynomial is built. `llsq_lin_consv` is `False` everywhere in our run scripts,
so the conservative-constraint path is skipped.

## Rabbit holes

- **Intermediate state.** `lsq_dim_stencil`, `lsq_idx_c`, `lsq_blk_c`, `lsq_weights_c`,
  `lsq_qtmat_c`, `lsq_moments`, `lsq_moments_hat`, `lsq_rmat_utri_c` and `lsq_rmat_rdiag_c` are
  Fortran scratch. They do not become icon4py interpolation fields. Porting them as fields
  because they exist in the Fortran is exactly the kind of fidelity that costs a week.
- **Torus seam correctness.** Verified rather than assumed: the TORUS branch agrees with an
  independent numpy replica to 3e-15 on seam cells. That number is why the convergence
  investigation later ruled the coefficients out immediately.
- **Neighbour-table ordering.** The butterfly orderings differ between `grid_manager` and
  `simple.py`. Match by cell index; never assume a fixed ordering.

## No-gos

- Higher-order (quadratic, cubic) reconstruction. The warm bubble does not need it.
- Cleaning up the `gridShape` lat/lon plus cart_x/y interface into `compute_coeffs`. Real, but
  it is a separate cleanup and was carried over as its own item.
