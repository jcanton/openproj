---
id: pitch-2a7f3e
kind: pitch
title: Tracer adv port LS coeffs
parent: null
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
appetite_weeks: null
shaped_by: null        # REQUIRED from schema_version 2; not in source
assignees:
  - nfarabullini
  - DropD
assigned_on: null
cycle: 34
priority: high
depends_on: []
tags:
  - greenline
  - warm-bubble
  - tracer-advection
prs: []
---

# [Greenline] Warm Bubble: Least-Squares Coefficients in Tracer Advection

> Shaping doc: <https://hackmd.io/z84FEYwkToCiqNicr3K5jQ> (team permalink <https://hackmd.io/@gridtools/r1fq-5LS-l>), tagged `cycle 34 02/26`, `warm bubble`.
> Shaped by: @ChiaRuiOng, @nfarabullini — Developers: "Nikki, Rico (for later)".

## Problem

The horizontal advection granule adopts second-order Miura advection scheme. However, the least-squares coefficients required in second-order Miura advection scheme with nonlinear local reconstruction are not ported to icon4py. A local reconstruction here means a 2D polynommial interpolation of a local patch from values at cell centers bounded by the C2E2C polygon. In mathematical notation, the interpolated value at coordinates (x,y) inside the local patch can be found by `q = Ba`, where `q` is the tracer value at neighboring cell centers and `a` is the coordinates. `A` is the least-squares matrix which is a function of distance between neighboring cell centers and the origin. We invert (pseudo-inverse if number of rows > number of unknowns) the matrix and store as pre-computed coefficients. This inverted matrix is used when computing interpolated values `f = B-1 q`,

```
B = (
     x1, y1, x1^2, ..., 
     x2, y2, x2^2, ..., 
     ...,
     xn, yn, xn^2, ..., 
    )
a = (a_x, a_y, a_xx, ...)
q = (q1, q2, q3, ...)
```

We only use the linear polynomial for the reconstruction in icon4py because only the second-order Miura scheme is currently supported.

![Stencil](https://hackmd.io/_uploads/rJSy-23Hbe.png)
![Equation](https://hackmd.io/_uploads/Sy_Zb2hH-e.png)

## Appetite

*(Section empty in the source note; the header line reads `- Appetite (FTEs, weeks):` with no value. See the migration notes below — `appetite_weeks` is deliberately null, not guessed.)*

## Solution

- The least-squares coefficients are declared as `lsq_pseudoinv` in ICON.
- `dim_c`, `dim_unk`, and `wgt_exp` are namelist parameters. They are set in [mo_interpol_config.f90](https://github.com/C2SM/icon-exclaim/blob/7076be7d4d0443d9027f9e2871d530da47af31dc/src/configure_model/mo_interpol_config.f90#L351).
- The actual computation of the least-squares coefficients can be found in subroutines [lsq_compute_coeff_cell](https://github.com/C2SM/icon-exclaim/blob/b392c1a77a331015a753bc9386eea4339e994e1a/src/shr_horizontal/mo_intp_coeffs_lsq_bln.f90#L536C12-L536C34) in `mo_intp_coeffs_lsq_bln.f90`.
- The code seems to be **slightly different in Torus and icosahedral grids**. We need to port most of the computation in [lsq_compute_coeff_cell_sphere](https://github.com/C2SM/icon-exclaim/blob/b392c1a77a331015a753bc9386eea4339e994e1a/src/shr_horizontal/mo_intp_coeffs_lsq_bln.f90#L595) and [lsq_compute_coeff_cell_torus](https://github.com/C2SM/icon-exclaim/blob/b392c1a77a331015a753bc9386eea4339e994e1a/src/shr_horizontal/mo_intp_coeffs_lsq_bln.f90#L1356).
- The intermediate variables `lsq_dim_stencil`, `lsq_idx_c`, `lsq_blk_c`, `lsq_weights_c`, `lsq_qtmat_c`, `lsq_moments`, `lsq_moments_hat`, `lsq_rmat_utri_c`, `lsq_rmat_rdiag_c` do not need to be stored as interpolation fields in icon4py.
- We may also need to port [create_stencil_c3](https://github.com/C2SM/icon-exclaim/blob/b392c1a77a331015a753bc9386eea4339e994e1a/src/shr_horizontal/mo_intp_coeffs_lsq_bln.f90#L100), because it is called to compute the `C2E2C` neighbor table which is subsequently used in the construction of `lsq_pseudoinv`. **Check whether we already have the neighbor table in icon4py**.
- Namelist parameter `llsq_lin_consv` is always `False`, which is the default value, in all EXCLAIM run scripts.
- we set `llsq_svd` to `True` in our exclaim run scripts. The part of the code if `llsq_svd == False` does not need to be ported.

In summary, the steps are:

1. merge the copy-paste and do `match geometry ICO/TORUS`
2. construct neighbor table `C2E2C` (may not be necessary).
3. construct the least-squares matrix `B`.
4. invert the matrix by utilizing Python library (or simply numpy?).
5. store the inverted matrix as `lsq_pseudoinv_x` and `lsq_pseudoinv_y` in the interpolation factory.
6. construct a data test for the least-squares coefficients.

## Rabbit holes

Higher-order least squares interpolation is not required for the warm bubble experiment.

## No-gos

*(Section empty in the source note.)*

## Progress

- [x] merge the copy-paste and do `match geometry ICO/TORUS`
- [x] construct the least-squares matrix `B`.
- [x] invert the matrix by utilizing library
- [x] construct a data test for the least-squares coefficients.
- [x] store the inverted matrix as `lsq_pseudoinv_x` and `lsq_pseudoinv_y` / make `lsq_pseudoinv_1` and `lsq_pseudoinv_2` factories
- [x] merge functionality of `math/projection.py::plane_torus_closest_coordinates` with `math/helpers.py::diff_on_edges_torus`
- [x] merge `math/projection.py::gnomonic_proj` and `gnomonic_proj_single_val`
- [ ] cleanup gridShape lat/lon + cart_x/y interface to compute_coeffs → carried over as task `task-2b6c94`

---

## Migration notes (not part of the original shaping doc)

**Source row** — row 16 of *[Greenline] Open projects TABLE* (<https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg>), verbatim:

```
| 16  | Tracer adv port LS coeffs | High | Done | N+Rico |  |  | [LS coeff. shape-up] | We need to port least square coeffs which are used in Miura 2nd-order scheme |
```

The table's `[LS coeff. shape-up]` link definition resolves to <https://hackmd.io/z84FEYwkToCiqNicr3K5jQ>, i.e. the shaping doc reproduced above — this pitch's body is table-declared, not inferred.

**Appetite is null on purpose.** No appetite is stated for this pitch anywhere: the note's `- Appetite (FTEs, weeks):` line is blank, its `## Appetite` section is empty, and the Appetite column of *OVERVIEW - Cycle 34 02/26* is blank on this row. The only appetite in the lineage belongs to the umbrella note *[Greenline] Warm Bubble Experiment Tasks for Cycle 34* (<https://hackmd.io/5ceTe0y2SZWJGZBwFDdMiQ>), which says "Full Cycle 34, with XY people" — cycle 34 is stated as 8 weeks long (betting table 27.01.2026, review meeting 24.03.2026) — but that covers all eight warm-bubble sub-pitches, so it cannot be attributed to this one.

**Who = "N+Rico".** N = Nikki = Nicoletta Farabullini, GitHub `nfarabullini` (a C2SM/icon4py contributor, and one of the two shapers of this note). Rico = Rico Haeuselmann, GitHub `DropD` (a C2SM/icon4py contributor); the corpus writes him as HackMD handle `@ricoh`, which is *not* his GitHub account. The note qualifies Rico as "(for later)".

**Dependencies.** The row's "Depends on" cell is empty, so `depends_on` is empty. Row 15 (*Tracer adv*) lists "16,17,18" in its own Depends on cell — that edge belongs on row 15, not here. The row-18 shaping doc explicitly decouples the two: "In order not to depend on porting of the 'lsq_pseudoinv_1 and lsq_pseudoinv_2' coefficients (done independently) [shaped here], we can initialize with 0 at first".

**PRs.** The table's PR column is empty for this row and the shaping doc cites no PR, so `prs` is empty. For the next stage: a GitHub search finds C2SM/icon4py#1028 "Least square tracer advection coefficients implementation" (merged 2026-02-05, author `nfarabullini`, body "porting of advection least square coefficients for both sphere and torus"), with follow-ups #1099, #1103 and #1379 — almost certainly this row's work, but not recorded in `prs` because no source cites them.

**Parent.** No project entity was created: the row's group ("rows 15-19, tracer advection") is an inferred label — the table encodes grouping only as blank rows and has no heading. The natural umbrella, if one is ever created, is *[Greenline] Warm Bubble Experiment Tasks for Cycle 34* (<https://hackmd.io/5ceTe0y2SZWJGZBwFDdMiQ>), which lists this pitch as one of eight subtasks.

**Priority.** The table uses four levels (High+, High, Medium, Low), mapped order-preserving onto 0/1/2/3; this row's "High" → 1.

**Status.** The table says Done and the implementation PR is merged, so status is `done` — but the Progress checklist still has one unchecked item, migrated as task `task-2b6c94` rather than dropped.
