---
id: issue-8e1a37
kind: issue
title: The f2py wrapper rebuilds on every test session
status: ready
reported_by: yellowhammer7
opened_on: 2026-01-14
tags: [f2py, throughflow]
pitched_into: [task-3a52d8, task-3e07b2]
created_schema_version: 2
---

Not a board row. This is an aside in the throughflow bindings note, sitting under step 2 and never
given a row of its own, converted here because it is a complaint about existing behaviour rather
than a piece of shaped work — which is what this rung is for.

> Every pytest session recompiles `bedstep_f2py`. Roughly forty seconds, every time, before a
> single test runs.

The wrapper is built by `f2py` at import time, from Fortran that lives on a module branch kiln4py
does not own. There is no version to key a cache on, no hash, and no install step: the build is
the import. So a developer running one throughflow test pays for the whole extension module, and
CI pays for it once per job.

`opened_on` is the date on the note the aside appears in, not a date anybody reported anything.
Nothing in the source records who noticed it first; `reported_by` is the note's author.

## What it was pitched into

`pitched_into` names the two binding steps, `task-3e07b2` and `task-3a52d8`, because the source
text attaches the complaint to both by name — the wrapper interface is where the rebuild cost is
decided, and the `f2py` compile step is where it is paid. Neither task's own body mentions this,
which is correct: the edge is written on the issue and in one direction only.

Both of those steps are `done`, so this issue reads `done` as well, without the word being written
into the file. Whether the rebuild actually got faster is not something the source says — what it
says is that the work this was folded into finished. That is the honest limit of a derived state,
and it is worth knowing that the corpus contains one.
