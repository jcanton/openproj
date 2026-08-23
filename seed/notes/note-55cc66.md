---
id: note-55cc66
title: The burner is the last thing still calling into Fortran every step
status: thinking
written_by: dabchickly
written_on: 2026-07-06
tags: [radiation, port]
became: [pitch-0e0001]
---
Half-formed at the time: everything else in the whole-roast case runs in Python
now, and the burner is the one call that still crosses the boundary. That crossing
costs a copy of the whole state twice per burner step.

Unclear then whether the answer was to port BURNER, to fire it less often, or to
accept the copies. Shaped into a pitch at the cycle 37 betting table.
