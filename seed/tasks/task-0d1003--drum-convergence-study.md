---
id: task-0d1003
kind: task
title: Convergence study on the drum mesh
parent: pitch-0d0001
status: ready
owner: jackdawrie
assignees: [jackdawrie, Oxpeckerly]
reviewers: [Oxpeckerly, avocetline]
review_waived: false
start_date: 2026-08-17
priority: high
depends_on: [task-0d1002]
tags: [griddle, transport, convergence, drum, testing]
prs: []
created_schema_version: 2
person_weeks: 2.5
---

# Convergence study on the drum mesh

## Problem

Nothing in the test suite demonstrates that the horizontal transport is second order.
A convergence study on a doubly-periodic drum mesh is the cheapest test that catches an
order loss without a Fortran oracle: transport a smooth bump, refine, fit a slope to the L1 and
L-infinity errors, expect 2 within 0.4. The first attempts produced a lottery, not a
slope: a 0.2 % jitter in mean face length swung the fit over 0.21 to 2.29. Both causes were in
the test.

## Appetite

Two and a half weeks: the measurement harness is the work, the runs are minutes.

## Solution

Fix the reference time: the driver floors `n_time_steps = int(relative / dtime)` while the
analytic reference uses the nominal integration time, so the leftover `r = T - n·dt` is an O(h)
phase error — fifteen times the true error on the finest mesh. Build the reference at
`n_time_steps * dtime_in_seconds`. Then replace the minimum-image Gaussian — only C0 on the
drum, shedding a dispersive wake off the half-domain kink — with a periodic sum over the +/-2
images.

## No-go

- Asserting an L-infinity order for the discontinuous case. A discontinuity does not converge in
  the max norm; assert L1 only.
