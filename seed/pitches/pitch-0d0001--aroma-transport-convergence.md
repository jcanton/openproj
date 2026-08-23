---
id: pitch-0d0001
kind: pitch
title: Aroma transport convergence
parent: proj-000001
status: in_progress
owner: Oxpeckerly
assignees: [Oxpeckerly, nightjarelli, jackdawrie]
reviewers: [jackdawrie, hoopoegrove]
review_waived: false
assigned_on: 2026-06-22
cycle: 36
priority: high
depends_on: []
tags: [griddle, whole-roast, transport, flume, drum, convergence]
prs: ["kilnlab/kiln4py#2360"]
created_schema_version: 2
person_weeks: 6.0
shaped_by: nightjarelli
---

# Aroma transport convergence

## Problem

The horizontal transport module runs second-order FLUME with a linear reconstruction over the
`C2F2C` patch, and nothing demonstrates it is actually second order. A datatest against
serialized KILN output only says "same numbers as Fortran at one resolution", and passes just as
happily if both codes are first order from a mis-sized blend stencil or a halo one row
too thin. Three unfinished pieces are entangled: the `blend_pinv_1` / `blend_pinv_2`
coefficients, halo exchanges in the module (`q_aroma_new` is the one field above 2e-5 under
MPI), and a drum convergence study.

## Appetite

Six weeks from cycle 36; the study slipping into 37 is accepted, not a surprise.

## Solution

Coefficients first, then the exchange, then the study: `linear_2nd_order` FLUME on a
doubly-periodic drum at refinement factors 1/2/4/8, fitting a slope to the L1 and L-infinity
errors against an analytic reference, tolerance band 0.4.

## Rabbit hole

- **Mesh provenance.** Meshes come from `kiln-mesh-tool`, not the downloaded
  `DRUM_1000X1000_*` files: `fit_resolution()` adjusts the height when it converts a domain
  size into row and column counts, so `domain_height` is 1039.23 for 100M/50M and 995.93 for
  25M/12M. Refining across that family compares two different continuous problems.
