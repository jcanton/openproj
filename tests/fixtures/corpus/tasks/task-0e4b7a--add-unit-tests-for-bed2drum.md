---
id: task-0e4b7a
kind: task
title: Add unit tests for bed2drum
parent: proj-7e57a0          # placeholder while testing
status: ready
owner: nightjarelli
reviewers: [hornbillow]
assignees: []
start_date: null
cycle: null
priority: low
depends_on: []
tags:
  - griddle
  - kiln4py
  - unit-tests
prs: []
person_weeks: 1
---

> **No shaping document for this one.** This body is written from the board row plus a read of
> the kiln4py source. Nobody shaped it and nobody bet it.

## Where this came from

An entry on the Griddle programme's open-projects board, in the group that collects small gaps
in test coverage. It carries a name, a priority of Low, and one line of note:
`math/helpers.py bed2drum_onX has no unit tests`. Owner, dependency, pull request, shaping
document and status are all blank on it. A blank status cell means nobody has picked it up.

That is why this record looks the way it does: `status: ready` because nothing said otherwise,
empty `assignees`, empty `depends_on`, empty `prs`, and `start_date: null`. Nothing here was
inferred from a neighbouring entry — the board groups by subsystem, and topical adjacency is not
a dependency.

## Why there is no shaping document

The programme keeps its shaping documents in one place and links them from the board, so the
search is cheap and it was done exhaustively rather than by sampling: every shaping document in
the space, plus the handful reachable only through links inside other documents. The strings
`bed2drum`, `bed_to_drum` and `mesh_transformations` appear nowhere except the board row itself.
This item was never shaped, never bet and never tagged to a cycle, which is why `cycle` is null.

## What bed2drum refers to

Read against `kiln4py` `main`. The `X` in the board's note is the mesh location suffix: the
functions are three `hearth.field_operator`s, and they live today in
`model/common/src/kiln4py/model/common/math/mesh_transformations.py`.

| operator | what it maps | covered by |
| --- | --- | --- |
| `bed_to_drum_on_cells` | bed coordinates to drum-frame Cartesian, per cell | factory test only |
| `bed_to_drum_on_edges` | the same, per edge | factory test only |
| `bed_to_drum_on_vertices` | the same, per vertex | factory test only |

`math/helpers.py`, the path the note names, no longer exists — the module was split and the
`bed2drum` family moved. The file reference is stale; the claim underneath it is not.

`model/common/tests/common/math/unit_tests/test_helpers.py` does exist, but imports only
`vector_operations` and `vertical_operations` and holds one test, of the cross product. The three
operators are otherwise reached only from `mesh/geometry_stencils.py`, `mesh/geometry.py` and
`tests/common/states/unit_tests/test_factory.py` — coverage on the way to something else, not a
test of any of them.

`bed2drum_onX` is a wildcard, not a task list, so no child records were created.

## Related, but deliberately not linked

The cycle-35 clean-up shaping document, which covers a neighbouring entry on the same board,
carries three items in the same neighbourhood:

- reorganise the basic maths operators across `common/math/` — helpers, operators, stencils
- clean up the math module: operators, helpers and the rest
- maybe: test the geometry stencils in isolation, against `mesh/geometry_stencils.py`

None of these is this entry. The first two are reorganisation rather than testing, and the third
targets the geometry stencils rather than the mesh transformations. They are here as context: no
`depends_on` edge was created, because the board's dependency cell is empty and inventing an edge
out of topical adjacency is fabrication.

## Appetite

Not stated. There is no shaping document, and the board carries no appetite column, so there is
nothing to carry over. The one week on this record is a placeholder, not a measurement.
