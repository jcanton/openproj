---
id: task-7d9f52
kind: task
title: Rerun the backend suite after the shutdown
parent: pitch-7b3e94
status: ready
owner: stonechatty
assignees: [stonechatty]
reviewers: [Whimbrelson]
review_waived: false
assigned_on: 2026-12-21
priority: medium
depends_on: [task-7c8e40, issue-9f2b48]
tags: [hearth, backend, validation]
prs: []
created_schema_version: 2
person_weeks: 2.0
---

# Rerun the backend suite after the shutdown

## Problem

Two backend releases land over the plant shutdown and the frozen API meets them for the first time
in January. What we will want to know then is one thing: which fields moved, and whether any of
them moved because of us. Nobody can answer that afterwards without a run from before.

## Solution

Run the full backend suite twice on the same commit — once on each scan lowering, on `hearth_cpu`
and `hearth_gpu` — and record the per-field deltas rather than a pass or a fail. The sequential
loop and the prefix pass sum a column in different orders and will not be bitwise equal; the
number that matters is how far apart they are on the fields the model actually reads, and whether
that distance is stable across the two releases.

Two weeks, starting the Monday before the shutdown so the first half of the pairing is taken on
the old backends while they are still installed, and finishing in January on the new ones.

`issue-9f2b48` is listed as a blocker because the reduction order it reports is the thing this
task measures, and the deltas are meaningless until somebody has said which order the driver
comparison is supposed to use. It is an issue and not a plan record: nothing schedules it, and it
moves no date here.
