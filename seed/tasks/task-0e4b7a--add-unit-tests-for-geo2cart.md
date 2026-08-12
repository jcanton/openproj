---
id: task-0e4b7a
kind: task
title: Add unit tests for geo2cart
parent: proj-7e57a0          # placeholder while testing
status: todo
owner: nfarabullini
reviewers: [havogt]
assignees: []
assigned_on: null
cycle: null
priority: 3
depends_on: []
tags:
  - greenline
  - icon4py
  - unit-tests
prs: []
effort_weeks: 1
---

> **Shaping doc not located during migration.** This body is a stub written from the task-table
> row plus verification against the icon4py repository. No shaping document exists for this item.

## Provenance

Row 86 of `[Greenline] Open projects TABLE` — <https://hackmd.io/HvHaFPQrRP-8d9UzMA_Gkg>
(team permalink <https://hackmd.io/@gridtools/HJ2p8dc4-x>).

The row verbatim:

| column | value |
| --- | --- |
| Nr | 86 |
| Name | Add unit tests for geo2cart |
| Priority | Low |
| Status | *(blank)* |
| Who | *(blank)* |
| Depends on | *(blank)* |
| PR | *(blank)* |
| Shape doc | *(blank)* |
| Notes | `math/helpers.py geo2cart_onX don't have unit tests` |

Every cell except Nr, Name, Priority and Notes is empty. There is no owner, no dependency, no PR,
no shaping doc and no recorded status — hence `status: todo`, empty `assignees`, empty `depends_on`,
empty `prs`, and `assigned_on: null`.

## Why there is no shaping document

The GridTools HackMD space was searched exhaustively rather than sampled: all 730 notes in the team
listing (`https://hackmd.io/api/@gridtools/notes`) were downloaded, plus 11 further notes that are
absent from the listing but reachable through links inside the corpus. The strings `geo2cart`,
`geographical_to_cartesian` and `coordinate_transformations` occur **nowhere in the corpus except
this table row itself**. This item was never shaped, never bet, and never tagged to a cycle, which
is why `cycle` is null.

## What `geo2cart_onX` refers to

Verified against `C2SM/icon4py` `main` on 2026-08-12. The wildcard `X` in the row's note stands for
the grid location suffix. The functions are three `gtx.field_operator`s, today in
`model/common/src/icon4py/model/common/math/coordinate_transformations.py`:

- `geographical_to_cartesian_on_cells`
- `geographical_to_cartesian_on_edges`
- `geographical_to_cartesian_on_vertices`

Note that `math/helpers.py`, the path named in the row, no longer exists — the module was split, and
the geo2cart family now lives in `coordinate_transformations.py`. The row's file reference is stale,
but its substance is not.

**The row's claim still holds.** `model/common/tests/common/math/unit_tests/test_helpers.py` exists
but imports only `vector_operations` and `vertical_operations`, and contains a single test
(`test_cross_product`). The only places `geographical_to_cartesian*` is referenced are
`math/coordinate_transformations.py` (definition), `grid/geometry_stencils.py`, `grid/geometry.py`,
and `tests/common/states/unit_tests/test_factory.py` — i.e. the coverage that exists is incidental,
through a factory test, and there is no direct unit test of the three operators.

The source enumerates no sub-work; `geo2cart_onX` is a wildcard, not a task list. No task entities
were created, and no project entity was created because the grouping of rows 86–89 is encoded only
as a blank table row — the table contains no group heading naming a project.

## Related, but deliberately not linked

`[Greenline] Cycle 35 refactoring/cleanup tasks` (<https://hackmd.io/iwxBLwDbQUG0D3FzrwiQgw>, the
shaping doc for row 88) carries three items in the same neighbourhood:

- `reorganize basic maths operators common/math/ helpers,operators,stencils/`
- `clean-up the math module: operators/helpers etc.`
- `Maybe: add tests for geometry stencils in isolation` (targets `grid/geometry_stencils.py`)

None of these is this row: the first two are reorganisation rather than testing, and the third
targets geometry stencils rather than the math coordinate transformations. They are recorded here as
context only. No `depends_on` edge was created, because row 86's dependency cell is empty and
inventing an edge from topical adjacency would be fabrication. A later stage may reasonably decide
that the math-module reorganisation should precede writing tests against those functions.

## Appetite

Not stated. No shaping doc exists, and the task table has no appetite or effort column, so there is
no figure to carry over or convert. `appetite_weeks` is left null rather than guessed; see
`unresolved`.
