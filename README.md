# openproj

A planning tool for a team that runs Shape Up: a server and a CLI, pointed at a plan repository you
own. The plan is markdown files in that repository — one file per record, the fields in frontmatter
and the shaping document as the body. The bet and the argument for it are one file, which is the
whole idea: there is no shape doc to link to, nothing to keep in step with anything else, and
`git log` on a plan is a record of decisions rather than of edits.

Nobody types a forecast. A person writes a size in person-weeks and the two dates that actually
happened: `start_date`, the day the work began — or on work not yet begun, the day it will — and,
when it is finished, `end_date`, the day it stopped. Everything else is derived: the forecast end,
the critical path and every rollup come from those, from the dependency graph, and from who is on
the work at what availability. A predicted end is never written into a file, because it moves every
time anything else in the plan does; a recorded one is, because it is the only thing that can say
afterwards whether a bet landed inside its cycle. The tool invents no number: a record nobody has
sized gets no span at all and weighs nothing anywhere, rather than a length nobody chose. When a
date looks wrong, the thing to change is a size, a dependency or an availability.

## In the browser

Served for a team — `serve --auth github` — you sign in with GitHub, and membership of the org
the server was started with is what decides who may
write. A save is one commit on the plan repository with you as its author, and a file you change by
hand and push is read on the next request. Both directions are first class on purpose — a tool that
owns your files is a tool you cannot leave.

The landing page is **Records** — every record in the plan, one line each, sorted by last edited,
with the search box above it. It is how you get back to the thing you were writing yesterday. The
PM work happens in the tabs, which are the same records seen several ways: **Table** is the one
people live in, **Graph** is the dependency diagram, where dependencies are drawn and removed in a
mode of its own, **Timeline** the derived Gantt, **Cycles** one page per cycle with its bets and
its capacity, **People** who is on what and who is full, and **Help**, which is the four documents
under `docs/`, drawn on one page inside the app. Every filter is in the URL, so a view is a link,
and a field can be asked for more than one value at a time — two statuses means either of them.
Pointing at a row, a node or a bar opens the same card in all three: what the record is, who is on
it, when it runs, and its shaping document under a rule.

The search box is a small language, and it is the same language on the server and in the browser:
bare words match a record's fields — its id, title, tags, PR references and the people named on it,
never the shaping document — and `field:value` asks one field. `and`, `or`, `not` and brackets do
what they look like, two terms side by side mean both, and `tag:gpu and tag:distributed` is the
query the dropdowns cannot express, because a menu means OR within a field. A field this plan has
not got matches nothing rather than everything, and a query that cannot be read says what is wrong
with it and matches nothing while you finish typing.

The two inboxes — issues and notes — are records like any other now, with the same page and the
same editor, and they are two because they answer different questions: an issue is "we found
something existing that is broken", a note is "we are thinking of creating something that does not
exist and our ideas are confused". Neither carries an appetite or an owner and neither appears on
the table, the graph or the timeline; they live on Records and on their own pages. **Promote** is
what stops either from being an inbox nobody empties: it turns a note into a project, a pitch or a
task, and an issue into a pitch or a task — in one commit, and the new record says in its own
shaping document where it came from.

`docs/quickstart.md` is the five-minute version for somebody opening it for the first time.

## Locally

```bash
uv sync
uv run openproj demo
```

That is the whole of it. `demo` builds a plan repository out of the bundled demo corpus in a
temporary directory, serves it with sign-in switched off, and prints the URL. No network, no
credentials, and nothing to clean up: the repository is fresh every run and goes when you stop the
server, so every button in it is safe to press. It draws the plan around the corpus's own "today"
rather than around yours — `--today` moves it — and signs you in as somebody the corpus names, so
the parts of the tool that are about a person are on screen too.

`seed/` is that corpus and nobody's plan; `seed/README.md` says which parts of it are invented.
Pointing the server at a plan of your own is the section after this one.

The same corpus, as static files:

```bash
uv run openproj render seed out --today 2026-08-17
open out/index.html
```

That is also the answer to what happens if the service goes away: the plan stays readable, and
stays checkable, from any clone.

```bash
uv run openproj check seed        # every rule, exits non-zero only on blockers
uv run openproj schedule seed     # the derived dates, one line per record, with the reason
```

`check` is the load-bearing one, and it is deliberately quiet about warnings. A warning that fails
the build is a rule that gets reverted rather than adopted, so only a blocker is worth gating a
merge on. All three take a plan repository as their first argument, and all three take `--today`,
because half of what they say depends on which day it is — `check` included, since one rule now asks
whether a start date has gone by. `seed/` is written around 2026-08-17, so
`openproj check seed --today 2026-08-17` is the check that agrees with what `openproj demo` draws.

## A plan of your own

```bash
uv run openproj init ~/kiln-plan --org kilnlab --as jackdawrie
```

`init` writes what a plan needs before its first record — the four files under `config/`, at the
newest schema version, a README and a `.gitignore` — and commits them under your git identity, so
the next command is `openproj new`. Nothing in it is invented: the cycle table is empty, the
holidays are empty, and the roster is you or nobody. The alternative was copying `seed/`, and a copy
of the demo's roster is a plan that names people who do not exist, with a calendar that is the
demo's forever. It refuses before writing anything if the directory is not empty or git has no
identity to commit as. At a terminal it asks for what the flags left out — the org, the remote, your
login, and whether to describe a Cloud Run deployment; from a script it asks nothing, and
`--no-prompt` asks nothing anywhere.

The server wants a bare clone, never the checkout you edit in. A save moves the branch without
touching a working tree, which is right where there is none and leaves a checkout's `git status`
reporting every saved record as deleted and untracked at once; `serve` says so at startup and reads
the checkout anyway, because reading one is harmless.

```bash
git clone --bare ~/kiln-plan plan.git
uv run openproj serve --repo plan.git --auth dev
```

`--auth dev` signs everybody in and is for a machine only you can reach. For a team it is
`--auth github --org kilnlab`, and the org has no default: `serve` refuses to start without one,
because that membership is the whole of the write gate, and the org is a fact about a team rather
than about the tool. `OPENPROJ_ORG` in the environment is the other way to say it.

Putting it on Cloud Run reads the deployment from the plan rather than from here. `init` writes
`deploy/openproj.env` into the plan when asked, or when given `--deploy KEY=VALUE`, and
`deploy/example.env` in this repository is the same file with every value blank. From a checkout of
this repository:

```bash
./gcloud_deploy.sh ~/kiln-plan/deploy/openproj.env
```

It creates what is not there yet — the secrets, the two service accounts, the registry — builds the
image and deploys; a second run redeploys the current commit and leaves all of that alone. The two
secrets, the GitHub App's private key and the OAuth client secret, go into Secret Manager at the
prompt and are never in that file. `deploy/RUNBOOK.md` is the walk-through.

**The tool and the plan are two repositories** — this one holds code, tests and fixtures; the plan
holds markdown and nothing else. A plan commit must not run the tool's CI, and the credential the
server writes with must be structurally incapable of touching source. The seam is the `--repo`
argument, so pointing a deployment at a different plan is a flag rather than a fork — and the facts
of a deployment, which plan, which org, which cloud project, travel with the plan for the same
reason: kept in the tool's source, they made the tool one team's.

## From anywhere, with nothing installed

Every command above also runs straight out of the published package, which is the form to reach for
from a script, a CI job, or a coding agent working in the codebase a plan is about:

```bash
uvx openproj new issue . --title "The roast profile parser lives in two places" --as jackdawrie
uvx --from git+https://github.com/jcanton/openproj openproj check .   # unreleased main
```

That includes `serve`, `render` and `demo`. Since 0.43.0 the wheel carries `static/` and `seed/`
beside the package, so the pages have their scripts and `demo` has its corpus without a checkout;
before that, an installed `serve` answered its first page with "the vendored static/ directory is
missing" while this file said every command ran from the package.

`new` is the write path for somebody without a browser. It mints the id, files the record under its
kind's directory, starts the body from that kind's template, stamps the date and the schema version
the repository is on — and holds the record to every rule `check` holds it to before anything reaches
the disk, so a record that would fail the gate never becomes a file. `docs/quickstart.md` has the
flags and the reasoning.

## Where to read next

|                        |                                                                                                                 |
| ---------------------- | --------------------------------------------------------------------------------------------------------------- |
| `docs/quickstart.md`   | day one — what a pitch, a task and a cycle are, and how to write one                                            |
| `docs/data-model.md`   | one record type and six kinds, what the index derives, and what promotes into what                              |
| `docs/architecture.md` | the pages, the two repositories, the layout of the code                                                         |
| `docs/shape-up.md`     | how the records map to a pitch note, a cycle sheet and a dependency table, and where this departs from the book |
| `AGENTS.md`            | the invariants, how to write code here, and how to find the bug that is already here                            |
| `design/`              | design records — why a subsystem is the way it is, and what was measured. Not user documentation                |
| `deploy/RUNBOOK.md`    | deploying to Cloud Run — the GitHub App, the OAuth App, the flags, and what each one is for                     |

The first four of those are also the app's **Help** page — the same bytes, read off the same files,
so there is one copy of every sentence and nothing to keep in step. The last three are for somebody
with a checkout and stay in the repository, and so does this file: it is the front door on GitHub,
and a reader already signed into the app has answered what it is for by arriving.

## Status

Published on PyPI as `openproj`, so `uvx openproj demo` is the whole install. Deployable to Cloud
Run from one env file, and one team runs it that way; that deployment is described in its own plan
repository's `deploy/README.md`, not here. `init` starts a plan with its configuration and no
records, on purpose: a plan fills up from what its team bets on rather than from a seeded example
nobody wrote.

🤖 Written by an agent on behalf of @jcanton
