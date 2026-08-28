---
id: task-0e1002
kind: task
title: Port the far-IR burner
parent: pitch-0e0001
status: ready
owner: hoopoegrove
assignees: [hoopoegrove, kittiwaker]
reviewers: [turnstonegru, jackdawrie]
review_waived: false
start_date: 2026-08-17
priority: medium
depends_on: [task-0e1001]
tags: [radiation, far-infrared, no-scatter-solver, emission-source, hearth]
prs: []
created_schema_version: 2
person_weeks: 2.0
---

# Port the far-IR burner

## Problem

Far-IR is what carries heat back into the bed from the drum wall, so without it the module produces
a one-sided heating rate and the `BurnerHeating` tendency cannot be compared against `burner-exit`.
KILN uses the cheapest solver in the library, `1scl`: no scattering, one angle at diffusivity
D = 1.66. The physics is simpler than near-IR; the work is the emission sources and two-sweep
transport.

## Appetite

Two weeks, the same pair, chained behind `task-0e1001` for its `kdist.py`, chunked
`(Cell, Gpt, K)` handling and host-side g-point reduction.

## Solution

The same `kdist.py` interpolation minus scattering, plus the major/minor absorber contributions
far-IR uses; `lay_source`, `lev_source` at both interfaces and `wall_source` from drum-wall
temperature and emissivity via the `emistab` table, band-to-g-point expansion host-side
(`np.take`). Then the no-scattering solver — `tau_loc = D * tau`, `exp(-tau_loc)`, and the
small-tau Padé/Taylor branch as a `where` on a computed field, never a Python-level `if`, or the
definedness analysis rejects it — then the wall-down and bed-up sweeps as the M1 scan pair.

## Rabbit holes

- **Sign and level conventions.** The band library indexes layers from the drum wall inward and
  KILN's interface flips some of them; `burner_interface.f90` on plant master is the authority,
  not the library's test driver. Getting `lev_source_inc`/`lev_source_dec` backwards shows up as a
  heating rate right in magnitude and wrong in sign near the bed surface.
