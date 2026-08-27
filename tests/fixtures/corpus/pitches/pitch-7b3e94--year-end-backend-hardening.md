---
id: pitch-7b3e94
kind: pitch
title: Year-end backend hardening
parent: proj-9a4c25
status: ready
owner: Whimbrelson
assignees: [Whimbrelson, stonechatty]
reviewers: [redpollard]
review_waived: false
start_date: null
cycle: 38
priority: medium
depends_on: [pitch-6f2d18]
tags: [hearth, backend, hardening]
prs: []
created_schema_version: 2
person_weeks: 3.0
---

# Year-end backend hardening

## Problem

Cycle 38 runs across the plant shutdown, which is the one stretch of the year when nobody is
adding stencils and the model side is quiet. That is worth something specific: the backend API
the emitter chooses lowerings through has been changed three times this year, each time by the
person who needed the change, and each time the model had to be edited to follow. With two
lowerings for the scan there will be a third change, and the right moment to declare the shape
final is after that one and before anybody writes against it in January.

## Appetite

Three person-weeks across cycle 38, two people, most of it in the weeks either side of the
shutdown. The shutdown itself is not build time and is not counted — the cycle is longer than a
four-week build for exactly that reason.

## Solution

Freeze the backend API once the scan lowering has landed: the emitter's entry points, the
lowering-selection hook and the two capability flags become the supported surface, everything
else moves behind an underscore, and the change is written down where the model side will read
it. Then re-run the full backend suite once the shutdown is over, on both lowerings, and record
which fields differ and by how much.

Ordered rather than parallel, and that ordering is the dependency on `pitch-6f2d18`: freezing a
surface the second lowering has not been merged through would freeze the wrong shape.

## Rabbit holes

- **A freeze is a promise, so the list has to be short.** Every symbol left public is one we
  cannot move next year. If the surface cannot be written on one screen it has not been frozen,
  it has been photographed.
- **The suite after the shutdown is not the suite before it.** Two backend releases land over the
  break. Rerunning against a moved floor and reporting the deltas as ours is the way this loses a
  week.

## No-gos

No deprecation shims for the symbols that go private — there is one caller of each and it is in
this repository. No performance work: the point of the rerun is the numbers, not improving them.

## For later

The same treatment for the connectivity API, which has the same problem and four callers instead
of one. It was cut to fit three weeks, and it is the first thing to shape for cycle 39.
