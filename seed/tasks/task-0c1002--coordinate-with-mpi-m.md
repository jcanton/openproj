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

JSBACH / ICON-Land is not ours. It is developed and owned at MPI-M, and we are about to port a
slice of it into icon4py while the Fortran keeps moving. Three things we cannot answer from the
source alone:

1. **Does ICON-Land build and test standalone?** The driver `mo_jsbach_model.f90` USEs 92 ICON
   infrastructure modules, so "standalone" clearly means *land without an atmosphere, still in
   the ICON tree* rather than a separable library. If MPI-M has site-level datatests for that
   configuration, they are a ready-made tier-1 oracle and we do not have to build a single-column
   golden-I/O harness ourselves.
2. **What is the true prognostic state set for SSE?** Our extracted field catalog (1152
   variables) flags prognostic status correctly about 90% of the time and demonstrably mislabels
   `t_soil_sl`. Confirming this needs someone who owns the code, not a better parser.
3. **How stable is `jsbach_lite`?** If the lite usecase or the tmx surface contract is expected
   to change this year we want to hear it before we pin kernel line-maps against it.

## Appetite

One week of effort, spread across the cycle.

## Solution

Send a short written list of questions to the ICON-Land group (Reiner Schnur as first contact),
then one call to work through them. Bring the scouting bundle — the handoff note, the field
catalog and the extraction script — so the conversation starts from something concrete rather
than from "we would like to port your model". Write the answers back into the plan doc and the
handoff note, and agree on a channel where they can sanity-check fidelity questions as the port
proceeds. Also flag the serialization instrumentation we carry on our ICON fork, so it is not a
surprise later if it ever wants to go upstream.

**Review is waived on this task because it produces no code** — the deliverable is a written
record of decisions in the plan doc, and the answers get reviewed in substance anyway when the
port that depends on them is reviewed.

## Rabbit holes

- Do not let this become a joint-development negotiation. We are asking questions and recording
  answers; a shared roadmap is a different conversation with different people in the room.
- Do not block the SSE slice on it. Our instrumentation already exists on our own fork and the
  bit-exact gate does not need upstream permission.

## No-gos

- No pull requests against ICON-Land in this pitch.
- No commitment to maintain a GT4Py land model on MPI-M's behalf, and no promise of a delivery
  date for anything beyond the SSE slice.
