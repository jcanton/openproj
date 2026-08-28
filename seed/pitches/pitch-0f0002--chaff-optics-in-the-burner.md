---
id: pitch-0f0002
kind: pitch
title: Chaff optics in the burner
parent: proj-000001
status: shaping
owner: null
assignees: []
reviewers: []
review_waived: false
start_date: null
cycle: null
priority: medium
depends_on: []
tags: [radiation, chaff, burner, optics]
prs: []
created_schema_version: 2
---

# Chaff optics in the burner

## Problem

Chaff comes off the bean through first crack and does not leave the drum: it lifts into the
freeboard, sits in the burner's line of sight, and scatters in both bands. `task-0e1001` ported the
near-IR chaff-scattering branch and `task-0e1002` the far-IR one, and both are green — against a
reference roast in which the chaff loading is a constant. `test_chaffburn_module` charges a bed
that never releases anything, so the branch that was ported has been exercised at exactly one
point: zero.

The Fortran is no better placed. KILN treats chaff as a binary flag per cell, on above
`chaffmin` and off below it, with a cell-mean loading and the 61-point lookup tables. That was a
1990s decision about a table small enough to fit in cache, and it is why the modelled freeboard
temperature drops by two degrees the moment a column crosses the threshold — a discontinuity in a
field that is continuous in the plant, which nobody has been able to remove because removing it
means changing the tables.

So there are two problems sitting on top of each other, and this is being written down before
anybody decides which one is being solved. Porting the discontinuity faithfully is cheap and
locks it in. Replacing it is a physics change in the middle of a validation campaign, which is the
thing `proj-000001` has a no-go about. Nobody has yet written a version of this that is neither.

<!-- Keep going here: what does a bounded version look like? The interpolated
     table is the obvious answer and it is not obviously the right one. -->

## Appetite
<!-- How much time this deserves and how that shapes the solution. The number
     itself is the Appetite field beside the body; this is the reasoning. -->

## Solution
<!-- The core elements, in a form that is easy to understand immediately. -->

## Rabbit holes
<!-- Details worth calling out now to avoid trouble later. -->

## No-gos
<!-- What is deliberately excluded, to fit the appetite or to keep the problem
     tractable. -->

## For later

A roast whose reference output has chaff in it. Every version of this pitch needs one and none of
them can produce one, because generating it is a Fortran run somebody has to schedule on the plant
rig. Worth starting before the shaping finishes, not worth waiting for.
