---
id: task-0c1002
kind: task
title: Coordinate with MPI-M
parent: pitch-0c0001
status: todo
owner: muellch
assignees: [muellch]
reviewers: []
review_waived: true
assigned_on: 2026-08-17
cycle: 37
priority: 2
depends_on: []
tags: [jsbach, icon-land, coordination, upstream, mpi-m]
prs: []
created_schema_version: 2
effort_weeks: 1.0
---

# Coordinate with MPI-M

## Problem

JSBACH / ICON-Land is owned at MPI-M and the Fortran keeps moving while we port a slice of it.
Three things the source cannot answer: whether ICON-Land builds and tests standalone — its driver
`mo_jsbach_model.f90` USEs 92 ICON infrastructure modules, so standalone means land without an
atmosphere, still inside the ICON tree — and whether MPI-M's datatests could be our tier-1 oracle;
the true prognostic state set for SSE, given that our field catalog mislabels `t_soil_sl`; and how
stable `jsbach_lite` and the tmx surface contract are before we pin kernel line-maps against them.

## Appetite

One week of effort, spread across the cycle.

## Solution

Send a short written list of questions to the ICON-Land group (Reiner Schnur as first contact),
then one call to work through them, bringing the scouting bundle — handoff note, field catalog,
extraction script. Write the answers into the plan doc and the handoff note, agree on a channel
for fidelity questions during the port, and flag the serialization instrumentation we carry on our
ICON fork. Review is waived: the deliverable is a written record, not code.

## No-gos

- No pull requests against ICON-Land in this pitch, and no commitment to maintain a GT4Py land
  model on MPI-M's behalf.
