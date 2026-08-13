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
prs: ["C2SM/icon4py#1399"]
created_schema_version: 2
appetite_weeks: 6.0
shaped_by: nfarabullini
---

# Tracer advection convergence

## Problem

The horizontal advection granule runs second-order MIURA with a linear reconstruction over the
`C2E2C` patch, and nothing we have demonstrates it is actually second order. A datatest against
serialized ICON output only says "same numbers as Fortran at one resolution" — it passes just as
happily if both codes are first order because of a mis-sized least-squares stencil or a halo one
row too thin. Three unfinished pieces are entangled: the `lsq_pseudoinv_1` / `lsq_pseudoinv_2`
coefficients, halo exchanges in the granule (`p_tracer_new` is the one field above 2e-5 under
MPI, everything else at roundoff), and a convergence study on a doubly-periodic torus.

## Appetite

Six weeks. Started in cycle 36; the convergence study slipping into 37 is accepted, not a surprise.

## Solution

Land the coefficients first, then the exchange, then the study. The study runs the
`linear_2nd_order` MIURA flux on a torus at refinement factors 1/2/4/8 and fits a slope to the
L1 and L-infinity errors against an analytic reference, with a tolerance band of 0.4 around the
nominal order.

## Rabbit holes

- **Grid provenance.** Grids come from `icon-grid-generator`, not the downloaded
  `TORUS_1000X1000_*` files: `domain_height` is 1039.23 for 100M/50M and 995.93 for 25M/12M,
  because `fit_resolution()` adjusts the height when it converts a domain size into row and
  column counts. Refining across that family compares two different continuous problems and the
  fitted slope is meaningless.
