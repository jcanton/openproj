---
id: pitch-0f0003
kind: pitch
title: Tap-deck rewrite
parent: proj-000002
status: shelved
owner: Ptarmigant
assignees: [Ptarmigant]
reviewers: [firecresta]
review_waived: false
assigned_on: null
cycle: null
priority: very_low
depends_on: []
tags: [tapdeck, hearth, rewrite]
prs: []
created_schema_version: 2
person_weeks: 4.0
---

# Tap-deck rewrite

> Shelved at the cycle-37 betting table. Shaped, agreed to be worth doing, and not the most useful
> four weeks anybody could name — see the notes on `cycles/0037.md`. It is on the shelf whole,
> with its reader task, so that the next table can bet it as written rather than reshape it.

## Problem

The tap deck is the pair either side of a validation run: the writer, which dumps a stencil's
inputs and outputs at named tap points while a hearth program runs, and the reader, which loads
the Fortran archive those are compared against. Both were written for one datatest, three years
ago, and both are now load-bearing for every module in the port.

Two things are wrong with them and they are the same thing twice. The writer reaches into the
emitter's internals to find out where a field lives, so it breaks on any backend change — it has
been patched four times this year, once per emitter change, and it is why `pitch-0f0001` is being
asked for a stable interface it does not otherwise need. The reader identifies an archive by path
and version string, which is how `roastref_bedphys_v06` was rebuilt underneath us and took two
cycles of green throughflow datatests with it. That is `issue-e6f7a8`, and the half of it that
holds — the no-go on the whole_roast project — is a rule people have to remember rather than a
thing the tool checks.

## Appetite

Four person-weeks, one person, one cycle. Enough for both halves and a migration of the existing
datatests; not enough to also rework how tap points are named, which is the part everybody
complains about and the part that is merely annoying.

## Solution

Give the writer the same footing as any other consumer of the backend: it asks the emitter for a
field's location through the supported interface and holds no pointer of its own, so an emitter
change breaks it at import rather than at the fourth decimal place. Give the reader a content
hash beside the version string, recorded when an archive is first used and checked on every load,
so an archive rebuilt in place fails loudly on the next run instead of silently two cycles later.

Neither half needs the other. The reader is `task-0f1003` and could ship alone; the writer is
`task-0f1004`, which is bet in cycle 37 under a different pitch because it was small enough to
carry there and because it is what a stable emitter interface is worth having for.

## Rabbit holes

- **Hashing a multi-gigabyte archive on every load.** Hash the manifest, not the payload — and
  write down that decision, because the first reviewer will ask.

## No-gos

No change to tap-point naming. No new archive format. Nothing that requires re-running a Fortran
job on the plant rig: every archive we have stays readable, hash or no hash.
