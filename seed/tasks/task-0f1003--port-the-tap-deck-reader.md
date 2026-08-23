---
id: task-0f1003
kind: task
title: Port the tap-deck reader
parent: pitch-0f0003
status: shelved
owner: Ptarmigant
assignees: [Ptarmigant]
reviewers: [firecresta]
review_waived: false
assigned_on: null
priority: very_low
depends_on: []
tags: [tapdeck, hearth, reader]
prs: []
created_schema_version: 2
person_weeks: 2.0
---

# Port the tap-deck reader

## Problem

The reader identifies a Fortran archive by path and version string, and nothing else. That is the
whole of its idea of identity, which is how `roastref_bedphys_v06` was rebuilt in place with
moisture-loss instrumentation, kept its name, and quietly changed the airflow tap points
underneath two cycles of green throughflow datatests — `issue-e6f7a8`.

It is also still the Fortran reader's structure in Python: an index file read into a dict, offsets
computed by hand, one code path per tap-point layout, and no way to open two archives at once
because the offsets live in a module global.

## Solution

Record a manifest hash the first time an archive is used — sizes, shapes and dtypes of every tap
point, in a stable order — and check it on every load, failing with the two version strings and
the first field that differs. Then give the reader an object: one archive per instance, offsets on
it rather than in a module, and the layout selected once at open rather than at each read.

Shelved with the rest of `pitch-0f0003` at the cycle-37 table. Left written down at full detail
because the next table should be able to bet it as it stands, and because `task-0f1004` is
sitting behind it and the checker says so.
