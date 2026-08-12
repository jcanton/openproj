# openproj

Planning for the icon4py team. Markdown files in a git repository are the source of truth, the
shaping document *is* the record, and every date is derived rather than typed.

A human types one date per item — `assigned_on` — and one size. Start dates, end dates, the critical
path and every rollup are computed from the dependency graph.

```bash
uv sync
uv run openproj check seed                          # validate; exits 1 on blockers
uv run openproj render seed out --today 2026-08-17  # write the three pages
uv run openproj schedule seed --json                # the computed schedule
open out/index.html
```

## The three views

`index.html` is a filterable, searchable table and the one people live in. `graph.html` is the
dependency DAG, grouped by project and pitch. `timeline.html` is the derived Gantt. All three render
from one in-memory index, share one filter model, and keep their state in the query string — so
every view is a shareable URL, the back button works, and there are no saved views to manage.

## Data model

One markdown file per entity: YAML frontmatter, then the shaping document as the body. Three kinds —
`project`, `pitch`, `task` — with ids like `pitch-a3f81c`, where the prefix must agree with the kind.

Two invariants are load-bearing:

- **Only `depends_on` is stored, on the dependent.** `blocks` is derived by reversing it. A stored
  copy would be stale by construction and would let one file contradict the graph.
- **Derived data never reaches frontmatter.** No computed dates in entity files, ever. Rescheduling
  one blocker would otherwise rewrite fifty files.

An entity may not depend on its own ancestor or descendant. Containment already requires a child
before its parent, so a dependency along the parent chain demands to be both before and after itself.

## Required fields

Requiredness is **status-gated** and enforced in three places: the create form, `openproj check` in
CI, and the index validation gate.

| status | additionally required |
|---|---|
| `todo` | `owner`; a reviewer or `review_waived`; a size; `shaped_by` on a pitch |
| `wip` | `assigned_on`; a reviewer who is not the owner |
| `done` | at least one PR |
| `shelved` | nothing — parked work is not broken work |

**Parse permissively, validate strictly.** Every field is optional at the type level, so a
hand-edited file with a missing field still loads and reports a problem instead of taking the index
down. Requiredness lives in `validate_all`, never in the parse types.

**Grandfathering.** Each rule records the `schema_version` that introduced it, and an entity is only
*blocked* by rules that existed when it was created; a newer rule warns instead. Without this,
adding one required field invalidates the whole repository at once and the rule gets reverted rather
than adopted. `shaped_by` is the live example: a version 2 rule warning against a version 1 corpus.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/render.py     the three pages
src/openproj/cli.py        check / render / schedule
seed/                      the corpus, converted from the HackMD task table
static/                    vendored, pinned JS — see static/VENDOR.md
docs/superpowers/          the spec and the plan
```

**No npm, no build step, no CDN.** A Node toolchain that rots is the most common way a small
internal tool becomes unbuildable in two years. `tests/test_render.py` asserts no rendered page
reaches the network.

## Deliberately not built

Real-time collaborative editing, notification infrastructure, user-defined custom fields, a
PR-based editing workflow, time tracking, burndown charts, per-project permissions. If you are about
to add one of these, read the spec first — each is excluded for a reason recorded there.

Nothing may make the CI bot write entity frontmatter. The bot owns `derived/` and nothing else;
if it starts patching frontmatter, bot and humans fight over the same files forever.

## Status

Phase 1: a static read-only viewer. No server, no auth, no writes — those are Phase 2, and only if
Gate 1 passes. Gate 1 is one question, asked at a planning meeting: **does anyone argue with a
date?** If nobody does, the timeline is not being read, and the right move is to stop.

Spec: `docs/superpowers/specs/2026-08-12-appetite-design.md`.
Plan and gates: `docs/superpowers/plans/2026-08-12-phase1.md`.

🤖 Written by an agent on behalf of @jcanton
