---
id: pitch-2a7f3e
kind: pitch
title: Transport port blend coeffs
parent: null
status: done
owner: null            # REQUIRED from schema_version 1; not in source
reviewers: []          # REQUIRED from schema_version 1; not in source
person_weeks: null
assignees:
  - nightjarelli
  - Dunnocksen
assigned_on: null
cycle: 34
priority: high
depends_on: []
tags:
  - griddle
  - whole-roast
  - transport
prs: []
---

# Griddle whole_roast: blend-weight coefficients in aroma transport

> Bet in cycle 34, tagged `whole roast`; this is the coefficients half.
> Shaped by: @Oxpeckerly, @nightjarelli — Developers: "Nightjar, Dunnock (for later)".

## Problem

The horizontal transport module uses the second-order FLUME scheme. The blend-weight coefficients
that scheme needs for its nonlinear local reconstruction are not ported to kiln4py. A local
reconstruction here means a 2D polynomial fit over the patch of cells bounded by the `C2F2C`
polygon, from the values at their centres. In the usual notation the value at (x,y) inside the
patch is `q = Ba`, where `q` holds the aroma concentration at the neighbouring centres and `a` the
polynomial coefficients. `B` is the blend matrix, a function of distance between each neighbour
centre and the origin. We invert it — pseudo-inverse when there are more rows than unknowns — and
store the result as pre-computed coefficients, so the per-step cost is a matrix-vector product:

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

We only need the linear polynomial, because the second-order FLUME scheme is the only one kiln4py
supports. The higher-order rows of `B` are most of what makes this look bigger than it is.

## Appetite

*No appetite was written down for this pitch. Cycle 34 was bet whole, across all eight whole_roast
sub-pitches, so nothing in that number belongs to this one alone.*

## Solution

- The blend-weight coefficients are declared as `blend_pinv` in KILN.
- `dim_c`, `dim_unk` and `wgt_exp` are namelist parameters. They are set in `kiln_blend_config.f90`.
- The computation itself lives in the subroutine `compute_blend_coeff_cell` in
  `kiln_blend_coeffs.f90`.
- The code is **slightly different on the drum mesh and on the full-plant mesh**. We need to port
  most of the computation in `compute_blend_coeff_cell_plant` and `compute_blend_coeff_cell_drum`.
- The intermediate variables `blend_dim_stencil`, `blend_idx_c`, `blend_blk_c`, `blend_weights_c`,
  `blend_qtmat_c`, `blend_moments`, `blend_moments_hat`, `blend_rmat_utri_c` and
  `blend_rmat_rdiag_c` do not need to be stored as interpolation fields in kiln4py.
- We may also need to port `create_stencil_c3`, because it is called to compute the `C2F2C`
  neighbour table that is subsequently used to construct `blend_pinv`. **Check whether we already
  have that neighbour table in kiln4py**.
- Namelist parameter `lblend_lin_consv` is always `False`, which is the default, in all Griddle run
  scripts.
- We set `lblend_svd` to `True` in our run scripts. The branch taken when `lblend_svd == False`
  does not need to be ported.

In summary, the steps are:

1. merge the copy-paste and do `match geometry PLANT/DRUM`
2. construct neighbour table `C2F2C` (may not be necessary).
3. construct the blend matrix `B`.
4. invert the matrix by utilizing a Python library (or simply numpy?).
5. store the inverted matrix as `blend_pinv_x` and `blend_pinv_y` in the interpolation factory.
6. construct a data test for the blend-weight coefficients.

## Rabbit holes

Higher-order blend interpolation is not required anywhere in the whole_roast experiment.

## No-gos

*(Left empty when this was shaped.)*

## Progress

- [x] merge the copy-paste and do `match geometry PLANT/DRUM`
- [x] construct the blend matrix `B`.
- [x] invert the matrix by utilizing library
- [x] construct a data test for the blend-weight coefficients.
- [x] store the inverted matrix as `blend_pinv_x` and `blend_pinv_y` / make `blend_pinv_1` and `blend_pinv_2` factories
- [x] merge functionality of `math/projection.py::drum_closest_coordinates` with `math/helpers.py::diff_on_faces_drum`
- [x] merge `math/projection.py::gnomonic_proj` and `gnomonic_proj_single_val`
- [ ] cleanup meshShape lat/lon + cart_x/y interface to compute_coeffs → carried over as task `task-2b6c94`

---

## Notes from the betting table

**The appetite line was left blank on purpose, and stayed blank.** Somebody asked for a number in
the room and nobody would give one: the honest answer was that the size depends entirely on whether
the two geometry variants really have to be ported separately, and that is not knowable until the
first one is read properly. The room bet the pitch anyway, on the strength of it being one clearly
bounded piece of a cycle that had already been bet whole. Nobody has to like that, but it is what
happened, and inventing a number afterwards would make the record say the room was more confident
than it was.

**"Nightjar, Dunnock (for later)".** Nightjar did the porting. Dunnock was written in as the second
name against the possibility that the mesh-shape interface turned into its own piece of work, which
is exactly what happened — see the last checklist item. He never picked it up inside cycle 34, so
the item was carried out as `task-2b6c94` rather than left ticking away here as a lie.

**No dependency on the transport pitch above it.** The obvious reading is that second-order
transport cannot run until these coefficients exist, so this pitch blocks that one. It does not.
The transport shaping explicitly decouples them: "In order not to depend on porting of the
`blend_pinv_1` and `blend_pinv_2` coefficients (done independently), we can initialize with 0 at
first." Zero coefficients give a first-order scheme, which is wrong but runs, and that was enough to
let both pieces of work start in the same cycle. The edge was left out of `depends_on` deliberately.

**Why `prs` is empty on a record marked done.** The implementation landed, and there are pull
requests behind it — the reconstruction itself, then two follow-ups for the drum geometry and one
for the data test. None of them were written down while the work was happening, and reconstructing
the list afterwards from a merge log is how a plan starts containing things nobody checked. The
validator complains about this, correctly, and the complaint is being left visible rather than
quieted with a plausible number.

**No parent project.** The natural umbrella is the whole_roast experiment itself, which is a
grouping the team says out loud and has never written down as a record. Five pitches share it. If
one is ever created this pitch belongs under it, along with the seven others the cycle-34 bet
covered.

**Priority.** High, in the sense the team uses it: not "urgent" but "the rest of the transport work
is standing behind it".
