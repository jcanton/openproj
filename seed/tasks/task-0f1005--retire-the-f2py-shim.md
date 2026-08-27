---
id: task-0f1005
kind: task
title: Retire the f2py shim
parent: null
status: ready
owner: jackdawrie
assignees: [jackdawrie]
reviewers: [hoopoegrove]
review_waived: false
start_date: 2026-08-17
cycle: 37
priority: low
depends_on: []
tags: [f2py, tooling, chore]
prs: []
created_schema_version: 2
person_weeks: 1.0
---

# Retire the f2py shim

## Problem

`tools/f2py_shim.py` exists to work around an f2py that stopped shipping two NumPy releases ago:
it rewrote the generated signature file so `bedstep_run` would accept an assumed-shape array. The
throughflow port needed it, `task-0b1001` and `task-0b1002` were built on top of it, and both are
done. Nothing needs it now.

It costs something anyway. It is imported by `conftest.py` at collection time, so every test
session rebuilds the wrapper module whether or not the session touches Fortran — thirty-odd
seconds on a laptop, which is most of what a fast unit-test run should cost in total. It also
pins `numpy<2.1` for the whole project, and a pin held by a workaround nobody needs is the kind
that becomes permanent because nobody can say what it is for.

## Solution

Delete it, delete the conftest import, generate the bindings with the shipped f2py, and rerun the
throughflow datatests to confirm the numbers do not move. Lift the NumPy pin in the same commit
and let CI say whether anything else was leaning on it.

A day's work with a parent nowhere. It belongs to no pitch and no project — shaping half a page
of chore would be worse than the loose end — so it is bet as a task in its own right in cycle 37,
and it is the reason `issue-c9d0e1` is open: the betting table lists bets, a bet is a pitch, and
this never appears there. `openproj check` reports it as a warning, which is at least somewhere.
