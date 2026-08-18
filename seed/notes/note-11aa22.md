---
id: note-11aa22
title: Is the grid file the thing we should be caching, or the connectivity we build from it?
status: thinking
written_by: halungge
written_on: 2026-08-14
tags: [grid, performance]
became: []
---
Every test that touches a real grid spends its first seconds rebuilding the same
connectivity tables from the same netCDF file, and we have started passing them
around in fixtures to avoid it. That works and it is spreading.

What I do not know:

- whether the expensive part is reading the file or building `c2e2c0` and friends
- whether a cache keyed on the grid file's hash would ever be invalidated correctly
  when somebody edits a grid by hand
- whether this is a test-suite problem or a runtime problem, which are different
  bets with different owners

Possibly this is two notes. Possibly it is nothing and the seconds are cheap.
