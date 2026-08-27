---
id: task-0f1004
kind: task
title: Wire the tap-deck writer to the new reader
parent: pitch-0f0001
status: ready
owner: Ptarmigant
assignees: [Ptarmigant]
reviewers: [firecresta]
review_waived: false
start_date: 2026-08-17
priority: medium
depends_on: [task-0f1003]
tags: [tapdeck, hearth, writer]
prs: []
created_schema_version: 2
person_weeks: 1.0
---

# Wire the tap-deck writer to the new reader

## Problem

The writer finds out where a field lives by reaching into the emitter's internals — it imports
`_field_slot` and walks the backend's allocation table itself. Every emitter change this year has
broken it, four times, each time in a datatest run that looked like a physics failure until
somebody read the traceback properly. The scan work is about to change that surface a fifth time.

It writes an archive the new reader will want a manifest for, and it is the only thing that
writes one, so the hash has to be produced here or it has to be produced by hand.

## Solution

Drop the internals. Ask the emitter for a field's location through the interface
`task-0f1001` is stabilising, take the writer's own copy of the allocation table out, and emit the
manifest — sizes, shapes and dtypes in the reader's stable order — beside the payload on close.
One week, because the interface is the work and the manifest is thirty lines.

Bet in cycle 37 under the scan pitch rather than under `pitch-0f0003`, because what makes it
worth doing now is the stable interface and not the rest of the tap-deck rewrite.

It waits on `task-0f1003`, which is shelved, and `openproj check` says so as a warning on this
file. That is the honest state and not a mistake to tidy up: the manifest this writes is defined
by the reader that would consume it, and writing a format nobody reads is how you get two
formats. If the reader is still on the shelf when this comes up in the cycle, the answer is to
re-bet the reader or to drop this, and both of those are decisions for the table.
