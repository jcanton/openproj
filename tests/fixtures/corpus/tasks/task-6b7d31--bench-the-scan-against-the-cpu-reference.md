---
id: task-6b7d31
kind: task
title: Bench the scan against the CPU reference
parent: pitch-6f2d18
status: in_progress
owner: redpollard
assignees: [redpollard]
reviewers: [Whimbrelson]
review_waived: false
assigned_on: 2026-08-13
priority: medium
depends_on: []
tags: [hearth, scan-operator, benchmark]
prs: ["kilnlab/hearth#799"]
created_schema_version: 2
person_weeks: 0.5
---

# Bench the scan against the CPU reference

## Problem

The 6.1x in the pitch is one measurement of one stencil taken by one person on one machine, and
every argument in this cycle rests on it. If the new lowering is to be judged, the number it is
judged against has to be reproducible by somebody else.

## Solution

A standing benchmark: the bed solver's forward elimination at three column counts on `hearth_cpu`,
`hearth_gpu` and `embedded`, run five times, median reported, committed under `bench/scan/` with
the machine and the driver version recorded beside the numbers. It runs on demand and not in CI —
a timing test in a pipeline is a flake with a schedule.

Half a week, and it is deliberately being done first, while the lowering it will measure is still
being written. A baseline taken after the change is not a baseline.
