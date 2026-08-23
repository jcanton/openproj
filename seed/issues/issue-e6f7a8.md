---
id: issue-e6f7a8
title: Throughflow tap points were regenerated in place
status: ready
reported_by: turnstonegru
opened_on: 2026-05-11
tags: [airflow, throughflow, reference-data]
pitched_into: [task-0b1001, task-0f1003]
---
`roastref_bedphys_v06` was rebuilt to add moisture-loss instrumentation and
written back under the same version, same path. It took the airflow tap points
with it. Two cycles of green throughflow datatests started failing tolerance on
`tend_qv` on a day nobody had touched throughflow.

We found it by diffing the archive against a copy somebody happened to still have
in a scratch directory. There is no other way to notice: the version number is
the only thing anybody compares, and it did not change.

Two pieces came out of it. The air-side port re-validated against the rebuilt
archive — that is `task-0b1001`, and it is done. Making the reader pin an archive
by content hash rather than by name is `task-0f1003`, and that was shelved with
the rest of the tap-deck rewrite, so the second half of this is not coming back
soon.

"Never regenerate an archive in place" is a no-go on the whole_roast project
because of this issue. That is the part that actually holds.
