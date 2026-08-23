---
id: issue-c9d0e1
title: The betting table has nowhere to put a chore
status: in_progress
reported_by: mudlarkish
opened_on: 2026-08-18
tags: [tooling, cycle]
pitched_into: []
---
Not a bug in the code, a bug in the shape of the plan, so it goes in here rather
than into a pitch.

`task-0f1005` — retire the f2py shim — is real cycle-37 work with an owner and a
week on it, and it hangs under no pitch, because nobody would shape a half-page
chore and nobody should. So the betting table never sees it. The cycle view lists
bets, a bet is a pitch, and a parentless task is not a bet: it is simply absent
from the one meeting where the cycle's contents are agreed.

Left `in_progress` rather than `ready` because half an answer already exists —
`openproj check` reports a parentless task as a warning, which is at least
somewhere it shows up — and because the other half is a choice nobody has made.
Either a task can be bet directly, which makes "bet" mean two things, or a cycle
grows a chore list beside its bets, which makes the cycle view two lists. Nothing
pitched until that is decided.
