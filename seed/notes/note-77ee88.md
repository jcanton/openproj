---
id: note-77ee88
title: Whatever became of the moisture-loss instrumentation idea
status: thinking
written_by: avocetline
written_on: 2026-04-20
tags: [reference-data]
became: [pitch-000000]
---
The idea was that the reference archives should carry the moisture-loss terms
themselves — the per-layer source and sink, not just the state either side of the
step — so the bed side could be validated without anybody rerunning Fortran to
get the intermediate quantities back.

I wrote it down after the cycle-35 review and it was promoted at the following
betting table, so this note should point at a pitch.

It does not point at anything. The id in `became` opens nothing, and the check
says so beside this note every time it runs. My best reconstruction: the pitch
was deleted rather than shelved, some weeks later, when the instrumentation was
added by rebuilding `roastref_bedphys_v06` in place instead — which got the terms
into the archive by the worst available route and cost us two cycles of trust in
the throughflow datatests (issue-e6f7a8).

Leaving the broken link rather than clearing it. The promotion happened; what is
missing is the record it went into, and blanking the field would turn a thing we
can still repair into a thing nobody remembers.
