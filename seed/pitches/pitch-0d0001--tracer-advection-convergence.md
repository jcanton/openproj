---
id: pitch-0d0001
kind: pitch
title: Tracer advection convergence
parent: proj-000001
status: in_progress
owner: OngChia
assignees: [OngChia, nfarabullini, jcanton]
reviewers: [jcanton, halungge]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: high
depends_on: []
tags: [greenline, warm-bubble, tracer-advection, miura, torus, convergence]
prs: ["C2SM/icon4py#1399"]
created_schema_version: 2
appetite_weeks: 6.0
shaped_by: nfarabullini
---

# Tracer advection convergence

## Problem

The horizontal advection granule runs second-order MIURA with a linear reconstruction over the
`C2E2C` patch, and nothing demonstrates it is actually second order. A datatest against
serialized ICON output only says "same numbers as Fortran at one resolution", and passes just as
happily if both codes are first order from a mis-sized least-squares stencil or a halo one row
too thin. Three unfinished pieces are entangled: the `lsq_pseudoinv_1` / `lsq_pseudoinv_2`
coefficients, halo exchanges in the granule (`p_tracer_new` is the one field above 2e-5 under
MPI), and a torus convergence study.

## Appetite

Six weeks from cycle 36; the study slipping into 37 is accepted, not a surprise.

## Solution

Coefficients first, then the exchange, then the study: `linear_2nd_order` MIURA on a
doubly-periodic torus at refinement factors 1/2/4/8, fitting a slope to the L1 and L-infinity
errors against an analytic reference, tolerance band 0.4.

## Rabbit hole

- **Grid provenance.** Grids come from `icon-grid-generator`, not the downloaded
  `TORUS_1000X1000_*` files: `fit_resolution()` adjusts the height when it converts a domain
  size into row and column counts, so `domain_height` is 1039.23 for 100M/50M and 995.93 for
  25M/12M. Refining across that family compares two different continuous problems.
