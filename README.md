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

## Two repositories

The tool and the plan are separate repositories, and stay separate in production.

```
C2SM/openproj        this repo — code, tests, and fixtures. No real plan data.
C2SM/<name>-plan     the data — markdown entities and config. No code.
```

`seed/` and `tests/fixtures/corpus/` live here only because they are a demo and a
test fixture. Neither is anybody's plan.

Three reasons the split is load-bearing:

- **A plan commit must not run the tool's CI.** Someone changing a status should not
  queue a test suite, and a red suite should not block someone changing a status.
- **The write credential must be structurally incapable of touching source.** The
  server commits to the plan repo continuously. Scoped to one repository with
  `contents: write`, a leaked token costs you a revertable plan; scoped wider it is a
  supply-chain foothold in a scientific codebase.
- **Their histories have nothing to say to each other.** `git log` on the plan is a
  record of decisions; on the tool it is a record of code. Interleaving them makes
  both harder to read, and `git blame` on an appetite field stops being useful.

The seam is the `--repo` argument. The server holds a bare clone of the plan repo and
knows nothing else about it, so pointing a deployment at a different plan is a flag,
not a fork.

```bash
uv run openproj serve --repo /srv/plan.git          # a bare clone of the data repo
uv run openproj serve --repo seed --auth dev        # the demo, locally
```

On Cloud Run the container clones the plan repo on boot and pushes on write, which is
also why the running service is close to stateless — the durable data is the git remote,
not the disk.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/render.py     the three pages
src/openproj/store.py      the git write layer — bare repo, one writer, scoped CAS
src/openproj/cli.py        check / render / schedule / serve
seed/                      the demo corpus
tests/fixtures/corpus/     the frozen golden corpus the scheduler goldens pin
static/                    vendored, pinned JS — see static/VENDOR.md
docs/superpowers/          the spec and the plan
```

**No npm, no build step, no CDN.** A Node toolchain that rots is the most common way a small
internal tool becomes unbuildable in two years. `tests/test_render.py` asserts no rendered page
reaches the network.

**`node` is not needed to build or run it, and is needed to test it fully.** Thirty-four tests run
the shipped page scripts against a minimal DOM — the table's rows, the timeline's tooltip, the
combobox and the cycle roster exist only after a script has run, so nothing in a rendered file
shows what they build. Without `node` on PATH those tests skip, and a suite missing them is green
for the wrong reason. `pytest` names every skip; a machine that is meant to gate a merge should
have `node` installed.

## Deliberately not built

Real-time collaborative editing, notification infrastructure, user-defined custom fields, a
PR-based editing workflow, time tracking, burndown charts, per-project permissions. If you are about
to add one of these, read the spec first — each is excluded for a reason recorded there.

Nothing may make the CI bot write entity frontmatter. The bot owns `derived/` and nothing else;
if it starts patching frontmatter, bot and humans fight over the same files forever.

## Status

Phase 1 is done: the static viewer renders, and Gate 1 was shown at a planning meeting.

Phase 2 is in progress. `store.py` — the git write layer — is complete: a bare repository with no
index to contend for, one writer behind an `flock`, and compare-and-swap scoped to the path being
written, so an edit to a different file retries invisibly and only a genuine overlap is refused.
The server and GitHub OAuth are next.

Spec: `docs/superpowers/specs/2026-08-12-appetite-design.md`.
Plan and gates: `docs/superpowers/plans/2026-08-12-phase1.md`.

🤖 Written by an agent on behalf of @jcanton
