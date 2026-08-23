---
id: note-b14d6a
kind: note
title: Whatever happened to the throughflow interface idea
status: thinking
written_by: yellowhammer7
written_on: 2026-02-19
tags: [throughflow]
became: [pitch-000000]
---

Step 4 of the bindings pitch was the interface — "expose the interface for use in `kiln4py`, port
the `bedstep` interface" — marked *if time permits*, and time did not permit. `task-3d84e9` carries
it as `shelved`, which is accurate about that pitch and says nothing about the idea.

The idea is still live and I would like to know where it went. Somebody plugs the module into the
physics driver eventually; the question is whether the interface is written on the kiln4py side, as
a thin adapter over the `f2py` module, or on the Fortran side, as a second entry point shaped for
the caller we actually have. Those are different amounts of work and different people, and the
board has never separated them.

## The link is broken and is being left broken

`became` points at a pitch that does not exist in this corpus. That is not a typo: the interface
work was re-shaped twice — once for the cycle-34 module-integration pitch and again for the
cycle-37 continuation — and neither of those board rows was converted into a record here, because
neither had a shaping note that could be read as one. The id written above is the one the
conversion notes name, and nothing opens it.

The consequence is exactly what it should be. The check reports the missing id beside this note,
and `state()` falls back to `thinking` rather than claiming a promotion nobody can open. That is
the state the idea is actually in.
