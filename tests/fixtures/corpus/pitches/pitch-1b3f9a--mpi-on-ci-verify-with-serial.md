---
id: pitch-1b3f9a
kind: pitch
title: MPI on CI verify with serial
parent: null
status: ready
owner: merganserly
reviewers: [jackdawrie]
person_weeks: 1
assignees: []
start_date: null
cycle: null
priority: low
depends_on: []
tags:
  - griddle
  - mpi
  - ci
prs: []
---

# MPI on CI verify with serial

**No shaping document yet.** What is written here is everything the board row said, and no more.

## What we know

The distributed job runs the throughflow and transport suites at two and four ranks, comparing each
against reference data recorded at that rank count. Nobody has run them against the single-rank
reference. If the multi-rank runs are bit-identical to the serial one — which the reproducibility
work is trying to make true — then the serial set is the one to compare against and the rest is
storage paid for a distinction we claim does not exist.

## Scope

`mpitask{1,2,4}` are the recorded reference directories the kiln4py datatests read; the layout is
`kiln4py/testdata/tapdata/mpitask{1,2,4}/drum_hex_50mm/tap_data`, and the loader that picks one by
rank count is
[`testing/tapdata.py`](https://github.com/kilnlab/kiln4py/blob/main/src/kiln4py/testing/tapdata.py).
`mpitask1` is the single-rank set. The ask is one line: make the MPI tests verify against
`mpitask1` instead of the rank-matched set. That is the whole of the stated scope — no interface
moves, no new fixtures — so nothing here was split into sub-tasks.

## What has been ruled out

Three things that look like this row and are not.

It is not the distributed-tests job itself. That one is about *which* tests run under MPI at all —
rank counts, which suites are enabled, whether the pipeline has GPU nodes to run them on — and it
keeps its own open list. Changing the reference data those tests compare against is orthogonal to
it, and either piece of work can land first without waiting on the other.

It is not the standalone driver's single-versus-multi-rank disagreement. The driver runs a whole
roast and drifts in the last bits of a global sum; these are per-tap-point field comparisons at a
fixed tolerance. Same symptom stated abstractly, different code, different fix, different people.

And it is not a tolerance change wearing a disguise. Nobody is proposing to loosen `atol` until the
serial data passes. If a suite fails against `mpitask1` and passes against `mpitask4`, that failure
is the finding: it goes back to the reproducibility work as a bug report, not into this row as a
number to be adjusted.

## What is not decided

Whether `mpitask2` and `mpitask4` get deleted afterwards, or kept as a second comparison so that a
regression in rank-dependence still has something to show up against. Keeping them costs test-data
storage and a slower checkout; deleting them means the only evidence of a rank-dependent bug is a
failure against serial data with nothing to diff it to.

Also open: whether the same switch applies to the transport suites, whose halo exchange is the part
most likely to be genuinely rank-dependent, or only to the throughflow ones this row was written
about. Nobody has argued either question yet, and neither needs settling before the first
experiment.
