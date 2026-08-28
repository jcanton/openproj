---
id: task-0c1002
kind: task
title: Coordinate with Kettleworth
parent: pitch-0c0001
status: ready
owner: mudlarkish
assignees: [mudlarkish]
reviewers: []
review_waived: true
start_date: 2026-08-17
priority: medium
depends_on: []
tags: [drumbed-core, drumbed, coordination, upstream, kettleworth]
prs: []
created_schema_version: 2
person_weeks: 1.0
---

# Coordinate with Kettleworth

## Problem

DRUMBED is owned at the Kettleworth Institute and the Fortran keeps moving while we port a slice of
it. Three things the source cannot answer: whether DRUMBED builds and tests standalone — its driver
`drumbed_model.f90` USEs 92 KILN infrastructure modules, so standalone means a bed with no air over
it, still inside the KILN tree — and whether Kettleworth's datatests could be our tier-1 oracle;
the true prognostic state set for `bed_heat`, given that our field catalog mislabels `t_bed_sl`; and
how stable `drumbed_lite` and the AIRFLOW surface contract are before we pin kernel line-maps
against them.

## Appetite

One week of effort, spread across the cycle.

## Solution

Send a short written list of questions to their maintainers, naming a first contact on each side,
then one call to work through it, bringing the scouting bundle — handoff note, field catalog,
extractor. Write the answers into the plan doc and the handoff note, agree on a channel
for fidelity questions during the port, and flag the serialization instrumentation we carry on our
KILN fork. Review is waived: the deliverable is a written record, not code.

## No-gos

- No pull requests against DRUMBED in this pitch, and no commitment to maintain a hearth bed model
  on Kettleworth's behalf.
