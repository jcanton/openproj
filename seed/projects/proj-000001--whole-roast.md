---
id: proj-000001
kind: project
title: whole_roast
parent: prod-0f0001
status: in_progress
owner: jackdawrie
assignees: [jackdawrie, hornbillow, hoopoegrove]
reviewers: [hoopoegrove, hornbillow]
review_waived: false
assigned_on: 2026-06-22
priority: high
depends_on: []
tags: [whole-roast, drum, coupled-validation, bed-physics, milestone]
prs: ["kilnlab/kiln4py#2312"]
created_schema_version: 2
---

# whole_roast

## Problem

Every kiln4py subsystem is validated alone and none of them together — core-solver tap-point
datatests against REF/D4, analytic drum convergence for transport, 97 AIRFLOW datatests against the
reference roast — each a different Fortran run in a differently-numbered archive. That is how `roastref_bedphys_v06` was regenerated in place with moisture-loss instrumentation
and silently took the airflow tap points with it. The reference is thin too: at all three times in
`test_chaffburn_module` every aroma field is identically zero.

## Appetite

Two cycles, 36 and 37. If the coupled run is not integrating by the end of 37, cut physics.

## Solution

One idealised roast on the doubly-periodic `Drum_Hex_20x4_50mm` mesh — chosen because the DRUMBED
pool already carries bed boundary conditions for it — a charge-to-drop cycle driven by the
standalone driver with aroma transport, AIRFLOW throughflow and a bed on. Five pitches feed it, rank
reproducibility first as the harness, the burner last. Done means one archive version behind
`exp.bed_roast_drum_airflow`, a datatest per module, 1- and 12-rank output bitwise identical at
`LEVELS=validation`, and aroma that is not zero.

## No-gos

No sphere mesh, no tilt, no chaff optics, no ambient coupling. No performance work until the run is
green. Never regenerate an archive in place.
