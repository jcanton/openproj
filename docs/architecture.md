# Architecture

## The pages

`index.html` is a filterable, searchable table and the one people live in. `graph.html` is the
dependency DAG, grouped by project and pitch. `timeline.html` is the derived Gantt. `cycles.html`,
`people.html` and `issues.html` are the cycle records with their betting tables, who is on what and
who is full, and the pile of things somebody noticed; `detail.html` is one record on its own page,
and under the server it is also where a record is edited.

They render from one in-memory index, share one filter model, and keep their state in the query
string — so every view is a shareable URL, the back button works, and there are no saved views to
manage.

`/deck/<n>` is the odd one out and is a route only. It is the deck for one cycle's review meeting —
a title slide, then one slide per piece of work bet into that cycle, each with its ticked points,
its percentage and its pull requests, and it prints one slide to a page. It takes a cycle number, so
it has no place in a static export that writes one file per view of the whole plan; it is reached
from that cycle's own page, and it is deliberately not a seventh tab. It is also the one page that
carries its images inside itself as `data:` URIs, because it is the one page meant to be handed to
somebody who was not in the room.

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
git clone --bare https://github.com/jcanton/icon4py-plan.git plan.git
uv run openproj serve --repo plan.git --auth dev
```

A **bare** clone, and not a directory of files: there is no working copy to contend for and no index
to lock, which is what makes one writer behind an `flock` a workable design. `--auth dev` skips
sign-in and is for a local run only; the deployment runs `--auth github`, which refuses to start
without a signing secret and an OAuth client. `deploy/RUNBOOK.md` has the rest.

On Cloud Run the container clones the plan repo on boot and pushes on write, which is
also why the running service is close to stateless — the durable data is the git remote,
not the disk.

## Layout

```
src/openproj/model.py      schemas, parse, round-trip serialise, validate_all
src/openproj/schedule.py   the scheduler — a pure function, the product
src/openproj/index.py      the snapshot every view renders from
src/openproj/render.py     the pages
src/openproj/store.py      the git write layer — bare repo, one writer, scoped CAS
src/openproj/web.py        the server: routes, auth, the write endpoints
src/openproj/cli.py        check / render / schedule / serve
seed/                      the demo corpus
tests/fixtures/corpus/     the frozen golden corpus the scheduler goldens pin
static/                    vendored, pinned JS — see static/VENDOR.md
docs/superpowers/          the spec and the plan
```

`store.py` is a bare repository with no index to contend for, one writer behind an `flock`, and
compare-and-swap scoped to the path being written — so an edit to a different file retries invisibly
and only a genuine overlap is refused.

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

## The design records

| | |
|---|---|
| `docs/superpowers/specs/2026-08-12-appetite-design.md` | the spec: what a size is, and what is excluded |
| `docs/superpowers/specs/2026-08-16-cycles-design.md` | cycles, betting and capacity |
| `docs/superpowers/specs/2026-08-16-tailoring-plan.md` | what the team actually does, and what was tailored to it |
| `docs/superpowers/plans/2026-08-12-phase1.md` | the plan and its gates |

🤖 Written by an agent on behalf of @jcanton
